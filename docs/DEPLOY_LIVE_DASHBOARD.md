# Deploy the live strategy dashboard (public URL)

Share the interactive dashboard (`live_composite` + whale + pairs) with your team or the public.

**Local only today:** `http://127.0.0.1:8765/` runs on your machine — others cannot open it.

---

## Option A — Render.com (recommended, free tier)

1. Push this repo to **GitHub** (your fork).
2. [render.com](https://render.com) → **New → Blueprint** → select repo.
3. Apply the blueprint (`render.yaml` uses **Python** runtime, not Docker).
4. Open `https://polymarket-live-dashboard.onrender.com/` (name may vary).

**If deploy failed:** Render dashboard → **polymarket-live-dashboard** → **Logs** (build + runtime).  
Common fix: push latest `render.yaml` + `requirements-live-dashboard.txt`, then **Manual Deploy**.

**Dashboard layout (v2.2):** five top screens — (1) Strategies LIVE, (2) Market, (3) Risk factors + All Weather regime, (4) Backtesting table, (5) Workflow. Transaction costs: **5 bps per leg, 10 bps round-trip** on every position change.

**Optional env vars (Render → Environment):**

| Variable | Purpose |
|----------|---------|
| `DASHBOARD_BASIC_AUTH` | `username:password` — simple login wall |
| `FRED_API_KEY` | Extra macro data in news panel |
| `PUBLIC_BASE_URL` | Shown in startup logs |
| `LIVE_LOOKBACK_DAYS` | Shorter history on free tier (default `250` on Render) |
| `LIVE_MAX_TRADES` | Cap Polymarket trade fetch (default `4000` on Render) |

**Never set on a public demo:** `POLYMARKET_PRIVATE_KEY`, `POLYMARKET_LIVE=1`.

---

## Option B — Docker (any VPS: AWS, GCP, DigitalOcean)

```bash
cd TradingAgents
docker build -f Dockerfile.live-dashboard -t polymarket-live .
docker run -p 8765:8765 -e DASHBOARD_BASIC_AUTH='team:secret' polymarket-live
```

Open `http://<server-ip>:8765/` (put nginx + HTTPS in front for production).

---

## Option C — Quick share (ngrok, same laptop)

```bash
python scripts/polymarket_meme_run.py live-app --public
# other terminal:
ngrok http 8765
```

Share the `https://….ngrok.io` link — lasts while your laptop and ngrok run.

---

## Local vs public server

```bash
# Local only (default)
python scripts/polymarket_meme_run.py live-app

# Listen on all interfaces (LAN / VPS)
python scripts/polymarket_meme_run.py live-app --public
```

Cloud sets `PORT` automatically; use `--port $PORT` if needed.

---

## Security (real money)

- Public dashboard = **research / monitoring only** (`POLYMARKET_LIVE=0`).
- Run **CLOB live trading** on a **private** machine with keys — not on Render.
- Use `DASHBOARD_BASIC_AUTH` if the URL should not be fully open.

---

## Verify deploy

```bash
curl -s https://YOUR-URL/health
curl -s https://YOUR-URL/api/version
```

Expect `dashboard_version: 2.4-dual-regime` and **8** strategy ids (3 PROD + 5 α sleeves).
