#!/usr/bin/env bash
set -euo pipefail

cd /home/serv/Carmen

start_if_missing() {
  local session="$1"
  local cmd="$2"
  local log="$3"

  if tmux has-session -t "$session" 2>/dev/null; then
    echo "[SKIP] tmux session exists: $session"
    return 0
  fi

  tmux new-session -d -s "$session" "zsh -lc 'source /home/serv/.zshrc && conda activate Quant && cd /home/serv/Carmen && exec ${cmd} 2>&1 | tee -a ${log}'"
}

check_target() {
  local target="$1"
  echo "===== ${target} ====="
  tmux capture-pane -pt "$target" | tail -30
  echo
}

start_if_missing "0" "python indicator/run.py" "/home/serv/Carmen/runtime/us_market.log"
start_if_missing "1" "python indicator/main_a.py" "/home/serv/Carmen/runtime/a_share_market.log"
start_if_missing "2" "python indicator/main_hk.py" "/home/serv/Carmen/runtime/hk_market.log"
start_if_missing "3" "python scripts/telegram_ai_listener.py" "/home/serv/Carmen/runtime/telegram_listener.log"

sleep 3

for target in 0:0 1:0 2:0 3:0; do
  if tmux list-panes -t "$target" >/dev/null 2>&1; then
    check_target "$target"
  else
    echo "===== ${target} ====="
    echo "[MISSING]"
    echo
  fi
done
