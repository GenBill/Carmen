#!/usr/bin/env python3
"""Telegram callback listener for Carmen.
Thin listener only: receive callback, ack fast, launch one-shot worker.
AI 分析仅读统一磁盘缓存，不现场调用模型。
"""
import html
import json
import os
import re
import subprocess
import sys
import time
from typing import Optional, Tuple

import requests

sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CARMEN_ROOT = os.path.dirname(SCRIPT_DIR)
INDICATOR_DIR = os.path.join(CARMEN_ROOT, 'indicator')
RUNTIME_DIR = os.path.join(CARMEN_ROOT, 'runtime')
OFFSET_FILE = os.path.join(RUNTIME_DIR, 'telegram_listener.offset')
TIMEOUT_SECONDS = 15
POLL_INTERVAL_SECONDS = 1

if INDICATOR_DIR not in sys.path:
    sys.path.insert(0, INDICATOR_DIR)

from telegram_notifier import load_telegram_token  # noqa: E402
from analysis import (  # noqa: E402
    get_analysis_context,
    read_analysis_cache_entry,
    validate_cache_for_use,
)


def ensure_runtime_dir():
    os.makedirs(RUNTIME_DIR, exist_ok=True)


def load_offset() -> int:
    ensure_runtime_dir()
    if not os.path.exists(OFFSET_FILE):
        return 0
    try:
        with open(OFFSET_FILE, 'r', encoding='utf-8') as f:
            return int(f.read().strip() or '0')
    except Exception:
        return 0


def save_offset(offset: int):
    ensure_runtime_dir()
    with open(OFFSET_FILE, 'w', encoding='utf-8') as f:
        f.write(str(offset))


def normalize_symbol(raw: str) -> str:
    value = raw.strip().upper()
    value = value.replace('[', '').replace(']', '')
    value = value.replace(' ', '').replace('-', '').replace('_', '')

    if value.endswith('.HK') or value.endswith('.SS') or value.endswith('.SZ'):
        return value
    if value.endswith('HK') and '.' not in value and value[:-2].isdigit():
        return f"{value[:-2]}.HK"
    if value.endswith('SS') and '.' not in value and value[:-2].isdigit():
        return f"{value[:-2]}.SS"
    if value.endswith('SZ') and '.' not in value and value[:-2].isdigit():
        return f"{value[:-2]}.SZ"
    if value.endswith('SH') and '.' not in value and value[:-2].isdigit():
        return f"{value[:-2]}.SS"
    if value.isdigit():
        if len(value) == 6:
            if value.startswith(('5', '6', '9')):
                return f"{value}.SS"
            return f"{value}.SZ"
        if len(value) == 4:
            return f"{value}.HK"
    if value.isalpha():
        return value
    return value


def send_message(bot_token: str, chat_id: str, text: str, reply_to_message_id: Optional[int] = None):
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)] or ['']
    for index, chunk in enumerate(chunks):
        data = {
            'chat_id': chat_id,
            'text': chunk,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }
        if reply_to_message_id and index == 0:
            data['reply_parameters'] = json.dumps({'message_id': reply_to_message_id}, ensure_ascii=False)
        response = requests.post(api_url, data=data, timeout=30)
        response.raise_for_status()


def answer_callback(bot_token: str, callback_query_id: str, text: str = '已收到，开始分析…'):
    api_url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    response = requests.post(api_url, data={'callback_query_id': callback_query_id, 'text': text}, timeout=15)
    response.raise_for_status()


def register_bot_commands(bot_token: str):
    api_url = f"https://api.telegram.org/bot{bot_token}/setMyCommands"
    commands = [
        {'command': 'ai_analysis', 'description': '仅读缓存：/ai_analysis 600519SS'}
    ]
    response = requests.post(api_url, data={'commands': json.dumps(commands, ensure_ascii=False)}, timeout=15)
    response.raise_for_status()


def extract_symbol_from_message(text: str) -> Optional[str]:
    match = re.match(r'^/ai_analysis(?:@\w+)?\s+(.+?)\s*$', text.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    return normalize_symbol(match.group(1))


def compose_telegram_cached_body(entry: dict) -> str:
    """
    把「结构化提炼」（refine_analysis）与「全文」（full_analysis）一并塞进会话；无全文时退回 summary_analysis。
    """
    full = (entry.get('full_analysis') or '').strip()
    refined = (entry.get('refine_analysis') or '').strip()
    summ = (entry.get('summary_analysis') or '').strip()

    if refined and full:
        sep = '\n\n' + ('─' * 18) + '\n\n'
        return f"【总结·提炼】\n{refined}{sep}【完整分析】\n{full}"
    if full:
        return full
    return summ


def resolve_cached_ai_text(symbol: str) -> Tuple[Optional[str], str]:
    """
    仅从统一缓存读取；返回 (正文, 说明)。
    先按 entry.status 分支；仅 completed 才做 validate_cache_for_use（需拉行情算 hash）。
    """
    entry = read_analysis_cache_entry(symbol)
    if not entry:
        return None, '暂无 AI 分析缓存'

    if entry.get('symbol') != symbol:
        return None, '缓存 symbol 与请求不一致，已拒绝。'

    st = entry.get('status') or ''

    if st == 'pending':
        return None, '分析进行中（pending）'

    if st == 'partial':
        body = compose_telegram_cached_body(entry).strip()
        if body:
            return body, '分析未完成（partial），以下为已生成的摘要/正文'
        return None, '分析未完成（partial）'

    if st == 'failed':
        return None, f"最近分析失败: {entry.get('error', '')}"

    if st == 'skipped':
        return None, '该股未触发后台 AI 条件（skipped）'

    if st == 'missing':
        return None, '暂无 AI 分析缓存'

    if st == 'completed':
        text = compose_telegram_cached_body(entry).strip()
        if not text:
            return None, 'completed 缓存中文本为空'

        ctx = get_analysis_context(symbol)
        if ctx is None:
            # yfinance/网络异常时无法做 hash/价格校验；仍展示缓存正文并标明未校验，避免「完全不可用」
            return text, (
                '缓存命中（completed）；当前无法拉取行情做一致性校验，若与实时价偏离以市场为准'
            )
        if not validate_cache_for_use(
            entry, symbol, ctx['data_hash'], ctx['current_price'],
        ):
            return None, '缓存与当前行情不一致或已过期（data_hash/价格/脏标记），请等待新一轮扫描。'

        return text, '缓存命中（completed）'

    return None, f"未知缓存状态: {st}"


def build_analysis_message(symbol: str, body: str, subtitle: str) -> str:
    safe_symbol = html.escape(symbol.replace('.SS', '[SS]').replace('.SZ', '[SZ]').replace('.HK', '[HK]'))
    header = html.escape(subtitle)
    return f"{header}\n股票: {safe_symbol}\n\n{html.escape(body)}"


def build_status_only_message(symbol: str, reason: str) -> str:
    safe_symbol = html.escape(symbol.replace('.SS', '[SS]').replace('.SZ', '[SZ]').replace('.HK', '[HK]'))
    return f"📭 无可用 AI 展示\n股票: {safe_symbol}\n\n{html.escape(reason)}"


def process_symbol(bot_token: str, chat_id: str, symbol: str, reply_to_message_id: Optional[int] = None):
    text, note = resolve_cached_ai_text(symbol)
    if text:
        msg = build_analysis_message(symbol, text, f'♻️ {note}')
    else:
        msg = build_status_only_message(symbol, note or '未知原因')
    send_message(bot_token, chat_id, msg, reply_to_message_id=reply_to_message_id)


def spawn_fundamental_worker(symbol: str, bot_token: str, chat_id: str, reply_to_message_id: Optional[int] = None) -> bool:
    ensure_runtime_dir()
    log_path = os.path.join(RUNTIME_DIR, f"fundamental_{symbol.replace('.', '_')}_{int(time.time())}.log")
    worker_script = os.path.join(SCRIPT_DIR, 'handle_fundamental_click.py')
    env = os.environ.copy()
    env.setdefault('PYTHONUNBUFFERED', '1')
    try:
        with open(log_path, 'w', encoding='utf-8') as log_file:
            subprocess.Popen(
                [
                    'python', '-u', worker_script,
                    '--symbol', symbol,
                    '--bot-token', bot_token,
                    '--chat-id', str(chat_id),
                    '--reply-to-message-id', str(reply_to_message_id or ''),
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=CARMEN_ROOT,
                env=env,
                start_new_session=True,
            )
        print(f"🚀 worker spawned: symbol={symbol} log={log_path}")
        return True
    except Exception as e:
        print(f"⚠️ spawn worker failed: {e}")
        return False


def handle_update(bot_token: str, expected_chat_id: str, update: dict):
    if 'callback_query' in update:
        query = update['callback_query']
        data = query.get('data', '')
        message = query.get('message', {})
        chat_id = str(message.get('chat', {}).get('id', ''))
        if chat_id != str(expected_chat_id):
            answer_callback(bot_token, query['id'], '未授权的聊天来源')
            return
        if data.startswith('ai_analysis:'):
            symbol = normalize_symbol(data.split(':', 1)[1])
            answer_callback(bot_token, query['id'], '已收到（仅读缓存）')
            process_symbol(bot_token, chat_id, symbol, reply_to_message_id=message.get('message_id'))
        elif data.startswith('fundamental:'):
            symbol = normalize_symbol(data.split(':', 1)[1])
            ok = spawn_fundamental_worker(symbol, bot_token, chat_id, reply_to_message_id=message.get('message_id'))
            answer_callback(bot_token, query['id'], '已收到，正在查询基本面…' if ok else '启动查询失败')
        return

    if 'message' in update:
        message = update['message']
        chat_id = str(message.get('chat', {}).get('id', ''))
        if chat_id != str(expected_chat_id):
            return
        text = message.get('text', '')
        symbol = extract_symbol_from_message(text)
        if not symbol:
            return
        send_message(
            bot_token,
            chat_id,
            f"🧠 已收到 /ai_analysis {html.escape(symbol)}（仅读缓存，不现场生成）",
            reply_to_message_id=message.get('message_id'),
        )
        process_symbol(bot_token, chat_id, symbol, reply_to_message_id=message.get('message_id'))


def main():
    bot_token, chat_id = load_telegram_token()
    offset = load_offset()
    api_url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    register_bot_commands(bot_token)
    print(f"🤖 Telegram AI listener 启动，chat_id={chat_id}")

    while True:
        try:
            response = requests.get(
                api_url,
                params={'timeout': TIMEOUT_SECONDS, 'offset': offset, 'allowed_updates': json.dumps(['message', 'callback_query'])},
                timeout=TIMEOUT_SECONDS + 10,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get('ok'):
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            for update in payload.get('result', []):
                offset = max(offset, update['update_id'] + 1)
                handle_update(bot_token, chat_id, update)
                save_offset(offset)
        except requests.exceptions.SSLError:
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ Telegram listener 异常: {e}")
            time.sleep(3)


if __name__ == '__main__':
    main()
