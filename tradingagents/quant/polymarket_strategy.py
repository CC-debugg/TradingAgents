"""Shared backtest engine for Polymarket + meme universe."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from typing import Any

import numpy as np
import pandas as pd

from tradingagents.dataflows.nautilus_data import get_nautilus_data_online


@dataclass
class StrategyConfig:
    start: str = "2020-01-01"
    end: str | None = None
    universe: list[dict[str, Any]] = field(default_factory=list)
    ema_fast: int = 20
    ema_slow: int = 60
    poly_ema_fast: int = 5
    poly_ema_slow: int = 15
    meme_long_only: bool = True
    portfolio_weight_mode: str = "sharpe_tilt"
    target_vol: float = 0.20
    vol_lookback: int = 20
    max_lev: float = 1.5
    tc_bps: float = 10.0
    risk_free: float = 0.04


DEFAULT_UNIVERSE = [
    {"name": "POLY_GTA", "nautilus_symbol": "POLY:gta-vi-released-before-june-2026"},
    {"name": "DOGE", "yfinance": "DOGE-USD", "coingecko_id": "dogecoin"},
    {"name": "WIF", "yfinance": "WIF-USD", "coingecko_id": "dogwifcoin"},
]


def _to_series(x, name=None):
    if isinstance(x, pd.DataFrame):
        x = x.squeeze()
    if hasattr(x, "columns"):
        x = x.iloc[:, 0]
    if name:
        x.name = name
    return x


def _parse_csv_price_output(payload, name):
    if not isinstance(payload, str) or not payload.strip():
        return None
    lines = [ln for ln in payload.splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        return None
    try:
        df = pd.read_csv(StringIO("\n".join(lines)))
        if df.empty:
            return None
        dt_col = df.columns[0]
        if dt_col.lower() in ("date", "datetime", "timestamp"):
            idx = pd.to_datetime(df[dt_col], errors="coerce")
        else:
            idx = pd.to_datetime(df.iloc[:, 0], errors="coerce")
        close_col = next((c for c in ["Close", "close"] if c in df.columns), None)
        if close_col is None:
            return None
        s = pd.Series(df[close_col].values, index=idx, name=name).dropna()
        s = s[~s.index.isna()].sort_index()
        return s if len(s) > 0 else None
    except Exception:
        return None


def _fetch_yf_close(ticker, start, end):
    try:
        import yfinance as yf

        s = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)["Close"]
        s = _to_series(s, ticker).dropna()
        return s if len(s) > 0 else None
    except Exception:
        return None


def _fetch_coingecko_close(coin_id, start, end, name):
    if not coin_id:
        return None
    try:
        import requests

        start_ts = int(pd.Timestamp(start).timestamp())
        end_ts = int((pd.Timestamp(end) + pd.Timedelta(days=1)).timestamp())
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
        r = requests.get(
            url, params={"vs_currency": "usd", "from": start_ts, "to": end_ts}, timeout=20
        )
        r.raise_for_status()
        prices = r.json().get("prices", [])
        if not prices:
            return None
        df = pd.DataFrame(prices, columns=["ts", "price"])
        df["date"] = pd.to_datetime(df["ts"], unit="ms").dt.floor("D")
        s = df.groupby("date")["price"].last().rename(name)
        return s.sort_index().dropna() if len(s) else None
    except Exception:
        return None


def load_universe_prices(cfg: StrategyConfig) -> dict[str, pd.Series]:
    end = cfg.end or pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    universe = cfg.universe or DEFAULT_UNIVERSE
    prices: dict[str, pd.Series] = {}
    for item in universe:
        nm = item["name"]
        s = None
        if item.get("nautilus_symbol"):
            raw = get_nautilus_data_online(item["nautilus_symbol"], cfg.start, end)
            s = _parse_csv_price_output(raw, nm)
        if s is None and item.get("yfinance"):
            s = _fetch_yf_close(item["yfinance"], cfg.start, end)
        if s is None:
            s = _fetch_coingecko_close(item.get("coingecko_id"), cfg.start, end, nm)
        if s is not None:
            prices[nm] = _to_series(s, nm).ffill().dropna()
    return prices


def _leg_returns(
    price: pd.Series,
    cfg: StrategyConfig,
    is_poly: bool,
    ema_fast: int | None = None,
    ema_slow: int | None = None,
) -> pd.Series:
    ema_fast = ema_fast if ema_fast is not None else (cfg.poly_ema_fast if is_poly else cfg.ema_fast)
    ema_slow = ema_slow if ema_slow is not None else (cfg.poly_ema_slow if is_poly else cfg.ema_slow)
    ret = price.pct_change()
    warmup = ema_slow
    ema_f = price.ewm(span=ema_fast, adjust=False).mean()
    ema_s = price.ewm(span=ema_slow, adjust=False).mean()
    signal = pd.Series(np.where(ema_f > ema_s, 1.0, -1.0), index=price.index)
    if cfg.meme_long_only and not is_poly:
        signal = signal.clip(lower=0.0)
    signal.iloc[:warmup] = 0.0
    vol_lb = min(cfg.vol_lookback, max(5, len(price) // 4))
    realized_vol = ret.rolling(vol_lb).std() * np.sqrt(252)
    target_daily = cfg.target_vol / np.sqrt(252)
    size = (target_daily / (realized_vol / np.sqrt(252))).clip(0, cfg.max_lev)
    size.iloc[:warmup] = 0.0
    position = signal * size
    tc = (signal.diff().abs() > 0) * (cfg.tc_bps / 10_000)
    leg_r = position.shift(1) * ret - tc
    leg_r.iloc[: warmup + 1] = 0.0
    return leg_r


def run_portfolio_backtest(
    prices: dict[str, pd.Series],
    cfg: StrategyConfig,
    ema_fast: int | None = None,
    ema_slow: int | None = None,
) -> tuple[pd.Series, pd.Series, dict[str, pd.Series]]:
    """Return (strategy_returns, weights, per_asset_returns)."""
    asset_returns: dict[str, pd.Series] = {}
    for name, price in prices.items():
        is_poly = name.startswith("POLY_")
        asset_returns[name] = _leg_returns(
            price, cfg, is_poly, ema_fast=ema_fast, ema_slow=ema_slow
        )
    ret_df = pd.DataFrame(asset_returns).dropna(how="all").fillna(0)
    rfd = cfg.risk_free / 252
    leg_sharpes = {}
    for col in ret_df.columns:
        r = ret_df[col].replace([np.inf, -np.inf], np.nan).dropna()
        leg_sharpes[col] = (r - rfd).mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0.0

    if cfg.portfolio_weight_mode == "equal":
        weights = pd.Series(1.0 / len(ret_df.columns), index=ret_df.columns)
    elif cfg.portfolio_weight_mode == "sharpe_tilt":
        tilt = pd.Series({k: max(0.1, v) for k, v in leg_sharpes.items()})
        weights = tilt / tilt.sum()
    else:
        vols = ret_df.std().replace(0, np.nan).dropna()
        weights = (1.0 / vols) / (1.0 / vols).sum()

    strat_r = ret_df[weights.index].dot(weights)
    return strat_r, weights, asset_returns


def sharpe_ratio(returns: pd.Series, rf: float = 0.04) -> float:
    r = returns.dropna().replace([np.inf, -np.inf], np.nan).dropna()
    if r.std() == 0 or len(r) < 5:
        return 0.0
    return float((r - rf / 252).mean() / r.std() * np.sqrt(252))
