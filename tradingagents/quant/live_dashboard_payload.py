"""JSON payload for interactive live strategy dashboard (browser refreshes on each open)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from tradingagents.dataflows.macro_news import fetch_macro_news_snapshot
from tradingagents.execution.polymarket_clob import clob_health_check
from tradingagents.quant.barra_risk_factors import (
    BARRA_FACTOR_META,
    barra_display_name,
    barra_factor_attribution,
    load_barra_factor_returns,
)
from tradingagents.quant.live_execution import build_live_execution_snapshot
from tradingagents.quant.live_strategies import collect_strategy_returns
from tradingagents.quant.polymarket_strategy import StrategyConfig, load_universe_prices
from tradingagents.quant.strategy_catalog import DASHBOARD_VERSION, STRATEGY_CATALOG, StrategySpec
from tradingagents.quant.whale_strategy import daily_whale_flow, strategy_metrics
from tradingagents.dataflows.polymarket_whale import (
    DEFAULT_CONDITION_IDS,
    fetch_large_trades_history,
    fetch_market_meta,
)

NY = ZoneInfo("America/New_York")
DEFAULT_SLUG = "gta-vi-released-before-june-2026"
MAX_EQUITY_POINTS = 500


def _downsample_equity(cum: pd.Series, max_points: int = MAX_EQUITY_POINTS) -> list[dict]:
    if cum.empty:
        return []
    if len(cum) > max_points:
        step = max(1, len(cum) // max_points)
        cum = cum.iloc[::step]
    out = []
    for dt, v in cum.items():
        ts = pd.Timestamp(dt)
        out.append({"t": ts.strftime("%Y-%m-%d"), "v": round(float(v), 6)})
    return out


def _attribution_rows(attr: pd.DataFrame, top_n: int = 12) -> list[dict]:
    if attr.empty:
        return []
    sub = attr[attr["factor"] != "ALPHA"].tail(top_n)
    rows = []
    for _, row in sub.iterrows():
        fid = str(row["factor"])
        rows.append(
            {
                "factor": fid,
                "label": barra_display_name(fid),
                "beta": round(float(row["beta"]), 4),
            }
        )
    return rows


def build_strategy_tab_results(
    start: str,
    end: str,
    slug: str = DEFAULT_SLUG,
) -> tuple[list[dict], pd.DataFrame]:
    """Same attribution loop as multi-strategy PNG; returns rich dicts + barra frame."""
    returns_map = collect_strategy_returns(start, end, slug)
    barra = load_barra_factor_returns(start, end)
    results: list[dict] = []
    for spec in STRATEGY_CATALOG:
        r = returns_map.get(spec.id)
        if r is None or r.dropna().empty:
            if not spec.runnable:
                continue
            continue
        r = r.dropna()
        m = strategy_metrics(r)
        attr = barra_factor_attribution(r, barra) if not barra.empty else pd.DataFrame()
        r2 = float(attr.attrs.get("r_squared", 0)) if not attr.empty else 0.0
        cum = (1 + r.fillna(0)).cumprod()
        results.append(
            {
                "spec": spec,
                "returns": r,
                "metrics": m,
                "attribution": attr,
                "r2": r2,
                "equity": _downsample_equity(cum),
                "factors": _attribution_rows(attr),
            }
        )
    return results, barra


def _spec_json(spec: StrategySpec) -> dict:
    return {
        "id": spec.id,
        "name": spec.name,
        "category": spec.category,
        "description": spec.description,
        "runnable": spec.runnable,
        "live_production": spec.live_production,
        "reference": spec.reference,
    }


def build_live_payload(
    lookback_days: int = 400,
    slug: str = DEFAULT_SLUG,
) -> dict:
    now = datetime.now(NY)
    end = now.strftime("%Y-%m-%d")
    start = (now - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    as_of = now.strftime("%Y-%m-%d %H:%M %Z")

    tab_results, barra = build_strategy_tab_results(start, end, slug)
    ids = {res["spec"].id for res in tab_results}
    if "live_composite" not in ids:
        wm = {r["spec"].id: r for r in tab_results}
        if "whale_flow" in wm and "pairs_stat_arb" in wm:
            from tradingagents.quant.live_execution import build_live_composite_returns

            wr = wm["whale_flow"]["returns"]
            pr = wm["pairs_stat_arb"]["returns"]
            comp = build_live_composite_returns(wr, pr).dropna()
            if len(comp):
                spec = next(s for s in STRATEGY_CATALOG if s.id == "live_composite")
                m = strategy_metrics(comp)
                attr = barra_factor_attribution(comp, barra) if not barra.empty else pd.DataFrame()
                r2 = float(attr.attrs.get("r_squared", 0)) if not attr.empty else 0.0
                cum = (1 + comp.fillna(0)).cumprod()
                tab_results.insert(
                    0,
                    {
                        "spec": spec,
                        "returns": comp,
                        "metrics": m,
                        "attribution": attr,
                        "r2": r2,
                        "equity": _downsample_equity(cum),
                        "factors": _attribution_rows(attr),
                    },
                )

    cfg = StrategyConfig(start=start, end=end)
    prices = load_universe_prices(cfg)
    meta = fetch_market_meta(slug) or {}
    cid = meta.get("conditionId") or DEFAULT_CONDITION_IDS.get(slug, "")
    trades = fetch_large_trades_history(
        min_cash_usd=500, market_slug=slug, condition_id=cid or None, max_trades=8000
    )
    ohlcv_start = start
    from tradingagents.dataflows.polymarket_gamma import fetch_polymarket_daily_ohlcv

    ohlcv = fetch_polymarket_daily_ohlcv(slug, ohlcv_start, end)
    poly = ohlcv["Close"].dropna() if not ohlcv.empty else pd.Series(dtype=float)
    if poly.empty and not trades.empty:
        from tradingagents.quant.live_strategies import _prob_from_trades

        poly = _prob_from_trades(trades)
    if len(poly):
        poly.index = pd.to_datetime(poly.index).tz_localize(None).normalize()
    flow = daily_whale_flow(trades).reindex(poly.index).fillna(0) if len(trades) and len(poly) else pd.DataFrame()

    exec_snap = build_live_execution_snapshot(
        flow,
        poly,
        prices.get("DOGE"),
        prices.get("WIF"),
        notional_usd=100.0,
    )
    sig = exec_snap["signals"]
    intents = exec_snap["clob_intents"]
    news_gate = exec_snap["news_gate"]

    news = fetch_macro_news_snapshot()
    ecb_df = news.get("ecb_headlines", pd.DataFrame())
    ecb = ecb_df.to_dict(orient="records") if not ecb_df.empty else []
    fred_rows = []
    for key in ("fred_fed_funds", "fred_cpi"):
        row = news.get(key)
        if row:
            fred_rows.append(row)

    strategies = []
    for res in tab_results:
        spec: StrategySpec = res["spec"]
        m = res["metrics"]
        strategies.append(
            {
                **_spec_json(spec),
                "metrics": {
                    "win_rate": round(float(m.get("win_rate", 0)), 4),
                    "sharpe": round(float(m.get("sharpe", 0)), 4),
                    "cagr": round(float(m.get("cagr", 0)), 4),
                    "total_return": round(float(m.get("total_return", 0)), 4),
                    "max_dd": round(float(m.get("max_dd", 0)), 4),
                },
                "r2_barra": round(float(res.get("r2", 0)), 4),
                "equity": res["equity"],
                "factors": res["factors"],
                "start": str(res["returns"].index.min().date()),
                "end": str(res["returns"].index.max().date()),
                "n_days": int(len(res["returns"])),
            }
        )

    return {
        "dashboard_version": DASHBOARD_VERSION,
        "as_of_ny": as_of,
        "universe": ["POLY_GTA", "DOGE", "WIF"],
        "slug": slug,
        "lookback_start": start,
        "lookback_end": end,
        "strategies": strategies,
        "signals": {k: float(v) for k, v in sig.items()},
        "signals_raw": {k: float(v) for k, v in exec_snap["signals_raw"].items()},
        "whale_live": exec_snap["whale"],
        "pairs_live": exec_snap["pairs"],
        "news_gate": news_gate,
        "gate_reason": exec_snap["gate_reason"],
        "production_strategies": exec_snap["production_strategies"],
        "clob_intents": [asdict(i) for i in intents],
        "clob_health": clob_health_check(),
        "news": {
            "fred_api_configured": bool(news.get("fred_api_configured")),
            "ecb": ecb,
            "fred": fred_rows,
        },
        "barra_factor_meta": {
            k: {"title": v["title"], "proxy": v["proxy"], "group": v["group"]}
            for k, v in BARRA_FACTOR_META.items()
        },
    }
