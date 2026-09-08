"""Lightweight research/EPS summary for Carmen Telegram signals."""
import html
import json
import os
import re
import time
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup


RUNTIME_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'runtime')
CACHE_FILE = os.path.join(RUNTIME_DIR, 'research_summary_cache.json')
CACHE_TTL_SECONDS = 24 * 3600
REQUEST_TIMEOUT_SECONDS = 4


def _load_cache() -> Dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_cache(cache: Dict) -> None:
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    tmp_path = CACHE_FILE + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, CACHE_FILE)


def _clean_text(value: str) -> str:
    return re.sub(r'\s+', ' ', value or '').strip()


def _a_share_code(symbol: str) -> Optional[str]:
    value = str(symbol or '').upper().strip()
    code = value.split('.', 1)[0]
    return code if code.isdigit() and len(code) == 6 else None


def _parse_forecast_table(soup: BeautifulSoup, caption_keyword: str) -> Dict[str, Dict[str, str]]:
    for table in soup.select('table'):
        caption = table.find('caption')
        if not caption or caption_keyword not in _clean_text(caption.get_text(' ')):
            continue
        rows: Dict[str, Dict[str, str]] = {}
        for tr in table.select('tbody tr'):
            cells = [_clean_text(cell.get_text(' ')) for cell in tr.find_all(['th', 'td'])]
            if len(cells) >= 6 and re.fullmatch(r'20\d{2}', cells[0]):
                rows[cells[0]] = {
                    'count': cells[1],
                    'min': cells[2],
                    'avg': cells[3],
                    'max': cells[4],
                }
        return rows
    return {}


def _parse_latest_reports(soup: BeautifulSoup, limit: int = 2) -> List[str]:
    reports: List[str] = []
    for item in soup.select('#stockreport dl'):
        rating = _clean_text(item.select_one('.subtitle').get_text(' ') if item.select_one('.subtitle') else '').replace(' ', '')
        title = _clean_text(item.select_one('.title').get_text(' ') if item.select_one('.title') else '')
        date = _clean_text(item.select_one('.date').get_text(' ') if item.select_one('.date') else '')
        org = title.split('：', 1)[0] if '：' in title else ''
        short_title = title.split('：', 1)[1] if '：' in title else title
        if date or org or short_title:
            prefix = f"{date} {org}".strip()
            rating_text = f" {rating}" if rating else ''
            reports.append(f"{prefix}{rating_text}: {short_title}")
        if len(reports) >= limit:
            break
    return reports


def fetch_a_share_research_summary(symbol: str) -> Dict:
    code = _a_share_code(symbol)
    if not code:
        return {'status': 'unsupported'}

    url = f'https://basic.10jqka.com.cn/{code}/worth.html'
    response = requests.get(
        url,
        headers={'User-Agent': 'Mozilla/5.0'},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    text = response.content.decode('gbk', errors='ignore')
    soup = BeautifulSoup(text, 'html.parser')

    title = _clean_text(soup.title.get_text(' ') if soup.title else '')
    name_match = re.match(r'([^()（）]+)[(（]', title)
    stock_name = name_match.group(1) if name_match else code
    eps = _parse_forecast_table(soup, '预测年报每股收益')
    profit = _parse_forecast_table(soup, '预测年报净利润')
    reports = _parse_latest_reports(soup)
    if not eps and not profit and not reports:
        return {'status': 'empty', 'source': url}
    return {
        'status': 'ok',
        'code': code,
        'name': stock_name,
        'eps': eps,
        'profit': profit,
        'reports': reports,
        'source': url,
        'fetched_at': int(time.time()),
    }


def get_research_summary(symbol: str) -> Dict:
    code = _a_share_code(symbol)
    if not code:
        return {'status': 'unsupported'}
    cache_key = code
    now = int(time.time())
    cache = _load_cache()
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and now - int(cached.get('fetched_at') or 0) < CACHE_TTL_SECONDS:
        return cached
    try:
        data = fetch_a_share_research_summary(symbol)
    except Exception as e:
        if isinstance(cached, dict):
            stale = dict(cached)
            stale['status'] = 'stale'
            stale['error'] = str(e)
            return stale
        return {'status': 'error', 'error': str(e)}
    cache[cache_key] = data
    _save_cache(cache)
    return data


def format_research_summary_note(symbol: str, telegram_html: bool = False) -> str:
    data = get_research_summary(symbol)
    status = data.get('status')
    if status == 'unsupported':
        return '🧾 研报/EPS: 暂未内置该市场自动摘要；点“查研报”做联网深查。'
    if status == 'error':
        err = _clean_text(str(data.get('error') or '抓取失败'))[:80]
        return f'🧾 研报/EPS: 暂缺（{html.escape(err) if telegram_html else err}）；点“查研报”做联网深查。'
    if status == 'empty':
        return '🧾 研报/EPS: 未抓到可靠公开盈利预测；点“查研报”做联网深查。'

    label = '缓存' if status == 'stale' else '同花顺F10'
    lines = [f'🧾 研报/EPS（{label}）']
    name = data.get('name') or _a_share_code(symbol) or symbol
    lines.append(f'股票: {html.escape(str(name)) if telegram_html else name}')
    eps = data.get('eps') or {}
    profit = data.get('profit') or {}
    for year in ('2026', '2027', '2028'):
        e = eps.get(year) or {}
        p = profit.get(year) or {}
        if e or p:
            eps_text = f"EPS均 {e.get('avg', 'N/A')} [{e.get('min', 'N/A')},{e.get('max', 'N/A')}]"
            profit_text = f"净利均 {p.get('avg', 'N/A')}亿 [{p.get('min', 'N/A')},{p.get('max', 'N/A')}]"
            lines.append(f'- {year}E: {eps_text} | {profit_text}')
    reports = data.get('reports') or []
    if reports:
        lines.append('最新研报:')
        lines.extend(f'- {item.replace("买 入", "买入").replace("增 持", "增持")}' for item in reports[:2])
    source = data.get('source')
    if source:
        lines.append(f'来源: {source}')
    out = '\n'.join(lines)
    return html.escape(out) if telegram_html else out
