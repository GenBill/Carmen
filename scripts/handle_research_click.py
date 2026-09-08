#!/usr/bin/env python3
"""One-shot worker for Carmen research-report button clicks."""
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
    parser = argparse.ArgumentParser(description='Handle Carmen research-report callback')
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--bot-token', required=True)
    parser.add_argument('--chat-id', required=True)
    parser.add_argument('--reply-to-message-id', default='')
    args = parser.parse_args()

    symbol = args.symbol.strip().upper()
    display_code = normalize_display_code(symbol)
    session_id = f"carmen-research-{symbol}-{uuid.uuid4().hex[:12]}"

    task_prompt = f"""查研报: {symbol}

你在为 Carmen 的 Telegram 通知按钮执行一次性任务。
目标：联网检索该股票/公司的公开研报、券商评级、目标价、盈利预测、公告解读或财报点评。
重点：优先提取未来 3 年业绩预期，尤其是每股收益 EPS 的变化。

要求：
1. 必须联网核实；优先找最近 90 天信息，最多输出 5 条。
2. A股优先查公开券商研报/PDF/东财研报/巨潮公告解读；港股和美股可退化为 analyst rating、price target、earnings call/news analysis。
3. 不要编造机构、评级、目标价、PDF 链接。没有可靠结果就明确写“未找到可靠公开研报”。
4. 使用 Telegram HTML parse mode；代码写成 <code>{display_code}</code>。
5. 每条尽量包含：日期｜机构/来源｜评级/动作｜标题｜链接。
6. 如研报含盈利预测，必须提取 2026/2027/2028 EPS、归母净利润、营收预测；没有 EPS 但有净利润时，可用总股本估算 EPS，并标注“估算”。
7. 链接要可直接打开；多个链接只列必要链接。
8. 直接调用 Telegram Bot API 发送到下面这个 Carmen bot chat，而不是回复当前 OpenClaw 对话。
9. 不要输出检索过程、调试信息、免责声明长文。

Telegram Bot Token: {args.bot_token}
Telegram Chat ID: {args.chat_id}
Reply To Message ID: {args.reply_to_message_id or '无'}

严格输出格式：
🧾 研报/评级速查
<code>{display_code}</code> 股票名

EPS/业绩预期：
- 2026E: EPS X.XX｜营收 X.XX亿｜归母净利 X.XX亿
- 2027E: EPS X.XX｜营收 X.XX亿｜归母净利 X.XX亿
- 2028E: EPS X.XX｜营收 X.XX亿｜归母净利 X.XX亿

1. 日期｜机构/来源｜评级/动作
标题
链接

没有可靠结果时：
🧾 研报/评级速查
<code>{display_code}</code>
未找到可靠公开研报/评级信息。
"""

    env = os.environ.copy()
    env.setdefault('PYTHONUNBUFFERED', '1')

    result = subprocess.run(
        [
            'openclaw', 'agent',
            '--session-id', session_id,
            '--message', task_prompt,
            '--timeout', '300',
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=360,
    )

    if result.returncode != 0:
        print(f"worker failed for {symbol}: {result.stderr}", file=sys.stderr)
        return 1

    print(f"worker ok for {symbol}; session_id={session_id}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
