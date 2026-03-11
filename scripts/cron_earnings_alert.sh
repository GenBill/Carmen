#!/bin/bash
set -eo pipefail

cd /home/serv/Carmen

LOG_FILE="/home/serv/Carmen/scripts/earnings_alert.log"

{
  echo "==== $(date '+%Y-%m-%d %H:%M:%S') earnings alert run ===="
  python3 /home/serv/Carmen/scripts/earnings_alert.py
  echo
} >> "$LOG_FILE" 2>&1
