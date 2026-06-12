import requests
import json
from datetime import datetime
import math
import os
import re
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from agent.deepseek import DeepSeekAPI

EVENTS_URL = "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=100"
TOP_N = 5
MAX_REMAINING_DAYS = 30

BLACKLIST_TAG_SLUGS = {
    'weather', 'sports', 'nba', 'nfl', 'mlb', 'nhl', 'soccer', 'football',
    'tennis', 'golf', 'ufc', 'mma', 'boxing', 'entertainment', 'movies',
    'tv', 'music', 'celebrity',
}

BLACKLIST_TITLE_KEYWORDS = {
    'gta', 'jesus', 'movie', 'oscar', 'grammy',
}

ELECTION_KEYWORDS = {
    'election', 'electoral', 'presidential election', 'general election',
    'primary election', 'runoff election',
}

US_CONTEXT_KEYWORDS = {
    'united states', 'america', 'american',
}

US_CONTEXT_PATTERN = re.compile(r'(?<![a-z])(?:us|u\.s\.|u\.s\.a\.|usa)(?![a-z])', re.IGNORECASE)


def is_non_us_election_market(text):
    text_lower = text.lower()
    if not any(keyword in text_lower for keyword in ELECTION_KEYWORDS):
        return False
    return not (
        any(keyword in text_lower for keyword in US_CONTEXT_KEYWORDS)
        or US_CONTEXT_PATTERN.search(text)
    )


def get_popular_events():
    resp = requests.get(EVENTS_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError("Unexpected Polymarket response format")
    return data


def build_report(events):
    now = datetime.utcnow()
    processed_markets = []

    for event in events:
        event_tags = event.get('tags', [])
        event_tag_slugs = {
            str(tag.get('slug', '')).strip().lower()
            for tag in event_tags
            if isinstance(tag, dict) and tag.get('slug')
        }
        if event_tag_slugs & BLACKLIST_TAG_SLUGS:
            continue

        markets = event.get('markets', [])
        for m in markets:
            question_text = str(m.get('question', event.get('title', '')))
            market_context = f"{event.get('title', '')} {question_text}"
            question_lower = question_text.lower()
            if any(keyword in question_lower for keyword in BLACKLIST_TITLE_KEYWORDS):
                continue
            if is_non_us_election_market(market_context):
                continue
            if not m.get('active') or m.get('closed'):
                continue

            prices_raw = m.get('outcomePrices', '["0", "1"]')
            prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
            try:
                prob = float(prices[0])
            except (IndexError, ValueError, TypeError):
                continue

            if prob <= 0.05 or prob >= 0.95:
                continue

            end_date_str = m.get('endDate')
            if not end_date_str:
                continue
            try:
                end_date = datetime.strptime(end_date_str.split('.')[0].replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
                remaining_days = (end_date - now).days + (end_date - now).seconds / 86400.0
            except Exception:
                continue
            if remaining_days <= 0 or remaining_days > MAX_REMAINING_DAYS:
                continue

            volume = float(m.get('volume', 0))
            if volume <= 0:
                continue

            relative_volume = volume / remaining_days
            processed_markets.append({
                'question': m.get('question', event.get('title')),
                'prob': prob,
                'relative_volume': relative_volume,
                'volume': volume,
                'days_left': remaining_days,
            })

    processed_markets.sort(key=lambda x: x['relative_volume'], reverse=True)
    return processed_markets


def render_report(processed_markets):
    lines = [
        "📊 Polymarket 趋势监控",
        "策略：热门度排序（总资金 / 剩余天数）",
        f"筛选条件：Top{TOP_N}，剩余天数<{MAX_REMAINING_DAYS}",
    ]
    for m in processed_markets[:TOP_N]:
        lines.append(f"\n🔹 {m['question']}")
        lines.append(f"  • 胜率: {m['prob']*100:.1f}% (Yes)")
        lines.append(f"  • 相对热度: ${m['relative_volume']/1000:.1f}k/day (剩余 {math.ceil(m['days_left'])} 天)")
    return "\n".join(lines)


def translate_report_with_deepseek(report_text):
    prompt = f"""
请将下面的 Polymarket 趋势监控报告翻译成中文后直接输出。
要求：
- 保留 emoji、百分比、Top 数量、剩余天数等数字。
- 美元金额和单位必须原样保留，不要换算或本地化；例如 `$12.3k/day` 必须仍输出 `$12.3k/day`。
- 市场问题标题要译成自然、准确的中文，但专名处理遵循下面规则。
- 人名、机构名、公司/品牌名默认保留英文原文，不要音译成中文。
- 只保留专名英文，其他语义必须翻译成中文。
- 国家、地区、职位、事件类型等普通语义可以翻译成中文。
- 不要添加解释、免责声明或额外分析。

原文：
{report_text}
"""
    deepseek = DeepSeekAPI(
        token_path="/home/serv/Carmen/agent/deepseek.token",
        system_prompt="你是专业金融市场翻译助手，只输出中文译文正文。",
        model_type="deepseek-chat",
    )
    translated = deepseek(prompt, agent_mode=False, enable_debate=False)
    translated = (translated or "").strip()
    if not translated:
        raise RuntimeError("DeepSeek translation returned empty output")
    return translated


if __name__ == "__main__":
    try:
        events = get_popular_events()
        processed_markets = build_report(events)

        if not processed_markets:
            print("No qualified Polymarket markets after filtering.", file=sys.stderr)
            sys.exit(2)

        report = render_report(processed_markets)
        print(translate_report_with_deepseek(report))
    except Exception as e:
        print(f"Monitor error: {e}", file=sys.stderr)
        sys.exit(1)
