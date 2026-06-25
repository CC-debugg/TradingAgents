#!/usr/bin/env bash
# Run IN TERMINAL ONLY (black window). Do NOT paste into TextEdit / nano / .env file.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
echo "=== TradingAgents Kraken go-live helper ==="
echo "Repo: $REPO"

if [[ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [[ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]]; then
  # shellcheck disable=SC1091
  source "$HOME/anaconda3/etc/profile.d/conda.sh"
fi
conda activate tradingagents 2>/dev/null || true

git pull
python scripts/kraken_repair_env.py || python scripts/kraken_patch_live_env.py

echo ""
echo "--- KRAKEN settings (no secrets) ---"
grep '^KRAKEN_' .env | grep -v SECRET || true

echo ""
echo "--- Health check ---"
python scripts/kraken_health_check.py

echo ""
echo "--- One live cycle ---"
python scripts/kraken_meme_live_loop.py --once --quick

echo ""
read -r -p "Start 24/7 loop? [y/N] " ans
if [[ "${ans,,}" == "y" ]]; then
  mkdir -p logs
  pkill -f kraken_meme_live_loop.py 2>/dev/null || true
  nohup python scripts/kraken_meme_live_loop.py --interval 300 --quick >> logs/kraken_loop.log 2>&1 &
  echo "PID: $!"
  echo "Log: tail -f logs/kraken_loop.log"
fi
