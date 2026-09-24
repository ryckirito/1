#!/usr/bin/env bash
# 每日收盘后运行：bash scripts/run_daily.sh [额外参数]
# 例：bash scripts/run_daily.sh --source yfinance --notify
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi
CONFIG_ARG=()
if [ -f config.yaml ]; then
  CONFIG_ARG=(--config config.yaml)
fi
python -m daily_report run "${CONFIG_ARG[@]}" "$@" 2>&1 | tee -a "logs/daily-$(date +%Y%m%d).log"
