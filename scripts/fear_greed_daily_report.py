#!/usr/bin/env python3
"""Send CNN Fear & Greed Index daily morning report via Daily News Telegram bot."""
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import requests

BASE_DIR = '/home/serv/Carmen'
INDICATOR_DIR = os.path.join(BASE_DIR, 'indicator')
if INDICATOR_DIR not in sys.path:
    sys.path.append(INDICATOR_DIR)

from telegram_notifier import build_telegram_request_kwargs, load_telegram_token, parse_telegram_chat_ids  # noqa: E402

INFO_BOT_TOKEN_PATH = '/home/serv/.openclaw/secrets/telegram_daily_news.token'
CNN_FEAR_GREED_URL = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'
TIMEOUT = 20
HKT = timezone(timedelta(hours=8))
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': 'https://www.cnn.com/markets/fear-and-greed',
    'Origin': 'https://www.cnn.com',
}
REQUEST_KWARGS = build_telegram_request_kwargs(timeout=15)

def fetch_payload() -> Dict[str, Any]:
    resp = requests.get(CNN_FEAR_GREED_URL, headers=REQUEST_HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError('CNN response is not a JSON object')
    if not isinstance(payload.get('fear_and_greed'), dict):
        raise RuntimeError('CNN response missing fear_and_greed')
    return payload


RATING_ZH = {
    'extreme fear': '极度恐惧',
    'fear': '恐惧',
    'neutral': '中性',
    'greed': '贪婪',
    'extreme greed': '极度贪婪',
}


def fmt_rating(value: Any) -> str:
    rating = str(value or '').lower().strip()
    return RATING_ZH.get(rating, str(value or 'N/A').strip() or 'N/A')


def fmt_num(value: Any, digits: int = 1) -> str:
    try:
        return f'{float(value):.{digits}f}'
    except Exception:
        return 'N/A'


def fmt_delta(now: Any, old: Any, digits: int = 1) -> str:
    try:
        delta = float(now) - float(old)
    except Exception:
        return 'N/A'
    sign = '+' if delta >= 0 else ''
    return f'{sign}{delta:.{digits}f}'


def parse_ts(value: Any) -> str:
    if value in (None, ''):
        return 'N/A'
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(HKT).strftime('%Y-%m-%d %H:%M HKT')
    except Exception:
        return str(value)


def build_message(payload: Dict[str, Any]) -> str:
    main = payload['fear_and_greed']
    score = main.get('score')
    rating = fmt_rating(main.get('rating'))
    ts = parse_ts(main.get('timestamp'))

    lines = [
        '🧊 风险偏好降温｜CNN Fear & Greed Index',
        f'当前指数: {fmt_num(score)} / 100（{rating}）',
        f'更新时间: {ts}',
        '',
        '指数前值:',
        f'• 前收盘: {fmt_num(main.get("previous_close"))}｜变化 {fmt_delta(score, main.get("previous_close"))}',
        f'• 1周前: {fmt_num(main.get("previous_1_week"))}｜变化 {fmt_delta(score, main.get("previous_1_week"))}',
        f'• 1月前: {fmt_num(main.get("previous_1_month"))}｜变化 {fmt_delta(score, main.get("previous_1_month"))}',
        f'• 1年前: {fmt_num(main.get("previous_1_year"))}｜变化 {fmt_delta(score, main.get("previous_1_year"))}',
    ]

    return '\n'.join(lines)


def send_telegram(text: str) -> None:
    bot_token, chat_id_text = load_telegram_token(INFO_BOT_TOKEN_PATH)
    chat_ids = parse_telegram_chat_ids(chat_id_text)
    if not chat_ids:
        raise RuntimeError('no Telegram chat ids configured')

    for idx, chat_id in enumerate(chat_ids):
        try:
            resp = requests.post(
                f'https://api.telegram.org/bot{bot_token}/sendMessage',
                data={
                    'chat_id': chat_id,
                    'text': text,
                    'disable_web_page_preview': True,
                },
                **REQUEST_KWARGS,
            )
            resp.raise_for_status()
        except Exception:
            if idx == 0:
                raise
            print(f'WARN extra forward failed chat_id={chat_id}', file=sys.stderr)


def main() -> int:
    payload = fetch_payload()
    msg = build_message(payload)
    if '--dry-run' in sys.argv:
        print(msg)
        return 0
    send_telegram(msg)
    print(f'sent fear & greed daily report: {fmt_num(payload["fear_and_greed"].get("score"))}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
