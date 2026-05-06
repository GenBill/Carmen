#!/usr/bin/env bash
set -euo pipefail

cd /home/serv/Carmen

start_fresh_session() {
  local session="$1"
  local cmd="$2"
  local log="$3"

  tmux kill-session -t "$session" 2>/dev/null || true
  tmux new-session -d -s "$session" "zsh -lc 'source /home/serv/.zshrc && conda activate Quant && cd /home/serv/Carmen && exec ${cmd} 2>&1 | tee -a ${log}'"
}

check_target() {
  local target="$1"
  echo "===== ${target} ====="
  tmux capture-pane -pt "$target" | tail -30
  echo
}

start_fresh_session "0" "python indicator/run.py" "/home/serv/Carmen/runtime/us_market.log"
start_fresh_session "1" "python indicator/main_a.py" "/home/serv/Carmen/runtime/a_share_market.log"
start_fresh_session "2" "python indicator/main_hk.py" "/home/serv/Carmen/runtime/hk_market.log"
start_fresh_session "3" "python scripts/telegram_ai_listener.py" "/home/serv/Carmen/runtime/telegram_listener.log"

sleep 8

check_target "0:0"
check_target "1:0"
check_target "2:0"
check_target "3:0"
