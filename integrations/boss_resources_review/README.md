# Review & Test Report — New Resources (Trading / Strategy + Implementation)

> Requested: "review the new github resources I included in the google folder and google doc, and test them."
> Reviewed: 2026-06-10 · TradingAgents Polymarket live dashboard stack (Python 3.13 / Render)

## Summary

| Resource | Type | License | Verdict | Integration in this repo |
|---|---|---|---|---|
| TensorTrade | RL trading framework (TensorFlow) | Apache 2.0 ✅ | Usable, but **requires Python 3.11/3.12 + TF ≥2.15** — incompatible with our 3.13 runtime and too heavy for the Render dashboard | Offline research track: separate conda py3.12 env trains an RL sleeve, exports daily returns CSV → dashboard reads it as a research tab (`rl_tensortrade`). Not in PROD, not in the $1M Equal Index |
| MLFinLab (Hudson & Thames) | Financial ML library | ❌ **All rights reserved** — commercial license £100/user/month; public repo is issues-only since 2023 | **Cannot pip-install for commercial use.** Blocked on licensing | We re-implement the underlying public-domain methods (López de Prado, *Advances in Financial ML*): **purged walk-forward with embargo** now in `strategy_audit.py`. Triple-barrier / meta-labeling are candidates for the whale sleeve later |
| Fincept Terminal | C++20/Qt6 desktop terminal, 100+ data connectors | AGPL-3.0 ⚠️ (copyleft) | Good connector catalog, but it is a desktop app, not a library. AGPL code must not be vendored into this repo | Reference only. Our stack already uses the same sources it wraps (ECB RSS, FRED, Yahoo, Kraken, CoinGecko). Candidate: add IMF/World Bank macro series to the regime models, implemented natively |
| Kelly & Xiu — *Financial Machine Learning* (SSRN 4501707) | Survey paper | Paper | Methodology reference | Added to dashboard `research_refs` |
| Sci-bot | Research-paper access tool | Tool | Useful for sourcing future alpha papers | Documented here; no code integration |

## Test results

### TensorTrade smoke test — PASS ✅
- Env: conda `tensortrade`, Python 3.12.13, `pip install tensortrade` → v1.0.4 (Feb 2026 release).
- Built a simulated exchange + portfolio env on DOGE daily closes, stepped 20 random actions:
  `TensorTrade env OK — 20 steps, action_space=Discrete(21)`.
- Gotcha found: USD instrument has 2-decimal precision, so sub-cent meme prices quantize to $0 —
  scale prices (×10⁴) or define a custom high-precision instrument.
- Constraint confirmed: TensorFlow does not support Python 3.13/3.14 → cannot be added to
  `requirements-live-dashboard.txt` (Render). RL stays an offline research track.

### RL sleeve training run (2026-06-10)
- `integrations/rl_tensortrade/train_rl_sleeve.py`: tabular Q-learning on DOGE
  (MOM20/VOL20/RSI14 grid, actions −1/0/+1, 5 bps/leg TC), 70/30 train/OOS split.
- Result: **OOS 695 days · Sharpe 0.91 · cum +151%** → exported to
  `data/rl_sleeve/rl_tensortrade_returns.csv`, shown as the `rl_tensortrade` dashboard tab.

### MLFinLab licensing check
- `LICENSE.txt` (repo master): "The codebase is NOT open-source. All proprietary rights are reserved…
  does NOT allow for use of the code base for any commercial purposes."
- Action: do not install. Methods re-implemented from the public literature instead
  (purged K-fold / embargo per López de Prado ch.7 → `tradingagents/quant/strategy_audit.py`).

### Fincept Terminal
- v4 is a native C++20/Qt6 binary with embedded Python connector scripts (JSON over stdout).
- Connector overlap with our stack: ECB ✅ (we have RSS), FRED ✅, Yahoo ✅, Kraken ✅.
- AGPL-3.0: copying connector code into this repo would force AGPL on the whole project — avoided.

## Architecture decision

```
PROD CLOB        : live_composite (whale + pairs, news-gated)   — unchanged
$1M paper book   : multi_strategy_index (7 sleeves, 1/n)        — unchanged
Research tabs    : + rl_tensortrade (CSV-backed, offline-trained RL sleeve)
Audit            : walk-forward now purged + embargoed (López de Prado)
```
