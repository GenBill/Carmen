#!/bin/zsh
# 工作日 16:00 北京时间（A 股 15:00 收盘后）
# 三市场 crontab 见 scripts/sector_rotation_daily.py
source /home/serv/.zshrc
set -eo pipefail

cd /home/serv/Carmen
export TZ="Asia/Shanghai"

PYTHON_BIN="/home/serv/miniforge3/envs/Quant/bin/python3"
SCRIPT_PATH="/home/serv/Carmen/scripts/sector_rotation_daily.py"
LOG_FILE="/home/serv/Carmen/scripts/a_share_sector_rotation.log"

{
  echo "--- Cron Run (A-share Sector Rotation): $(date) ---"
  "$PYTHON_BIN" "$SCRIPT_PATH" --market A
  echo
} >> "$LOG_FILE" 2>&1
