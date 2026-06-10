"""CSV-backed RL research sleeve (trained offline via integrations/rl_tensortrade)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

RL_RETURNS_CSV = Path(__file__).resolve().parents[2] / "data" / "rl_sleeve" / "rl_tensortrade_returns.csv"


def load_rl_sleeve_returns(start: str | None = None, end: str | None = None) -> pd.Series:
    """Daily returns of the offline-trained RL sleeve; empty Series if not trained yet."""
    if not RL_RETURNS_CSV.exists():
        return pd.Series(dtype=float)
    try:
        df = pd.read_csv(RL_RETURNS_CSV, parse_dates=["date"])
    except Exception:
        return pd.Series(dtype=float)
    if "rl_tensortrade" not in df.columns or df.empty:
        return pd.Series(dtype=float)
    s = df.set_index("date")["rl_tensortrade"].dropna().sort_index()
    if start:
        s = s.loc[pd.Timestamp(start):]
    if end:
        s = s.loc[:pd.Timestamp(end)]
    return s
