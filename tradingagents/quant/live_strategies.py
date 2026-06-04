"""Collect daily returns for production strategies (live pipeline)."""

from __future__ import annotations

import pandas as pd

from tradingagents.dataflows.polymarket_gamma import fetch_polymarket_daily_ohlcv
from tradingagents.dataflows.polymarket_whale import (
    DEFAULT_CONDITION_IDS,
    fetch_large_trades_history,
    fetch_market_meta,
)
from tradingagents.quant.live_execution import build_live_composite_returns
from tradingagents.quant.pairs_stat_arb import pairs_spread_returns_v2
from tradingagents.quant.polymarket_strategy import StrategyConfig, load_universe_prices
from tradingagents.quant.whale_strategy import (
    WhaleStrategyConfig,
    backtest_whale_strategy,
    daily_whale_flow,
    whale_flow_signal_v2,
)

DEFAULT_SLUG = "gta-vi-released-before-june-2026"


def _prob_from_trades(trades: pd.DataFrame) -> pd.Series:
    if trades.empty:
        return pd.Series(dtype=float)
    df = trades.copy()
    df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_convert(None).dt.normalize()
    yes = df[df["outcome"].str.upper() == "YES"].groupby("date")["price"].last()
    no = df[df["outcome"].str.upper() == "NO"].groupby("date")["price"].last()
    idx = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
    yes = yes.reindex(idx).ffill()
    no = no.reindex(idx).ffill()
    prob = yes.copy()
    prob[prob.isna()] = (1.0 - no[prob.isna()]).clip(0, 1)
    return prob.dropna()


def collect_strategy_returns(
    start: str,
    end: str,
    slug: str = DEFAULT_SLUG,
) -> dict[str, pd.Series]:
    cfg = StrategyConfig(start=start, end=end)
    prices = load_universe_prices(cfg)
    out: dict[str, pd.Series] = {}

    meta = fetch_market_meta(slug) or {}
    cid = meta.get("conditionId") or DEFAULT_CONDITION_IDS.get(slug, "")
    trades = fetch_large_trades_history(
        min_cash_usd=500, market_slug=slug, condition_id=cid or None, max_trades=8000
    )
    ohlcv = fetch_polymarket_daily_ohlcv(slug, start, end)
    poly = ohlcv["Close"].dropna() if not ohlcv.empty else _prob_from_trades(trades)
    if len(poly):
        poly.index = pd.to_datetime(poly.index).tz_localize(None).normalize()

    if len(trades) and len(poly):
        flow = daily_whale_flow(trades).reindex(poly.index).fillna(0)
        v2_cfg = WhaleStrategyConfig()
        sig_v2 = whale_flow_signal_v2(flow, poly, v2_cfg)
        wr_v2, _ = backtest_whale_strategy(poly, sig_v2, fee_bps=v2_cfg.fee_bps)
        out["whale_flow"] = wr_v2

    doge = prices.get("DOGE")
    wif = prices.get("WIF")
    if doge is not None and wif is not None:
        out["pairs_stat_arb"] = pairs_spread_returns_v2(doge, wif)

    if "whale_flow" in out and "pairs_stat_arb" in out:
        out["live_composite"] = build_live_composite_returns(out["whale_flow"], out["pairs_stat_arb"])

    cleaned: dict[str, pd.Series] = {}
    for k, s in out.items():
        if s is None or len(s) == 0:
            continue
        s = s.copy()
        s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        s = s.groupby(s.index).sum()
        if len(s) > 5000:
            s = s.iloc[-5000:]
        cleaned[k] = s.dropna()
    return cleaned


def latest_signals(cfg: StrategyConfig, prices: dict[str, pd.Series], poly: pd.Series) -> dict[str, float]:
    from tradingagents.quant.live_execution import build_live_execution_snapshot

    slug = DEFAULT_SLUG
    meta = fetch_market_meta(slug) or {}
    cid = meta.get("conditionId") or DEFAULT_CONDITION_IDS.get(slug, "")
    trades = fetch_large_trades_history(min_cash_usd=500, market_slug=slug, condition_id=cid or None, max_trades=8000)
    flow = daily_whale_flow(trades) if not trades.empty else pd.DataFrame()
    if not poly.empty and not flow.empty:
        flow = flow.reindex(pd.to_datetime(poly.index).normalize()).fillna(0)
    snap = build_live_execution_snapshot(flow, poly, prices.get("DOGE"), prices.get("WIF"))
    return snap["signals"]
