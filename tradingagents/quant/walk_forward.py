"""Walking-forward optimization: train (less) → test (more), rolling OOS windows."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd

from .polymarket_strategy import StrategyConfig, run_portfolio_backtest, sharpe_ratio


@dataclass
class WalkForwardConfig:
    train_days: int = 252
    test_days: int = 63
    step_days: int | None = None
    ema_fast_grid: tuple[int, ...] = (10, 20, 30)
    ema_slow_grid: tuple[int, ...] = (40, 60, 90)
    min_train_bars: int = 120


def generate_walk_forward_windows(
    index: pd.DatetimeIndex,
    train_days: int,
    test_days: int,
    step_days: int | None = None,
) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """List of (train_start, train_end, test_start, test_end) inclusive."""
    step = step_days or test_days
    windows = []
    i = train_days
    while i + test_days <= len(index):
        train_start = index[i - train_days]
        train_end = index[i - 1]
        test_start = index[i]
        test_end = index[min(i + test_days - 1, len(index) - 1)]
        windows.append((train_start, train_end, test_start, test_end))
        i += step
    return windows


def optimize_ema_on_train(
    train_prices: dict[str, pd.Series],
    cfg: StrategyConfig,
    fast_grid: tuple[int, ...],
    slow_grid: tuple[int, ...],
) -> tuple[int, int, float]:
    best = (fast_grid[0], slow_grid[0], -np.inf)
    for ef, es in product(fast_grid, slow_grid):
        if ef >= es:
            continue
        strat, _, _ = run_portfolio_backtest(train_prices, cfg, ema_fast=ef, ema_slow=es)
        sh = sharpe_ratio(strat, cfg.risk_free)
        if sh > best[2]:
            best = (ef, es, sh)
    return int(best[0]), int(best[1]), float(best[2])


def run_walk_forward(
    prices: dict[str, pd.Series],
    cfg: StrategyConfig,
    wf: WalkForwardConfig,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Rolling train → test. Returns (fold_metrics_df, stitched_oos_returns).
    """
    idx = pd.DatetimeIndex(sorted(set().union(*[p.index for p in prices.values()])))
    windows = generate_walk_forward_windows(
        idx, wf.train_days, wf.test_days, wf.step_days
    )
    rows = []
    oos_parts: list[pd.Series] = []

    for train_start, train_end, test_start, test_end in windows:
        train_prices = {
            k: v.loc[train_start:train_end] for k, v in prices.items() if len(v.loc[train_start:train_end]) >= wf.min_train_bars
        }
        if len(train_prices) < 1:
            continue
        ef, es, train_sh = optimize_ema_on_train(
            train_prices, cfg, wf.ema_fast_grid, wf.ema_slow_grid
        )
        test_prices = {k: v.loc[test_start:test_end] for k, v in prices.items()}
        strat, _, _ = run_portfolio_backtest(test_prices, cfg, ema_fast=ef, ema_slow=es)
        test_sh = sharpe_ratio(strat, cfg.risk_free)
        test_ret = float((1 + strat).prod() - 1) if len(strat) else 0.0
        rows.append(
            {
                "train_start": train_start.date(),
                "train_end": train_end.date(),
                "test_start": test_start.date(),
                "test_end": test_end.date(),
                "train_sharpe": train_sh,
                "test_sharpe": test_sh,
                "test_return": test_ret,
                "ema_fast": ef,
                "ema_slow": es,
            }
        )
        oos_parts.append(strat)

    folds = pd.DataFrame(rows)
    if oos_parts:
        oos = pd.concat(oos_parts).sort_index()
        oos = oos[~oos.index.duplicated(keep="last")]
    else:
        oos = pd.Series(dtype=float)
    return folds, oos
