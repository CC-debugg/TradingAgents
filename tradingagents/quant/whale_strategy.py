"""Whale trade-flow signals → backtest + walk-forward on Polymarket Yes probability."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tradingagents.quant.trading_costs import FEE_BPS_PER_LEG


@dataclass
class WhaleStrategyConfig:
    flow_window: int = 7
    min_flow_usd: float = 12_000.0
    min_whale_trades: int = 4
    fee_bps: float = FEE_BPS_PER_LEG
    hold_days: int = 1
    require_trend_confirm: bool = True
    prob_ema_fast: int = 5
    prob_ema_slow: int = 15


# Legacy defaults for comparison tab
LEGACY_WHALE_CONFIG = WhaleStrategyConfig(
    flow_window=5,
    min_flow_usd=5000.0,
    min_whale_trades=1,
    require_trend_confirm=False,
)


def signed_whale_flow(trades: pd.DataFrame) -> pd.DataFrame:
    """Per-trade signed USD: BUY=+, SELL=-, on Yes/No outcome."""
    if trades.empty:
        return pd.DataFrame()
    df = trades.copy()
    sign = np.where(df["side"].str.upper() == "BUY", 1.0, -1.0)
    df["signed_usd"] = sign * df["cash_usd"].astype(float)
    return df


def daily_whale_flow(trades: pd.DataFrame) -> pd.DataFrame:
    """Aggregate whale signed USD by calendar day and outcome."""
    df = signed_whale_flow(trades)
    if df.empty:
        return pd.DataFrame()
    df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_convert(None).dt.normalize()
    yes = df[df["outcome"].str.upper() == "YES"]
    no = df[df["outcome"].str.upper() == "NO"]
    y = yes.groupby("date")["signed_usd"].sum().rename("flow_yes_usd")
    n = no.groupby("date")["signed_usd"].sum().rename("flow_no_usd")
    cnt = df.groupby("date").size().rename("n_trades")
    out = pd.concat([y, n, cnt], axis=1).fillna(0)
    out["flow_net_usd"] = out["flow_yes_usd"] - out["flow_no_usd"]
    return out.sort_index()


def whale_flow_signal(flow: pd.DataFrame, cfg: WhaleStrategyConfig) -> pd.Series:
    """
    +1 = follow whale net buying pressure on Yes (vs No).
    0 = flat when rolling flow below threshold.
    """
    if flow.empty:
        return pd.Series(dtype=float)
    net = flow["flow_net_usd"].rolling(cfg.flow_window, min_periods=1).sum()
    sig = pd.Series(0.0, index=flow.index)
    sig[net >= cfg.min_flow_usd] = 1.0
    sig[net <= -cfg.min_flow_usd] = -1.0
    return sig


def whale_flow_signal_v2(
    flow: pd.DataFrame,
    prob: pd.Series,
    cfg: WhaleStrategyConfig | None = None,
) -> pd.Series:
    """
    Higher-conviction whale follow: min flow + min trade count + EMA trend confirm.
    Fewer trades, better alignment → typically higher win rate vs legacy.
    """
    cfg = cfg or WhaleStrategyConfig()
    if flow.empty:
        return pd.Series(dtype=float)
    net = flow["flow_net_usd"].rolling(cfg.flow_window, min_periods=1).sum()
    n_tr = flow.get("n_trades", pd.Series(0, index=flow.index)).rolling(cfg.flow_window, min_periods=1).sum()
    sig = pd.Series(0.0, index=flow.index)
    strong = (net.abs() >= cfg.min_flow_usd) & (n_tr >= cfg.min_whale_trades)
    sig[strong & (net >= cfg.min_flow_usd)] = 1.0
    sig[strong & (net <= -cfg.min_flow_usd)] = -1.0

    if cfg.require_trend_confirm and len(prob.dropna()) > cfg.prob_ema_slow:
        p = prob.dropna().sort_index()
        ef = p.ewm(span=cfg.prob_ema_fast, adjust=False).mean()
        es = p.ewm(span=cfg.prob_ema_slow, adjust=False).mean()
        trend = pd.Series(0.0, index=p.index)
        trend[ef > es] = 1.0
        trend[ef < es] = -1.0
        sig = sig.reindex(p.index).fillna(0.0)
        tr = trend.reindex(sig.index).fillna(0.0)
        sig[(sig > 0) & (tr < 0)] = 0.0
        sig[(sig < 0) & (tr > 0)] = 0.0
    return sig


def latest_whale_signal(
    flow: pd.DataFrame,
    prob: pd.Series,
    cfg: WhaleStrategyConfig | None = None,
) -> dict[str, float | str]:
    """Rolling-window whale conviction for live dashboard / CLOB."""
    return whale_execution_detail(flow, prob, None, cfg)


def whale_execution_detail(
    flow: pd.DataFrame,
    prob: pd.Series,
    trades: pd.DataFrame | None = None,
    cfg: WhaleStrategyConfig | None = None,
) -> dict[str, float | str | list | bool | None]:
    """Rich whale snapshot: flow, volume, EMA trend, threshold checks."""
    cfg = cfg or WhaleStrategyConfig()
    empty: dict[str, float | str | list | bool | None] = {
        "signal": 0.0,
        "flow_net_usd": 0.0,
        "flow_yes_usd": 0.0,
        "flow_no_usd": 0.0,
        "n_trades": 0,
        "volume_usd": 0.0,
        "avg_trade_usd": 0.0,
        "max_trade_usd": 0.0,
        "flow_window_days": cfg.flow_window,
        "min_flow_usd": cfg.min_flow_usd,
        "min_whale_trades": cfg.min_whale_trades,
        "mode": "v2_conviction",
        "prob_last": None,
        "prob_as_of": None,
        "ema_fast": None,
        "ema_slow": None,
        "trend": "unknown",
        "checks": [],
        "daily_flow": [],
        "trades_through": None,
    }
    if flow.empty or prob.empty:
        return empty

    sig = whale_flow_signal_v2(flow, prob, cfg)
    last = float(sig.dropna().iloc[-1]) if len(sig.dropna()) else 0.0
    tail = flow.iloc[-cfg.flow_window :]
    flow_net = float(tail["flow_net_usd"].sum())
    flow_yes = float(tail["flow_yes_usd"].sum()) if "flow_yes_usd" in tail else 0.0
    flow_no = float(tail["flow_no_usd"].sum()) if "flow_no_usd" in tail else 0.0
    n_tr = int(tail["n_trades"].sum()) if "n_trades" in tail else 0

    p = prob.dropna().sort_index()
    prob_last = float(p.iloc[-1])
    prob_as_of = str(p.index[-1].date())
    ef = es = None
    trend = "flat"
    if len(p) > cfg.prob_ema_slow:
        ef = float(p.ewm(span=cfg.prob_ema_fast, adjust=False).mean().iloc[-1])
        es = float(p.ewm(span=cfg.prob_ema_slow, adjust=False).mean().iloc[-1])
        if ef > es:
            trend = "up"
        elif ef < es:
            trend = "down"

    volume_usd = avg_trade = max_trade = 0.0
    trades_through = None
    if trades is not None and not trades.empty and len(tail):
        tdf = trades.copy()
        tdf["date"] = pd.to_datetime(tdf["timestamp"]).dt.tz_convert(None).dt.normalize()
        win_start = pd.Timestamp(tail.index.min()).normalize()
        win_end = pd.Timestamp(tail.index.max()).normalize()
        mask = (tdf["date"] >= win_start) & (tdf["date"] <= win_end)
        tw = tdf.loc[mask]
        if not tw.empty:
            volume_usd = float(tw["cash_usd"].sum())
            avg_trade = float(tw["cash_usd"].mean())
            max_trade = float(tw["cash_usd"].max())
            trades_through = str(tw["timestamp"].max().date())

    daily_flow = []
    for dt, row in tail.iterrows():
        daily_flow.append(
            {
                "date": str(pd.Timestamp(dt).date()),
                "flow_net_usd": round(float(row["flow_net_usd"]), 0),
                "flow_yes_usd": round(float(row.get("flow_yes_usd", 0)), 0),
                "flow_no_usd": round(float(row.get("flow_no_usd", 0)), 0),
                "n_trades": int(row.get("n_trades", 0)),
            }
        )

    flow_ok = abs(flow_net) >= cfg.min_flow_usd
    trades_ok = n_tr >= cfg.min_whale_trades
    direction = "long_yes" if flow_net >= cfg.min_flow_usd else "short_yes" if flow_net <= -cfg.min_flow_usd else "flat"
    trend_ok = True
    if cfg.require_trend_confirm and trend in ("up", "down"):
        if direction == "long_yes" and trend != "up":
            trend_ok = False
        if direction == "short_yes" and trend != "down":
            trend_ok = False
    if direction == "flat":
        trend_ok = False

    checks = [
        {
            "id": "flow",
            "label": f"|7d net flow| ≥ ${cfg.min_flow_usd:,.0f}",
            "ok": flow_ok,
            "value": f"${flow_net:,.0f} (yes ${flow_yes:,.0f} / no ${flow_no:,.0f})",
        },
        {
            "id": "trades",
            "label": f"≥ {cfg.min_whale_trades} large trades in window",
            "ok": trades_ok,
            "value": str(n_tr),
        },
        {
            "id": "trend",
            "label": f"EMA({cfg.prob_ema_fast}) vs EMA({cfg.prob_ema_slow}) agrees",
            "ok": trend_ok,
            "value": f"trend={trend}" + (f" · fast={ef:.3f} slow={es:.3f}" if ef and es else ""),
        },
    ]

    return {
        "signal": last,
        "flow_net_usd": flow_net,
        "flow_yes_usd": flow_yes,
        "flow_no_usd": flow_no,
        "n_trades": n_tr,
        "volume_usd": round(volume_usd, 2),
        "avg_trade_usd": round(avg_trade, 2),
        "max_trade_usd": round(max_trade, 2),
        "flow_window_days": cfg.flow_window,
        "min_flow_usd": cfg.min_flow_usd,
        "min_whale_trades": cfg.min_whale_trades,
        "mode": "v2_conviction",
        "prob_last": round(prob_last, 4),
        "prob_as_of": prob_as_of,
        "ema_fast": round(ef, 4) if ef is not None else None,
        "ema_slow": round(es, 4) if es is not None else None,
        "trend": trend,
        "checks": checks,
        "daily_flow": daily_flow,
        "trades_through": trades_through,
        "direction_hint": direction,
    }


def backtest_whale_strategy(
    prob: pd.Series,
    signal: pd.Series,
    fee_bps: float = FEE_BPS_PER_LEG,
) -> tuple[pd.Series, pd.DataFrame]:
    """
    PnL from positioning on Yes implied probability changes.
    Returns (daily_returns, trade_log).
    """
    p = prob.dropna().sort_index()
    p.index = pd.to_datetime(p.index).tz_localize(None).normalize()
    sig = signal.reindex(p.index).fillna(0).shift(1).fillna(0)
    ret = p.pct_change()
    tc = (sig.diff().abs() > 0) * (fee_bps / 10_000)
    strat_r = sig * ret - tc

    active = sig != 0
    trade_log = pd.DataFrame(
        {
            "date": p.index,
            "signal": sig.values,
            "prob": p.values,
            "daily_return": strat_r.values,
            "in_position": active.values,
        }
    )
    return strat_r, trade_log


def strategy_metrics(returns: pd.Series, trade_log: pd.DataFrame | None = None) -> dict[str, float]:
    r = returns.dropna().replace([np.inf, -np.inf], np.nan).dropna()
    if len(r) < 2:
        return {
            "n_days": float(len(r)),
            "win_rate": 0.0,
            "sharpe": 0.0,
            "total_return": 0.0,
            "cagr": 0.0,
            "n_trades": 0,
            "max_dd": 0.0,
        }

    if trade_log is not None and not trade_log.empty and "signal" in trade_log.columns:
        tlog = trade_log.set_index("date")
        aligned = tlog.reindex(r.index)
        positioned = aligned["signal"].abs() > 0
        active_r = r[positioned]
        n_trades = int((aligned["signal"].diff().abs() > 0).sum())
    else:
        active_r = r[r != 0]
        n_trades = int((r != 0).sum())

    win_rate = float((active_r > 0).mean()) if len(active_r) else 0.0
    tot = float((1 + r).prod() - 1)
    n = len(r)
    cagr = float((1 + tot) ** (252 / n) - 1) if n >= 1 and tot > -1 else 0.0
    sh = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0.0
    cum = (1 + r).cumprod()
    return {
        "n_days": float(n),
        "win_rate": win_rate,
        "win_rate_all_days": float((r > 0).mean()),
        "sharpe": sh,
        "total_return": tot,
        "cagr": cagr,
        "n_trades": n_trades,
        "max_dd": float((cum / cum.cummax() - 1).min()),
    }


def walk_forward_whale(
    prob: pd.Series,
    flow: pd.DataFrame,
    train_days: int = 30,
    test_days: int = 14,
    windows: tuple[int, ...] = (3, 5, 7, 10),
    thresholds: tuple[float, ...] = (2000, 5000, 10000, 20000),
    fee_bps: float = FEE_BPS_PER_LEG,
) -> tuple[pd.DataFrame, pd.Series, WhaleStrategyConfig]:
    """
    Rolling train: pick (flow_window, min_flow_usd) by train Sharpe.
    Test: run whale signal on next test_days.
    """
    idx = prob.dropna().index.intersection(flow.index)
    idx = pd.DatetimeIndex(sorted(idx))
    if len(idx) < train_days + test_days + 10:
        return pd.DataFrame(), pd.Series(dtype=float), WhaleStrategyConfig()

    rows = []
    oos_parts: list[pd.Series] = []
    best_cfg = WhaleStrategyConfig()

    i = train_days
    while i + test_days <= len(idx):
        train_idx = idx[i - train_days : i]
        test_idx = idx[i : i + test_days]
        best_sh = -np.inf
        best = WhaleStrategyConfig()
        for w in windows:
            for th in thresholds:
                cfg = WhaleStrategyConfig(flow_window=w, min_flow_usd=th, fee_bps=fee_bps)
                sig = whale_flow_signal(flow.loc[train_idx], cfg)
                tr, tlog = backtest_whale_strategy(prob, sig, fee_bps=fee_bps)
                sh = strategy_metrics(tr.loc[train_idx], tlog)["sharpe"]
                if sh > best_sh:
                    best_sh = sh
                    best = cfg
        sig_test = whale_flow_signal(flow, best)
        tr_test, tlog = backtest_whale_strategy(prob, sig_test, fee_bps=fee_bps)
        tr_test = tr_test.loc[test_idx]
        m = strategy_metrics(tr_test, tlog)
        rows.append(
            {
                "train_start": train_idx[0].date(),
                "train_end": train_idx[-1].date(),
                "test_start": test_idx[0].date(),
                "test_end": test_idx[-1].date(),
                "flow_window": best.flow_window,
                "min_flow_usd": best.min_flow_usd,
                "train_sharpe": best_sh,
                "test_sharpe": m["sharpe"],
                "test_return": m["total_return"],
                "test_win_rate": m["win_rate"],
                "test_n_trades": m["n_trades"],
            }
        )
        oos_parts.append(tr_test)
        best_cfg = best
        i += test_days

    folds = pd.DataFrame(rows)
    if oos_parts:
        oos = pd.concat(oos_parts).sort_index()
        oos = oos[~oos.index.duplicated(keep="last")]
    else:
        oos = pd.Series(dtype=float)
    return folds, oos, best_cfg
