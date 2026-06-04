"""Andrew Ang / BlackRock SQA-style macro factor proxies (Factors → Assets).

Reference: Greenberg, Babu, Ang (2016) JPM; BlackRock macro factor deck.
Uses liquid ETF/index proxies via yfinance — not licensed Barra/Aladdin.
"""

from __future__ import annotations

import pandas as pd

# Factor code → (display name, yfinance ticker, description)
ANG_MACRO_FACTORS: dict[str, dict[str, str]] = {
    "ECON_GROWTH": {
        "title": "Economic growth",
        "proxy": "SPY",
        "desc": "Equity market beta / growth exposure",
    },
    "REAL_RATES": {
        "title": "Real rates",
        "proxy": "TIP",
        "desc": "Inflation-linked bonds (real yield proxy)",
    },
    "INFLATION": {
        "title": "Inflation",
        "proxy": "GLD",
        "desc": "Nominal vs real wedge proxy (commodity/inflation hedge)",
    },
    "CREDIT": {
        "title": "Credit",
        "proxy": "HYG",
        "desc": "Credit spread risk (high yield)",
    },
    "EM": {
        "title": "Emerging markets",
        "proxy": "EEM",
        "desc": "EM equity risk premium",
    },
    "FX": {
        "title": "FX / USD",
        "proxy": "UUP",
        "desc": "US dollar strength",
    },
    "COMMOD": {
        "title": "Commodities",
        "proxy": "DBC",
        "desc": "Broad commodity beta",
    },
    "POLICY_RATES": {
        "title": "Policy / duration",
        "proxy": "TLT",
        "desc": "Long nominal rates (duration)",
    },
    "CRYPTO": {
        "title": "Crypto beta",
        "proxy": "DOGE-USD",
        "desc": "Meme/crypto risk factor",
    },
}


def load_ang_macro_returns(start: str, end: str) -> pd.DataFrame:
    """Daily factor return proxies aligned on business days."""
    import yfinance as yf

    tickers = {code: meta["proxy"] for code, meta in ANG_MACRO_FACTORS.items()}
    out = {}
    for code, tk in tickers.items():
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


def ang_factor_display_name(code: str) -> str:
    meta = ANG_MACRO_FACTORS.get(code, {"title": code, "proxy": "?"})
    return f"{code} · {meta['title']} ({meta['proxy']})"
