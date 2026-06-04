"""MSCI Barra-style risk factor proxies (open-source ETFs — not licensed Barra).

Maps strategy returns to macro + style factors for daily live attribution dashboards.
"""

from __future__ import annotations

import pandas as pd

# Barra-like taxonomy: MACRO + STYLE (US equity factor ETFs)
BARRA_FACTOR_META: dict[str, dict[str, str]] = {
    # --- Macro (Ang / BlackRock SQA aligned) ---
    "BARRA_EQUITY_MARKET": {"group": "MACRO", "title": "Equity market", "proxy": "SPY"},
    "BARRA_REAL_RATES": {"group": "MACRO", "title": "Real rates", "proxy": "TIP"},
    "BARRA_INFLATION": {"group": "MACRO", "title": "Inflation", "proxy": "GLD"},
    "BARRA_CREDIT": {"group": "MACRO", "title": "Credit", "proxy": "HYG"},
    "BARRA_EM": {"group": "MACRO", "title": "Emerging markets", "proxy": "EEM"},
    "BARRA_FX_USD": {"group": "MACRO", "title": "USD", "proxy": "UUP"},
    "BARRA_COMMODITY": {"group": "MACRO", "title": "Commodities", "proxy": "DBC"},
    "BARRA_RATES": {"group": "MACRO", "title": "Nominal rates", "proxy": "TLT"},
    # --- Style (classic Barra / Fama-French extensions) ---
    "BARRA_SIZE": {"group": "STYLE", "title": "Size (SMB proxy)", "proxy": "IWM"},
    "BARRA_VALUE": {"group": "STYLE", "title": "Value", "proxy": "VLUE"},
    "BARRA_MOMENTUM": {"group": "STYLE", "title": "Momentum", "proxy": "MTUM"},
    "BARRA_LOW_VOL": {"group": "STYLE", "title": "Low volatility", "proxy": "USMV"},
    "BARRA_QUALITY": {"group": "STYLE", "title": "Quality", "proxy": "QUAL"},
    # --- Crypto sleeve ---
    "BARRA_CRYPTO": {"group": "ALT", "title": "Crypto beta", "proxy": "DOGE-USD"},
}


def barra_display_name(code: str) -> str:
    m = BARRA_FACTOR_META.get(code, {"group": "?", "title": code, "proxy": "?"})
    return f"{code} · {m['title']} ({m['proxy']}) [{m['group']}]"


def load_barra_factor_returns(start: str, end: str) -> pd.DataFrame:
    import yfinance as yf

    out = {}
    for code, meta in BARRA_FACTOR_META.items():
        tk = meta["proxy"]
        try:
            s = yf.download(tk, start=start, end=end, auto_adjust=True, progress=False)["Close"]
            if hasattr(s, "squeeze"):
                s = s.squeeze()
            out[code] = s.pct_change()
        except Exception:
            continue
    if not out:
        return pd.DataFrame()
    df = pd.DataFrame(out).dropna(how="all")
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df


def barra_factor_attribution(strat_r: pd.Series, factor_returns: pd.DataFrame) -> pd.DataFrame:
    from .qlib_bridge import factor_attribution

    attr = factor_attribution(strat_r, factor_returns)
    if not attr.empty:
        attr["group"] = attr["factor"].map(
            lambda f: BARRA_FACTOR_META.get(f, {}).get("group", "ALPHA")
            if f != "ALPHA"
            else "ALPHA"
        )
    return attr
