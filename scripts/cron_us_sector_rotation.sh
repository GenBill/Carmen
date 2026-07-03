#!/bin/zsh
# 工作日 10:00 北京时间（按北京时间日历日汇总）
source /home/serv/.zshrc
set -eo pipefail

cd /home/serv/Carmen
export TZ="Asia/Shanghai"

PYTHON_BIN="/home/serv/miniforge3/envs/Quant/bin/python3"
SCRIPT_PATH="/home/serv/Carmen/scripts/sector_rotation_daily.py"
LOG_FILE="/home/serv/Carmen/scripts/us_sector_rotation.log"

{
  echo "--- Cron Run (US Sector Rotation): $(date) ---"
  "$PYTHON_BIN" "$SCRIPT_PATH" --market US
  echo
} >> "$LOG_FILE" 2>&1
