#!/bin/zsh
# 工作日 17:00 北京时间（港股 16:00 收盘后）
source /home/serv/.zshrc
set -eo pipefail

cd /home/serv/Carmen
export TZ="Asia/Shanghai"

PYTHON_BIN="/home/serv/miniforge3/envs/Quant/bin/python3"
SCRIPT_PATH="/home/serv/Carmen/scripts/sector_rotation_daily.py"
LOG_FILE="/home/serv/Carmen/scripts/hk_sector_rotation.log"

{
  echo "--- Cron Run (HK Sector Rotation): $(date) ---"
  "$PYTHON_BIN" "$SCRIPT_PATH" --market HK
  echo
} >> "$LOG_FILE" 2>&1
