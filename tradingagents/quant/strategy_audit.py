"""Unified strategy audit: metrics, rolling, walk-forward, correlation, overlap warnings."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.quant.hf_manager import BASE_SLEEVE_IDS, SLEEVE_LOGIC
from tradingagents.quant.strategy_walk_forward import walk_forward_returns
from tradingagents.quant.trading_costs import ROUND_TRIP_BPS
from tradingagents.quant.whale_strategy import strategy_metrics

MAX_WF_FOLDS = 12
ROLLING_WINDOW = 60
SPARKLINE_POINTS = 40
OVERLAP_CORR_THRESHOLD = 0.6


def _annualized_vol(returns: pd.Series) -> float:
    r = returns.dropna()
    if len(r) < 2 or r.std() == 0:
        return 0.0
    return float(r.std() * np.sqrt(252))


def _turnover_estimate(returns: pd.Series) -> float:
    """Proxy turnover: fraction of days with non-zero return."""
    r = returns.dropna()
    if len(r) < 2:
        return 0.0
    return float((r != 0).mean())


def _tc_drag_metrics(returns: pd.Series, n_trades: int) -> dict[str, float]:
    """Estimate TC drag from trade count and round-trip bps."""
    r = returns.dropna()
    gross = float((1 + r).prod() - 1) if len(r) else 0.0
    rt_frac = ROUND_TRIP_BPS / 10_000
    tc_total = n_trades * rt_frac
    tc_drag_bps = round(tc_total * 10_000, 1)
    tc_pct_gross = round(tc_total / abs(gross), 4) if abs(gross) > 1e-9 else 0.0
    return {
        "round_trip_bps": ROUND_TRIP_BPS,
        "turnover": round(_turnover_estimate(r), 4),
        "tc_drag_bps": tc_drag_bps,
        "tc_pct_gross": tc_pct_gross,
    }


def _rolling_series(returns: pd.Series, window: int = ROLLING_WINDOW) -> dict:
    r = returns.dropna().sort_index()
    if len(r) < window + 5:
        return {"sharpe": [], "return": []}

    def _downsample(vals: list[dict]) -> list[dict]:
        if len(vals) <= SPARKLINE_POINTS:
            return vals
        step = max(1, len(vals) // SPARKLINE_POINTS)
        return vals[::step]

    sharpe_pts: list[dict] = []
    ret_pts: list[dict] = []
    for i in range(window, len(r) + 1):
        chunk = r.iloc[i - window : i]
        sh = float(chunk.mean() / chunk.std() * np.sqrt(252)) if chunk.std() > 0 else 0.0
        cum = float((1 + chunk).prod() - 1)
        dt = str(r.index[i - 1].date())
        sharpe_pts.append({"t": dt, "v": round(sh, 3)})
        ret_pts.append({"t": dt, "v": round(cum, 4)})

    return {"sharpe": _downsample(sharpe_pts), "return": _downsample(ret_pts)}


def _adaptive_walk_forward(returns: pd.Series) -> dict:
    """Adaptive train/test windows; up to MAX_WF_FOLDS folds in output."""
    r = returns.dropna().sort_index()
    n = len(r)
    if n < 80:
        return walk_forward_returns(r, train_days=30, test_days=14)

    train_days = min(120, max(40, n // 8))
    test_days = min(30, max(14, n // 20))
    wf = walk_forward_returns(r, train_days=train_days, test_days=test_days)
    folds = wf.get("folds") or []
    if len(folds) > MAX_WF_FOLDS:
        wf["folds"] = folds[-MAX_WF_FOLDS:]
    wf["max_folds_shown"] = MAX_WF_FOLDS
    return wf


def _avg_abs_corr_vs(ref_returns: pd.Series, target: pd.Series) -> float:
    df = pd.DataFrame({"ref": ref_returns, "tgt": target}).dropna()
    if len(df) < 20:
        return 0.0
    return round(abs(float(df.corr().iloc[0, 1])), 3)


def _correlation_matrix(returns_map: dict[str, pd.Series], ids: list[str]) -> dict[str, dict[str, float]]:
    cols = {k: returns_map[k] for k in ids if k in returns_map and len(returns_map[k])}
    if len(cols) < 2:
        return {}
    df = pd.DataFrame(cols).dropna(how="all").fillna(0)
    if len(df) < 20:
        return {}
    corr = df.corr()
    return {a: {b: round(float(corr.loc[a, b]), 3) for b in corr.columns} for a in corr.index}


def _overlap_warnings(corr: dict[str, dict[str, float]], ids: list[str]) -> list[dict]:
    warnings: list[dict] = []
    for i, a in enumerate(ids):
        logic_a = SLEEVE_LOGIC.get(a, {}).get("logic_type", "")
        for b in ids[i + 1 :]:
            rho = abs(corr.get(a, {}).get(b, 0.0))
            logic_b = SLEEVE_LOGIC.get(b, {}).get("logic_type", "")
            if rho > OVERLAP_CORR_THRESHOLD and logic_a and logic_a == logic_b:
                warnings.append(
                    {
                        "a": a,
                        "b": b,
                        "rho": round(rho, 3),
                        "logic_type": logic_a,
                        "message": f"|ρ|={rho:.2f} > {OVERLAP_CORR_THRESHOLD} with same logic_type={logic_a}",
                    }
                )
    return warnings


def audit_single(
    strategy_id: str,
    returns: pd.Series,
    returns_map: dict[str, pd.Series] | None = None,
) -> dict:
    """Full audit JSON for one sleeve or book."""
    r = returns.dropna().sort_index()
    m = strategy_metrics(r)
    vol = _annualized_vol(r)
    tc = _tc_drag_metrics(r, int(m.get("n_trades", 0)))
    rolling = _rolling_series(r)
    wf = _adaptive_walk_forward(r)

    avg_corr_whale = 0.0
    avg_corr_pairs = 0.0
    if returns_map:
        if "whale_flow" in returns_map and strategy_id != "whale_flow":
            avg_corr_whale = _avg_abs_corr_vs(returns_map["whale_flow"], r)
        if "pairs_stat_arb" in returns_map and strategy_id != "pairs_stat_arb":
            avg_corr_pairs = _avg_abs_corr_vs(returns_map["pairs_stat_arb"], r)

    logic = SLEEVE_LOGIC.get(strategy_id, {})

    return {
        "id": strategy_id,
        "logic_type": logic.get("logic_type", "composite"),
        "venue": logic.get("venue", ""),
        "metrics": {
            "sharpe": round(float(m.get("sharpe", 0)), 4),
            "cagr": round(float(m.get("cagr", 0)), 4),
            "total_return": round(float(m.get("total_return", 0)), 4),
            "vol_ann": round(vol, 4),
            "max_dd": round(float(m.get("max_dd", 0)), 4),
            "win_rate": round(float(m.get("win_rate", 0)), 4),
            "n_days": int(m.get("n_days", 0)),
            "n_trades": int(m.get("n_trades", 0)),
            **tc,
        },
        "rolling_60d": rolling,
        "walk_forward": wf,
        "avg_abs_corr_whale": avg_corr_whale,
        "avg_abs_corr_pairs": avg_corr_pairs,
    }


def build_strategy_audit(returns_map: dict[str, pd.Series]) -> dict:
    """Audit all base sleeves + multi_strategy_index + hf_manager_book."""
    audit_ids = list(BASE_SLEEVE_IDS)
    for book in ("multi_strategy_index", "hf_manager_book", "live_composite"):
        if book in returns_map and len(returns_map[book].dropna()):
            audit_ids.append(book)

    entries: dict[str, dict] = {}
    for sid in audit_ids:
        if sid not in returns_map or returns_map[sid].dropna().empty:
            continue
        entries[sid] = audit_single(sid, returns_map[sid], returns_map)

    sleeve_ids = [s for s in BASE_SLEEVE_IDS if s in entries]
    corr = _correlation_matrix(returns_map, sleeve_ids)
    overlap = _overlap_warnings(corr, sleeve_ids)

    summary_rows = []
    for sid, entry in entries.items():
        m = entry["metrics"]
        wf = entry.get("walk_forward") or {}
        summary_rows.append(
            {
                "id": sid,
                "sharpe": m["sharpe"],
                "vol_ann": m["vol_ann"],
                "max_dd": m["max_dd"],
                "n_trades": m["n_trades"],
                "oos_sharpe": wf.get("oos_sharpe", 0.0),
                "avg_abs_corr_pairs": entry.get("avg_abs_corr_pairs", 0.0),
            }
        )

    return {
        "entries": entries,
        "summary": summary_rows,
        "correlation": corr,
        "overlap_warnings": overlap,
        "sleeve_ids": sleeve_ids,
    }
