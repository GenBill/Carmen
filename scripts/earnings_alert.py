#!/usr/bin/env python3
import os
import sys
import html
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set

import requests

REPORTER_PATH = '/home/serv/.openclaw/workspace/scripts/reporter.py'

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
INDICATOR_DIR = os.path.join(BASE_DIR, 'indicator')
if INDICATOR_DIR not in sys.path:
    sys.path.append(INDICATOR_DIR)

from telegram_notifier import TelegramNotifier, load_telegram_token, build_telegram_request_kwargs, parse_telegram_chat_ids  # noqa: E402

# Dedicated earnings-alert watchlist. Keep this independent from trading/buy-signal watchlists.
WATCHLIST_PATH = os.path.join(BASE_DIR, 'data', 'earnings_watchlist_us.txt')
INFO_BOT_TOKEN_PATH = '/home/serv/.openclaw/secrets/telegram_daily_news.token'
LOG_PREFIX = '[earnings-alert]'
NASDAQ_CALENDAR_URL = 'https://api.nasdaq.com/api/calendar/earnings'
LOOKAHEAD_DAYS = 3
TIMEOUT = 20

REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Accept': 'application/json',
    'Origin': 'https://www.nasdaq.com',
    'Referer': 'https://www.nasdaq.com/',
}

TELEGRAM_REQUEST_KWARGS = build_telegram_request_kwargs(timeout=10)


def log(msg: str) -> None:
    print(f'{LOG_PREFIX} {msg}')


def load_watchlist(path: str) -> List[str]:
    symbols = []
    seen: Set[str] = set()
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            symbol = raw.strip().upper()
            if not symbol or symbol.startswith('#'):
                continue
            if symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)
    return symbols


def fetch_earnings_calendar(day: datetime) -> List[Dict]:
    date_str = day.strftime('%Y-%m-%d')
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.get(
                NASDAQ_CALENDAR_URL,
                params={'date': date_str},
                headers=REQUEST_HEADERS,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get('data', {}).get('rows', [])
            if isinstance(rows, list):
                return rows
            return []
        except Exception as e:
            last_error = e
    log(f'failed to fetch earnings calendar for {date_str}: {last_error}')
    return []


def normalize_time_label(value: Optional[str]) -> str:
    if not value:
        return '未标注'
    value = str(value).strip()
    mapping = {
        'time-not-supplied': '时间未提供',
        'amc': '盘后',
        'bmo': '盘前',
        'dmh': '盘中',
    }
    return mapping.get(value.lower(), value)


def build_alert_message(matches: List[Dict]) -> str:
    header = f'🚨 财报临近预警（独立列表）\n接下来 {LOOKAHEAD_DAYS} 天内，财报监控列表里有这些标的将发布财报：'
    lines = [header]
    for item in matches:
        lines.append(
            f"\n🔔 {html.escape(item['symbol'])} - {html.escape(item['name'])}"
            f"\n• 财报日期: {item['report_date']}"
            f"\n• 披露时段: {html.escape(item['time_label'])}"
            f"\n• 距今天数: {item['days_until']} 天"
        )
    lines.append('\n⚠️ 注意：这是财报事件预警，不是买入信号。')
    return '\n'.join(lines)


def collect_upcoming_matches(symbols: List[str]) -> List[Dict]:
    symbol_set = set(symbols)
    today = datetime.now()
    matches: Dict[str, Dict] = {}

    for offset in range(LOOKAHEAD_DAYS + 1):
        day = today + timedelta(days=offset)
        rows = fetch_earnings_calendar(day)
        for row in rows:
            symbol = str(row.get('symbol', '')).strip().upper()
            if symbol not in symbol_set:
                continue

            report_date = day.strftime('%Y-%m-%d')
            key = f'{symbol}|{report_date}'
            matches[key] = {
                'symbol': symbol,
                'name': str(row.get('name', '')).strip() or symbol,
                'report_date': report_date,
                'time_label': normalize_time_label(row.get('time')),
                'days_until': offset,
            }

    return sorted(matches.values(), key=lambda x: (x['days_until'], x['symbol']))


def main() -> int:
    if not os.path.exists(WATCHLIST_PATH):
        log(f'watchlist not found: {WATCHLIST_PATH}')
        return 1

    symbols = load_watchlist(WATCHLIST_PATH)
    us_symbols = [s for s in symbols if '.' not in s]
    if not us_symbols:
        log('no US symbols found in watchlist')
        return 0

    log(f'loaded {len(us_symbols)} US earnings watchlist symbols from {WATCHLIST_PATH}')

    matches = collect_upcoming_matches(us_symbols)
    if not matches:
        log('no upcoming earnings within 7 days')
        return 0

    bot_token, chat_id = load_telegram_token(INFO_BOT_TOKEN_PATH)
    notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)

    message = build_alert_message(matches)

    retry_schedule = [60, 300, 600]
    attempt = 0
    fault_lens_sent = False
    while True:
        attempt += 1
        try:
            response = None
            for idx, target_chat_id in enumerate(parse_telegram_chat_ids(notifier.chat_id)):
                try:
                    response = requests.post(
                        notifier.api_url,
                        data={
                            'chat_id': target_chat_id,
                            'text': message,
                            'disable_web_page_preview': True,
                        },
                        **TELEGRAM_REQUEST_KWARGS,
                    )
                    response.raise_for_status()
                except Exception:
                    if idx == 0:
                        raise
                    log(f'Daily News extra forward failed chat_id={target_chat_id}')
            if attempt > 1:
                log(f'plain text telegram push finally succeeded on attempt {attempt}')
            log(f'sent {len(matches)} earnings alerts')
            return 0
        except Exception as e:
            error_detail = ''
            if 'response' in locals() and hasattr(response, 'text'):
                error_detail = f' Server response: {response.text}'
            if attempt > 3 and not fault_lens_sent:
                fault_msg = (
                    f'earnings_alert.py telegram send failed >3 times; manual intervention needed. '
                    f'attempt={attempt}; matches={len(matches)}; error={str(e)}{error_detail}'
                )
                try:
                    import subprocess
                    subprocess.run(
                        [
                            '/usr/bin/python3', REPORTER_PATH,
                            '--type', 'network_error',
                            '--source', 'earnings_alert.py',
                            '--message', fault_msg,
                        ],
                        check=False,
                        timeout=30,
                    )
                    fault_lens_sent = True
                    log('fault lens warning sent after >3 failed attempts')
                except Exception as report_err:
                    log(f'fault lens warning failed: {report_err}')
            wait_time = retry_schedule[min(attempt - 1, len(retry_schedule) - 1)]
            log(f'plain text telegram push failed on attempt {attempt}: {e}{error_detail}, retry in {wait_time}s')
            time.sleep(wait_time)


if __name__ == '__main__':
    raise SystemExit(main())
