# Polymarket + Meme Coins — Master Summary (English)

**Regenerate master image:** `python scripts/polymarket_master_dashboard.py`  
**Single-page visual:** `assets/dashboard_outputs/polymarket_master_dashboard.png`

---

## 1. Project scope

| Pillar | What was built |
|--------|----------------|
| **Data** | Polymarket Gamma/CLOB + Nautilus; meme spot (DOGE, WIF); Polymarket Data API for whales |
| **Strategy** | EMA trend + volatility targeting; meme long-only; `sharpe_tilt` portfolio weights |
| **Validation** | Walk-forward optimization (252d train / 63d test, 33 OOS folds) |
| **ML / Qlib** | Factor CSV export; optional LGBModel; sklearn/MOM fallback |
| **Whale / Arb** | Holders, large trades, Yes/No bundle arb with tx costs, latency vs DOGE |
| **Solana** | Bridge to ChangeYourself0613 Rust/Jito bot (external execution) |

**Universe (v2):** `POLY_GTA`, `DOGE`, `WIF` · **Benchmark:** DOGE buy & hold

---

## 2. All image outputs

| File | Section | Description |
|------|---------|-------------|
| **`polymarket_master_dashboard.png`** | **MASTER** | This page — thumbnails of all charts + metrics |
| `polymarket_meme_dashboard.png` | A | Main 15-panel backtest dashboard |
| `polymarket_walkforward_oos.png` | B | Stitched OOS equity + per-fold Sharpe |
| `polymarket_whale_arb_analysis.png` | C | Whales, bundle arb, latency, long-short POLY |
| `polymarket_meme_charts_meme.png` | D | Meme normalized index, vol, correlation |
| `polymarket_meme_charts_polymarket.png` | E | Polymarket Yes probability over time |
| `polymarket_meme_charts_cross.png` | F | POLY×DOGE corr, weights, underwater |
| `polymarket_meme_charts_performance.png` | G | CAGR vs drawdown, win rates |
| `polymarket_active_markets.png` | H | Active Polymarket markets (Gamma) |
| `polymarket_factor_attribution.png` | I | Macro factor attribution |
| `polymarket_meme_overview_en.png` | J | English architecture overview |

---

## 3. CSV / data outputs

| File | Contents |
|------|----------|
| `polymarket_meme_metrics.csv` | Portfolio vs DOGE B&H, per-asset, scenarios, Monte Carlo, correlations, GitHub map |
| `polymarket_walkforward_metrics.csv` | Each WFO fold, OOS summary, factor attribution |
| `polymarket_whale_arb_metrics.csv` | Holders, whale trades, arb patterns, lag scan, cost model |
| `solana_arb_scan.csv` | Sample circular DEX route scan (illustrative) |
| `data/qlib_crypto/*.csv` | Qlib-format factor panels (DOGE, WIF) |

---

## 4. Key numbers

### In-sample trend portfolio (`polymarket_meme_dashboard`)

| Metric | Strategy | DOGE B&H |
|--------|----------|----------|
| Total return | +158.9% | +4839.3% |
| CAGR | +10.8% | +52.2% |
| Sharpe | **+0.39** | +0.70 |
| Max drawdown | **-20.2%** | -92.3% |

Per-leg Sharpe: POLY_GTA **+0.78**, DOGE **+0.40**, WIF **-0.17**

### Walk-forward out-of-sample

| Metric | Value |
|--------|--------|
| Stitched OOS Sharpe | **+0.42** |
| Stitched OOS total return | **+122.2%** |
| Folds | 33 |

### Whale / arbitrage (GTA market)

| Item | Result |
|------|--------|
| Spot Yes/No bundle arb | Not profitable after fees (sum ≈ 1.0) |
| Large trades tracked | 150 (≥ $500 filter) |
| POLY long-short Sharpe | ~-0.27 on probability series |

---

## 5. Commands

```bash
python scripts/polymarket_meme_run.py dashboard    # charts A,D–J (main + panels)
python scripts/polymarket_meme_run.py walkforward  # chart B + WF CSV
python scripts/polymarket_meme_run.py whale-arb    # chart C + whale CSV
python scripts/polymarket_meme_run.py solana-setup
python scripts/polymarket_master_dashboard.py      # MASTER collage
```

---

## 6. What is / is not included

| Included | Not included |
|----------|----------------|
| Trend + vol-target backtest | Kalshi ↔ Polymarket delta arb |
| Walk-forward OOS | Live Polymarket order execution |
| Qlib data + ML fallback | Full on-chain Solana arb backtest in Python |
| Whale + bundle arb **analysis** | Polymarket/agents copy-trading bot runtime |

---

*Research / education only. Not financial advice.*
