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
from tradingagents.quant.all_weather_regime import (
    WORKFLOW_STEPS,
    build_regime_snapshot,
    transaction_costs_json,
)
from tradingagents.quant.live_execution import build_live_execution_snapshot
from tradingagents.quant.live_portfolio_sim import portfolio_pnl_snapshot, sim_capital, sim_start_date
from tradingagents.quant.live_strategies import collect_strategy_returns, fetch_live_data_bundle
from tradingagents.quant.regime_allocator import blend_returns, regime_dynamic_weights
from tradingagents.quant.regime_models import build_dual_regime_snapshot
from tradingagents.quant.strategy_walk_forward import walk_forward_returns
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


def _apply_dynamic_composite(
    returns_map: dict[str, pd.Series],
    barra: pd.DataFrame,
) -> tuple[dict[str, pd.Series], dict[str, float], dict]:
    dual = build_dual_regime_snapshot(barra)
    merged_tilt = dual.get("merged_sleeve_tilt", {})
    weights = regime_dynamic_weights(returns_map, merged_tilt, production_only=False)
    comp = blend_returns(returns_map, weights)
    out = dict(returns_map)
    if len(comp):
        out["live_composite"] = comp
    return out, weights, dual


def _correlation_json(returns_map: dict[str, pd.Series], ids: list[str]) -> dict:
    cols = {k: returns_map[k] for k in ids if k in returns_map and len(returns_map[k])}
    if len(cols) < 2:
        return {}
    df = pd.DataFrame(cols).dropna(how="all").fillna(0)
    if len(df) < 20:
        return {}
    return {a: {b: round(float(df.corr().loc[a, b]), 3) for b in df.columns} for a in df.columns}


def build_strategy_tab_results(
    start: str,
    end: str,
    slug: str = DEFAULT_SLUG,
    bundle: dict | None = None,
) -> tuple[list[dict], pd.DataFrame, dict[str, str], dict[str, pd.Series], dict[str, float]]:
    """Build one tab per catalog entry; placeholders when a leg fails."""
    if bundle is None:
        bundle = fetch_live_data_bundle(start, end, slug)
    returns_map, errors = collect_strategy_returns(start, end, slug, bundle=bundle)
    barra = load_barra_factor_returns(start, end)
    returns_map, dynamic_weights, _dual = _apply_dynamic_composite(returns_map, barra)
    results: list[dict] = []
    for spec in STRATEGY_CATALOG:
        if not spec.runnable:
            continue
        r = returns_map.get(spec.id)
        if r is None or r.dropna().empty:
            err = errors.get(spec.id) or errors.get("whale_flow") or errors.get("pairs_stat_arb")
            results.append(_placeholder_tab(spec, err))
            continue
        results.append(_tab_from_returns(spec, r, barra))
    return results, barra, errors, returns_map, dynamic_weights


def _spot_snapshot(series: pd.Series | None, unit: str = "USD") -> dict:
    if series is None or series.empty:
        return {"price": None, "as_of": None, "chg_1d_pct": None, "unit": unit}
    s = series.dropna().sort_index()
    chg = None
    if len(s) >= 2:
        chg = round(float((s.iloc[-1] / s.iloc[-2] - 1) * 100), 2)
    return {
        "price": round(float(s.iloc[-1]), 6),
        "as_of": str(s.index[-1].date()),
        "chg_1d_pct": chg,
        "unit": unit,
    }


def _build_assets_live(
    bundle: dict,
    exec_snap: dict,
    slug: str,
) -> list[dict]:
    """Per-asset live prices, signals, and when-we-trade hints."""
    poly = bundle.get("poly", pd.Series(dtype=float))
    doge = bundle.get("prices", {}).get("DOGE")
    wif = bundle.get("prices", {}).get("WIF")
    whale = exec_snap.get("whale") or {}
    pairs = exec_snap.get("pairs") or {}
    sig = exec_snap.get("signals") or {}
    raw = exec_snap.get("signals_raw") or {}
    reasons = exec_snap.get("gate_reason") or {}
    gate = exec_snap.get("news_gate") or {}

    poly_snap = _spot_snapshot(poly, "prob")
    if poly_snap["price"] is not None:
        poly_snap["price_pct"] = round(poly_snap["price"] * 100, 2)

    whale_blocks = [c["label"] for c in whale.get("checks", []) if not c.get("ok")]
    pairs_blocks = [c["label"] for c in pairs.get("checks", []) if not c.get("ok")]

    def _status(raw_sig: float, gated_sig: float, blocks: list[str]) -> str:
        if not gate.get("allow_new_trades", True):
            return "blocked_macro"
        if abs(gated_sig) > 0.01:
            return "trade"
        if abs(raw_sig) > 0.01 and abs(gated_sig) < 0.01:
            return "gated"
        if blocks:
            return "wait"
        return "flat"

    return [
        {
            "id": "POLY_GTA",
            "name": "Polymarket GTA",
            "venue": "Polymarket CLOB",
            "slug": slug,
            "price": poly_snap.get("price"),
            "price_pct": poly_snap.get("price_pct"),
            "price_label": "Yes implied prob",
            "as_of": poly_snap.get("as_of") or whale.get("prob_as_of"),
            "chg_1d_pct": poly_snap.get("chg_1d_pct"),
            "signal_raw": raw.get("POLY_GTA", 0),
            "signal_gated": sig.get("POLY_GTA", 0),
            "gate_reason": reasons.get("POLY_GTA", ""),
            "sleeve": "whale_flow v2",
            "trade_when": "7d net whale flow ≥ $12k, ≥4 large trades, EMA trend agrees",
            "status": _status(float(raw.get("POLY_GTA", 0)), float(sig.get("POLY_GTA", 0)), whale_blocks),
            "blocking": whale_blocks,
            "data_through": whale.get("trades_through") or poly_snap.get("as_of"),
        },
        {
            "id": "DOGE",
            "name": "Dogecoin",
            "venue": "Spot (Yahoo / Kraken / CoinGecko)",
            "price": pairs.get("doge_price"),
            "price_label": "USD",
            "as_of": pairs.get("doge_as_of"),
            "chg_1d_pct": pairs.get("doge_chg_1d_pct"),
            "signal_raw": raw.get("DOGE", 0),
            "signal_gated": sig.get("DOGE", 0),
            "gate_reason": reasons.get("DOGE", ""),
            "sleeve": "pairs_stat_arb v2",
            "trade_when": "Pairs: |z|>2 → long DOGE / short WIF (or opposite)",
            "status": _status(float(raw.get("DOGE", 0)), float(sig.get("DOGE", 0)), pairs_blocks),
            "blocking": pairs_blocks,
            "spread_z": pairs.get("spread_z"),
        },
        {
            "id": "WIF",
            "name": "dogwifhat",
            "venue": "Spot (Yahoo / Kraken / CoinGecko)",
            "price": pairs.get("wif_price"),
            "price_label": "USD",
            "as_of": pairs.get("wif_as_of"),
            "chg_1d_pct": pairs.get("wif_chg_1d_pct"),
            "signal_raw": raw.get("WIF", 0),
            "signal_gated": sig.get("WIF", 0),
            "gate_reason": reasons.get("WIF", ""),
            "sleeve": "pairs_stat_arb v2",
            "trade_when": "Pairs: |z|>2 → hedge leg vs DOGE",
            "status": _status(float(raw.get("WIF", 0)), float(sig.get("WIF", 0)), pairs_blocks),
            "blocking": pairs_blocks,
            "spread_z": pairs.get("spread_z"),
        },
    ]


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
    tab_results, barra, fetch_errors, returns_map, dynamic_weights = build_strategy_tab_results(
        start, end, slug, bundle=bundle
    )
    regime_snap = {**build_regime_snapshot(barra), **build_dual_regime_snapshot(barra)}

    exec_snap = build_live_execution_snapshot(
        bundle["flow"],
        bundle["poly"],
        bundle["prices"].get("DOGE"),
        bundle["prices"].get("WIF"),
        notional_usd=100.0,
        trades=bundle.get("trades"),
    )
    assets_live = _build_assets_live(bundle, exec_snap, slug)
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
            entry["walk_forward"] = walk_forward_returns(res["returns"])
            entry["sim_pnl"] = portfolio_pnl_snapshot(res["returns"])
        else:
            entry["start"] = None
            entry["end"] = None
            entry["n_days"] = 0
            entry["walk_forward"] = {}
            entry["sim_pnl"] = portfolio_pnl_snapshot(pd.Series(dtype=float))
        strategies.append(entry)

    book_returns = returns_map.get("live_composite", pd.Series(dtype=float))
    portfolio_sim = portfolio_pnl_snapshot(book_returns)

    return {
        "dashboard_version": DASHBOARD_VERSION,
        "as_of_ny": as_of,
        "universe": ["POLY_GTA", "DOGE", "WIF"],
        "slug": slug,
        "lookback_start": start,
        "lookback_end": end,
        "lookback_days": lookback_days,
        "metrics_note": (
            f"Tab metrics = backtest over last {lookback_days} calendar days "
            f"({start} → {end}), recomputed on each refresh — not tick-level live PnL."
        ),
        "transaction_costs": transaction_costs_json(),
        "macro_regime": regime_snap,
        "dynamic_weights": dynamic_weights,
        "strategy_correlation": _correlation_json(returns_map, list(dynamic_weights.keys())),
        "portfolio_sim": portfolio_sim,
        "sim_config": {
            "start": sim_start_date(),
            "capital_usd": sim_capital(),
            "note": "Paper book PnL from sim start using composite daily returns (5+5 bps TC included).",
        },
        "research_refs": [
            {
                "id": "ab2002",
                "cite": "Ang & Bekaert (2002) JFE — International Asset Allocation with Regime Shifts",
                "pdf": "Markov Regimes - How Regimes Affect Asset Allocation - By Ang and Bekaert.pdf",
                "use": "2-state AB bull/bear → beta scaling",
            },
            {
                "id": "jpm_regime",
                "cite": "JPMorgan AM — Regime-based investing",
                "pdf": "Markov Regimes - JPM Regime-based investing.pdf",
                "use": "4-quadrant growth×inflation sleeve rotation",
            },
            {
                "id": "biz_cycle",
                "cite": "Macro Regimes — Dynamic asset allocation through the business cycle",
                "pdf": "Macro Regimes - Dynamic_Asset_Allocation_Through_the_Business_Cycle.pdf",
                "use": "Stagflation / Goldilocks quadrant tilts",
            },
            {
                "id": "wq101_cs",
                "cite": "Kakushadze (2016) — 101 Formulaic Alphas (WorldQuant)",
                "pdf": "Paper - 101 Alphas - WorldQuant World Quant.pdf",
                "use": "cs_momentum_rank sleeve",
            },
            {
                "id": "wq101_rev",
                "cite": "Lehmann (1990) + WorldQuant Alpha #12 reversal family",
                "pdf": "Paper - 101 Alphas - WorldQuant World Quant.pdf",
                "use": "short_term_reversal sleeve (uncorrelated to 20d TS mom)",
            },
            {
                "id": "moskowitz2012",
                "cite": "Moskowitz, Ooi & Pedersen (2012) — Time series momentum",
                "pdf": "Journal of Financial Economics",
                "use": "ts_momentum_meme sleeve",
            },
            {
                "id": "ang_smart_beta",
                "cite": "Andrew Ang — Smart Beta (BlackRock guide)",
                "pdf": "Smart Beta - Blackrock Guide by Andrew Ang.pdf",
                "use": "vol_risk_parity inverse-vol weights",
            },
        ],
        "workflow": WORKFLOW_STEPS,
        "assets_live": assets_live,
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
