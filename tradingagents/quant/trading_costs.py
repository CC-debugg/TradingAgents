"""Standard transaction costs for backtest + live dashboard (5 bps per leg)."""

from __future__ import annotations

# 5 bps on each buy or sell → 10 bps round-trip (enter + exit)
FEE_BPS_PER_LEG = 5.0
ROUND_TRIP_BPS = FEE_BPS_PER_LEG * 2


def cost_on_signal_change(changed: bool, legs: int = 1) -> float:
    """Return transaction cost fraction for a signal flip (per leg)."""
    if not changed:
        return 0.0
    return (FEE_BPS_PER_LEG / 10_000) * legs


def cost_series_from_signal(signal) -> "pd.Series":
    """Daily TC series: 5 bps per leg on each |Δsignal| > 0."""
    import pandas as pd

    flips = signal.diff().abs() > 0
    return flips.astype(float) * (FEE_BPS_PER_LEG / 10_000)


def round_trip_cost_pairs_spread(signal, fee_bps: float = FEE_BPS_PER_LEG) -> "pd.Series":
    """Pairs trade: 5 bps per leg (DOGE + WIF) on each position change → 10 bps per rebalance."""
    import pandas as pd

    flips = signal.diff().abs() > 0
    return flips.astype(float) * (fee_bps / 10_000) * 2
