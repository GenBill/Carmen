#!/usr/bin/env python3
"""US/China macro data pre-alert and post-release stock-market impact notes.

Runs from cron every few minutes. Source: Nasdaq economic calendar.
Sends:
- pre-alert once when a watched event is roughly 1 day away
- post-release analysis once after actual data appears
"""
import hashlib
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

BASE_DIR = '/home/serv/Carmen'
INDICATOR_DIR = os.path.join(BASE_DIR, 'indicator')
if INDICATOR_DIR not in sys.path:
    sys.path.append(INDICATOR_DIR)

from telegram_notifier import load_telegram_token, build_telegram_request_kwargs  # noqa: E402

INFO_BOT_TOKEN_PATH = '/home/serv/.openclaw/secrets/telegram_daily_news.token'
STATE_PATH = '/home/serv/Carmen/runtime/economic_data_alert_state.json'
LOG_PREFIX = '[economic-data-alert]'
NASDAQ_ECON_URL = 'https://api.nasdaq.com/api/calendar/economicevents'
TIMEOUT = 20
REQUEST_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Accept': 'application/json',
    'Origin': 'https://www.nasdaq.com',
    'Referer': 'https://www.nasdaq.com/',
}
TELEGRAM_REQUEST_KWARGS = build_telegram_request_kwargs(timeout=15)
WYRD_TRIGGER_SCRIPT = '/home/serv/.openclaw/workspace/scripts/wyrd_telegram_trigger.sh'

WATCH_COUNTRIES = {'United States', 'China'}

# 精确白名单：只追踪主流市场会交易的宏观指标；不使用关键词模糊命中。
# 例：CPI Index / CPI n.s.a / Cleveland CPI / Jobless 4-week Avg / Fed speeches 等全部不追踪。
WATCH_EVENT_NAMES = {
    'United States': {
        'CPI', 'Core CPI',
        'PPI', 'Core PPI',
        'PCE Price Index', 'Core PCE Price Index',
        'Fed Interest Rate Decision', 'FOMC Economic Projections', 'FOMC Statement', 'FOMC Press Conference',
        'Nonfarm Payrolls', 'Unemployment Rate', 'Average Hourly Earnings', 'Initial Jobless Claims',
        'Retail Sales', 'Core Retail Sales',
        'Industrial Production', 'ISM Manufacturing PMI', 'ISM Non-Manufacturing PMI', 'ISM Services PMI',
        'GDP', 'GDP Price Index',
        'Trade Balance', 'Export Price Index', 'Import Price Index',
    },
    'China': {
        'CPI', 'PPI',
        'GDP', 'Industrial Production', 'Retail Sales',
        'NBS Manufacturing PMI', 'Non Manufacturing PMI', 'Caixin Manufacturing PMI', 'Caixin Services PMI',
        'Trade Balance', 'Exports', 'Imports',
        'M2 Money Stock', 'New Loans', 'Outstanding Loan Growth', 'Chinese Total Social Financing',
        'Loan Prime Rate 1Y', 'Loan Prime Rate 5Y',
    },
}

PRE_ALERT_MIN_HOURS = 20
PRE_ALERT_MAX_HOURS = 28
POST_GRACE_DAYS = 3
EARLY_ACTUAL_STALE_GRACE = timedelta(minutes=15)
COUNTRY_TIMEZONES = {
    # Nasdaq's economicevents API exposes the release clock as `gmt`, but for these
    # rows it is the source-market wall-clock time (e.g. US CPI 08:30 ET), not UTC.
    'United States': ZoneInfo('America/New_York'),
    'China': ZoneInfo('Asia/Shanghai'),
}


def log(msg: str) -> None:
    print(f'{LOG_PREFIX} {msg}')


def load_state() -> Dict:
    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            data.setdefault('pre_sent', {})
            data.setdefault('post_sent', {})  # legacy: treated as both raw+analysis sent
            data.setdefault('raw_sent', {})
            data.setdefault('analysis_sent', {})
            data.setdefault('stale_actual', {})
            return data
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f'failed to load state: {e}')
    return {'pre_sent': {}, 'post_sent': {}, 'raw_sent': {}, 'analysis_sent': {}, 'stale_actual': {}}


def save_state(state: Dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = f'{STATE_PATH}.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)


def clean_text(value: Optional[str]) -> str:
    if value is None:
        return ''
    value = html.unescape(str(value)).replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', value).strip()


def blank_value(value: Optional[str]) -> bool:
    v = clean_text(value)
    return not v or v in {'-', '--', '—', 'N/A'}


def fetch_calendar(day: datetime) -> List[Dict]:
    date_str = day.strftime('%Y-%m-%d')
    last_error = None
    for _ in range(3):
        try:
            resp = requests.get(
                NASDAQ_ECON_URL,
                params={'date': date_str},
                headers=REQUEST_HEADERS,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get('data', {}).get('rows', [])
            if isinstance(rows, list):
                for row in rows:
                    row['_calendar_date'] = date_str
                return rows
            return []
        except Exception as e:
            last_error = e
    log(f'failed to fetch calendar {date_str}: {last_error}')
    return []


def parse_event_dt_utc(row: Dict) -> Optional[datetime]:
    date_str = row.get('_calendar_date')
    gmt = clean_text(row.get('gmt'))
    if not date_str or not gmt or not re.match(r'^\d{1,2}:\d{2}$', gmt):
        return None
    try:
        hh, mm = map(int, gmt.split(':'))
        y, m, d = map(int, date_str.split('-'))
        country = clean_text(row.get('country'))
        tz = COUNTRY_TIMEZONES.get(country, timezone.utc)
        return datetime(y, m, d, hh, mm, tzinfo=tz).astimezone(timezone.utc)
    except Exception:
        return None


def event_key(row: Dict, event_dt: datetime) -> str:
    raw = '|'.join([
        clean_text(row.get('country')),
        clean_text(row.get('eventName')).lower(),
        event_dt.strftime('%Y-%m-%dT%H:%MZ'),
    ])
    digest = hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]
    return f'{event_dt.strftime("%Y%m%d%H%M")}-{digest}'


def category(event_name: str) -> str:
    n = event_name.lower()
    if any(k in n for k in ['cpi', 'consumer price', 'inflation']):
        return 'inflation_cpi'
    if any(k in n for k in ['ppi', 'producer price']):
        return 'inflation_ppi'
    if any(k in n for k in ['pce', 'deflator']):
        return 'inflation_pce'
    if any(k in n for k in ['fed', 'fomc', 'interest rate', 'rate decision', 'loan prime rate', 'lpr', 'reserve requirement']):
        return 'rates'
    if any(k in n for k in ['payroll', 'unemployment', 'jobless', 'hourly earnings']):
        return 'jobs'
    if any(k in n for k in ['retail sales', 'industrial production', 'pmi', 'ism', 'gdp']):
        return 'growth'
    if any(k in n for k in ['trade balance', 'exports', 'imports']):
        return 'trade'
    if any(k in n for k in ['yuan loans', 'new loans', 'outstanding loan growth', 'm2', 'credit', 'social financing']):
        return 'credit'
    return 'macro'


def watched(row: Dict) -> bool:
    country = clean_text(row.get('country'))
    name = clean_text(row.get('eventName'))
    return country in WATCH_EVENT_NAMES and name in WATCH_EVENT_NAMES[country]


def format_dt_hkt(dt_utc: datetime) -> str:
    return dt_utc.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M HKT')


def send_message(text: str) -> None:
    bot_token, chat_id = load_telegram_token(INFO_BOT_TOKEN_PATH)
    resp = requests.post(
        f'https://api.telegram.org/bot{bot_token}/sendMessage',
        data={
            'chat_id': chat_id,
            'text': text,
            'disable_web_page_preview': True,
        },
        **TELEGRAM_REQUEST_KWARGS,
    )
    resp.raise_for_status()


def build_pre_message(row: Dict, event_dt: datetime) -> str:
    country = clean_text(row.get('country'))
    name = clean_text(row.get('eventName'))
    consensus = clean_text(row.get('consensus')) or '未给出'
    previous = clean_text(row.get('previous')) or '未给出'
    return '\n'.join([
        '⏰ 宏观数据发布预警（提前约1天）',
        f'国家/地区: {country}',
        f'数据: {name}',
        f'发布时间: {format_dt_hkt(event_dt)}',
        f'市场预期: {consensus}',
        f'前值: {previous}',
        '发布后我会自动推送一次股票市场影响分析。',
    ])


def build_raw_data_message(row: Dict, event_dt: datetime) -> str:
    country = clean_text(row.get('country'))
    name = clean_text(row.get('eventName'))
    actual = clean_text(row.get('actual')) or '未公布'
    consensus = clean_text(row.get('consensus')) or '未给出'
    previous = clean_text(row.get('previous')) or '未给出'
    return '\n'.join([
        '📊 宏观数据已发布（原始数据）',
        f'国家/地区: {country}',
        f'数据: {name}',
        f'发布时间: {format_dt_hkt(event_dt)}',
        f'实际: {actual}',
        f'预期: {consensus}',
        f'前值: {previous}',
        'Wyrd 分析随后发送。',
    ])


def prune_state(state: Dict, now: datetime) -> None:
    cutoff = (now - timedelta(days=45)).strftime('%Y%m%d%H%M')
    for section in ('pre_sent', 'post_sent', 'raw_sent', 'analysis_sent', 'stale_actual'):
        items = state.get(section, {})
        state[section] = {k: v for k, v in items.items() if k[:12] >= cutoff}


def collect_rows(now: datetime) -> Iterable[Dict]:
    dates = set()
    for offset in range(-1, 3):
        dates.add((now + timedelta(days=offset)).strftime('%Y-%m-%d'))
    for date_str in sorted(dates):
        day = datetime.strptime(date_str, '%Y-%m-%d')
        for row in fetch_calendar(day):
            if watched(row):
                yield row


def release_group_name(rows: List[Dict]) -> str:
    names = {clean_text(r.get('eventName')) for r in rows}
    if names <= {'CPI', 'Core CPI'}:
        return 'CPI / Core CPI'
    if names <= {'PPI', 'Core PPI'}:
        return 'PPI / Core PPI'
    if names <= {'PCE Price Index', 'Core PCE Price Index'}:
        return 'PCE / Core PCE'
    return ' / '.join(sorted(names))


def group_category(row: Dict) -> str:
    return category(clean_text(row.get('eventName')))


def group_key(country: str, event_dt: datetime, rows: List[Dict]) -> str:
    raw = '|'.join([country, event_dt.strftime('%Y-%m-%dT%H:%MZ'), group_category(rows[0]), release_group_name(rows)])
    digest = hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12]
    return f'{event_dt.strftime("%Y%m%d%H%M")}-{digest}'


def collect_groups(now: datetime) -> List[Dict]:
    groups: Dict[Tuple[str, datetime, str], List[Dict]] = {}
    for row in collect_rows(now):
        event_dt = parse_event_dt_utc(row)
        if event_dt is None:
            continue
        country = clean_text(row.get('country'))
        key = (country, event_dt, group_category(row))
        groups.setdefault(key, []).append(row)

    result = []
    for (country, event_dt, _cat), rows in groups.items():
        rows = sorted(rows, key=lambda r: clean_text(r.get('eventName')))
        result.append({'country': country, 'event_dt': event_dt, 'rows': rows, 'key': group_key(country, event_dt, rows)})
    return sorted(result, key=lambda g: (g['event_dt'], g['country'], release_group_name(g['rows'])))


def format_china_credit_value(value: str) -> str:
    raw = clean_text(value)
    if not raw or raw == '未给出':
        return raw or '未给出'
    if re.fullmatch(r'[0-9,]+(?:\.\d+)?B', raw):
        return f'{raw} CNY'
    return raw


def display_value(row: Dict, field: str) -> str:
    value = clean_text(row.get(field))
    if not value:
        value = '未公布' if field == 'actual' else '未给出'
    country = clean_text(row.get('country'))
    name = clean_text(row.get('eventName'))
    if country == 'China' and name in {'Chinese Total Social Financing', 'New Loans'}:
        return format_china_credit_value(value)
    return value


def format_row_values(row: Dict) -> str:
    name = clean_text(row.get('eventName'))
    actual = display_value(row, 'actual')
    consensus = display_value(row, 'consensus')
    previous = display_value(row, 'previous')
    return f'{name}: 实际 {actual} / 预期 {consensus} / 前值 {previous}'


def build_pre_group_message(group: Dict) -> str:
    country = group['country']
    event_dt = group['event_dt']
    rows = group['rows']
    lines = [
        '⏰ 宏观数据发布预警（提前约1天）',
        f'国家/地区: {country}',
        f'数据: {release_group_name(rows)}',
        f'发布时间: {format_dt_hkt(event_dt)}',
    ]
    for row in rows:
        consensus = display_value(row, 'consensus')
        previous = display_value(row, 'previous')
        lines.append(f'• {clean_text(row.get("eventName"))}: 预期 {consensus} / 前值 {previous}')
    lines.append('发布后 daily news 会先发原始数据，随后 Wyrd 发市场影响分析。')
    return '\n'.join(lines)


def build_raw_group_message(group: Dict) -> str:
    lines = [
        '📊 宏观数据已发布（原始数据）',
        f'国家/地区: {group["country"]}',
        f'数据: {release_group_name(group["rows"])}',
        f'发布时间: {format_dt_hkt(group["event_dt"])}',
    ]
    lines.extend(f'• {format_row_values(row)}' for row in group['rows'])
    lines.append('Wyrd 分析随后发送。')
    return '\n'.join(lines)


def build_wyrd_group_prompt(group: Dict) -> str:
    values = '\n'.join(f'- {format_row_values(row)}' for row in group['rows'])
    return f'''你是 Wyrd，正在给 GenBill 发一条 Telegram 私聊。不要说“收到任务”，不要解释系统流程。

写法：专业财经分析师的快讯播报感；措辞克制、判断清晰、信息密度高。
开头示例：
“美国 CPI 数据刚公布：实际 x，预期 y，前值 z。该数据高于预期，短线核心影响是降息预期回落、美债收益率上行压力增加。”

内容要求：
- 先用一条新闻快讯式主句概括：数据 + 实际/预期/前值 + 超预期方向。
- 必须结合实时市场背景与国际形势生成判断：至少检查当下美股/港股/A股相关期货或指数、美债收益率、美元指数，以及近期主要政策/地缘/风险事件。
- 分析对股票市场影响：美股、A股/港股、利率/美元/风格方向；给出接下来该盯盘的确认信号。
- 可以指出相对受益/承压的风格或板块，但不要给确定性买卖指令。
- 不要使用固定模板结论，不要长篇宏观课，不要使用夸张情绪词。
- 120-220 字，最多 4 个短段落/要点。

原始数据：
国家/地区: {group['country']}
指标组: {release_group_name(group['rows'])}
发布时间: {format_dt_hkt(group['event_dt'])}
{values}

只输出最终要发送的正文。'''


def trigger_wyrd_group_analysis(group: Dict) -> None:
    prompt = build_wyrd_group_prompt(group)
    cmd = ['/bin/zsh', WYRD_TRIGGER_SCRIPT, prompt]
    env = os.environ.copy()
    env.setdefault('HOME', '/home/serv')
    subprocess.run(
        cmd,
        cwd='/home/serv/.openclaw/workspace',
        env=env,
        check=True,
        timeout=960,
    )


def main() -> int:
    now = datetime.now(timezone.utc)
    state = load_state()
    prune_state(state, now)

    pre_count = 0
    raw_count = 0
    analysis_count = 0
    for group in collect_groups(now):
        event_dt = group['event_dt']
        key = group['key']
        hours_until = (event_dt - now).total_seconds() / 3600

        legacy_pre_done = any(event_key(row, event_dt) in state.get('pre_sent', {}) for row in group['rows'])
        if PRE_ALERT_MIN_HOURS <= hours_until <= PRE_ALERT_MAX_HOURS and key not in state['pre_sent'] and not legacy_pre_done:
            send_message(build_pre_group_message(group))
            state['pre_sent'][key] = now.isoformat()
            pre_count += 1

        has_actual = any(not blank_value(row.get('actual')) for row in group['rows'])
        if has_actual and now < event_dt - EARLY_ACTUAL_STALE_GRACE:
            # Nasdaq sometimes carries already-published values on a future-dated row.
            # Mark it so it will not fire hours later as a fake "just released" alert.
            state['stale_actual'].setdefault(key, now.isoformat())

        post_ready = (
            event_dt <= now
            and now - event_dt <= timedelta(days=POST_GRACE_DAYS)
            and has_actual
            and key not in state.get('stale_actual', {})
        )
        legacy_post_done = (
            key in state.get('post_sent', {})
            or any(event_key(row, event_dt) in state.get('post_sent', {}) for row in group['rows'])
        )
        legacy_raw_done = any(event_key(row, event_dt) in state.get('raw_sent', {}) for row in group['rows'])
        legacy_analysis_done = any(event_key(row, event_dt) in state.get('analysis_sent', {}) for row in group['rows'])
        if post_ready and not legacy_post_done and not legacy_raw_done and key not in state['raw_sent']:
            send_message(build_raw_group_message(group))
            state['raw_sent'][key] = now.isoformat()
            raw_count += 1

        if post_ready and not legacy_post_done and not legacy_analysis_done and key not in state['analysis_sent']:
            trigger_wyrd_group_analysis(group)
            state['analysis_sent'][key] = now.isoformat()
            analysis_count += 1

    save_state(state)
    log(f'done pre={pre_count} raw={raw_count} wyrd_analysis={analysis_count}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
