#!/bin/bash
set -eo pipefail

cd /home/serv/Carmen

PYTHON_BIN="/home/serv/miniforge3/envs/Quant/bin/python3"
SCRIPT_PATH="/home/serv/Carmen/scripts/polymarket_monitor.py"
LOG_FILE="/home/serv/Carmen/scripts/polymarket_cron.log"
INFO_BOT_TOKEN_FILE="/home/serv/.openclaw/secrets/telegram_daily_news.token"

{
  echo "--- Cron Run (Daily News Bot): $(date) ---"

  RAW_OUTPUT=$($PYTHON_BIN "$SCRIPT_PATH")
  if [ -z "$RAW_OUTPUT" ]; then
    echo "Error: No output from monitor."
    exit 1
  fi

  BOT_TOKEN=$(sed -n '1p' "$INFO_BOT_TOKEN_FILE" | tr -d '\r')
  CHAT_ID=$(sed -n '2p' "$INFO_BOT_TOKEN_FILE" | tr -d '\r')

  BOT_TOKEN="$BOT_TOKEN" CHAT_ID="$CHAT_ID" TEXT_REPORT="$RAW_OUTPUT" $PYTHON_BIN - <<'PY'
import os
import requests
bot_token = os.environ['BOT_TOKEN']
chat_id = os.environ['CHAT_ID']
text_report = os.environ['TEXT_REPORT']
resp = requests.post(
    f"https://api.telegram.org/bot{bot_token}/sendMessage",
    data={
        "chat_id": chat_id,
        "text": text_report,
        "disable_web_page_preview": True,
    },
    timeout=20,
)
print(resp.text)
resp.raise_for_status()
PY
  echo
} >> "$LOG_FILE" 2>&1
