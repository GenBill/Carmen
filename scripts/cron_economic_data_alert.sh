#!/bin/zsh
source /home/serv/.zshrc
set -eo pipefail

cd /home/serv/Carmen
export TZ="Asia/Hong_Kong"

PYTHON_BIN="/home/serv/miniforge3/envs/Quant/bin/python3"
SCRIPT_PATH="/home/serv/Carmen/scripts/economic_data_alert.py"
LOG_FILE="/home/serv/Carmen/scripts/economic_data_alert.log"

{
  echo "--- Cron Run (Economic Data Alert): $(date) ---"
  "$PYTHON_BIN" "$SCRIPT_PATH"
  echo
} >> "$LOG_FILE" 2>&1
