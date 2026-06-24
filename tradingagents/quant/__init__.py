"""Quant modules: Polymarket+meme strategy, walk-forward, Qlib bridge."""

from __future__ import annotations

__all__ = [
    "StrategyConfig",
    "load_universe_prices",
    "run_portfolio_backtest",
]


def __getattr__(name: str):
    """Lazy import so Kraken-only paths do not require yfinance at import time."""
    if name in __all__:
        from .polymarket_strategy import StrategyConfig, load_universe_prices, run_portfolio_backtest

        return {
            "StrategyConfig": StrategyConfig,
            "load_universe_prices": load_universe_prices,
            "run_portfolio_backtest": run_portfolio_backtest,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
