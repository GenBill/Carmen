import requests
import json
from datetime import datetime
import math

EVENTS_URL = "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=100"

BLACKLIST_TAG_SLUGS = {
    'weather', 'sports', 'nba', 'nfl', 'mlb', 'nhl', 'soccer', 'football',
    'tennis', 'golf', 'ufc', 'mma', 'boxing', 'entertainment', 'movies',
    'tv', 'music', 'celebrity',
}

BLACKLIST_TITLE_KEYWORDS = {
    'gta', 'jesus', 'movie', 'oscar', 'grammy',
}


def get_popular_events():
    try:
        resp = requests.get(EVENTS_URL, timeout=15)
        return resp.json()
    except Exception:
        return []


if __name__ == "__main__":
    try:
        events = get_popular_events()
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
                question_lower = question_text.lower()
                if any(keyword in question_lower for keyword in BLACKLIST_TITLE_KEYWORDS):
                    continue
                if not m.get('active') or m.get('closed'):
                    continue

                prices_raw = m.get('outcomePrices', '["0", "1"]')
                prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                try:
                    prob = float(prices[0])
                except (IndexError, ValueError):
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
                if remaining_days <= 0:
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

        print("📊 *Polymarket 趋势监控 (工业蓝)*")
        print("_策略：热门度排序 (总资金 / 剩余天数)_")
        for m in processed_markets[:10]:
            print(f"\n🔹 *{m['question']}*")
            print(f"  • 胜率: `{m['prob']*100:.1f}%` (Yes)")
            print(f"  • 相对热度: `${m['relative_volume']/1000:.1f}k/day` (剩余 {math.ceil(m['days_left'])} 天)")
    except Exception as e:
        print(f"Monitor error: {e}")
