"""Walk-forward OOS metrics for any daily return series (max history)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.quant.walk_forward import generate_walk_forward_windows
from tradingagents.quant.whale_strategy import strategy_metrics


def walk_forward_returns(
    returns: pd.Series,
    train_days: int = 60,
    test_days: int = 21,
    min_bars: int = 40,
) -> dict:
    """
    Rolling OOS on a fixed signal (no param search) — longest history available.
    Shrinks train/test if series is short.
    """
    r = returns.dropna().sort_index()
    if len(r) < min_bars + test_days + 10:
        return {"n_folds": 0, "oos_sharpe": 0.0, "oos_return": 0.0, "folds": []}

    idx = pd.DatetimeIndex(r.index)
    td, tst = train_days, test_days
    while td + tst + 5 > len(idx) and td > 20:
        td = max(20, td // 2)
        tst = max(10, tst // 2)

    windows = generate_walk_forward_windows(idx, td, tst, step_days=tst)
    if not windows:
        return {"n_folds": 0, "oos_sharpe": 0.0, "oos_return": 0.0, "folds": []}

    rows = []
    oos_parts: list[pd.Series] = []
    for train_start, train_end, test_start, test_end in windows:
        tr = r.loc[train_start:train_end]
        te = r.loc[test_start:test_end]
        if len(tr) < 15 or len(te) < 5:
            continue
        mt = strategy_metrics(tr)
        me = strategy_metrics(te)
        rows.append(
            {
                "train_start": str(train_start.date()),
                "train_end": str(train_end.date()),
                "test_start": str(test_start.date()),
                "test_end": str(test_end.date()),
                "train_sharpe": round(float(mt.get("sharpe", 0)), 3),
                "test_sharpe": round(float(me.get("sharpe", 0)), 3),
                "test_return": round(float(me.get("total_return", 0)), 4),
            }
        )
        oos_parts.append(te)

    if not oos_parts:
        return {"n_folds": 0, "oos_sharpe": 0.0, "oos_return": 0.0, "folds": []}

    oos = pd.concat(oos_parts).sort_index()
    oos = oos[~oos.index.duplicated(keep="last")]
    m = strategy_metrics(oos)
    return {
        "n_folds": len(rows),
        "train_days": td,
        "test_days": tst,
        "oos_sharpe": round(float(m.get("sharpe", 0)), 3),
        "oos_return": round(float(m.get("total_return", 0)), 4),
        "oos_cagr": round(float(m.get("cagr", 0)), 4),
        "history_start": str(r.index.min().date()),
        "history_end": str(r.index.max().date()),
        "folds": rows[-8:],
    }
