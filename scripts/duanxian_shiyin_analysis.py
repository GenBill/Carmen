#!/usr/bin/env python3
"""One-shot worker: ask Hermes to run 短线是银 mode and send the result to Carmen Telegram."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CARMEN_ROOT = Path(__file__).resolve().parent.parent
HERMES_BIN = "/home/serv/.local/bin/hermes"
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def normalize_display_code(symbol: str) -> str:
    if symbol.endswith((".SS", ".SZ", ".HK")):
        return symbol.split(".", 1)[0]
    return symbol


def build_prompt(symbol: str) -> str:
    display_code = normalize_display_code(symbol)
    return f"""短线是银分析 {symbol}

你在为 Carmen Telegram bot 执行一次性 AI 任务。必须按下面流程做：
1. 启用/读取本机已安装的 `duanxian-shiyin` skill（唐能通《短线是银》全八卷体系）。
2. 必须获取实时/最新行情和约 250 根日 K。优先运行：
   `source /home/serv/.zshrc && conda run -n Quant python /home/serv/Wyrd-Memory/scripts/stock_quote_bridge.py --symbol {symbol} --days 250`
3. 基于行情事实 + skill 规则综合分析；不要使用 DeepSeek。
4. 只输出最终中文正文，不解释执行过程，不调用 Telegram，不输出调试日志。
5. A股/港股代码去掉交易所后缀；使用 Telegram HTML，把代码写成 <code>{display_code}</code>。
6. 第一行固定为：📘 短线是银 AI 分析
7. 内容包括：标的与时间、行情和均线/量线事实、短线是银形态判读、买点/持有/止损条件、风险提示。
8. 行情获取失败时，输出简洁失败原因。
9. 本任务是临时任务，不写入长期记忆。
"""


def _load_proxy() -> str | None:
    env_file = Path("/home/serv/.hermes/.env")
    if env_file.exists():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            if raw.strip().startswith("TELEGRAM_PROXY="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("TELEGRAM_PROXY") or os.environ.get("HTTPS_PROXY")


def send_telegram(token: str, chat_id: str, html_text: str, reply_to_message_id: str = "") -> None:
    payload = {"chat_id": chat_id, "text": html_text, "parse_mode": "HTML"}
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    proxy = _load_proxy()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}) if proxy else urllib.request.ProxyHandler({})
    )
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=urllib.parse.urlencode(payload).encode(),
        method="POST",
    )
    with opener.open(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8", "replace"))
    if not body.get("ok"):
        raise RuntimeError(f"Telegram send failed: {body.get('description', 'unknown error')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Hermes duanxian-shiyin analysis worker.")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--bot-token", required=True)
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--reply-to-message-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    symbol = args.symbol.strip().upper()
    prompt = build_prompt(symbol)
    if args.dry_run:
        print(prompt)
        return 0

    result = subprocess.run(
        [HERMES_BIN, "chat", "-Q", "-q", prompt],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        cwd=CARMEN_ROOT,
        timeout=480,
        check=False,
    )
    if result.returncode != 0:
        print(f"duanxian Hermes worker failed for {symbol}: {(result.stderr or result.stdout)[-1000:]}", file=sys.stderr)
        return 1
    reply = ANSI_RE.sub("", result.stdout or "").strip()
    if reply.startswith("session_id:"):
        reply = "\n".join(reply.splitlines()[1:]).strip()
    if not reply:
        print(f"duanxian Hermes worker returned empty reply for {symbol}", file=sys.stderr)
        return 1
    send_telegram(args.bot_token, args.chat_id, reply, args.reply_to_message_id)
    print(f"duanxian Hermes worker ok for {symbol}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
