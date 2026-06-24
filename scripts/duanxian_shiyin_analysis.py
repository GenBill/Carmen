#!/usr/bin/env python3
"""One-shot worker: ask OpenClaw to run 短线是银 mode and send result to Carmen bot."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import uuid


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CARMEN_ROOT = os.path.dirname(SCRIPT_DIR)


def normalize_display_code(symbol: str) -> str:
    if symbol.endswith(".SS") or symbol.endswith(".SZ") or symbol.endswith(".HK"):
        return symbol.split(".", 1)[0]
    return symbol


def build_prompt(symbol: str, bot_token: str, chat_id: str, reply_to_message_id: str) -> str:
    display_code = normalize_display_code(symbol)
    return f"""短线是银分析 {symbol}

你在为 Carmen Telegram bot 执行一次性 AI 任务。必须按下面流程做：

1. 启用/读取本机已安装的 `duanxian-shiyin` skill（唐能通《短线是银》全八卷体系）。
2. 必须获取实时/最新行情和约 250 根日 K。优先运行：
   `source /home/serv/.zshrc && conda run -n Quant python /home/serv/.openclaw/workspace/scripts/stock_quote_bridge.py --symbol {symbol} --days 250`
3. 基于行情事实 + skill 规则进行 AI 综合分析，不要使用 DeepSeek，不要走 Carmen 的 deepseek agent。
4. 输出必须是中文，直接给结论，不要解释执行过程。
5. A股/港股显示代码时去掉交易所后缀，只保留纯代码；例如 300686.SZ -> 300686，0016.HK -> 0016。
6. 必须使用 Telegram HTML parse mode 风格输出，把纯代码写成 <code>{display_code}</code>。
7. 标题第一行固定为：📘 短线是银 AI 分析
8. 内容结构：
   - 标的与时间
   - 行情与均线/量线事实
   - 按短线是银体系判读：价托/量托/多方炮/空方炮/芝麻量/飞行理论/蚂蚁功/三线止损，命中什么说什么，未命中也说明
   - 关键买点、持有条件、止损条件
   - 风险提示
9. 最后必须直接调用 Telegram Bot API 发送到下面这个 Carmen bot chat，而不是回复当前 OpenClaw 对话。
10. 如果行情获取失败，仍然向 Telegram 发送失败原因。

Telegram Bot Token: {bot_token}
Telegram Chat ID: {chat_id}
Reply To Message ID: {reply_to_message_id or '无'}

严格：本任务是临时任务；不要写入长期记忆；不要发散到基本面长文；不要输出调试日志。
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OpenClaw duanxian-shiyin analysis worker.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--bot-token", required=True)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--reply-to-message-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    symbol = args.symbol.strip().upper()
    session_id = f"tmp-carmen-duanxian-{symbol.replace('.', '-')}-{uuid.uuid4().hex[:12]}"
    task_prompt = build_prompt(symbol, args.bot_token, args.chat_id, args.reply_to_message_id or "")

    if args.dry_run:
        print(session_id)
        print(task_prompt)
        return 0

    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")

    result = subprocess.run(
        [
            "openclaw", "agent",
            "--session-id", session_id,
            "--message", task_prompt,
            "--timeout", "420",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=CARMEN_ROOT,
        timeout=480,
    )

    if result.returncode != 0:
        print(f"duanxian openclaw worker failed for {symbol}: {result.stderr}", file=sys.stderr)
        return 1

    print(f"duanxian openclaw worker ok for {symbol}; session_id={session_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
