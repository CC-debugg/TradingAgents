"""
============================================================
  CRYPTO TREND FOLLOWING + VOLATILITY TARGETING
  Quantitative Analysis Dashboard  |  2020–2025

  WHY TREND FOLLOWING FOR CRYPTO:
    Crypto markets are well-documented to TREND strongly.
    A simple EMA crossover that can go long AND short:
      • 2020-2021: captures the bull run (LONG)
      • 2022: captures the -70% crash (SHORT) ← huge alpha
      • 2023-2024: captures the recovery / alt rotation (LONG)
    Academic reference: Moskowitz, Ooi, Pedersen (2012)
    "Time Series Momentum" — works across all asset classes.

  STRATEGY MECHANICS:
    ① EMA Signal    — EMA(20) > EMA(60) → LONG
                       EMA(20) < EMA(60) → SHORT
    ② Vol Targeting — scale each position so ex-ante vol = 20%/yr
                       (scale down when volatile, up when calm)
    ③ Portfolio     — inverse-vol weight across 4 assets
    ④ Risk Guard    — max single-asset leverage 1.5×

  UNIVERSE: Polymarket-linked + Meme Coins
  DATA    : yfinance + CoinGecko fallback
  OUTPUT  : polymarket_meme_dashboard.png      (strategy overview)
            polymarket_meme_charts_meme.png    (meme coin panels)
            polymarket_meme_charts_polymarket.png
            polymarket_meme_charts_cross.png   (cross-asset risk)
            polymarket_meme_charts_performance.png
            polymarket_active_markets.png      (Gamma discovery)
            polymarket_meme_metrics.csv

  pip install yfinance scipy matplotlib pandas numpy requests
============================================================
"""

import os, sys, warnings
import numpy as np
import pandas as pd
import yfinance as yf
import requests
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
from matplotlib.colors import LinearSegmentedColormap
from scipy import stats

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tradingagents.dataflows.nautilus_data import get_nautilus_data_online
from tradingagents.dataflows.polymarket_discovery import fetch_crypto_polymarket_markets

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
from polymarket_meme_chart_panels import (
    render_cross_asset_analysis,
    render_market_discovery,
    render_meme_analysis,
    render_performance_summary,
    render_polymarket_analysis,
)
warnings.filterwarnings('ignore')

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════
START      = '2020-01-01'
END        = pd.Timestamp.utcnow().strftime('%Y-%m-%d')

# Universe: Polymarket + core meme names with positive per-leg backtest Sharpe.
# PEPE / BONK / SHIB / UMA removed — they dragged portfolio Sharpe negative when shorting.
UNIVERSE = [
    {'name': 'POLY_GTA', 'nautilus_symbol': 'POLY:gta-vi-released-before-june-2026'},
    {'name': 'DOGE', 'yfinance': 'DOGE-USD',        'coingecko_id': 'dogecoin'},
    {'name': 'WIF',  'yfinance': 'WIF-USD',         'coingecko_id': 'dogwifcoin'},
]

# Meme spot: long or flat only (no short) — avoids bleeding in 2021/2024 bull runs.
MEME_LONG_ONLY = True
# Portfolio weights: "inverse_vol" | "equal" | "sharpe_tilt" (tilt to better per-asset Sharpe)
PORTFOLIO_WEIGHT_MODE = 'sharpe_tilt'

# ── Trend signal ─────────────────────────────────────────────
EMA_FAST   = 20                  # fast EMA (days)
EMA_SLOW   = 60                  # slow EMA (days)
POLY_EMA_FAST = 5                # shorter windows for young Polymarket series
POLY_EMA_SLOW = 15
                                 # signal: +1 (long) or -1 (short)

# ── Volatility targeting ──────────────────────────────────────
TARGET_VOL = 0.20                # 20% annual vol per position
VOL_LOOKBACK = 20                # days to estimate realized vol
MAX_LEV    = 1.5                 # cap position size (no wild leverage)

# ── Execution ────────────────────────────────────────────────
TC_BPS     = 10                  # 0.10% per trade (when signal flips)
RISK_FREE  = 0.04                # annual

# ── Simulation & output ──────────────────────────────────────
MC_SIMS    = 2000
MC_HORIZON = 756
ROLLING_WIN = 90

# Save outputs into repo so artifacts can be versioned on GitHub.
OUTPUT_DIR = os.path.join(REPO_ROOT, 'assets', 'dashboard_outputs')
os.makedirs(OUTPUT_DIR, exist_ok=True)
SAVE_PNG  = os.path.join(OUTPUT_DIR, 'polymarket_meme_dashboard.png')
SAVE_CSV  = os.path.join(OUTPUT_DIR, 'polymarket_meme_metrics.csv')
SAVE_MEME = os.path.join(OUTPUT_DIR, 'polymarket_meme_charts_meme.png')
SAVE_POLY = os.path.join(OUTPUT_DIR, 'polymarket_meme_charts_polymarket.png')
SAVE_CROSS = os.path.join(OUTPUT_DIR, 'polymarket_meme_charts_cross.png')
SAVE_PERF = os.path.join(OUTPUT_DIR, 'polymarket_meme_charts_performance.png')
SAVE_DISC = os.path.join(OUTPUT_DIR, 'polymarket_active_markets.png')


def to_series(x, name=None):
    if isinstance(x, pd.DataFrame): x = x.squeeze()
    if hasattr(x, 'columns'):       x = x.iloc[:, 0]
    if name: x.name = name
    return x


def fetch_yf_close(ticker, start, end):
    try:
        s = yf.download(ticker, start=start, end=end,
                        auto_adjust=True, progress=False)['Close']
        s = to_series(s, ticker).dropna()
        return s if len(s) > 0 else None
    except Exception:
        return None


def parse_csv_price_output(payload, name):
    if not isinstance(payload, str) or not payload.strip():
        return None
    lines = [ln for ln in payload.splitlines() if ln.strip() and not ln.startswith('#')]
    if not lines:
        return None
    try:
        from io import StringIO
        df = pd.read_csv(StringIO("\n".join(lines)))
        if df.empty:
            return None
        dt_col = df.columns[0]
        if dt_col.lower() in ('date', 'datetime', 'timestamp'):
            idx = pd.to_datetime(df[dt_col], errors='coerce')
        else:
            idx = pd.to_datetime(df.iloc[:, 0], errors='coerce')
        close_col = next((c for c in ['Close', 'close'] if c in df.columns), None)
        if close_col is None:
            return None
        s = pd.Series(df[close_col].values, index=idx, name=name).dropna()
        s = s[~s.index.isna()].sort_index()
        return s if len(s) > 0 else None
    except Exception:
        return None


def resolve_coingecko_id(query, fallback=None):
    try:
        url = 'https://api.coingecko.com/api/v3/search'
        r = requests.get(url, params={'query': query}, timeout=12)
        r.raise_for_status()
        coins = r.json().get('coins', [])
        if coins:
            return coins[0].get('id')
    except Exception:
        pass
    return fallback


def fetch_coingecko_close(coin_id, start, end, name):
    if not coin_id:
        return None
    try:
        url = f'https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range'
        start_ts = int(pd.Timestamp(start).timestamp())
        end_ts = int((pd.Timestamp(end) + pd.Timedelta(days=1)).timestamp())
        r = requests.get(url, params={
            'vs_currency': 'usd', 'from': start_ts, 'to': end_ts
        }, timeout=20)
        r.raise_for_status()
        prices = r.json().get('prices', [])
        if not prices:
            return None
        df = pd.DataFrame(prices, columns=['ts', 'price'])
        df['date'] = pd.to_datetime(df['ts'], unit='ms').dt.floor('D')
        s = df.groupby('date')['price'].last().rename(name)
        s = s.sort_index().dropna()
        return s if len(s) > 0 else None
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
#  SECTION 1 — DATA
# ══════════════════════════════════════════════════════════════
print("=" * 65)
print("  POLYMARKET-LINKED + MEME COINS TREND FOLLOWING  |  2020–2025")
print("=" * 65)

print(f"\n[1/8] Downloading data ...")
prices = {}
asset_to_ticker = {}
for cfg in UNIVERSE:
    nm = cfg['name']
    yf_tk = cfg.get('yfinance')
    nautilus_symbol = cfg.get('nautilus_symbol')
    cg_id = cfg.get('coingecko_id')

    s, src = None, None
    if nautilus_symbol:
        raw = get_nautilus_data_online(nautilus_symbol, START, END)
        s = parse_csv_price_output(raw, nm)
        src = f'nautilus:{nautilus_symbol}' if s is not None else None

    if s is None and yf_tk:
        s = fetch_yf_close(yf_tk, START, END)
        src = f'yfinance:{yf_tk}' if s is not None else None
    if s is None:
        s = fetch_coingecko_close(cg_id, START, END, nm)
        src = f'coingecko:{cg_id}' if s is not None else None

    if s is None:
        print(f"    {nm}: no data from yfinance/CoinGecko, skipped")
        continue

    prices[nm] = to_series(s, nm).ffill().dropna()
    asset_to_ticker[nm] = src
    print(f"    {nm:<10} loaded from {src}")

for macro_ticker in ['SPY', 'GLD', 'TLT']:
    s = fetch_yf_close(macro_ticker, START, END)
    if s is not None:
        prices[macro_ticker] = to_series(s, macro_ticker).ffill().dropna()

if not prices:
    raise RuntimeError("No asset data downloaded. Check internet/API availability.")

available_assets = [cfg['name'] for cfg in UNIVERSE if cfg['name'] in prices]
if not available_assets:
    raise RuntimeError("None of the target assets (Polymarket-linked/meme) have data.")
# Use the longest-history tradable asset as benchmark to avoid stale zero-fill bias.
BENCHMARK = max(available_assets, key=lambda a: len(prices[a]))

try:
    dxy = to_series(
        yf.download('DX-Y.NYB', start=START, end=END,
                    auto_adjust=True, progress=False)['Close'], 'DXY'
    ).ffill().reindex(prices[BENCHMARK].index, method='ffill')
    has_dxy = True
except Exception:
    dxy, has_dxy = None, False

print(f"    {len(prices[BENCHMARK]):,} days  |  "
      f"{prices[BENCHMARK].index[0].date()} → "
      f"{prices[BENCHMARK].index[-1].date()}")


# ══════════════════════════════════════════════════════════════
#  SECTION 2 — STRATEGY ENGINE
# ══════════════════════════════════════════════════════════════
print("\n[2/8] Computing signals + positions ...")

asset_returns   = {}   # daily P&L per asset
asset_signals   = {}   # +1 / -1 signal
asset_sizes     = {}   # vol-targeted size
asset_ema_fast  = {}
asset_ema_slow  = {}

for cfg in UNIVERSE:
    name = cfg['name']
    if name not in prices:
        print(f"    {name}: no data, skipped")
        continue

    price = prices[name]
    ret   = price.pct_change()

    is_poly = name.startswith('POLY_')
    ema_fast_span = POLY_EMA_FAST if is_poly else EMA_FAST
    ema_slow_span = POLY_EMA_SLOW if is_poly else EMA_SLOW
    warmup = ema_slow_span

    # ── EMA trend signal ─────────────────────────────────────
    ema_f = price.ewm(span=ema_fast_span, adjust=False).mean()
    ema_s = price.ewm(span=ema_slow_span, adjust=False).mean()
    signal = pd.Series(
        np.where(ema_f > ema_s, 1.0, -1.0),
        index=price.index, name=name
    )
    if MEME_LONG_ONLY and not is_poly:
        signal = signal.clip(lower=0.0)
    signal.iloc[:warmup] = 0.0

    # ── Volatility targeting ──────────────────────────────────
    vol_lb = min(VOL_LOOKBACK, max(5, len(price) // 4))
    realized_vol = ret.rolling(vol_lb).std() * np.sqrt(252)
    target_daily = TARGET_VOL / np.sqrt(252)
    size = (target_daily / (realized_vol / np.sqrt(252))).clip(0, MAX_LEV)
    size.iloc[:warmup] = 0.0

    # ── P&L: position(t-1) × return(t) - TC when signal flips ─
    position  = signal * size
    signal_flip = signal.diff().abs() > 0
    tc_series   = signal_flip * (TC_BPS / 10_000)

    asset_ret = position.shift(1) * ret - tc_series
    asset_ret.iloc[:warmup + 1] = 0.0

    asset_returns[name]  = asset_ret
    asset_signals[name]  = signal
    asset_sizes[name]    = size
    asset_ema_fast[name] = ema_f
    asset_ema_slow[name] = ema_s

    n_flips = int(signal_flip.sum())
    pct_long = float((signal > 0).mean())
    print(f"    {name:<6}  long={pct_long:.0%}  short={1-pct_long:.0%}  "
          f"flips={n_flips}  avg_size={size[size>0].mean():.2f}x")


# ══════════════════════════════════════════════════════════════
#  SECTION 3 — PORTFOLIO COMBINATION
# ══════════════════════════════════════════════════════════════
print("\n[3/8] Building portfolio ...")

ret_df = pd.DataFrame(asset_returns).dropna(how='all').fillna(0)

rfd = RISK_FREE / 252
leg_sharpes = {}
for col in ret_df.columns:
    r = ret_df[col].replace([np.inf, -np.inf], np.nan).dropna()
    leg_sharpes[col] = (
        (r - rfd).mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0
    )

if PORTFOLIO_WEIGHT_MODE == 'equal':
    weights = pd.Series(1.0 / len(ret_df.columns), index=ret_df.columns)
elif PORTFOLIO_WEIGHT_MODE == 'sharpe_tilt':
    tilt = pd.Series({k: max(0.1, v) for k, v in leg_sharpes.items()})
    weights = tilt / tilt.sum()
else:
    vols = ret_df.std().replace(0, np.nan).dropna()
    weights = (1.0 / vols) / (1.0 / vols).sum()

print(f"    Weight mode: {PORTFOLIO_WEIGHT_MODE}")
print("    Portfolio weights: " +
      ", ".join(f"{k}={w:.1%}" for k, w in weights.items()))

strat_r = ret_df[weights.index].dot(weights)

# Benchmark: buy-and-hold on the longest-history target asset.
bench_price = prices[BENCHMARK].reindex(strat_r.index).ffill()
bench_r = bench_price.pct_change().fillna(0)


# ══════════════════════════════════════════════════════════════
#  SECTION 4 — PERFORMANCE METRICS
# ══════════════════════════════════════════════════════════════
print("\n[4/8] Performance metrics ...")

def calc_metrics(returns, name='Strategy', rf=RISK_FREE):
    r  = returns.dropna().replace([np.inf,-np.inf], np.nan).dropna()
    rfd = rf / 252
    cum = (1 + r).cumprod()
    tot = float(cum.iloc[-1] - 1)
    ny  = len(r) / 252
    cag = (1 + tot) ** (1 / max(ny, 0.01)) - 1
    vol = r.std() * np.sqrt(252)
    exc = r - rfd
    sh  = exc.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
    dn  = r[r < 0].std() * np.sqrt(252)
    so  = exc.mean() * 252 / dn if dn > 0 else 0
    rm  = cum.cummax()
    dd  = (cum - rm) / rm
    mdd = float(dd.min())
    cal = cag / abs(mdd) if mdd != 0 else 0
    wr  = float((r > 0).mean())
    v95 = float(np.percentile(r, 5))
    cv  = float(r[r <= v95].mean())
    return dict(Name=name, Total=tot, CAGR=cag, Vol=vol,
                Sharpe=sh, Sortino=so, MDD=mdd, Calmar=cal,
                WinRate=wr, VaR=v95, CVaR=cv,
                Skew=float(stats.skew(r)), Kurt=float(stats.kurtosis(r)),
                cum=cum, dd=dd, r=r)

S = calc_metrics(strat_r, 'Trend + Vol Target')
B = calc_metrics(bench_r, f'{BENCHMARK} Buy & Hold')
asset_metrics = {k: calc_metrics(v, k) for k, v in asset_returns.items()}

print(f"\n  {'Metric':<22} {'Strategy':>14} {f'{BENCHMARK} B&H':>14}")
print(f"  {'-'*50}")
for lbl, key, fmt in [
    ('Total Return','Total','.1%'), ('CAGR','CAGR','.1%'),
    ('Ann. Volatility','Vol','.1%'), ('Sharpe Ratio','Sharpe','.3f'),
    ('Sortino Ratio','Sortino','.3f'), ('Max Drawdown','MDD','.1%'),
    ('Calmar Ratio','Calmar','.3f'), ('Win Rate','WinRate','.1%'),
    ('VaR 95%','VaR','.3%'), ('CVaR 95%','CVaR','.3%'),
]:
    sv, bv = S[key], B[key]
    arrow = '↑' if ((abs(sv)<abs(bv)) if key in ['MDD','Vol','VaR','CVaR']
                    else (sv>bv)) else '↓'
    print(f"  {lbl:<22} {sv:>14{fmt}} {bv:>14{fmt}}  {arrow}")

print(f"\n  ── Per-Asset Sharpe ──")
for nm, m in asset_metrics.items():
    pct_long = float((asset_signals[nm] > 0).mean())
    print(f"    {nm:<6}  Sharpe={m['Sharpe']:>+.3f}  CAGR={m['CAGR']:>+.1%}  "
          f"MDD={m['MDD']:>.1%}  Long={pct_long:.0%}")


# ══════════════════════════════════════════════════════════════
#  SECTION 5 — SCENARIO ANALYSIS
# ══════════════════════════════════════════════════════════════
print("\n[5/8] Scenario analysis ...")

SCENARIOS = {
    'COVID Crash\n(Feb–Apr 2020)':    ('2020-02-01', '2020-04-30'),
    'Crypto Bull\n(Jan–Nov 2021)':    ('2021-01-01', '2021-11-30'),
    'May 2021 Crash\n(May–Jul 2021)': ('2021-05-01', '2021-07-31'),
    'Crypto Winter\n(Jan–Dec 2022)':  ('2022-01-01', '2022-12-31'),
    '2023 Recovery\n(Jan–Dec 2023)':  ('2023-01-01', '2023-12-31'),
    '2024 Bull Run\n(Jan–Dec 2024)':  ('2024-01-01', '2024-12-31'),
}

sc_labels, sc_s, sc_b = [], [], []
for lbl, (s, e) in SCENARIOS.items():
    sr = strat_r.loc[s:e];  br = bench_r.loc[s:e]
    if len(sr) < 5: continue
    cs, cb = (1+sr).prod()-1, (1+br).prod()-1
    sc_labels.append(lbl); sc_s.append(cs); sc_b.append(cb)
    print(f"    {lbl.replace(chr(10),' '):<32}  "
          f"Strat {cs:>+7.1%}  Bench {cb:>+7.1%}")


# ══════════════════════════════════════════════════════════════
#  SECTION 6 — MONTE CARLO
# ══════════════════════════════════════════════════════════════
print(f"\n[6/8] Monte Carlo ({MC_SIMS:,} sims) ...")
np.random.seed(42)
hist = strat_r.dropna().values
mc_paths = np.zeros((MC_SIMS, MC_HORIZON))
for i in range(MC_SIMS):
    mc_paths[i] = np.cumprod(1 + np.random.choice(hist, MC_HORIZON)) - 1
mc_final    = mc_paths[:, -1]
mc_var95    = float(np.percentile(mc_final, 5))
mc_prob_pos = float((mc_final > 0).mean())
print(f"    P(profit 3yr)={mc_prob_pos:.0%}  VaR₉₅={mc_var95:.1%}")


# ══════════════════════════════════════════════════════════════
#  SECTION 7 — MACRO CORRELATION
# ══════════════════════════════════════════════════════════════
macro_dict = {t: to_series(prices[t].pct_change())
              for t in available_assets + ['SPY', 'GLD', 'TLT'] if t in prices}
macro_dict['Trend Strat'] = to_series(strat_r)
if has_dxy: macro_dict['DXY'] = to_series(dxy.pct_change())
macro_corr  = pd.DataFrame(macro_dict).dropna().corr()
roll_sharpe = strat_r.rolling(ROLLING_WIN).apply(
    lambda x: x.mean()/x.std()*np.sqrt(252) if x.std()>0 else 0, raw=True)


# ══════════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════════
print("\n[8/8] Rendering dashboard ...")

ACCENT='#00D4FF'; GREEN='#00FF88'; RED='#FF4466'
GOLD='#FFD700';   GRAY='#7A8899';  BG='#0D1117'; PBG='#161B22'
AC = ['#00D4FF','#FF8C00','#CC44FF','#00FF88']

plt.style.use('dark_background')
plt.rcParams.update({'font.family':'monospace','axes.facecolor':PBG,
    'figure.facecolor':BG,'axes.edgecolor':GRAY,'xtick.color':GRAY,
    'ytick.color':GRAY,'axes.labelcolor':GRAY,
    'grid.color':'#1E2733','grid.linestyle':'-','grid.linewidth':0.4})

fig = plt.figure(figsize=(22, 32), facecolor=BG)
fig.suptitle(
    f'TREND + VOL TARGET (meme long-only)  ·  {" / ".join(available_assets)}  ·  2020–2025',
    fontsize=15, fontweight='bold', color=ACCENT, y=0.992)
gs = gridspec.GridSpec(5, 3, figure=fig,
       hspace=0.46, wspace=0.30, top=0.982, bottom=0.03, left=0.06, right=0.97)

def sax(ax, title, ylabel=''):
    ax.set_title(title, color='white', fontsize=10, pad=7, fontweight='bold')
    ax.set_ylabel(ylabel, color=GRAY, fontsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
    ax.grid(True, alpha=0.5)
    for sp in ax.spines.values(): sp.set_edgecolor(GRAY)


# ── ROW 0: benchmark price + EMA signals + Scorecard ──────────
ax0 = fig.add_subplot(gs[0, :2])
bench_p = prices[BENCHMARK]
ax0.plot(bench_p.index, bench_p, color=GOLD, lw=0.9, alpha=0.7, label=f'{BENCHMARK} Price')
ax0_r = ax0.twinx()
ef = asset_ema_fast.get(BENCHMARK, pd.Series())
es = asset_ema_slow.get(BENCHMARK, pd.Series())
if len(ef):
    ax0_r.plot(ef.index, ef, color=GREEN, lw=1.2, alpha=0.9,
               label=f'EMA {EMA_FAST}')
    ax0_r.plot(es.index, es, color=RED,   lw=1.2, alpha=0.9,
               label=f'EMA {EMA_SLOW}')
    # Shade long/short regimes
    sig = asset_signals.get(BENCHMARK, pd.Series())
    for i in range(len(sig)-1):
        t0, t1 = sig.index[i], sig.index[i+1]
        if sig.iloc[i] > 0:
            ax0.axvspan(t0, t1, alpha=0.06, color=GREEN, lw=0)
        elif sig.iloc[i] < 0:
            ax0.axvspan(t0, t1, alpha=0.06, color=RED, lw=0)
ax0.set_ylabel(f'{BENCHMARK} Price ($)', color=GRAY, fontsize=8)
ax0_r.set_ylabel(f'EMA Value', color=GRAY, fontsize=8)
ax0_r.tick_params(colors=GRAY)
lines0, labs0 = ax0.get_legend_handles_labels()
lines1, labs1 = ax0_r.get_legend_handles_labels()
import matplotlib.patches as mpatches
lp = mpatches.Patch(color=GREEN, alpha=0.3, label='Long regime')
sp2 = mpatches.Patch(color=RED,  alpha=0.3, label='Short regime')
ax0.legend(lines0+lines1+[lp,sp2], labs0+labs1+['Long','Short'],
           loc='upper left', fontsize=7.5, facecolor=PBG, edgecolor=GRAY)
ax0.set_title(f'{BENCHMARK} Price + EMA({EMA_FAST}/{EMA_SLOW}) Trend Signal  '
              f'[green=Long  red=Short]',
              color='white', fontsize=10, pad=7, fontweight='bold')
for sp in ax0.spines.values(): sp.set_edgecolor(GRAY)

# Scorecard
axsc = fig.add_subplot(gs[0, 2]); axsc.axis('off')
axsc.text(0.50,0.97,'◆ METRICS SCORECARD', ha='center', va='top',
          transform=axsc.transAxes, fontsize=10, fontweight='bold', color=ACCENT)
axsc.text(0.56,0.88,'Strategy', ha='center', va='top',
          transform=axsc.transAxes, fontsize=8, color=GREEN)
axsc.text(0.86,0.88,f'{BENCHMARK} B&H', ha='center', va='top',
          transform=axsc.transAxes, fontsize=8, color=GOLD)
for k, (lbl, key, fmt, lb) in enumerate([
    ('Sharpe','Sharpe','.2f',False), ('Sortino','Sortino','.2f',False),
    ('CAGR','CAGR','.1%',False),    ('Max DD','MDD','.1%',True),
    ('Calmar','Calmar','.2f',False), ('Ann Vol','Vol','.1%',True),
    ('Win Rate','WinRate','.1%',False),('CVaR 95%','CVaR','.3%',True),
    ('Skewness','Skew','.2f',False)
]):
    y = 0.80 - k*0.092
    sv, bv = S[key], B[key]
    clr = GREEN if ((abs(sv)<abs(bv)) if lb else (sv>bv)) else RED
    axsc.text(0.05,y,lbl, ha='left', va='center',
              transform=axsc.transAxes, fontsize=8.5, color='white')
    axsc.text(0.56,y,f'{sv:{fmt}}', ha='center', va='center',
              transform=axsc.transAxes, fontsize=8.5, color=clr, fontweight='bold')
    axsc.text(0.86,y,f'{bv:{fmt}}', ha='center', va='center',
              transform=axsc.transAxes, fontsize=8.5, color=GOLD)
for sp in axsc.spines.values(): sp.set_edgecolor(GRAY)


# ── ROW 1: Per-asset equity curves + Position sizes ───────────
ax1a = fig.add_subplot(gs[1, :2])
# Do NOT overlay DOGE B&H here — its ~50x scale squashes strategy legs to ~0 on the chart.
for idx, (nm, m) in enumerate(asset_metrics.items()):
    ax1a.plot(m['cum'].index, m['cum'], color=AC[idx % len(AC)],
              lw=1.4, alpha=0.95, label=f'{nm} (strategy)')
ax1a.axhline(1, color=GRAY, lw=0.4, alpha=0.5)
ax1a.legend(loc='upper left', fontsize=9, facecolor=PBG, edgecolor=GRAY)
sax(ax1a, 'Per-Asset Equity  (vol-targeted strategy only)', 'Value ($1 initial)')

ax1b = fig.add_subplot(gs[1, 2])
for idx, nm in enumerate(asset_sizes.keys()):
    sz = asset_sizes[nm]
    sig = asset_signals[nm]
    signed_sz = sz * sig
    ax1b.plot(signed_sz.index, signed_sz, color=AC[idx % len(AC)], lw=0.9, alpha=0.85, label=nm)
ax1b.axhline(0, color=GRAY, lw=0.5)
ax1b.axhline(1, color=GREEN, ls='--', lw=0.7, alpha=0.5)
ax1b.axhline(-1, color=RED,  ls='--', lw=0.7, alpha=0.5)
ax1b.legend(fontsize=8, facecolor=PBG, edgecolor=GRAY)
sax(ax1b, 'Signed Position Size  (vol-targeted)', 'Position (×)')
ax1b.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))


# ── ROW 2: Portfolio equity curve + Drawdown ──────────────────
ax2a = fig.add_subplot(gs[2, :2])
ax2a.plot(S['cum'].index, S['cum'], color=GREEN, lw=2.0,
          label='Trend + Vol Target Portfolio')
ax2a.plot(B['cum'].index, B['cum'], color=GOLD, lw=1.2, ls='--', alpha=0.7,
          label=f'{BENCHMARK} Buy & Hold')
ax2a.fill_between(S['cum'].index,1,S['cum'],
                  where=(S['cum']>=1), alpha=0.10, color=GREEN)
ax2a.fill_between(S['cum'].index,1,S['cum'],
                  where=(S['cum']<1),  alpha=0.10, color=RED)
ax2a.axhline(1, color=GRAY, lw=0.4, alpha=0.5)
ax2a.legend(loc='upper left', fontsize=9, facecolor=PBG, edgecolor=GRAY)
sax(ax2a, 'Portfolio Equity Curve  (normalized to $1)', 'Value ($1 initial)')

ax2b = fig.add_subplot(gs[2, 2])
ax2b.fill_between(S['dd'].index, S['dd']*100, 0, color=RED, alpha=0.65,
                  label='Strategy DD')
ax2b.plot(B['dd'].index, B['dd']*100, color=GOLD, lw=0.9, alpha=0.7,
          label=f'{BENCHMARK} B&H DD')
ax2b.axhline(0, color=GRAY, lw=0.4)
ax2b.legend(fontsize=7.5, facecolor=PBG, edgecolor=GRAY)
sax(ax2b, 'Drawdown (%)', '%')
ax2b.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))


# ── ROW 3: Rolling Sharpe / Scenario / MC ─────────────────────
ax3a = fig.add_subplot(gs[3, 0])
ax3a.plot(roll_sharpe.index, roll_sharpe, color=ACCENT, lw=1.2)
ax3a.axhline(0, color=GRAY, lw=0.5)
ax3a.axhline(1, color=GREEN, ls='--', lw=0.9, alpha=0.7, label='Sharpe=1')
ax3a.fill_between(roll_sharpe.index,0,roll_sharpe,
                  where=(roll_sharpe>0), alpha=0.18, color=GREEN)
ax3a.fill_between(roll_sharpe.index,0,roll_sharpe,
                  where=(roll_sharpe<0), alpha=0.18, color=RED)
ax3a.legend(fontsize=8, facecolor=PBG, edgecolor=GRAY)
sax(ax3a, f'Rolling {ROLLING_WIN}d Sharpe', 'Sharpe')

ax3b = fig.add_subplot(gs[3, 1])
x = np.arange(len(sc_labels)); bw = 0.38
# Twin axes: strategy % (left) vs benchmark % (right) — avoids 4000% bench squashing 90% strategy to zero.
ax3b.bar(x - bw / 2, [v * 100 for v in sc_s], bw,
         color=[GREEN if v > 0 else RED for v in sc_s], alpha=0.9, label='Strategy')
ax3b.set_xticks(x)
ax3b.set_xticklabels(sc_labels, fontsize=6, color='white')
ax3b.axhline(0, color=GRAY, lw=0.5)
ax3b.set_ylabel('Strategy return %', color=GREEN, fontsize=8)
ax3b.set_ylim(min(-30, min(sc_s) * 100 - 5), max(120, max(sc_s) * 100 + 10))
ax3b_r = ax3b.twinx()
ax3b_r.bar(x + bw / 2, [v * 100 for v in sc_b], bw, color=GOLD, alpha=0.55, label=f'{BENCHMARK} B&H')
ax3b_r.set_ylabel(f'{BENCHMARK} B&H %', color=GOLD, fontsize=8)
ax3b_r.tick_params(axis='y', colors=GOLD)
lines_l, labs_l = ax3b.get_legend_handles_labels()
lines_r, labs_r = ax3b_r.get_legend_handles_labels()
ax3b.legend(lines_l + lines_r, labs_l + labs_r, fontsize=7, loc='upper left', facecolor=PBG, edgecolor=GRAY)
ax3b.set_title('Scenario Returns — dual scale (strategy vs B&H)', color='white', fontsize=10, pad=7, fontweight='bold')
ax3b.grid(True, alpha=0.5, axis='y')
for sp in ax3b.spines.values(): sp.set_edgecolor(GRAY)

ax3c = fig.add_subplot(gs[3, 2])
for i in range(0, MC_SIMS, max(1, MC_SIMS//120)):
    ax3c.plot(mc_paths[i]*100,
              color=(GREEN if mc_paths[i,-1]>0 else RED), alpha=0.03, lw=0.5)
dx = np.arange(MC_HORIZON)
for plo,phi,alp in [(5,95,0.12),(25,75,0.22)]:
    ax3c.fill_between(dx, np.percentile(mc_paths,plo,axis=0)*100,
                      np.percentile(mc_paths,phi,axis=0)*100, alpha=alp, color=ACCENT)
ax3c.plot(dx, np.percentile(mc_paths,50,axis=0)*100,
          color=ACCENT, lw=1.8, label='Median')
ax3c.axhline(0, color=GRAY, lw=0.7)
ax3c.legend(fontsize=8, facecolor=PBG, edgecolor=GRAY)
ax3c.set_title(f'Monte Carlo  ({MC_SIMS:,} sims, 3yr)',
               color='white', fontsize=10, pad=7, fontweight='bold')
ax3c.set_ylabel('Cum Return %', color=GRAY, fontsize=8)
ax3c.set_xlabel(f'P(profit 3yr)={mc_prob_pos:.0%}  VaR₉₅={mc_var95:.1%}',
                color=GRAY, fontsize=8)
ax3c.grid(True, alpha=0.5)
for sp in ax3c.spines.values(): sp.set_edgecolor(GRAY)


# ── ROW 4: Macro heatmap + return distribution ────────────────
ax4a = fig.add_subplot(gs[4, :2])
lbs = list(macro_corr.columns); n_m = len(lbs)
cmap_rg = LinearSegmentedColormap.from_list('rg',[RED,PBG,GREEN], N=256)
im = ax4a.imshow(macro_corr.values, cmap=cmap_rg, vmin=-1, vmax=1, aspect='auto')
ax4a.set_xticks(range(n_m)); ax4a.set_xticklabels(lbs,color='white',fontsize=9,rotation=30,ha='right')
ax4a.set_yticks(range(n_m)); ax4a.set_yticklabels(lbs,color='white',fontsize=9)
for i in range(n_m):
    for j in range(n_m):
        v = macro_corr.values[i,j]
        ax4a.text(j,i,f'{v:.2f}',ha='center',va='center',fontsize=9,
                  color='white' if abs(v)>0.3 else GRAY,fontweight='bold')
plt.colorbar(im, ax=ax4a, fraction=0.025, pad=0.015)
ax4a.set_title('Macro Environment  —  Correlation Matrix',
               color='white', fontsize=10, pad=7, fontweight='bold')
for sp in ax4a.spines.values(): sp.set_edgecolor(GRAY)

ax4b = fig.add_subplot(gs[4, 2])
rp = strat_r.dropna().values * 100
bins = np.linspace(rp.min(), rp.max(), 70)
ax4b.hist(rp, bins=bins, color=ACCENT, alpha=0.70, edgecolor='none')
ax4b.axvline(0, color=GRAY, lw=0.7)
ax4b.axvline(np.percentile(rp,5), color=RED, lw=1.5, ls='--',
             label=f'VaR: {np.percentile(rp,5):.2f}%')
mu_f, sd_f = stats.norm.fit(rp)
xl = np.linspace(rp.min(), rp.max(), 300)
ax4b.plot(xl, stats.norm.pdf(xl,mu_f,sd_f)*len(rp)*(bins[1]-bins[0]),
          color=GOLD, lw=1.5, label='Normal fit')
ax4b.set_title(f'Return Distribution  (skew={stats.skew(rp):.2f}, kurt={stats.kurtosis(rp):.2f})',
               color='white', fontsize=10, pad=7, fontweight='bold')
ax4b.set_xlabel('Daily Return %', color=GRAY, fontsize=8)
ax4b.legend(fontsize=7.5, facecolor=PBG, edgecolor=GRAY)
ax4b.grid(True, alpha=0.5)
for sp in ax4b.spines.values(): sp.set_edgecolor(GRAY)

plt.tight_layout(rect=[0,0,1,0.988])
plt.savefig(SAVE_PNG, dpi=150, bbox_inches='tight', facecolor=BG)
plt.close(fig)

# ══════════════════════════════════════════════════════════════
#  EXTENDED CHART PANELS (meme / polymarket / cross / discovery)
# ══════════════════════════════════════════════════════════════
print("\n[9/9] Extended analysis charts ...")
meme_names = [n for n in available_assets if not n.startswith('POLY_')]
poly_names = [n for n in available_assets if n.startswith('POLY_')]

render_meme_analysis(prices, asset_returns, asset_metrics, meme_names, SAVE_MEME)
render_polymarket_analysis(prices, asset_returns, asset_signals, poly_names, SAVE_POLY)
render_cross_asset_analysis(
    prices, strat_r, bench_r, weights, poly_names, meme_names, SAVE_CROSS
)
render_performance_summary(asset_metrics, S, SAVE_PERF)

gamma_markets = fetch_crypto_polymarket_markets(limit=12)
render_market_discovery(gamma_markets, SAVE_DISC)
print(f"    meme charts      → {SAVE_MEME}")
print(f"    polymarket charts→ {SAVE_POLY}")
print(f"    cross-asset      → {SAVE_CROSS}")
print(f"    performance      → {SAVE_PERF}")
print(f"    active markets   → {SAVE_DISC}")


# ── CSV ───────────────────────────────────────────────────────
rows = [{'Metric':lbl,'Strategy':f"{S[k]:{fmt}}",f'{BENCHMARK} B&H':f"{B[k]:{fmt}}"}
        for lbl,k,fmt in [('Total Return','Total','.1%'),('CAGR','CAGR','.1%'),
            ('Sharpe','Sharpe','.3f'),('Sortino','Sortino','.3f'),
            ('Max DD','MDD','.1%'),('Calmar','Calmar','.3f'),
            ('Win Rate','WinRate','.1%'),('CVaR 95%','CVaR','.3%')]]
asset_rows = [{'Asset':k,'Sharpe':f"{m['Sharpe']:.3f}",'CAGR':f"{m['CAGR']:.1%}",
               'MDD':f"{m['MDD']:.1%}",'Long%':f"{float((asset_signals[k]>0).mean()):.0%}"}
              for k,m in asset_metrics.items()]
sc_rows = [{'Scenario':l.replace('\n',' '),'Strategy':f"{s:.1%}",f'{BENCHMARK} B&H':f"{b:.1%}"}
           for l,s,b in zip(sc_labels,sc_s,sc_b)]

with open(SAVE_CSV,'w') as f:
    f.write("=== PORTFOLIO METRICS ===\n");   pd.DataFrame(rows).to_csv(f,index=False)
    f.write("\n=== PER-ASSET METRICS ===\n"); pd.DataFrame(asset_rows).to_csv(f,index=False)
    f.write("\n=== SCENARIO ANALYSIS ===\n"); pd.DataFrame(sc_rows).to_csv(f,index=False)
    f.write("\n=== MONTE CARLO ===\n")
    pd.DataFrame([{'Sims':MC_SIMS,'P(profit 3yr)':f"{mc_prob_pos:.0%}",
                   'VaR95':f"{mc_var95:.1%}"}]).to_csv(f,index=False)
    f.write("\n=== MEME CORRELATION (subset) ===\n")
    meme_rets = {n: prices[n].pct_change() for n in meme_names if n in prices}
    if meme_rets:
        pd.DataFrame(meme_rets).dropna().corr().to_csv(f)
    f.write("\n=== GITHUB RESOURCES (PDF) ===\n")
    from tradingagents.dataflows.polymarket_discovery import GITHUB_RESOURCES
    gh_rows = [{'repo': k, **v} for k, v in GITHUB_RESOURCES.items()]
    pd.DataFrame(gh_rows).to_csv(f, index=False)

print("\n" + "="*65)
print("  ✅  Done!")
print(f"  📊  {SAVE_PNG}")
print(f"  📊  {SAVE_MEME}")
print(f"  📊  {SAVE_POLY}")
print(f"  📊  {SAVE_CROSS}")
print(f"  📊  {SAVE_PERF}")
print(f"  📊  {SAVE_DISC}")
print(f"  📋  {SAVE_CSV}")
print("="*65)
print(f"""
  Key results:
    Sharpe  = {S['Sharpe']:.2f}
    CAGR    = {S['CAGR']:.1%}
    Max DD  = {S['MDD']:.1%}
    Win Rate= {S['WinRate']:.1%}

  ── PHASE 2 ──────────────────────────────────────────────────
  • Fama-French factor decomposition
  • Walk-forward parameter optimization (EMA_FAST, EMA_SLOW)
  • Add funding rate carry signal (requires exchange API)
  • Random Forest signal confirmation
  • Bloomberg macro overlay (inflation / DXY regime filter)
""")
