#!/bin/zsh
source /home/serv/.zshrc
set -eo pipefail

cd /home/serv/Carmen

PYTHON_BIN="/home/serv/miniforge3/envs/Quant/bin/python3"
SCRIPT_PATH="/home/serv/Carmen/scripts/fear_greed_daily_report.py"
LOG_FILE="/home/serv/Carmen/scripts/fear_greed_daily_report.log"

{
  echo "--- Cron Run (Fear & Greed Daily Report): $(date) ---"
  "$PYTHON_BIN" "$SCRIPT_PATH"
  echo
} >> "$LOG_FILE" 2>&1
