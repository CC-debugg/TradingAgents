# Polymarket + Meme Coins Project

Quantitative risk + multi-agent research stack built on **TradingAgents**, aligned with *GlobalAi26 QuantFin Risk Management* course resources.

## Architecture (v2)

### System overview

```mermaid
flowchart TB
  subgraph inputs [Inputs — QuantFin PDF + GitHub]
    PDF[QuantFin PDF]
    GH1[TradingAgents repo]
    GH2[NautilusTrader]
    GH3[Polymarket Gamma/CLOB APIs]
    GH4[yfinance / CoinGecko]
  end

  subgraph entry [Entry]
    RUN["polymarket_meme_run.py"]
    RUN -->|dashboard| DASH["polymarket_meme_dashboard.py"]
    RUN -->|agents| TA["TradingAgentsGraph.propagate"]
  end

  subgraph data [Data layer]
    NT["nautilus_data.py\nPOLY:slug"]
    GAMMA["polymarket_gamma.py\nCLOB fallback"]
    YF["yfinance / CoinGecko\nDOGE, WIF"]
    DISC["polymarket_discovery.py\nactive markets"]
    NT -->|sparse bars| GAMMA
  end

  subgraph universe [Trading universe v2]
    P["POLY_GTA\nGTA VI market"]
    M1["DOGE"]
    M2["WIF"]
  end

  subgraph engine [Strategy engine]
    SIG["EMA trend\nPoly 5/15 · Meme 20/60"]
    LO["MEME_LONG_ONLY\nlong or flat"]
    VT["Vol targeting 20% ann."]
    WT["PORTFOLIO_WEIGHT_MODE\nsharpe_tilt"]
    SIG --> LO --> VT --> WT
  end

  subgraph outputs [Outputs]
    PNG1["polymarket_meme_dashboard.png"]
    PNG2["charts_meme / polymarket / cross / performance"]
    PNG3["polymarket_active_markets.png"]
    CSV["polymarket_meme_metrics.csv"]
    TERM["Terminal dialogue\n[1/8]…[9/9] + Key results"]
    DEC["=== Decision ===\nagents only"]
  end

  PDF --> RUN
  GH1 --> TA
  GH2 --> NT
  GH3 --> GAMMA
  GH4 --> YF

  DASH --> NT
  DASH --> YF
  DASH --> DISC
  NT --> P
  YF --> M1
  YF --> M2
  P --> engine
  M1 --> engine
  M2 --> engine
  engine --> PNG1
  engine --> PNG2
  engine --> CSV
  DASH --> TERM
  DISC --> PNG3
  TA --> DEC
```

### Dashboard pipeline (terminal steps)

```mermaid
flowchart LR
  S1["[1/8] Download\nPOLY_GTA · DOGE · WIF\n+ SPY GLD TLT macro"]
  S2["[2/8] Signals\nEMA + vol size\nmeme long-only"]
  S3["[3/8] Portfolio\nsharpe_tilt weights"]
  S4["[4/8] Metrics\nvs DOGE B&H"]
  S5["[5/8] Scenarios\n2020–2024 regimes"]
  S6["[6/8] Monte Carlo\n2000 sims"]
  S7["[8/8] Main PNG\n15-panel dashboard"]
  S8["[9/9] Extended PNGs\nmeme · poly · cross · perf · discovery"]
  S9["CSV + Done\nKey results dialogue"]

  S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7 --> S8 --> S9
```

### Data routing (per symbol)

```mermaid
flowchart TD
  SYM{Symbol type?}
  SYM -->|POLY:slug| NAUT["get_nautilus_data_online"]
  NAUT --> OK{Nautilus bars\n≥ min history?}
  OK -->|yes| OHLCV[Daily OHLCV CSV]
  OK -->|no| CLOB["polymarket_gamma\nGamma slug + CLOB prices-history"]
  CLOB --> OHLCV
  SYM -->|DOGE-USD / WIF-USD| YFIN["yfinance → CoinGecko fallback"]
  YFIN --> OHLCV
  OHLCV --> BT["Backtest loop"]
```

| Layer | Tool | Role |
|-------|------|------|
| Prediction markets | [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) or **Gamma/CLOB API** | `POLY:gta-vi-released-before-june-2026` |
| Meme spot | yfinance + CoinGecko | **DOGE**, **WIF** (v2 universe) |
| Strategy | EMA + vol target + **meme long-only** + **sharpe_tilt** | Portfolio Sharpe target ≥ 0 |
| Charts | `polymarket_meme_chart_panels.py` | 5 extended PNGs + main dashboard |
| Research agents | [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Optional `agents` → `=== Decision ===` |
| Market scan | Gamma API via `polymarket_discovery.py` | `polymarket_active_markets.png` |
| External bots | [Polymarket/agents](https://github.com/Polymarket/agents) etc. | Documented in [GITHUB_INTEGRATION.md](./GITHUB_INTEGRATION.md) |

## Quick start

```bash
cd TradingAgents
pip install -e ".[dev]"   # or your env
pip install yfinance scipy matplotlib numpy requests

# 1) Regenerate dashboard + metrics
python scripts/polymarket_meme_run.py dashboard

# 2) LLM multi-agent pass on a meme ticker (requires API keys in .env)
python scripts/polymarket_meme_run.py agents --ticker DOGE-USD --date 2025-05-01

# 3) Both
python scripts/polymarket_meme_run.py all --ticker DOGE-USD --date 2025-05-01
```

Outputs (see [GITHUB_INTEGRATION.md](./GITHUB_INTEGRATION.md)):

- `polymarket_meme_dashboard.png` — main strategy dashboard
- `polymarket_meme_charts_meme.png` — meme coin analysis
- `polymarket_meme_charts_polymarket.png` — Polymarket probability
- `polymarket_meme_charts_cross.png` — cross-asset / risk
- `polymarket_meme_charts_performance.png` — risk-return summary
- `polymarket_active_markets.png` — Gamma API market discovery
- `polymarket_meme_metrics.csv`

## Data vendors

Set in config or environment:

```python
config["data_vendors"]["core_stock_apis"] = "nautilus"
```

| Symbol | Meaning |
|--------|---------|
| `POLY:gta-vi-released-before-june-2026` | Polymarket Yes price (0–1) |
| `DOGE-USD` | Falls back to yfinance via nautilus router |

Optional full Nautilus install:

```bash
pip install -U "nautilus_trader[polymarket]"
```

Without it, `tradingagents.dataflows.polymarket_gamma` uses public Gamma + CLOB endpoints.

## Universe (dashboard v2)

| Leg | Symbol | Notes |
|-----|--------|--------|
| Polymarket | **POLY_GTA** | `gta-vi-released-before-june-2026`; long/short |
| Meme | **DOGE**, **WIF** | long-or-flat only |
| Excluded | PEPE, BONK, SHIB, UMA | Removed — hurt portfolio Sharpe under old rules |
| Benchmark | DOGE buy & hold | Scorecard reference |
| Macro (corr only) | SPY, GLD, TLT | Not traded |

## Phase 2 — now implemented

| PDF item | Command | Output |
|----------|---------|--------|
| **Qlib** | `python scripts/polymarket_walkforward_qlib.py` | `data/qlib_crypto/*.csv`, LGBModel or sklearn fallback |
| **Walk-forward OOS** | same | `polymarket_walkforward_oos.png`, `polymarket_walkforward_metrics.csv` |
| **Solana arb (#3 Rust/Jito)** | `python scripts/solana_arb_bridge.py setup` | [integrations/solana_arbitrage](../integrations/solana_arbitrage/) |

```bash
python scripts/polymarket_meme_run.py walkforward
python scripts/polymarket_meme_run.py solana-setup
pip install -e ".[quant]"   # optional: pyqlib + sklearn
```

### Walk-forward diagram

```mermaid
flowchart LR
  T[Train 252d\noptimize EMA] --> TEST[Test 63d OOS]
  TEST --> NEXT[Step 63d forward]
  NEXT --> T
  TEST --> STITCH[Stitch OOS returns]
  STITCH --> CHART[walkforward_oos.png]
```

### Whale + Arbitrage module

```bash
python scripts/polymarket_meme_run.py whale-arb
```

| Feature | Implementation |
|---------|----------------|
| **Whale** | Data API `/holders`, `/trades` (cash filter), concentration HHI |
| **Bundle arb** | Yes+No ask sum &lt; $1 − fees − gas − min profit bps |
| **Latency** | DOGE (fast) vs POLY Yes (lag 0–5d), hit-rate vs tx costs |
| **Long-short** | EMA on Polymarket implied probability |
| **Patterns** | Historical count of profitable arb windows |

Outputs: `polymarket_whale_arb_analysis.png`, `polymarket_whale_arb_metrics.csv`

```mermaid
flowchart TB
  WH[Whale: holders + large trades]
  ARB[Bundle arb: Yes+No < 1 - costs]
  LAT[Latency: Market1 vs Market2 delayed]
  LS[Long-short on POLY probability]
  WH --> OUT[whale_arb_analysis.png]
  ARB --> OUT
  LAT --> OUT
  LS --> OUT
```

Still Phase 2 (optional): Kalshi cross-venue arb, [Kronos](https://github.com/shiyu-coder/Kronos).

## Disclaimer

For research and education only. Not financial advice.
