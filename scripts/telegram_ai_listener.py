#!/usr/bin/env python3
"""Telegram callback listener for Carmen.
Thin listener only: receive callback, ack fast, launch one-shot worker.
"""
import html
import json
import os
import re
import subprocess
import sys
import time
from typing import Optional

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
from analysis import analyze_stock_with_ai  # noqa: E402


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


def infer_market(symbol: str) -> str:
    if symbol.endswith('.HK') or symbol.endswith('.SS') or symbol.endswith('.SZ'):
        return 'HKA'
    return 'US'


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
        {'command': 'ai_analysis', 'description': '分析指定股票，例如 /ai_analysis 600519SS'}
    ]
    response = requests.post(api_url, data={'commands': json.dumps(commands, ensure_ascii=False)}, timeout=15)
    response.raise_for_status()


def extract_symbol_from_message(text: str) -> Optional[str]:
    match = re.match(r'^/ai_analysis(?:@\w+)?\s+(.+?)\s*$', text.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    return normalize_symbol(match.group(1))


def build_analysis_text(symbol: str, analysis: str, cached: bool) -> str:
    safe_symbol = html.escape(symbol.replace('.SS', '[SS]').replace('.SZ', '[SZ]').replace('.HK', '[HK]'))
    header = '♻️ AI分析（缓存命中）' if cached else '🤖 AI分析结果'
    return f"{header}\n股票: {safe_symbol}\n\n{html.escape(analysis)}"


def get_cached_analysis(symbol: str) -> Optional[str]:
    from analysis import load_analysis_cache, get_stock_data, calculate_data_hash

    daily_data, hourly_data = get_stock_data(symbol, 250)
    if daily_data is None or daily_data.empty:
        return None
    data_hash = calculate_data_hash(symbol, daily_data, hourly_data)
    cache_data = load_analysis_cache(symbol)
    if cache_data and cache_data.get('data_hash') == data_hash:
        return cache_data.get('analysis')
    return None


def process_symbol(bot_token: str, chat_id: str, symbol: str, reply_to_message_id: Optional[int] = None):
    cached_analysis = get_cached_analysis(symbol)
    cached = cached_analysis is not None
    analysis = cached_analysis or analyze_stock_with_ai(symbol, market=infer_market(symbol))
    send_message(bot_token, chat_id, build_analysis_text(symbol, analysis, cached), reply_to_message_id=reply_to_message_id)


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
            answer_callback(bot_token, query['id'])
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
        send_message(bot_token, chat_id, f"🧠 已收到 /ai_analysis {html.escape(symbol)}，开始分析…", reply_to_message_id=message.get('message_id'))
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
