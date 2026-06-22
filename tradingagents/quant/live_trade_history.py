"""Live trade history: backtest fills + persisted refresh order log."""

from __future__ import annotations

import csv
import hashlib
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from tradingagents.execution.polymarket_clob import OrderIntent, execute_intents, live_trading_enabled
from tradingagents.quant.pairs_stat_arb import pairs_spread_signal_v2
from tradingagents.quant.whale_strategy import WhaleStrategyConfig, whale_flow_signal_v2

NY = ZoneInfo("America/New_York")
LIVE_LOG_COLUMNS = (
    "recorded_at_ny",
    "book",
    "strategy",
    "asset",
    "action",
    "side",
    "outcome",
    "size_usd",
    "limit_price",
    "status",
    "mode",
    "gate_score",
    "gate_label",
    "reason",
    "message",
    "refresh_fp",
    "poly_signal",
    "doge_signal",
    "wif_signal",
)


def _history_path() -> Path:
    raw = os.environ.get("LIVE_TRADE_HISTORY_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "data" / "live" / "trade_history.csv"


def _describe_whale_action(prev: float, curr: float) -> tuple[str, str, str]:
    """Return (action, side, outcome)."""
    if prev == curr:
        return "", "", ""
    if prev == 0 and curr > 0:
        return "OPEN", "BUY", "Yes"
    if prev == 0 and curr < 0:
        return "OPEN", "BUY", "No"
    if curr == 0:
        return "CLOSE", "SELL", "Yes" if prev > 0 else "No"
    if prev > 0 and curr < 0:
        return "FLIP", "BUY", "No"
    if prev < 0 and curr > 0:
        return "FLIP", "BUY", "Yes"
    return "ADJUST", "BUY" if curr > 0 else "BUY", "Yes" if curr > 0 else "No"


def _describe_pairs_action(prev: float, curr: float) -> list[dict]:
    if prev == curr:
        return []
    rows: list[dict] = []
    if prev == 0 and curr != 0:
        if curr > 0:
            rows.append({"action": "OPEN", "side": "BUY", "asset": "DOGE", "leg": "long"})
            rows.append({"action": "OPEN", "side": "SELL", "asset": "WIF", "leg": "short"})
        else:
            rows.append({"action": "OPEN", "side": "SELL", "asset": "DOGE", "leg": "short"})
            rows.append({"action": "OPEN", "side": "BUY", "asset": "WIF", "leg": "long"})
    elif curr == 0:
        if prev > 0:
            rows.append({"action": "CLOSE", "side": "SELL", "asset": "DOGE", "leg": "long"})
            rows.append({"action": "CLOSE", "side": "BUY", "asset": "WIF", "leg": "short"})
        else:
            rows.append({"action": "CLOSE", "side": "BUY", "asset": "DOGE", "leg": "short"})
            rows.append({"action": "CLOSE", "side": "SELL", "asset": "WIF", "leg": "long"})
    else:
        rows.append({"action": "FLIP", "side": "BUY", "asset": "DOGE", "leg": "spread"})
        rows.append({"action": "FLIP", "side": "BUY", "asset": "WIF", "leg": "spread"})
    return rows


def trades_from_signal_series(
    strategy_id: str,
    asset: str,
    signal: pd.Series,
    price: pd.Series | None = None,
    z: pd.Series | None = None,
    max_rows: int = 150,
) -> list[dict]:
    """Extract OPEN/CLOSE/FLIP rows when signal changes."""
    sig = signal.dropna().sort_index()
    if len(sig) < 2:
        return []
    rows: list[dict] = []
    prev = float(sig.iloc[0])
    for i in range(1, len(sig)):
        curr = float(sig.iloc[i])
        dt = sig.index[i]
        if strategy_id == "pairs_stat_arb":
            leg_rows = _describe_pairs_action(prev, curr)
            for leg in leg_rows:
                px = None
                if price is not None and leg["asset"] in ("DOGE", "WIF"):
                    # price series passed as dict externally — skip here
                    pass
                rows.append(
                    {
                        "date": str(pd.Timestamp(dt).date()),
                        "strategy": strategy_id,
                        "asset": leg["asset"],
                        "action": leg["action"],
                        "side": leg["side"],
                        "outcome": leg.get("leg", ""),
                        "signal": round(curr, 3),
                        "z_score": round(float(z.loc[dt]), 3) if z is not None and dt in z.index else None,
                        "price": px,
                        "reason": f"spread z={z.loc[dt]:.2f}" if z is not None and dt in z.index else "pairs v2",
                    }
                )
        else:
            action, side, outcome = _describe_whale_action(prev, curr)
            if not action:
                prev = curr
                continue
            px = round(float(price.loc[dt]), 4) if price is not None and dt in price.index else None
            rows.append(
                {
                    "date": str(pd.Timestamp(dt).date()),
                    "strategy": strategy_id,
                    "asset": asset,
                    "action": action,
                    "side": side,
                    "outcome": outcome,
                    "signal": round(curr, 3),
                    "z_score": None,
                    "price": px,
                    "reason": "whale_flow v2",
                }
            )
        prev = curr
    return rows[-max_rows:]


def build_prod_backtest_trades(
    flow: pd.DataFrame,
    poly: pd.Series,
    doge: pd.Series | None,
    wif: pd.Series | None,
    max_rows: int = 120,
) -> list[dict]:
    rows: list[dict] = []
    if len(poly) and not flow.empty:
        cfg = WhaleStrategyConfig()
        sig = whale_flow_signal_v2(flow, poly, cfg)
        rows.extend(trades_from_signal_series("whale_flow", "POLY_GTA", sig, price=poly, max_rows=max_rows))
    if doge is not None and wif is not None:
        psig, z = pairs_spread_signal_v2(doge, wif)
        pair_rows = trades_from_signal_series("pairs_stat_arb", "DOGE/WIF", psig, z=z, max_rows=max_rows)
        doge_px = doge.reindex(psig.index).ffill()
        wif_px = wif.reindex(psig.index).ffill()
        for r in pair_rows:
            dt = pd.Timestamp(r["date"])
            if r["asset"] == "DOGE" and dt in doge_px.index:
                r["price"] = round(float(doge_px.loc[dt]), 6)
            elif r["asset"] == "WIF" and dt in wif_px.index:
                r["price"] = round(float(wif_px.loc[dt]), 6)
        rows.extend(pair_rows)
    rows.sort(key=lambda x: (x["date"], x["strategy"], x["asset"]))
    return rows[-max_rows:]


def _intent_fingerprint(
    intents: list[OrderIntent],
    gate_score: float,
    signals: dict[str, float],
) -> str:
    payload = (
        f"{gate_score:.3f}|"
        f"{signals.get('POLY_GTA', 0):.3f}|"
        f"{signals.get('DOGE', 0):.3f}|"
        f"{signals.get('WIF', 0):.3f}|"
        + "|".join(f"{i.market_slug}:{i.outcome}:{i.side}:{i.size_usd:.2f}" for i in intents)
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _load_live_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _append_live_log(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LIVE_LOG_COLUMNS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for row in rows:
            w.writerow(row)


def record_live_refresh(
    as_of_ny: str,
    intents: list[OrderIntent],
    execution_results: list[dict],
    news_gate: dict,
    signals: dict[str, float],
    *,
    book: str = "live_composite",
    persist: bool = True,
) -> dict:
    """
    Append current refresh orders to CSV (deduped by intent fingerprint).
    Returns current orders + saved history tail for dashboard.
    """
    path = _history_path()
    gate_score = float(news_gate.get("score", 0) or 0)
    gate_label = str(news_gate.get("label", ""))
    mode = "live" if live_trading_enabled() else "dry_run"
    fp = _intent_fingerprint(intents, gate_score, signals)

    existing = _load_live_log(path)
    last_fp = existing[-1].get("refresh_fp") if existing else None  # type: ignore[attr-defined]

    new_rows: list[dict] = []
    if fp != last_fp or not existing:
        for intent, result in zip(intents, execution_results, strict=False):
            strategy = "whale_flow" if "poly" in intent.reason else "pairs_stat_arb"
            asset = "POLY_GTA" if intent.market_slug.startswith("gta") else intent.market_slug.replace("-USD", "")
            new_rows.append(
                {
                    "recorded_at_ny": as_of_ny,
                    "book": book,
                    "strategy": strategy,
                    "asset": asset,
                    "action": "ORDER",
                    "side": intent.side,
                    "outcome": intent.outcome,
                    "size_usd": round(float(intent.size_usd), 2),
                    "limit_price": round(float(intent.limit_price), 6) if intent.limit_price else 0,
                    "status": result.get("status", "dry_run"),
                    "mode": mode,
                    "gate_score": round(gate_score, 3),
                    "gate_label": gate_label,
                    "reason": intent.reason,
                    "message": result.get("message", ""),
                    "refresh_fp": fp,
                    "poly_signal": round(float(signals.get("POLY_GTA", 0)), 3),
                    "doge_signal": round(float(signals.get("DOGE", 0)), 3),
                    "wif_signal": round(float(signals.get("WIF", 0)), 3),
                }
            )
        if persist:
            _append_live_log(path, new_rows)
            existing = _load_live_log(path)

    tail = existing[-200:] if existing else new_rows
    current = []
    for intent, result in zip(intents, execution_results, strict=False):
        strategy = "whale_flow" if "poly" in intent.reason else "pairs_stat_arb"
        asset = "POLY_GTA" if intent.market_slug.startswith("gta") else intent.market_slug.replace("-USD", "")
        current.append(
            {
                "strategy": strategy,
                "asset": asset,
                "side": intent.side,
                "outcome": intent.outcome,
                "action": _human_order_label(intent),
                "size_usd": round(float(intent.size_usd), 2),
                "limit_price": round(float(intent.limit_price), 6) if intent.limit_price else None,
                "status": result.get("status", "dry_run"),
                "mode": mode,
                "reason": intent.reason,
                "message": result.get("message", ""),
            }
        )

    flat = current == []
    return {
        "log_path": str(path),
        "mode": mode,
        "n_saved": len(existing),
        "current_orders": current,
        "position_summary": _position_summary(signals),
        "live_log_tail": tail[-80:],
        "note": (
            "Each dashboard refresh appends PROD order intents to trade_history.csv. "
            "dry_run = logged only; live = sent when POLYMARKET_LIVE=1."
        ),
        "flat": flat,
    }


def _human_order_label(intent: OrderIntent) -> str:
    if intent.market_slug.startswith("gta"):
        if intent.outcome == "Yes" and intent.side == "BUY":
            return "BUY Yes (long GTA prob up)"
        if intent.outcome == "No" and intent.side == "BUY":
            return "BUY No (short GTA prob down)"
    if intent.market_slug == "DOGE-USD":
        return f"{intent.side} DOGE spot"
    if intent.market_slug == "WIF-USD":
        return f"{intent.side} WIF spot"
    return f"{intent.side} {intent.outcome}"


def _position_summary(signals: dict[str, float]) -> list[dict]:
    out = []
    poly = float(signals.get("POLY_GTA", 0))
    doge = float(signals.get("DOGE", 0))
    wif = float(signals.get("WIF", 0))
    if abs(poly) > 0.01:
        out.append({"asset": "POLY_GTA", "position": "Long Yes" if poly > 0 else "Long No", "signal": poly})
    else:
        out.append({"asset": "POLY_GTA", "position": "Flat", "signal": poly})
    if abs(doge) > 0.01 or abs(wif) > 0.01:
        out.append({"asset": "DOGE/WIF", "position": f"Spread DOGE={doge:+.2f} WIF={wif:+.2f}", "signal": doge})
    else:
        out.append({"asset": "DOGE/WIF", "position": "Flat", "signal": 0})
    return out


def build_trade_history_payload(
    bundle: dict,
    exec_snap: dict,
    as_of_ny: str,
    *,
    persist: bool = True,
) -> dict:
    intents = exec_snap.get("all_intents") or exec_snap.get("clob_intents") or []
    results = execute_intents(intents)
    backtest = build_prod_backtest_trades(
        bundle.get("flow", pd.DataFrame()),
        bundle.get("poly", pd.Series(dtype=float)),
        bundle.get("prices", {}).get("DOGE"),
        bundle.get("prices", {}).get("WIF"),
    )
    live = record_live_refresh(
        as_of_ny,
        intents,
        results,
        exec_snap.get("news_gate") or {},
        exec_snap.get("signals") or {},
        persist=persist,
    )
    return {
        "backtest_trades": backtest,
        "execution_results": results,
        **live,
    }
