from datetime import datetime
from pathlib import Path
import json
from display_utils import capture_output

# 关注清单文件路径
ALERT_FILE = Path(__file__).parent / 'daily_watchlist.json'


def add_to_watchlist(symbol: str, action: str, score: list, stock_data: dict):
    """
    添加股票到当日关注清单
    
    Args:
        symbol: 股票代码
        action: 'BUY' 或 'SELL'
        score: [买入分数, 卖出分数]
        stock_data: 股票数据
    """
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 读取现有清单
    watchlist = {}
    if ALERT_FILE.exists():
        try:
            with open(ALERT_FILE, 'r', encoding='utf-8') as f:
                watchlist = json.load(f)
        except:
            watchlist = {}
    
    # 确保今日清单存在
    if today not in watchlist:
        watchlist[today] = {'buy': [], 'sell': []}
    
    # 准备记录
    record = {
        'symbol': symbol,
        'time': datetime.now().strftime('%H:%M:%S'),
        'price': stock_data.get('close', 0),
        'score': score,
        'rsi': stock_data.get('rsi'),
        'dif': stock_data.get('dif'),
        'dea': stock_data.get('dea'),
        'volume_ratio': round(stock_data.get('estimated_volume', 0) / stock_data.get('avg_volume', 1), 2) if stock_data.get('avg_volume') else 0
    }
    
    # 添加到对应列表（避免重复）
    target_list = watchlist[today]['buy'] if action == 'BUY' else watchlist[today]['sell']
    
    # 检查是否已存在
    existing = [item for item in target_list if item['symbol'] == symbol]
    if not existing:
        target_list.append(record)
        
        # 保存到文件
        with open(ALERT_FILE, 'w', encoding='utf-8') as f:
            json.dump(watchlist, f, indent=2, ensure_ascii=False)
        
        return True
    return False


def get_today_watchlist():
    """获取今日关注清单"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    if ALERT_FILE.exists():
        try:
            with open(ALERT_FILE, 'r', encoding='utf-8') as f:
                watchlist = json.load(f)
                return watchlist.get(today, {'buy': [], 'sell': []})
        except:
            pass
    
    return {'buy': [], 'sell': []}


def print_watchlist_summary():
    """打印今日关注清单摘要"""
    watchlist = get_today_watchlist()
    
    buy_count = len(watchlist['buy'])
    sell_count = len(watchlist['sell'])
    
    if buy_count > 0 or sell_count > 0:
        capture_output(f"\n📋 今日关注清单: {buy_count} 买入信号 | {sell_count} 卖出信号")
        
        if buy_count > 0:
            capture_output(f"  🟢 买入: {', '.join([item['symbol'] for item in watchlist['buy']])}")
        
        if sell_count > 0:
            capture_output(f"  🔴 卖出: {', '.join([item['symbol'] for item in watchlist['sell']])}")
        
        capture_output("")
