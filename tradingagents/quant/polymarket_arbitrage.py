"""Polymarket / crypto arbitrage models: costs, latency, long-short, pattern scan."""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ArbEconomics:
    """All costs must be covered before counting arb as profitable."""

    poly_fee_bps_per_leg: float = 20.0
    slippage_bps_per_leg: float = 10.0
    gas_usd_per_bundle: float = 0.05
    latency_ms: float = 500.0
    min_net_profit_bps: float = 5.0
    notional_usd: float = 100.0

    def total_cost_bps(self, n_legs: int = 2) -> float:
        return n_legs * (self.poly_fee_bps_per_leg + self.slippage_bps_per_leg)

    def total_cost_usd(self, n_legs: int = 2) -> float:
        return self.notional_usd * self.total_cost_bps(n_legs) / 10_000 + self.gas_usd_per_bundle

    def min_gross_edge(self) -> float:
        """Minimum price edge (in $ per $1 face) required."""
        return self.total_cost_usd() / self.notional_usd + self.min_net_profit_bps / 10_000


def parse_outcome_prices(market: dict) -> tuple[float, float]:
    raw = market.get("outcomePrices")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    if not raw or len(raw) < 2:
        return 0.0, 0.0
    return float(raw[0]), float(raw[1])


def yes_no_bundle_arbitrage(
    yes_ask: float,
    no_ask: float,
    econ: ArbEconomics,
) -> dict:
    """
    Buy Yes + No for < $1 → $1 at resolution (complete-set / Dutch-book style).
    Profit only if gross edge > fees + gas + min_net_profit_bps.
    """
    gross_edge = 1.0 - (yes_ask + no_ask)
    cost_usd = econ.total_cost_usd(n_legs=2)
    net_usd = gross_edge * econ.notional_usd - cost_usd
    net_bps = (net_usd / econ.notional_usd) * 10_000 if econ.notional_usd else 0
    return {
        "yes_ask": yes_ask,
        "no_ask": no_ask,
        "sum_asks": yes_ask + no_ask,
        "gross_edge": gross_edge,
        "gross_edge_bps": gross_edge * 10_000,
        "cost_usd": cost_usd,
        "net_usd": net_usd,
        "net_bps": net_bps,
        "profitable": net_bps >= econ.min_net_profit_bps,
        "min_gross_edge_required": econ.min_gross_edge(),
    }


def scan_yes_no_arb_panel(
    yes_series: pd.Series,
    no_series: pd.Series,
    econ: ArbEconomics,
) -> pd.DataFrame:
    """Historical pattern: when did Yes+No < 1 minus costs?"""
    df = pd.DataFrame({"yes": yes_series, "no": no_series}).dropna()
    if df.empty:
        return pd.DataFrame()
    rows = []
    for ts, row in df.iterrows():
        r = yes_no_bundle_arbitrage(float(row["yes"]), float(row["no"]), econ)
        r["datetime"] = ts
        rows.append(r)
    out = pd.DataFrame(rows).set_index("datetime")
    return out


def latency_delayed_arbitrage(
    market1: pd.Series,
    market2: pd.Series,
    econ: ArbEconomics,
    delay_bars: int = 1,
) -> pd.DataFrame:
    """
    Cross-venue / cross-asset arb with latency.
    market1 = fast venue (e.g. CEX DOGE), market2 = slow (e.g. POLY prob).
    Signal: m1_return at t vs m2_return at t+delay.
    """
    r1 = market1.pct_change()
    r2 = market2.pct_change().shift(delay_bars)
    aligned = pd.DataFrame({"r_fast": r1, "r_slow": r2}).dropna()
    if aligned.empty:
        return pd.DataFrame()

    spread = aligned["r_fast"] - aligned["r_slow"]
    threshold = econ.min_gross_edge()
    rows = []
    for ts, sp in spread.items():
        gross = abs(sp)
        cost = econ.total_cost_usd(n_legs=2) / econ.notional_usd
        net = gross - cost
        rows.append(
            {
                "datetime": ts,
                "spread_return": sp,
                "gross": gross,
                "cost_frac": cost,
                "net": net,
                "profitable": net > threshold,
                "delay_bars": delay_bars,
                "latency_ms": econ.latency_ms,
            }
        )
    return pd.DataFrame(rows).set_index("datetime")


def long_short_poly_returns(
    prob_series: pd.Series,
    econ: ArbEconomics,
    ema_fast: int = 5,
    ema_slow: int = 15,
) -> pd.Series:
    """Long-short on Polymarket implied probability (not spot crypto)."""
    p = prob_series.dropna()
    if len(p) < ema_slow + 2:
        return pd.Series(dtype=float)
    ema_f = p.ewm(span=ema_fast, adjust=False).mean()
    ema_s = p.ewm(span=ema_slow, adjust=False).mean()
    signal = pd.Series(np.where(ema_f > ema_s, 1.0, -1.0), index=p.index)
    signal.iloc[:ema_slow] = 0.0
    ret = p.pct_change()
    tc = (signal.diff().abs() > 0) * (econ.poly_fee_bps_per_leg / 10_000)
    return signal.shift(1) * ret - tc


def find_arb_patterns(arb_panel: pd.DataFrame, min_occurrences: int = 3) -> pd.DataFrame:
    """Summarize recurring profitable arb windows."""
    if arb_panel.empty or "profitable" not in arb_panel.columns:
        return pd.DataFrame(
            [{"pattern": "no_data", "count": 0, "mean_net_bps": 0}]
        )
    prof = arb_panel[arb_panel["profitable"]]
    if prof.empty:
        return pd.DataFrame(
            [{"pattern": "no_profitable_windows", "count": 0, "mean_net_bps": 0}]
        )
    monthly = prof.resample("ME").size()
    patterns = [
        {
            "pattern": "bundle_yes_no_under_1",
            "count": int(len(prof)),
            "mean_net_bps": float(prof["net_bps"].mean()),
            "median_net_bps": float(prof["net_bps"].median()),
            "max_net_bps": float(prof["net_bps"].max()),
            "pct_of_days": float(len(prof) / max(len(arb_panel), 1)),
            "active_months": int((monthly > 0).sum()),
        }
    ]
    return pd.DataFrame(patterns)


def crypto_proxy_arb_vs_poly(
    doge: pd.Series,
    poly_yes: pd.Series,
    econ: ArbEconomics,
    max_lag: int = 5,
) -> pd.DataFrame:
    """Scan lags: CEX move today vs POLY reaction N days later (latency pattern)."""
    d_ret = doge.pct_change()
    p_ret = poly_yes.pct_change()
    rows = []
    for lag in range(0, max_lag + 1):
        delayed = p_ret.shift(lag)
        aligned = pd.DataFrame({"doge": d_ret, "poly": delayed}).dropna()
        if len(aligned) < 30:
            continue
        corr = aligned["doge"].corr(aligned["poly"])
        spread = (aligned["doge"] - aligned["poly"]).abs()
        hit_rate = float((spread > econ.min_gross_edge()).mean())
        rows.append(
            {
                "lag_days": lag,
                "correlation": corr,
                "mean_abs_spread": float(spread.mean()),
                "arb_hit_rate": hit_rate,
                "latency_ms_assumed": econ.latency_ms + lag * 86_400_000,
            }
        )
    return pd.DataFrame(rows)
