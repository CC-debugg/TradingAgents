"""JSON payload for interactive live strategy dashboard (browser refreshes on each open)."""

from __future__ import annotations

import os
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
from tradingagents.quant.live_execution import build_live_composite_returns, build_live_execution_snapshot
from tradingagents.quant.live_strategies import collect_strategy_returns, fetch_live_data_bundle
from tradingagents.quant.strategy_catalog import DASHBOARD_VERSION, STRATEGY_CATALOG, StrategySpec
from tradingagents.quant.whale_strategy import daily_whale_flow, strategy_metrics

NY = ZoneInfo("America/New_York")
DEFAULT_SLUG = "gta-vi-released-before-june-2026"
MAX_EQUITY_POINTS = 500


def _lookback_days() -> int:
    raw = os.environ.get("LIVE_LOOKBACK_DAYS", "400").strip()
    try:
        return max(60, int(raw))
    except ValueError:
        return 400


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


def _tab_from_returns(spec: StrategySpec, r: pd.Series, barra: pd.DataFrame) -> dict:
    r = r.dropna()
    m = strategy_metrics(r)
    attr = barra_factor_attribution(r, barra) if not barra.empty else pd.DataFrame()
    r2 = float(attr.attrs.get("r_squared", 0)) if not attr.empty else 0.0
    cum = (1 + r.fillna(0)).cumprod()
    return {
        "spec": spec,
        "data_ok": True,
        "data_error": None,
        "returns": r,
        "metrics": m,
        "attribution": attr,
        "r2": r2,
        "equity": _downsample_equity(cum),
        "factors": _attribution_rows(attr),
    }


def _placeholder_tab(spec: StrategySpec, error: str | None) -> dict:
    return {
        "spec": spec,
        "data_ok": False,
        "data_error": error or "data unavailable",
        "returns": pd.Series(dtype=float),
        "metrics": strategy_metrics(pd.Series(dtype=float)),
        "attribution": pd.DataFrame(),
        "r2": 0.0,
        "equity": [],
        "factors": [],
    }


def _resolve_returns(spec: StrategySpec, returns_map: dict[str, pd.Series]) -> pd.Series | None:
    r = returns_map.get(spec.id)
    if r is not None and not r.dropna().empty:
        return r
    if spec.id != "live_composite":
        return None
    wr = returns_map.get("whale_flow")
    pr = returns_map.get("pairs_stat_arb")
    if wr is None or pr is None or wr.dropna().empty or pr.dropna().empty:
        return None
    comp = build_live_composite_returns(wr, pr).dropna()
    return comp if len(comp) else None


def build_strategy_tab_results(
    start: str,
    end: str,
    slug: str = DEFAULT_SLUG,
    bundle: dict | None = None,
) -> tuple[list[dict], pd.DataFrame, dict[str, str]]:
    """Build one tab per catalog entry; placeholders when a leg fails."""
    if bundle is None:
        bundle = fetch_live_data_bundle(start, end, slug)
    returns_map, errors = collect_strategy_returns(start, end, slug, bundle=bundle)
    barra = load_barra_factor_returns(start, end)
    results: list[dict] = []
    for spec in STRATEGY_CATALOG:
        if not spec.runnable:
            continue
        r = _resolve_returns(spec, returns_map)
        if r is None:
            err = errors.get(spec.id) or errors.get("whale_flow") or errors.get("pairs_stat_arb")
            results.append(_placeholder_tab(spec, err))
            continue
        results.append(_tab_from_returns(spec, r, barra))
    return results, barra, errors


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
    lookback_days: int | None = None,
    slug: str = DEFAULT_SLUG,
) -> dict:
    if lookback_days is None:
        lookback_days = _lookback_days()
    now = datetime.now(NY)
    end = now.strftime("%Y-%m-%d")
    start = (now - pd.Timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    as_of = now.strftime("%Y-%m-%d %H:%M %Z")

    bundle = fetch_live_data_bundle(start, end, slug)
    tab_results, barra, fetch_errors = build_strategy_tab_results(start, end, slug, bundle=bundle)

    exec_snap = build_live_execution_snapshot(
        bundle["flow"],
        bundle["poly"],
        bundle["prices"].get("DOGE"),
        bundle["prices"].get("WIF"),
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
        data_ok = bool(res.get("data_ok", True))
        entry = {
            **_spec_json(spec),
            "data_ok": data_ok,
            "data_error": res.get("data_error"),
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
        }
        if data_ok and len(res["returns"]):
            entry["start"] = str(res["returns"].index.min().date())
            entry["end"] = str(res["returns"].index.max().date())
            entry["n_days"] = int(len(res["returns"]))
        else:
            entry["start"] = None
            entry["end"] = None
            entry["n_days"] = 0
        strategies.append(entry)

    return {
        "dashboard_version": DASHBOARD_VERSION,
        "as_of_ny": as_of,
        "universe": ["POLY_GTA", "DOGE", "WIF"],
        "slug": slug,
        "lookback_start": start,
        "lookback_end": end,
        "catalog_ids": [s.id for s in STRATEGY_CATALOG if s.runnable],
        "strategies": strategies,
        "fetch_errors": {k: v for k, v in fetch_errors.items() if v},
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
