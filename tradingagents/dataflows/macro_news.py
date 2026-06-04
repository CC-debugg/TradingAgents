"""Open-source macro news: FRED + ECB RSS (no Bloomberg)."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

NY = ZoneInfo("America/New_York")
ECB_RSS = "https://www.ecb.europa.eu/rss/press.html"
FRED_OBS = "https://api.stlouisfed.org/fred/series/observations"


def fetch_ecb_headlines(limit: int = 15) -> pd.DataFrame:
    rows = []
    try:
        r = requests.get(ECB_RSS, timeout=15, headers={"User-Agent": "TradingAgents/1.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//item") or root.findall(".//atom:entry", ns)
        for it in items[:limit]:
            title = (it.findtext("title") or it.findtext("{*}title") or "").strip()
            pub = it.findtext("pubDate") or it.findtext("{*}updated") or ""
            link = it.findtext("link") or ""
            if title:
                rows.append({"source": "ECB", "title": title[:200], "published": pub, "url": link})
    except Exception:
        pass
    return pd.DataFrame(rows)


def fetch_fred_latest(series_id: str, api_key: str | None = None) -> dict | None:
    """Latest observation for a FRED series (optional API key)."""
    key = api_key or os.environ.get("FRED_API_KEY", "")
    if not key:
        return None
    try:
        r = requests.get(
            FRED_OBS,
            params={
                "series_id": series_id,
                "api_key": key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 2,
            },
            timeout=15,
        )
        r.raise_for_status()
        obs = r.json().get("observations", [])
        if not obs:
            return None
        latest = obs[0]
        return {
            "series_id": series_id,
            "date": latest.get("date"),
            "value": latest.get("value"),
        }
    except Exception:
        return None


def fetch_macro_news_snapshot() -> dict:
    """Daily snapshot for live CSV (ECB always; FRED if key set)."""
    now = datetime.now(NY).strftime("%Y-%m-%d %H:%M %Z")
    ecb = fetch_ecb_headlines(12)
    fred_rates = fetch_fred_latest("DFF")  # Fed funds effective rate
    fred_cpi = fetch_fred_latest("CPIAUCSL")
    return {
        "as_of_ny": now,
        "ecb_headlines": ecb,
        "fred_fed_funds": fred_rates,
        "fred_cpi": fred_cpi,
        "fred_api_configured": bool(os.environ.get("FRED_API_KEY")),
    }
