"""Polymarket market discovery via Gamma API.

Aligns with PDF / GitHub stack:
  - https://github.com/Polymarket/agents (official agent toolkit + market-data patterns)
  - https://github.com/harish-garg/Awesome-Polymarket-Tools (curated index)
"""

from __future__ import annotations

import requests

GAMMA_BASE = "https://gamma-api.polymarket.com"

# PDF QuantFin_RiskManagement — Polymarket / Crypto GitHub map
GITHUB_RESOURCES = {
    "tradingagents": {
        "url": "https://github.com/TauricResearch/TradingAgents",
        "integrated": True,
        "usage": "Multi-agent LLM; scripts/polymarket_meme_run.py agents",
    },
    "nautilus_trader": {
        "url": "https://github.com/nautechsystems/nautilus_trader",
        "integrated": True,
        "usage": "POLY:<slug> via tradingagents.dataflows.nautilus_data",
    },
    "polymarket_agents": {
        "url": "https://github.com/Polymarket/agents",
        "integrated": "api_patterns",
        "usage": "Gamma/CLOB data patterns in polymarket_gamma.py",
    },
    "polymarket_gamma_clob": {
        "url": "https://docs.polymarket.com",
        "integrated": True,
        "usage": "tradingagents.dataflows.polymarket_gamma",
    },
    "awesome_polymarket_tools": {
        "url": "https://github.com/harish-garg/Awesome-Polymarket-Tools",
        "integrated": "documented",
        "usage": "docs/GITHUB_INTEGRATION.md Phase 2",
    },
    "copy_trading_brunofancy": {
        "url": "https://github.com/Brunofancy/polymarket-copy-trading-bot-agent",
        "integrated": False,
        "usage": "External bot; wire via Polymarket CLOB credentials",
    },
    "polybot_texsellix": {
        "url": "https://github.com/texsellix/polymarket-trading-bot",
        "integrated": False,
        "usage": "Whale mirror bot; separate CLI",
    },
    "quiknode_polymarket_guide": {
        "url": "https://github.com/quiknode-labs/qn-guide-examples",
        "integrated": "documented",
        "usage": "defi/polymarket-copy-bot reference",
    },
    "kronos": {
        "url": "https://github.com/shiyu-coder/Kronos",
        "integrated": False,
        "usage": "Phase 2 candlestick foundation model",
    },
    "qlib": {
        "url": "https://github.com/microsoft/qlib",
        "integrated": True,
        "usage": "tradingagents/quant/qlib_bridge.py + polymarket_walkforward_qlib.py",
    },
    "solana_arbitrage": {
        "url": "https://github.com/ChangeYourself0613/Solana-Arbitrage-Bot",
        "integrated": True,
        "usage": "integrations/solana_arbitrage + scripts/solana_arb_bridge.py (selected PDF #3)",
    },
}


def fetch_active_markets(
    limit: int = 20,
    order: str = "volume_24hr",
    keyword: str | None = None,
) -> list[dict]:
    """Top active Polymarket markets from Gamma API."""
    try:
        r = requests.get(
            f"{GAMMA_BASE}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": min(limit, 100),
                "order": order,
                "ascending": "false",
            },
            timeout=15,
        )
        r.raise_for_status()
        markets = r.json()
        if not isinstance(markets, list):
            return []
        if keyword:
            kw = keyword.lower()
            markets = [
                m for m in markets
                if kw in (m.get("question") or "").lower()
                or kw in (m.get("slug") or "").lower()
            ]
        return markets[:limit]
    except Exception:
        return []


def fetch_crypto_polymarket_markets(limit: int = 8) -> list[dict]:
    """Markets tagged crypto/bitcoin/ethereum/meme in question text."""
    keywords = ("crypto", "bitcoin", "ethereum", "btc", "eth", "solana", "meme", "doge")
    seen_slugs: set[str] = set()
    out: list[dict] = []
    for kw in keywords:
        for m in fetch_active_markets(limit=30, keyword=kw):
            slug = m.get("slug") or ""
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                out.append(m)
            if len(out) >= limit:
                return out
    if len(out) < limit:
        for m in fetch_active_markets(limit=limit * 2):
            slug = m.get("slug") or ""
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                out.append(m)
            if len(out) >= limit:
                break
    return out[:limit]
