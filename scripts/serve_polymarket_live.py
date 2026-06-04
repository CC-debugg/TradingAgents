#!/usr/bin/env python3
"""
Interactive LIVE strategy dashboard — refresh on each page load / tab click.

  python scripts/serve_polymarket_live.py              # localhost
  python scripts/serve_polymarket_live.py --public     # 0.0.0.0 (LAN / cloud)

API: GET /api/live  → JSON (recomputes strategy returns + Barra + news)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

APP_DIR = os.path.join(REPO_ROOT, "assets", "dashboard_outputs", "live_app")
DEFAULT_PORT = 8765
PORT_SCAN = 10  # local only — cloud uses fixed PORT


def _resolve_bind() -> tuple[str, int, bool]:
    """Return (host, port, allow_port_scan)."""
    public = os.environ.get("PUBLIC", "").strip().lower() in ("1", "true", "yes")
    host = os.environ.get("HOST", "0.0.0.0" if public else "127.0.0.1")
    port_env = os.environ.get("PORT", "").strip()
    if port_env.isdigit():
        return host, int(port_env), False
    return host, DEFAULT_PORT, True


def _basic_auth_ok(header: str | None, required: str) -> bool:
    if not required or ":" not in required:
        return True
    user, pwd = required.split(":", 1)
    expected = base64.b64encode(f"{user}:{pwd}".encode()).decode()
    if not header or not header.startswith("Basic "):
        return False
    return header.split(" ", 1)[1].strip() == expected


class LiveDashboardHandler(BaseHTTPRequestHandler):
    server_version = "PolymarketLive/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[live] {self.address_string()} - {fmt % args}")

    def _require_auth(self) -> bool:
        required = os.environ.get("DASHBOARD_BASIC_AUTH", "").strip()
        if _basic_auth_ok(self.headers.get("Authorization"), required):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Polymarket Live Dashboard"')
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Authentication required")
        return False

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, code: int, data: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if not self._require_auth():
            return
        path = urlparse(self.path).path
        if path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if path == "/api/version":
            try:
                from tradingagents.quant.strategy_catalog import DASHBOARD_VERSION, STRATEGY_CATALOG

                self._send_json(
                    200,
                    {
                        "dashboard_version": DASHBOARD_VERSION,
                        "strategy_ids": [s.id for s in STRATEGY_CATALOG],
                        "n_strategies": len(STRATEGY_CATALOG),
                    },
                )
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        if path == "/api/live":
            try:
                from tradingagents.quant.live_dashboard_payload import build_live_payload

                payload = build_live_payload()
                self._send_json(200, payload)
            except Exception as exc:
                self._send_json(
                    500,
                    {"error": str(exc), "trace": traceback.format_exc()},
                )
            return

        if path in ("/", "/app", "/index.html"):
            index = os.path.join(APP_DIR, "index.html")
            if not os.path.isfile(index):
                self._send_json(404, {"error": f"missing {index}"})
                return
            with open(index, "rb") as f:
                self._send_bytes(200, f.read(), "text/html; charset=utf-8")
            return

        self._send_json(404, {"error": "not found", "path": path})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()


def _create_server(host: str, port: int, scan: bool) -> tuple[ThreadingHTTPServer, int]:
    if not scan:
        return ThreadingHTTPServer((host, port), LiveDashboardHandler), port
    last_err: OSError | None = None
    for p in range(port, port + PORT_SCAN):
        try:
            httpd = ThreadingHTTPServer((host, p), LiveDashboardHandler)
            if p != port:
                print(f"  Note: port {port} was busy → using {p}")
            return httpd, p
        except OSError as exc:
            if exc.errno in (48, 98):
                last_err = exc
                if p == port:
                    print(
                        f"  Port {port} already in use — "
                        f"open http://{host}:{port}/ or kill the old process."
                    )
                continue
            raise
    raise last_err or OSError(f"no free port in {port}..{port + PORT_SCAN - 1}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Polymarket live interactive dashboard")
    parser.add_argument("--port", type=int, default=None, help="Port (default: $PORT or 8765)")
    parser.add_argument("--host", default=None, help="Bind host (default: 127.0.0.1 or 0.0.0.0 with --public)")
    parser.add_argument(
        "--public",
        action="store_true",
        help="Bind 0.0.0.0 for LAN/cloud; forces POLYMARKET_LIVE=0",
    )
    args = parser.parse_args()

    if args.public:
        os.environ.setdefault("PUBLIC", "1")
        os.environ["POLYMARKET_LIVE"] = "0"

    default_host, default_port, scan = _resolve_bind()
    host = args.host or default_host
    port = args.port if args.port is not None else default_port
    if os.environ.get("PORT", "").strip().isdigit():
        scan = False

    os.makedirs(APP_DIR, exist_ok=True)
    from tradingagents.quant.strategy_catalog import DASHBOARD_VERSION, STRATEGY_CATALOG

    httpd, bound_port = _create_server(host, port, scan)
    public_url = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if public_url:
        url = public_url.rstrip("/") + "/"
    elif host == "0.0.0.0":
        url = f"http://0.0.0.0:{bound_port}/  (use your server IP or Render URL)"
    else:
        url = f"http://{host}:{bound_port}/"

    ids = [s.id for s in STRATEGY_CATALOG]
    auth = os.environ.get("DASHBOARD_BASIC_AUTH", "").strip()
    print("=" * 65)
    print(f"  LIVE INTERACTIVE DASHBOARD · {DASHBOARD_VERSION}")
    print(f"  Strategies: {ids}  ({len(ids)} tabs)")
    print(f"  Bind: {host}:{bound_port}  public_mode={args.public or host == '0.0.0.0'}")
    if auth:
        print("  Auth: DASHBOARD_BASIC_AUTH enabled (login required)")
    print("")
    print(f"  >>> OPEN IN BROWSER:  {url}")
    print("  Deploy guide: docs/DEPLOY_LIVE_DASHBOARD.md")
    print("  Ctrl+C = stop")
    print("=" * 65)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
