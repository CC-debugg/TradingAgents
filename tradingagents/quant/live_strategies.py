"""Collect daily returns for production strategies (live pipeline)."""

from __future__ import annotations

import os

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


def _max_trades() -> int:
    raw = os.environ.get("LIVE_MAX_TRADES", "8000").strip()
    try:
        return max(500, int(raw))
    except ValueError:
        return 8000


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


def _clean_returns(out: dict[str, pd.Series]) -> dict[str, pd.Series]:
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


def fetch_live_data_bundle(
    start: str,
    end: str,
    slug: str = DEFAULT_SLUG,
) -> dict:
    """Single network pass shared by strategy tabs and execution snapshot."""
    errors: dict[str, str] = {}
    cfg = StrategyConfig(start=start, end=end)

    prices: dict[str, pd.Series] = {}
    try:
        prices = load_universe_prices(cfg)
        for sym in ("DOGE", "WIF"):
            if sym not in prices:
                errors[sym] = "price fetch failed (Yahoo/CoinGecko/Kraken); retry refresh"
    except Exception as exc:
        errors["prices"] = str(exc)

    meta: dict = {}
    try:
        meta = fetch_market_meta(slug) or {}
    except Exception as exc:
        errors["market_meta"] = str(exc)

    cid = meta.get("conditionId") or DEFAULT_CONDITION_IDS.get(slug, "")
    trades = pd.DataFrame()
    try:
        trades = fetch_large_trades_history(
            min_cash_usd=500,
            market_slug=slug,
            condition_id=cid or None,
            max_trades=_max_trades(),
        )
    except Exception as exc:
        errors["trades"] = str(exc)

    poly = pd.Series(dtype=float)
    try:
        ohlcv = fetch_polymarket_daily_ohlcv(slug, start, end)
        poly = ohlcv["Close"].dropna() if not ohlcv.empty else pd.Series(dtype=float)
    except Exception as exc:
        errors["ohlcv"] = str(exc)

    if poly.empty and not trades.empty:
        try:
            poly = _prob_from_trades(trades)
        except Exception as exc:
            errors["poly_from_trades"] = str(exc)

    if len(poly):
        poly.index = pd.to_datetime(poly.index).tz_localize(None).normalize()

    flow = pd.DataFrame()
    if len(trades) and len(poly):
        try:
            flow = daily_whale_flow(trades).reindex(poly.index).fillna(0)
        except Exception as exc:
            errors["whale_flow"] = str(exc)

    return {
        "prices": prices,
        "trades": trades,
        "poly": poly,
        "flow": flow,
        "errors": errors,
        "slug": slug,
        "start": start,
        "end": end,
    }


def collect_strategy_returns(
    start: str,
    end: str,
    slug: str = DEFAULT_SLUG,
    bundle: dict | None = None,
) -> tuple[dict[str, pd.Series], dict[str, str]]:
    if bundle is None:
        bundle = fetch_live_data_bundle(start, end, slug)

    errors = dict(bundle.get("errors", {}))
    prices = bundle["prices"]
    poly = bundle["poly"]
    trades = bundle["trades"]
    flow = bundle["flow"]
    out: dict[str, pd.Series] = {}

    if len(trades) and len(poly) and not flow.empty:
        try:
            v2_cfg = WhaleStrategyConfig()
            sig_v2 = whale_flow_signal_v2(flow, poly, v2_cfg)
            wr_v2, _ = backtest_whale_strategy(poly, sig_v2, fee_bps=v2_cfg.fee_bps)
            out["whale_flow"] = wr_v2
        except Exception as exc:
            errors["whale_flow"] = str(exc)
    else:
        errors.setdefault("whale_flow", "missing Polymarket trades or price series")

    doge = prices.get("DOGE")
    wif = prices.get("WIF")
    if doge is not None and wif is not None:
        try:
            out["pairs_stat_arb"] = pairs_spread_returns_v2(doge, wif)
        except Exception as exc:
            errors["pairs_stat_arb"] = str(exc)
    else:
        errors.setdefault("pairs_stat_arb", "missing DOGE or WIF prices")

    if "whale_flow" in out and "pairs_stat_arb" in out:
        try:
            out["live_composite"] = build_live_composite_returns(out["whale_flow"], out["pairs_stat_arb"])
        except Exception as exc:
            errors["live_composite"] = str(exc)

    return _clean_returns(out), errors


def latest_signals(cfg: StrategyConfig, prices: dict[str, pd.Series], poly: pd.Series) -> dict[str, float]:
    from tradingagents.quant.live_execution import build_live_execution_snapshot

    slug = DEFAULT_SLUG
    meta = fetch_market_meta(slug) or {}
    cid = meta.get("conditionId") or DEFAULT_CONDITION_IDS.get(slug, "")
    trades = fetch_large_trades_history(
        min_cash_usd=500, market_slug=slug, condition_id=cid or None, max_trades=_max_trades()
    )
    flow = daily_whale_flow(trades) if not trades.empty else pd.DataFrame()
    if not poly.empty and not flow.empty:
        flow = flow.reindex(pd.to_datetime(poly.index).normalize()).fillna(0)
    snap = build_live_execution_snapshot(flow, poly, prices.get("DOGE"), prices.get("WIF"))
    return snap["signals"]
