#!/bin/bash
set -eo pipefail

cd /home/serv/Carmen

PYTHON_BIN="/home/serv/miniforge3/envs/Quant/bin/python3"
SCRIPT_PATH="/home/serv/Carmen/scripts/polymarket_monitor.py"
LOG_FILE="/home/serv/Carmen/scripts/polymarket_cron.log"
INFO_BOT_TOKEN_FILE="/home/serv/.openclaw/secrets/telegram_daily_news.token"
MAX_RETRIES=3
RETRY_SLEEP=1800

send_report() {
  local raw_output="$1"
  local bot_token
  local chat_id

  bot_token=$(sed -n '1p' "$INFO_BOT_TOKEN_FILE" | tr -d '\r')
  chat_id=$(sed -n '2p' "$INFO_BOT_TOKEN_FILE" | tr -d '\r')

  BOT_TOKEN="$bot_token" CHAT_ID="$chat_id" TEXT_REPORT="$raw_output" "$PYTHON_BIN" - <<'PY'
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
}

{
  echo "--- Cron Run (Daily News Bot): $(date) ---"

  attempt=0
  success=0

  while [ "$attempt" -le "$MAX_RETRIES" ]; do
    if RAW_OUTPUT=$($PYTHON_BIN "$SCRIPT_PATH" 2>&1); then
      send_report "$RAW_OUTPUT"
      echo
      success=1
      break
    fi

    attempt=$((attempt + 1))
    echo "Attempt ${attempt}/$((MAX_RETRIES + 1)) failed: $RAW_OUTPUT"

    if [ "$attempt" -gt "$MAX_RETRIES" ]; then
      break
    fi

    echo "Sleeping ${RETRY_SLEEP}s before retry..."
    sleep "$RETRY_SLEEP"
  done

  if [ "$success" -ne 1 ]; then
    echo "Polymarket monitor failed after $((MAX_RETRIES + 1)) attempts."
    echo
    exit 1
  fi
} >> "$LOG_FILE" 2>&1
