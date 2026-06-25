#!/usr/bin/env bash
# Run IN TERMINAL ONLY (black window). Do NOT paste into TextEdit / nano / .env file.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
echo "=== TradingAgents Kraken go-live helper ==="
echo "Repo: $REPO"

PY="$(command -v python || true)"
if [[ -n "$PY" ]] && "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  VER="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  echo "Using active Python: $PY ($VER)"
else
  _conda_sh=""
  if command -v conda >/dev/null 2>&1; then
    _conda_base="$(conda info --base 2>/dev/null || true)"
    if [[ -n "$_conda_base" && -f "$_conda_base/etc/profile.d/conda.sh" ]]; then
      _conda_sh="$_conda_base/etc/profile.d/conda.sh"
    fi
  fi
  for _c in "$_conda_sh" \
             "$HOME/miniconda3/etc/profile.d/conda.sh" \
             "$HOME/anaconda3/etc/profile.d/conda.sh" \
             "/opt/anaconda3/etc/profile.d/conda.sh" \
             "/opt/miniconda3/etc/profile.d/conda.sh"; do
    if [[ -n "$_c" && -f "$_c" ]]; then
      # shellcheck disable=SC1090
      source "$_c"
      conda activate tradingagents
      PY="$(command -v python)"
      break
    fi
  done
  if [[ -z "$PY" ]] || ! "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    echo "ERROR: need Python 3.10+ in tradingagents env." >&2
    echo "You are in: $(python --version 2>&1 || echo unknown)" >&2
    echo "Try: conda activate tradingagents" >&2
    exit 1
  fi
  VER="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  echo "Python: $PY ($VER)"
fi

# Ensure minimal runtime (full requirements.txt needs Rust for orjson).
if ! python -c "import pandas, requests" 2>/dev/null; then
  echo "Installing minimal Kraken live deps ..."
  python -m pip install -r requirements-kraken-live.txt
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
