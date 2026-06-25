#!/usr/bin/env bash
# Run IN TERMINAL ONLY (black window). Do NOT paste into TextEdit / nano / .env file.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
echo "=== TradingAgents Kraken go-live helper ==="
echo "Repo: $REPO"

_conda_sh=""
for _c in "$HOME/miniconda3/etc/profile.d/conda.sh" \
           "$HOME/anaconda3/etc/profile.d/conda.sh" \
           "/opt/anaconda3/etc/profile.d/conda.sh" \
           "/opt/miniconda3/etc/profile.d/conda.sh"; do
  if [[ -f "$_c" ]]; then
    _conda_sh="$_c"
    break
  fi
done

if [[ -z "$_conda_sh" ]]; then
  echo "ERROR: conda not found. Install Anaconda or create env tradingagents (Python 3.12)." >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$_conda_sh"
conda activate tradingagents

PY="$(which python)"
VER="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "Python: $PY ($VER)"
if "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
  :
else
  echo "ERROR: need Python 3.10+ (tradingagents env). Got $VER from base anaconda?" >&2
  echo "Try: conda create -n tradingagents python=3.12 -y && conda activate tradingagents" >&2
  exit 1
fi

git pull
python scripts/kraken_repair_env.py || true
python scripts/kraken_patch_live_env.py

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
if [[ "${ans,,}" == "y" || "${ans,,}" == "yes" ]]; then
  mkdir -p logs
  pkill -f kraken_meme_live_loop.py 2>/dev/null || true
  nohup python scripts/kraken_meme_live_loop.py --interval 300 --quick >> logs/kraken_loop.log 2>&1 &
  echo "PID: $!"
  echo "Log: tail -f logs/kraken_loop.log"
fi
