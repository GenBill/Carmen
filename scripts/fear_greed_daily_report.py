#!/usr/bin/env python3
"""Send daily CNN Fear & Greed / VIX K-index report via Carmen Telegram bot."""
import json
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

CNN_FEAR_GREED_URL = 'https://production.dataviz.cnn.io/index/fearandgreed/graphdata'
STATE_FILE = os.path.join(INDICATOR_DIR, 'runtime', 'k_index_state.json')
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


def fetch_vix_history() -> List[Dict[str, Any]]:
    import yfinance as yf

    hist = yf.Ticker('^VIX').history(period='18mo', interval='1d')
    if hist is None or hist.empty or 'Close' not in hist:
        raise RuntimeError('yfinance VIX history is empty')
    closes = hist['Close'].dropna()
    if closes.empty:
        raise RuntimeError('yfinance VIX close values are empty')

    rows: List[Dict[str, Any]] = []
    for idx, close in closes.items():
        ts = idx.isoformat() if hasattr(idx, 'isoformat') else str(idx)
        day = idx.date().isoformat() if hasattr(idx, 'date') else str(idx)[:10]
        rows.append({'date': day, 'value': float(close), 'timestamp': ts, 'source': 'yfinance'})
    return rows


def latest_vix(vix_history: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not vix_history:
        raise RuntimeError('VIX history is empty')
    return vix_history[-1]


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


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f'WARN failed to load K-index state: {e}', file=sys.stderr)
        return {}


def save_state(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def build_k_index(score: Any, vix: Any) -> Optional[float]:
    try:
        cnn_score = float(score)
        vix_value = float(vix)
    except Exception:
        return None
    if vix_value <= 0:
        return None
    return cnn_score / vix_value


def fmt_k(value: Any) -> str:
    try:
        return f'{float(value):.2f}'
    except Exception:
        return 'N/A'


def detect_cross_alert(k_index: Optional[float], previous_k: Any) -> Optional[str]:
    if k_index is None:
        return None
    try:
        prev = float(previous_k)
    except Exception:
        return None

    if prev > 1 and k_index < 1:
        return '✅ K指数下穿1：加仓信号'
    if prev > 2 and k_index < 2:
        return '⚠️ K指数下穿2：减仓，等待下一轮加仓点'
    return None


def build_k_status(k_index: Optional[float]) -> str:
    if k_index is None:
        return 'K指数: N/A'
    if k_index < 1:
        zone = '低于1，加仓区'
    elif k_index < 2:
        zone = '1-2，重点观察区'
    else:
        zone = '高于2，偏贪婪/等待回落'
    near = ''
    if abs(k_index - 1) <= 0.15:
        near = '，接近1'
    elif abs(k_index - 2) <= 0.15:
        near = '，接近2'
    return f'K指数: {fmt_k(k_index)}（{zone}{near}）'


def cnn_day_from_ts_ms(value: Any) -> Optional[str]:
    try:
        dt = datetime.fromtimestamp(float(value) / 1000, tz=timezone.utc)
        return dt.date().isoformat()
    except Exception:
        return None


def extract_cnn_history(payload: Dict[str, Any]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    historical = payload.get('fear_and_greed_historical') or {}
    for item in historical.get('data') or []:
        day = cnn_day_from_ts_ms(item.get('x'))
        score = item.get('y')
        if not day:
            continue
        try:
            out[day] = float(score)
        except Exception:
            continue
    main = payload.get('fear_and_greed') or {}
    day = cnn_day_from_ts_ms(main.get('timestamp'))
    if day:
        try:
            out[day] = float(main.get('score'))
        except Exception:
            pass
    return out


def build_k_series(payload: Dict[str, Any], vix_history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cnn_by_day = extract_cnn_history(payload)
    rows: List[Dict[str, Any]] = []
    for vix_row in vix_history:
        day = str(vix_row.get('date') or '')
        if day not in cnn_by_day:
            continue
        vix_value = vix_row.get('value')
        k_index = build_k_index(cnn_by_day[day], vix_value)
        if k_index is None:
            continue
        rows.append({
            'date': day,
            'cnn': cnn_by_day[day],
            'vix': float(vix_value),
            'k': k_index,
        })
    return rows


def select_row_on_or_before(rows: List[Dict[str, Any]], target_day: str) -> Optional[Dict[str, Any]]:
    candidates = [row for row in rows if str(row.get('date')) <= target_day]
    if candidates:
        return candidates[-1]

    target = datetime.fromisoformat(target_day).date()
    for row in rows:
        try:
            row_day = datetime.fromisoformat(str(row.get('date'))).date()
        except Exception:
            continue
        if row_day >= target and (row_day - target).days <= 7:
            return row
    return None


def fmt_k_trend_line(label: str, current: Optional[Dict[str, Any]], old: Optional[Dict[str, Any]]) -> str:
    if not current or not old:
        return f'• {label}: N/A'
    delta = fmt_delta(current.get('k'), old.get('k'), digits=2)
    return (
        f'• {label}: K {fmt_k(old.get("k"))}｜变化 {delta}｜'
        f'CNN {fmt_num(old.get("cnn"))} / VIX {fmt_num(old.get("vix"), 2)}'
    )


def build_k_trend_lines(k_series: List[Dict[str, Any]]) -> List[str]:
    if not k_series:
        return ['• K趋势数据不足']
    current = k_series[-1]
    current_day = datetime.fromisoformat(str(current['date'])).date()
    previous = k_series[-2] if len(k_series) >= 2 else None
    week = select_row_on_or_before(k_series, (current_day - timedelta(days=7)).isoformat())
    month = select_row_on_or_before(k_series, (current_day - timedelta(days=30)).isoformat())
    year = select_row_on_or_before(k_series, (current_day - timedelta(days=365)).isoformat())
    return [
        fmt_k_trend_line('前收盘', current, previous),
        fmt_k_trend_line('1周前', current, week),
        fmt_k_trend_line('1月前', current, month),
        fmt_k_trend_line('1年前', current, year),
    ]


def build_message(
    payload: Dict[str, Any],
    vix: Dict[str, Any],
    vix_history: List[Dict[str, Any]],
    previous_k: Any = None,
) -> str:
    main = payload['fear_and_greed']
    score = main.get('score')
    rating = fmt_rating(main.get('rating'))
    ts = parse_ts(main.get('timestamp'))
    vix_value = vix.get('value')
    vix_ts = parse_ts(vix.get('timestamp'))
    k_index = build_k_index(score, vix_value)
    cross_alert = detect_cross_alert(k_index, previous_k)
    k_series = build_k_series(payload, vix_history)

    lines = [
        '🧊 Carmen K指数日报',
        f'当前指数: {fmt_num(score)} / 100（{rating}）',
        f'VIX: {fmt_num(vix_value, 2)}',
        build_k_status(k_index),
    ]
    if previous_k not in (None, ''):
        lines.append(f'上次K指数: {fmt_k(previous_k)}')
    if cross_alert:
        lines.extend(['', cross_alert])
    lines.extend([
        '',
        f'CNN更新时间: {ts}',
        f'VIX更新时间: {vix_ts}',
        '',
        'K指数趋势:',
        *build_k_trend_lines(k_series),
    ])

    return '\n'.join(lines)


def send_telegram(text: str) -> None:
    bot_token, chat_id_text = load_telegram_token()
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
    vix_history = fetch_vix_history()
    vix = latest_vix(vix_history)
    state = load_state()
    previous_k = state.get('last_k_index')
    msg = build_message(payload, vix, vix_history, previous_k=previous_k)
    if '--dry-run' in sys.argv:
        print(msg)
        return 0
    send_telegram(msg)
    score = payload['fear_and_greed'].get('score')
    k_index = build_k_index(score, vix.get('value'))
    state.update({
        'last_k_index': k_index,
        'last_cnn_score': score,
        'last_vix': vix.get('value'),
        'last_sent_at': datetime.now(HKT).isoformat(),
    })
    save_state(state)
    print(f'sent K-index daily report: cnn={fmt_num(score)} vix={fmt_num(vix.get("value"), 2)} k={fmt_k(k_index)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
