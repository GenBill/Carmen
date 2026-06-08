#!/bin/zsh
source /home/serv/.zshrc
set -eo pipefail

cd /home/serv/Carmen

PYTHON_BIN="/home/serv/miniforge3/envs/Quant/bin/python3"
SCRIPT_PATH="/home/serv/Carmen/scripts/polymarket_monitor.py"
LOG_FILE="/home/serv/Carmen/scripts/polymarket_cron.log"
INFO_BOT_TOKEN_FILE="/home/serv/.openclaw/secrets/telegram_daily_news.token"
MAX_RETRIES=4
RETRY_SLEEP=1800

send_report() {
  local raw_output="$1"
  local bot_token
  local chat_ids

  bot_token=$(sed -n '1p' "$INFO_BOT_TOKEN_FILE" | tr -d '\r')
  chat_ids=$(sed -n '2,$p' "$INFO_BOT_TOKEN_FILE" | grep -v '^#' | tr '\n' ' ' | tr -d '\r')

  BOT_TOKEN="$bot_token" CHAT_IDS="$chat_ids" TEXT_REPORT="$raw_output" "$PYTHON_BIN" - <<'PY'
import os
import re
import requests

bot_token = os.environ['BOT_TOKEN']
chat_ids = []
for item in re.split(r'[\s,;]+', os.environ.get('CHAT_IDS', '')):
    item = item.strip()
    if item and item not in chat_ids:
        chat_ids.append(item)
text_report = os.environ['TEXT_REPORT']
proxy = os.environ.get('TELEGRAM_PROXY_URL', 'http://127.0.0.1:7890')
request_kwargs = {'timeout': 20}
if proxy:
    request_kwargs['proxies'] = {'http': proxy, 'https': proxy}
if not chat_ids:
    raise RuntimeError('no Telegram chat ids configured')
for idx, chat_id in enumerate(chat_ids):
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": text_report,
                "disable_web_page_preview": True,
            },
            **request_kwargs,
        )
        print(resp.text)
        resp.raise_for_status()
    except Exception as e:
        if idx == 0:
            raise
        print(f"WARN extra forward failed chat_id={chat_id}: {e}")
PY
}

{
  echo "--- Cron Run (Daily News Bot): $(date) ---"

  attempt=0
  success=0

  while [ "$attempt" -le "$MAX_RETRIES" ]; do
    STDERR_FILE=$(mktemp /tmp/polymarket_monitor_stderr.XXXXXX)
    if RAW_OUTPUT=$($PYTHON_BIN "$SCRIPT_PATH" 2>"$STDERR_FILE"); then
      if [ -s "$STDERR_FILE" ]; then
        echo "Monitor stderr (not sent):"
        cat "$STDERR_FILE"
      fi
      rm -f "$STDERR_FILE"
      send_report "$RAW_OUTPUT"
      echo
      success=1
      break
    fi

    STDERR_OUTPUT=$(cat "$STDERR_FILE" 2>/dev/null || true)
    rm -f "$STDERR_FILE"
    attempt=$((attempt + 1))
    echo "Attempt ${attempt}/$((MAX_RETRIES + 1)) failed."
    if [ -n "$RAW_OUTPUT" ]; then
      echo "stdout: $RAW_OUTPUT"
    fi
    if [ -n "$STDERR_OUTPUT" ]; then
      echo "stderr: $STDERR_OUTPUT"
    fi

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
