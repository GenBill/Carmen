#!/usr/bin/env bash
set -euo pipefail

cd /home/serv/Carmen
source /home/serv/.zshrc >/dev/null 2>&1 || true

restart_target() {
  local target="$1"
  local cmd="$2"

  tmux send-keys -t "${target}" C-c
  sleep 2
  tmux send-keys -t "${target}" "conda activate Quant && ${cmd}" Enter
}

restart_target "0:0" "python indicator/run.py"
restart_target "1:0" "python indicator/main_a.py"
restart_target "2:0" "python indicator/main_hk.py"
restart_target "3:0" "python scripts/telegram_ai_listener.py"

sleep 8

for s in 0 1 2 3; do
  echo "===== session ${s} ====="
  tmux capture-pane -pt "${s}:0" | tail -30
  echo
done
