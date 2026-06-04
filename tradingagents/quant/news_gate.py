"""Macro news gate for live execution (ECB RSS + optional FRED; Bloomberg-ready hook)."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

# Keyword lists — coarse sentiment for gating (not NLP model).
RISK_OFF = (
    "inflation",
    "hike",
    "tightening",
    "crisis",
    "war",
    "recession",
    "slowdown",
    "default",
    "stress",
    "volatility",
    "uncertainty",
    "downgrade",
    "sanction",
)
RISK_ON = (
    "cut",
    "ease",
    "easing",
    "growth",
    "support",
    "recovery",
    "stabil",
    "expansion",
    "accommod",
    "lower rates",
    "stimulus",
)

GATE_BLOCK_THRESHOLD = -0.35


def _score_text(text: str) -> tuple[float, list[str]]:
    t = text.lower()
    hits: list[str] = []
    score = 0.0
    for w in RISK_OFF:
        if w in t:
            score -= 1.0
            hits.append(f"-{w}")
    for w in RISK_ON:
        if w in t:
            score += 1.0
            hits.append(f"+{w}")
    return score, hits


def score_macro_news(news_snapshot: dict[str, Any]) -> dict[str, Any]:
    """
    Return normalized macro score in [-1, 1] and whether new risk trades are allowed.
    """
    titles: list[str] = []
    ecb = news_snapshot.get("ecb_headlines")
    if isinstance(ecb, pd.DataFrame) and not ecb.empty:
        titles.extend(ecb["title"].astype(str).tolist())
    elif isinstance(ecb, list):
        titles.extend(str(r.get("title", "")) for r in ecb)

    raw = 0.0
    all_hits: list[str] = []
    for title in titles[:20]:
        s, hits = _score_text(title)
        raw += s
        all_hits.extend(hits[:3])

    # FRED: rising fed funds / high CPI → slight risk-off tilt
    ff = news_snapshot.get("fred_fed_funds") or {}
    if ff.get("value") not in (None, ".", ""):
        try:
            if float(ff["value"]) >= 4.5:
                raw -= 0.5
                all_hits.append("-high_fed_funds")
        except (TypeError, ValueError):
            pass

    # squash to [-1, 1]
    import math

    norm = math.tanh(raw / 4.0) if raw else 0.0
    allow = norm > GATE_BLOCK_THRESHOLD
    if norm <= GATE_BLOCK_THRESHOLD:
        label = "risk_off — block new entries"
    elif norm >= 0.35:
        label = "risk_on — full size allowed"
    else:
        label = "neutral — reduced conviction"

    return {
        "score": round(norm, 4),
        "raw_score": round(raw, 2),
        "allow_new_trades": allow,
        "label": label,
        "keyword_hits": list(dict.fromkeys(all_hits))[:12],
        "n_headlines": len(titles),
    }


def apply_news_gate(signal: float, gate: dict[str, Any]) -> tuple[float, str]:
    """Zero out new risk when macro gate blocks; scale down in neutral zone."""
    if not gate.get("allow_new_trades", True):
        return 0.0, "blocked_by_news_gate"
    score = float(gate.get("score", 0))
    if abs(signal) < 1e-9:
        return 0.0, "flat"
    if score < 0:
        return signal * 0.5, "half_size_neutral_macro"
    return signal, "full_size"
