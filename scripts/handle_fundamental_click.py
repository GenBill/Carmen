#!/usr/bin/env python3
"""One-shot worker for Carmen fundamental button clicks."""
import argparse
import os
import subprocess
import sys
import uuid


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CARMEN_ROOT = os.path.dirname(SCRIPT_DIR)


def normalize_display_code(symbol: str) -> str:
    if symbol.endswith('.SS') or symbol.endswith('.SZ') or symbol.endswith('.HK'):
        return symbol.split('.', 1)[0]
    return symbol


def main():
    parser = argparse.ArgumentParser(description='Handle Carmen fundamental callback')
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--bot-token', required=True)
    parser.add_argument('--chat-id', required=True)
    parser.add_argument('--reply-to-message-id', default='')
    args = parser.parse_args()

    symbol = args.symbol.strip().upper()
    display_code = normalize_display_code(symbol)
    session_id = f"carmen-fundamental-{symbol}-{uuid.uuid4().hex[:12]}"

    task_prompt = f"""查基本面: {symbol}

你在为 Carmen 的 Telegram 通知按钮执行一次性任务。
要求：
1. 使用联网检索，快速核实该股票/公司的【股票名、板块、主营业务】。
2. A股/港股显示代码时去掉交易所后缀，只保留纯代码；例如 300686.SZ -> 300686，0016.HK -> 0016。
3. 必须使用 HTML parse mode 风格输出，把纯代码写成 <code>{display_code}</code>，保证 Telegram 中可点按复制。
4. “📊 基本面速览” 后面必须立刻换行。
5. 标题第二行必须是：<code>{display_code}</code> 股票名
6. 第三行必须是：板块：XXX｜主营：XXX
7. 直接调用 Telegram Bot API 发送到下面这个 Carmen bot chat，而不是回复当前 OpenClaw 对话。
8. 不要解释过程，不要输出调试信息。
9. 如果信息不足，保守回复：
📊 基本面速览
<code>{display_code}</code>
未找到可靠基本面信息。

Telegram Bot Token: {args.bot_token}
Telegram Chat ID: {args.chat_id}
Reply To Message ID: {args.reply_to_message_id or '无'}

严格输出格式：
📊 基本面速览
<code>{display_code}</code> 股票名
板块：XXX｜主营：XXX
"""

    env = os.environ.copy()
    env.setdefault('PYTHONUNBUFFERED', '1')

    result = subprocess.run(
        [
            'openclaw', 'agent',
            '--session-id', session_id,
            '--message', task_prompt,
            '--timeout', '240',
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )

    if result.returncode != 0:
        print(f"worker failed for {symbol}: {result.stderr}", file=sys.stderr)
        return 1

    print(f"worker ok for {symbol}; session_id={session_id}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
