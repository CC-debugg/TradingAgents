# Polymarket Live Dashboard — System Workflow (v2.8)

**Dashboard:** https://polymarket-live-dashboard.onrender.com/  
**Repo:** TradingAgents · `tradingagents/quant/` + `assets/dashboard_outputs/live_app/`  
**Version:** `2.8-rl-purged-audit`

---

## End-to-end workflow

```mermaid
flowchart TB
  subgraph INPUTS["① INPUTS (refreshed on each /api/live)"]
    POLY["Polymarket CLOB<br/>large trades + Yes prob (GTA market)"]
    CRYPTO["Crypto spot<br/>DOGE · WIF (Yahoo / Kraken / CoinGecko)"]
    MACRO["Macro overlay<br/>ECB RSS · FRED (optional) · news gate score"]
    BARRA["Barra-style factors<br/>ETF proxies (GLD, HYG, EEM, TLT, …)"]
  end

  subgraph SLEEVES["② BASE SLEEVES (n=7) — distinct return sources"]
    W["whale_flow<br/>order-flow / POLY"]
    P["pairs_stat_arb<br/>spread MR · DOGE/WIF"]
    A1["ts_momentum_meme<br/>β-neutral momentum"]
    A2["cs_momentum_rank<br/>lead–lag spread"]
    A3["short_term_reversal<br/>extreme-move fade"]
    A4["poly_mean_reversion<br/>POLY shock fade"]
    A5["vol_risk_parity<br/>slow β-neutral"]
  end

  subgraph RESEARCH["②b RESEARCH (excluded from Index & PROD)"]
    RL["rl_tensortrade<br/>Q-learning · TensorTrade track<br/>offline CSV → dashboard tab"]
  end

  subgraph REGIME["③ REGIME MODELS (HF Manager weights)"]
    BW["Bridgewater All Weather"]
    AB["Ang & Bekaert 2-state"]
    JPM["JPM growth × inflation quadrant"]
    TILT["merged_sleeve_tilt × inverse-correlation blend"]
  end

  subgraph BOOKS["④ PORTFOLIO BOOKS (3 assembly modes)"]
    PROD["live_composite<br/>whale + pairs only<br/>macro news-gated"]
    EQ["multi_strategy_index<br/>equal 1/n on 7 sleeves<br/>★ $1M paper book"]
    HF["hf_manager_book<br/>regime-dynamic weights<br/>refreshed each live call"]
  end

  subgraph AUDIT["⑤ UNIFIED AUDIT"]
    AUD["strategy_audit<br/>Sharpe · vol · MaxDD · trades · TC drag<br/>walk-forward OOS · purged WF (embargo)<br/>7×7 correlation · overlap warnings"]
  end

  subgraph OUTPUTS["⑥ OUTPUTS"]
    API["/api/live JSON payload"]
    UI["Live dashboard UI<br/>11 strategy tabs · sticky $1M bar"]
    PAPER["portfolio_sim<br/>$1M from 2026-06-04 · Equal Index"]
    CLOB["clob_intents<br/>PROD dry-run (POLY CLOB)"]
  end

  POLY --> W
  POLY --> A4
  POLY --> PROD
  CRYPTO --> P
  CRYPTO --> A1
  CRYPTO --> A2
  CRYPTO --> A3
  CRYPTO --> A5
  MACRO --> PROD
  BARRA --> REGIME

  W --> BOOKS
  P --> BOOKS
  A1 --> BOOKS
  A2 --> BOOKS
  A3 --> BOOKS
  A4 --> BOOKS
  A5 --> BOOKS

  BW --> TILT
  AB --> TILT
  JPM --> TILT
  TILT --> HF

  BOOKS --> AUD
  RL --> API
  AUD --> API
  BOOKS --> API
  API --> UI
  API --> PAPER
  PROD --> CLOB
```

---

## Strategy list (11 dashboard tabs)

| Layer | ID | Role |
|-------|-----|------|
| **Book** | `live_composite` | PRODUCTION — whale + pairs, news-gated → CLOB intents |
| **Book** | `multi_strategy_index` | Equal 1/n benchmark — **official $1M paper PnL** |
| **Book** | `hf_manager_book` | Regime-dynamic blend (Ang + JPM + Bridgewater tilt) |
| **Sleeve** | `whale_flow` | Polymarket large-trade flow + EMA trend |
| **Sleeve** | `pairs_stat_arb` | DOGE/WIF log-spread z-score mean reversion |
| **Sleeve** | `ts_momentum_meme` | 15d β-neutral residual momentum |
| **Sleeve** | `cs_momentum_rank` | DOGE→WIF lead–lag spread |
| **Sleeve** | `short_term_reversal` | Fade \|5d\| ≥ 8% basket moves |
| **Sleeve** | `poly_mean_reversion` | Fade ≥2.5% daily Yes-prob shocks |
| **Sleeve** | `vol_risk_parity` | 25d slow β-neutral diversifier |
| **Research** | `rl_tensortrade` | Offline Q-learning (TensorTrade env); not in Index or PROD |

**Tradable assets:** POLY_GTA (prediction market) · DOGE · WIF — no equities.

---

## Data flow (one refresh cycle)

```mermaid
sequenceDiagram
  participant User as Browser
  participant Srv as serve_polymarket_live.py
  participant Pay as build_live_payload()
  participant Data as fetch_live_data_bundle()
  participant Sig as live_execution + alpha_sleeves
  participant Books as hf_manager + regime_allocator
  participant Audit as strategy_audit

  User->>Srv: GET /api/live
  Srv->>Pay: build_live_payload()
  Pay->>Data: Polymarket trades, prices, macro
  Data->>Sig: 7 sleeve daily returns
  Sig->>Books: equal index + HF book + PROD composite
  Books->>Audit: metrics, WF, correlation
  Audit->>Pay: strategy_audit + allocation
  Pay->>Srv: JSON (strategies, portfolio_sim, …)
  Srv->>User: dashboard render
```

---

## Status & performance (as of architecture v2.8)

| Item | Status |
|------|--------|
| **Hosting** | Render.com — auto-deploy from `main` (`render.yaml`) |
| **Live execution** | PROD CLOB = **dry-run** only (`POLYMARKET_LIVE` off) |
| **$1M paper book** | Tracks **Multi-Strategy Index** from `2026-06-04` |
| **Transaction costs** | 5 bps/leg · 10 bps round-trip in all backtests |
| **Crypto CEX execution** | Not wired (Kraken/Coinbase TBD for live plumbing test) |
| **Polymarket live orders** | Stub ready (`py-clob-client`); US compliance TBD |

| Metric (Multi-Strategy Index, ~400d backtest) | Value |
|-----------------------------------------------|-------|
| Sharpe (full sample) | ~2.77 |
| Walk-forward OOS Sharpe | ~2.85 |
| Max drawdown | ~−3.9% |
| Purged WF (embargo 3d) | in `strategy_audit` |

*Backtest Sharpe is inflated by in-sample sleeve tuning; expect ~½ live. Forward validation = frozen-rule paper book since June 4.*

---

## Planned next steps (per program direction)

```mermaid
flowchart LR
  NOW["Today<br/>Render dashboard<br/>dry-run PROD"]
  P1["Phase 1<br/>Prefect daily orchestration<br/>+ run logs"]
  P2["Phase 2<br/>$100 Kraken plumbing test<br/>long legs only"]
  P3["Phase 3<br/>Live fills vs paper reconciliation<br/>on dashboard"]

  NOW --> P1 --> P2 --> P3
```

**LLM / agentic:** Live book = rule-based quant (no LangGraph in production path). RL research uses TensorTrade + Q-learning. TradingAgents repo includes LLM agents for separate research workflows; orchestration upgrade target = **Prefect + LangGraph + AgentOps** (program recommendation).

---

## Google Sheet columns (copy-paste)

| Column | Value |
|--------|-------|
| **Dashboard link** | https://polymarket-live-dashboard.onrender.com/ |
| **Github** | *(your fork or Global AI org URL)* |
| **Hosting** | Render.com · Blueprint `render.yaml` · env: `LIVE_SIM_START`, `LIVE_SIM_CAPITAL`, `LIVE_LOOKBACK_DAYS` |
| **LLM/Agentic Platform** | Rule-based live sleeves; TensorTrade RL research track; Prefect orchestration planned |

**Workflow diagram link:** this file — `docs/WORKFLOW.md` in repo (or export Mermaid to PNG for Sheet tab).
