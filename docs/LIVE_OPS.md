# Live operations (16:00 America/New_York)

## Universe

- **POLY_GTA** — Polymarket CLOB (`gta-vi-released-before-june-2026`)
- **DOGE** — yfinance spot
- **WIF** — yfinance spot

**Public URL for team:** see [DEPLOY_LIVE_DASHBOARD.md](./DEPLOY_LIVE_DASHBOARD.md) (Render / Docker).

## Real money checklist

1. Dashboard must show **v2.1-production**, **3 PROD tabs**, and **「When do we trade?」**.
2. After code update — restart server and hard-refresh (**Cmd+Shift+R**):
   ```bash
   lsof -i :8765 && kill <PID>
   python scripts/polymarket_meme_run.py live-app
   ```
3. Trade **Live composite** gated signals only (poly long-short / latency removed).
4. **News gate** score ≤ −0.35 → do not open new risk.
5. CLOB live (start small): `POLYMARKET_LIVE=1` + `POLYMARKET_PRIVATE_KEY`.
6. **Kraken CEX** (DOGE/WIF): set `KRAKEN_API_KEY` + `KRAKEN_API_SECRET` in `.env`. Default **dry-run**; live with `KRAKEN_LIVE=1`. Shorts need `KRAKEN_USE_MARGIN=1`.
7. Health check: `python scripts/kraken_health_check.py` (add `--live --validate-only` to test auth without submitting).
8. **All 7 sleeves** show per-sleeve intents on dashboard; set `LIVE_ALPHA_SLEEVES=1` to execute α sleeves on refresh (default: PROD whale+pairs only).

```bash
# .env (never commit)
KRAKEN_API_KEY=...
KRAKEN_API_SECRET=...
KRAKEN_LIVE=0
KRAKEN_MAX_ORDER_USD=50
KRAKEN_MAX_DAILY_NOTIONAL_USD=200
python scripts/kraken_health_check.py
```

## Interactive LIVE UI (click strategy tabs, refresh on open)

```bash
python scripts/polymarket_meme_run.py live-app
# browser: http://127.0.0.1:8765/
```

Each page load calls `GET /api/live` and recomputes returns, Barra β, ECB/FRED news, and signals. Use **Refresh now** or enable **Auto 60s**.

## Daily command (PNG + CSV archive)

```bash
python scripts/polymarket_meme_run.py live-daily
# or full ops (live + strategy tabs + master):
python scripts/polymarket_meme_run.py daily-ops
```

## Outputs

| Path | Content |
|------|---------|
| `assets/dashboard_outputs/polymarket_strategy_tabs.png` | Latest strategy tabs + **MSCI Barra-style** factor β |
| `assets/dashboard_outputs/polymarket_strategy_tabs_metrics.csv` | Win rate, Sharpe, R² per strategy |
| `assets/dashboard_outputs/live/polymarket_live_snapshot_*_ny.csv` | ECB headlines, CLOB intents, Barra attribution, signals |
| `assets/dashboard_outputs/live/polymarket_strategy_tabs_*_ny.png` | Timestamped archive copy |

## News (open source)

- **ECB RSS** — always fetched
- **FRED** — optional; set `FRED_API_KEY` in environment for Fed funds / CPI latest prints

## MSCI Barra

Licensed **MSCI Barra** is not included. We use **ETF proxies** for macro + style factors (`tradingagents/quant/barra_risk_factors.py`). Label dashboards as **Barra-style proxy**.

## CLOB live trading

Default: **dry run** (orders logged, not sent).

```bash
export POLYMARKET_PRIVATE_KEY="0x..."
export POLYMARKET_CHAIN_ID="137"
export POLYMARKET_LIVE=1
pip install py-clob-client   # required for live submission (order builder WIP)
python scripts/polymarket_meme_run.py live-daily --live
```

Meme legs (DOGE/WIF) execute on **Kraken REST** when `KRAKEN_LIVE=1` (see `tradingagents/execution/kraken_spot.py`). Risk caps: `KRAKEN_MAX_ORDER_USD`, `KRAKEN_MAX_DAILY_NOTIONAL_USD`.

## Cron (macOS example, 16:00 ET weekdays)

```cron
0 16 * * 1-5 cd /Users/zhouziqing/TradingAgents && /path/to/python scripts/polymarket_daily_ops.py >> logs/live_ops.log 2>&1
```

## Strategies on tabs

1. portfolio_ema_vol  
2. whale_flow  
3. poly_ema_ls  
4. latency_doge_poly  
5. **pairs_stat_arb** (DOGE/WIF)  
6. **macro_regime_tilt** (Barra macro regimes)  
7. bundle_yes_no (research)
