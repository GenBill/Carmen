#!/usr/bin/env bash
set -euo pipefail

cd /home/serv/Carmen
restart_target() {
  local target="$1"
  local cmd="$2"

  if ! tmux has-session -t "${target%%:*}" 2>/dev/null; then
    echo "[ERROR] tmux session not found: ${target%%:*}" >&2
    return 1
  fi

  tmux send-keys -t "${target}" C-c
  sleep 2
  tmux send-keys -t "${target}" "conda activate Quant && ${cmd}" Enter
}

check_target() {
  local target="$1"
  echo "===== ${target} ====="
  tmux capture-pane -pt "${target}" | tail -30
  echo
}

restart_target "0:0" "python indicator/run.py"
restart_target "1:0" "python indicator/main_a.py"
restart_target "2:0" "python indicator/main_hk.py"
restart_target "3:0" "python scripts/telegram_ai_listener.py"

sleep 8

check_target "0:0"
check_target "1:0"
check_target "2:0"
check_target "3:0"
