"""Shared backtest engine for Polymarket + meme universe."""

from __future__ import annotations

import json
import os
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
    {"name": "DOGE", "yfinance": "DOGE-USD", "coingecko_id": "dogecoin", "kraken": "DOGEUSD"},
    {"name": "WIF", "yfinance": "WIF-USD", "coingecko_id": "dogwifcoin", "kraken": "WIFUSD"},
]

_KRAKEN_OHLC = "https://api.kraken.com/0/public/OHLC"
_HTTP_HEADERS = {"User-Agent": "TradingAgents-LiveDashboard/1.0"}


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
        from tradingagents.dataflows.stockstats_utils import yf_retry
        import yfinance as yf

        t = yf.Ticker(ticker)
        data = yf_retry(lambda: t.history(start=start, end=end, auto_adjust=True))
        if data is None or data.empty or "Close" not in data.columns:
            return None
        s = _to_series(data["Close"], ticker).dropna()
        if s.index.tz is not None:
            s.index = s.index.tz_localize(None)
        return s if len(s) > 0 else None
    except Exception:
        return None


def _fetch_coingecko_ohlc(coin_id, start, end, name):
    if not coin_id:
        return None
    try:
        import time

        import requests

        days = max(30, min(365, (pd.Timestamp(end) - pd.Timestamp(start)).days + 5))
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
        for attempt in range(3):
            r = requests.get(
                url,
                params={"vs_currency": "usd", "days": days},
                timeout=25,
                headers=_HTTP_HEADERS,
            )
            if r.status_code == 429 and attempt < 2:
                time.sleep(2.0 * (attempt + 1))
                continue
            r.raise_for_status()
            rows = r.json()
            if not rows:
                return None
            idx = pd.to_datetime([row[0] for row in rows], unit="ms").floor("D")
            closes = [float(row[4]) for row in rows]
            s = pd.Series(closes, index=idx, name=name).sort_index()
            s = s.loc[pd.Timestamp(start) : pd.Timestamp(end)]
            return s.dropna() if len(s) else None
    except Exception:
        return None


def _fetch_coingecko_close(coin_id, start, end, name):
    if not coin_id:
        return None
    try:
        import time

        import requests

        start_ts = int(pd.Timestamp(start).timestamp())
        end_ts = int((pd.Timestamp(end) + pd.Timedelta(days=1)).timestamp())
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart/range"
        for attempt in range(3):
            r = requests.get(
                url,
                params={"vs_currency": "usd", "from": start_ts, "to": end_ts},
                timeout=25,
                headers=_HTTP_HEADERS,
            )
            if r.status_code == 429 and attempt < 2:
                time.sleep(2.0 * (attempt + 1))
                continue
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


def _fetch_kraken_close(pair, start, end, name):
    if not pair:
        return None
    try:
        import requests

        since = int(pd.Timestamp(start).timestamp())
        r = requests.get(
            _KRAKEN_OHLC,
            params={"pair": pair, "interval": 1440, "since": since},
            timeout=25,
            headers=_HTTP_HEADERS,
        )
        r.raise_for_status()
        payload = r.json()
        if payload.get("error"):
            return None
        result = payload.get("result") or {}
        ohlc_key = next((k for k in result if k != "last"), None)
        if not ohlc_key:
            return None
        rows = result[ohlc_key]
        idx = pd.to_datetime([row[0] for row in rows], unit="s").floor("D")
        closes = [float(row[4]) for row in rows]
        s = pd.Series(closes, index=idx, name=name).sort_index()
        s = s.loc[pd.Timestamp(start) : pd.Timestamp(end)]
        return s.dropna() if len(s) else None
    except Exception:
        return None


def _price_cache_dir() -> str:
    return os.environ.get("LIVE_PRICE_CACHE_DIR", "/tmp/ta_live_prices")


def _read_price_cache(name: str, max_age_hours: int = 36) -> pd.Series | None:
    path = os.path.join(_price_cache_dir(), f"{name}.json")
    if not os.path.isfile(path):
        return None
    try:
        age_h = (pd.Timestamp.utcnow().timestamp() - os.path.getmtime(path)) / 3600
        if age_h > max_age_hours:
            return None
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        idx = pd.to_datetime(obj["dates"])
        s = pd.Series(obj["close"], index=idx, name=name).sort_index()
        return s.dropna() if len(s) else None
    except Exception:
        return None


def _write_price_cache(name: str, series: pd.Series) -> None:
    try:
        d = _price_cache_dir()
        os.makedirs(d, exist_ok=True)
        s = series.dropna().sort_index()
        obj = {"dates": [str(x.date()) for x in s.index], "close": [float(v) for v in s.values]}
        with open(os.path.join(d, f"{name}.json"), "w", encoding="utf-8") as f:
            json.dump(obj, f)
    except Exception:
        pass


def _fetch_meme_close(item: dict[str, Any], start: str, end: str) -> pd.Series | None:
    """Yahoo → CoinGecko OHLC → Kraken → disk cache (cloud-safe)."""
    nm = item["name"]
    s = None
    if item.get("yfinance"):
        s = _fetch_yf_close(item["yfinance"], start, end)
    if s is None or len(s) < 20:
        cg = _fetch_coingecko_ohlc(item.get("coingecko_id"), start, end, nm)
        if cg is not None and len(cg) >= 20:
            s = cg
    if s is None or len(s) < 20:
        cg2 = _fetch_coingecko_close(item.get("coingecko_id"), start, end, nm)
        if cg2 is not None and len(cg2) >= 20:
            s = cg2
    if s is None or len(s) < 20:
        kr = _fetch_kraken_close(item.get("kraken"), start, end, nm)
        if kr is not None and len(kr) >= 20:
            s = kr
    if s is None or len(s) < 20:
        s = _read_price_cache(nm)
    if s is not None and len(s) >= 20:
        _write_price_cache(nm, s)
    return s


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
            s = _fetch_meme_close(item, cfg.start, end)
        if s is None and item.get("coingecko_id"):
            s = _fetch_coingecko_ohlc(item["coingecko_id"], cfg.start, end, nm)
        if s is None:
            s = _fetch_coingecko_close(item.get("coingecko_id"), cfg.start, end, nm)
        if s is None and item.get("kraken"):
            s = _fetch_kraken_close(item["kraken"], cfg.start, end, nm)
        if s is None and nm in ("DOGE", "WIF"):
            s = _read_price_cache(nm)
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
