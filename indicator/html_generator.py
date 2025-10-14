"""
HTML报告生成器
将股票数据转换为美观的静态HTML页面
"""

import json
from datetime import datetime
from typing import List, Dict, Any
import hashlib


def calculate_content_hash(data: dict) -> str:
    """计算数据内容的哈希值，用于检测内容是否变化"""
    # 只对关键数据计算哈希，忽略时间戳
    key_data = {
        'stocks': data.get('stocks', []),
        'stats': data.get('stats', {}),
        'market_status': data.get('market_info', {}).get('status', '')
    }
    content_str = json.dumps(key_data, sort_keys=True)
    return hashlib.md5(content_str.encode()).hexdigest()


def generate_html_report(report_data: dict, output_file: str = 'docs/index.html') -> bool:
    """
    生成HTML报告
    
    Args:
        report_data: 包含股票数据、市场状态等信息的字典
        output_file: 输出HTML文件路径
        
    Returns:
        bool: 是否生成新内容（内容有变化）
    """
    import os
    
    # 检查文件是否存在
    file_exists = os.path.exists(output_file)
    
    if not file_exists:
        print(f"💡 HTML文件不存在，将强制生成: {output_file}")
    
    # 检查是否有内容变化
    new_hash = calculate_content_hash(report_data)
    
    if file_exists:
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if f'data-hash="{new_hash}"' in content:
                    return False  # 内容未变化，无需重新生成
        except Exception as e:
            print(f"⚠️ 读取旧HTML文件时出错: {e}")
            pass  # 读取失败，重新生成
    
    # 生成HTML内容
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta data-hash="{new_hash}">
    <title>Carmen Stock Scanner - 盘前/盘后股票扫描</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }}
        
        .header {{
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        
        .header h1 {{
            font-size: 2.5em;
            margin-bottom: 10px;
            font-weight: 700;
        }}
        
        .header .subtitle {{
            font-size: 1.1em;
            opacity: 0.9;
        }}
        
        .market-info {{
            background: #f8f9fa;
            padding: 20px 30px;
            border-bottom: 2px solid #e9ecef;
        }}
        
        .market-info-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
        }}
        
        .info-item {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        
        .info-label {{
            font-weight: 600;
            color: #495057;
        }}
        
        .info-value {{
            color: #212529;
        }}
        
        .status-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
        }}
        
        .status-premarket {{
            background: #fff3cd;
            color: #856404;
        }}
        
        .status-afterhours {{
            background: #d1ecf1;
            color: #0c5460;
        }}
        
        .status-open {{
            background: #d4edda;
            color: #155724;
        }}
        
        .stats-bar {{
            background: white;
            padding: 15px 30px;
            border-bottom: 2px solid #e9ecef;
            display: flex;
            justify-content: space-around;
            flex-wrap: wrap;
            gap: 20px;
        }}
        
        .stat-item {{
            text-align: center;
        }}
        
        .stat-value {{
            font-size: 1.8em;
            font-weight: 700;
            color: #2a5298;
        }}
        
        .stat-label {{
            font-size: 0.9em;
            color: #6c757d;
            margin-top: 5px;
        }}
        
        .table-container {{
            padding: 30px;
            overflow-x: auto;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.95em;
        }}
        
        thead {{
            background: #343a40;
            color: white;
        }}
        
        th {{
            padding: 15px 10px;
            text-align: left;
            font-weight: 600;
            position: sticky;
            top: 0;
            z-index: 10;
        }}
        
        tbody tr {{
            border-bottom: 1px solid #dee2e6;
            transition: background-color 0.2s;
        }}
        
        tbody tr:hover {{
            background-color: #f8f9fa;
        }}
        
        tbody tr.watchlist {{
            background-color: #fff3cd;
        }}
        
        tbody tr.watchlist:hover {{
            background-color: #ffeaa7;
        }}
        
        td {{
            padding: 12px 10px;
        }}
        
        .symbol {{
            font-weight: 700;
            font-size: 1.1em;
            color: #2a5298;
        }}
        
        .symbol.watchlist-symbol {{
            color: #856404;
        }}
        
        .symbol::before {{
            content: "⭐ ";
            display: none;
        }}
        
        .watchlist .symbol::before {{
            display: inline;
        }}
        
        .price-positive {{
            color: #28a745;
            font-weight: 600;
        }}
        
        .price-negative {{
            color: #dc3545;
            font-weight: 600;
        }}
        
        .rsi-arrow {{
            font-size: 1.2em;
        }}
        
        .signal-badge {{
            display: inline-block;
            padding: 6px 12px;
            border-radius: 6px;
            font-weight: 600;
            font-size: 0.85em;
        }}
        
        .signal-buy {{
            background: #d4edda;
            color: #155724;
        }}
        
        .signal-sell {{
            background: #f8d7da;
            color: #721c24;
        }}
        
        .footer {{
            background: #f8f9fa;
            padding: 20px 30px;
            text-align: center;
            color: #6c757d;
            font-size: 0.9em;
            border-top: 2px solid #e9ecef;
        }}
        
        .blacklist-summary {{
            background: #fff3cd;
            padding: 15px 30px;
            border-top: 2px solid #ffc107;
            color: #856404;
        }}
        
        @media (max-width: 768px) {{
            .header h1 {{
                font-size: 1.8em;
            }}
            
            .table-container {{
                padding: 15px;
            }}
            
            table {{
                font-size: 0.85em;
            }}
            
            th, td {{
                padding: 8px 5px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Carmen Stock Scanner</h1>
            <div class="subtitle">NASDAQ 盘前/盘后技术指标扫描</div>
        </div>
        
        <div class="market-info">
            <div class="market-info-grid">
                <div class="info-item">
                    <span class="info-label">市场状态:</span>
                    <span class="status-badge {report_data['market_info']['status_class']}">{report_data['market_info']['status']}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">更新时间:</span>
                    <span class="info-value">{report_data['market_info']['update_time']}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">扫描模式:</span>
                    <span class="info-value">{report_data['market_info']['mode']}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">技术指标:</span>
                    <span class="info-value">{report_data['market_info']['indicators']}</span>
                </div>
            </div>
        </div>
        
        <div class="stats-bar">
            <div class="stat-item">
                <div class="stat-value">{report_data['stats']['total_scanned']}</div>
                <div class="stat-label">扫描股票</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{report_data['stats']['success_count']}</div>
                <div class="stat-label">成功获取</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{report_data['stats']['signal_count']}</div>
                <div class="stat-label">交易信号</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">{report_data['stats']['blacklist_count']}</div>
                <div class="stat-label">黑名单过滤</div>
            </div>
        </div>
        
        <div class="table-container">
            <table>
                <thead>
                    <tr>
                        <th>股票代码</th>
                        <th>价格涨跌</th>
                        <th>量比</th>
                        <th>RSI (前→今)</th>
                        <th>MACD指标</th>
                        <th>交易信号</th>
                    </tr>
                </thead>
                <tbody>
"""
    
    # 添加股票数据行
    for stock in report_data['stocks']:
        row_class = 'watchlist' if stock.get('is_watchlist', False) else ''
        symbol_class = 'symbol watchlist-symbol' if stock.get('is_watchlist', False) else 'symbol'
        
        html_content += f"""                    <tr class="{row_class}">
                        <td class="{symbol_class}">{stock['symbol']}</td>
                        <td>{stock['price_change']}</td>
                        <td>{stock['volume_ratio']}</td>
                        <td>{stock['rsi']}</td>
                        <td>{stock['macd']}</td>
                        <td>{stock['signal']}</td>
                    </tr>
"""
    
    # 完成HTML
    html_content += f"""                </tbody>
            </table>
        </div>
        
        <div class="blacklist-summary">
            <strong>📋 黑名单摘要:</strong> {report_data['blacklist']['summary']}
        </div>
        
        <div class="footer">
            <p>自动生成于 {report_data['generation_time']}</p>
            <p>Powered by Carmen Stock Scanner | RSI{report_data['market_info']['rsi_period']} | MACD({report_data['market_info']['macd_params']})</p>
        </div>
    </div>
</body>
</html>
"""
    
    # 保存HTML文件
    os.makedirs(os.path.dirname(output_file) if os.path.dirname(output_file) else '.', exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # 生成meta信息文件用于追溯和debug
    save_meta_info(report_data, new_hash, output_file)
    
    return True  # 内容已更新


def save_meta_info(report_data: dict, content_hash: str, html_file: str):
    """
    保存meta信息文件用于追溯和debug
    
    Args:
        report_data: 报告数据
        content_hash: 内容哈希值
        html_file: HTML文件路径
    """
    import os
    from datetime import datetime
    
    # 确定meta文件路径（与HTML同目录）
    html_dir = os.path.dirname(html_file) if os.path.dirname(html_file) else '.'
    meta_file = os.path.join(html_dir, 'meta.json')
    
    # 构建meta信息
    meta_info = {
        'last_update': datetime.now().isoformat(),
        'last_update_readable': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'content_hash': content_hash,
        'html_file': html_file,
        'html_file_size': os.path.getsize(html_file) if os.path.exists(html_file) else 0,
        'market_status': report_data.get('market_info', {}).get('status', 'Unknown'),
        'update_time': report_data.get('market_info', {}).get('update_time', 'N/A'),
        'mode': report_data.get('market_info', {}).get('mode', 'N/A'),
        'stats': {
            'total_scanned': report_data.get('stats', {}).get('total_scanned', 0),
            'success_count': report_data.get('stats', {}).get('success_count', 0),
            'signal_count': report_data.get('stats', {}).get('signal_count', 0),
            'blacklist_count': report_data.get('stats', {}).get('blacklist_filtered', 0),
            'stocks_displayed': len(report_data.get('stocks', []))
        },
        'config': {
            'rsi_period': report_data.get('market_info', {}).get('rsi_period', 8),
            'macd_params': report_data.get('market_info', {}).get('macd_params', '8,17,9')
        }
    }
    
    # 如果meta文件已存在，读取历史记录
    history = []
    if os.path.exists(meta_file):
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                old_meta = json.load(f)
                history = old_meta.get('update_history', [])
        except Exception as e:
            print(f"⚠️ 读取旧meta文件失败: {e}")
    
    # 添加当前更新到历史记录（保留最近10条）
    history.append({
        'timestamp': meta_info['last_update'],
        'timestamp_readable': meta_info['last_update_readable'],
        'content_hash': content_hash,
        'market_status': meta_info['market_status'],
        'stocks_count': meta_info['stats']['stocks_displayed'],
        'signals': meta_info['stats']['signal_count']
    })
    
    # 只保留最近10条记录
    if len(history) > 10:
        history = history[-10:]
    
    meta_info['update_history'] = history
    meta_info['total_updates'] = len(history)
    
    # 保存meta文件
    try:
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(meta_info, f, ensure_ascii=False, indent=2)
        print(f"📝 Meta信息已保存: {meta_file}")
    except Exception as e:
        print(f"⚠️ 保存meta文件失败: {e}")


def format_price_change(price: float, change_pct: float) -> str:
    """格式化价格和涨跌幅"""
    sign = '+' if change_pct >= 0 else ''
    css_class = 'price-positive' if change_pct >= 0 else 'price-negative'
    return f'<span class="{css_class}">${price:.2f} {sign}{change_pct:.2f}%</span>'


def format_rsi(rsi_prev: float, rsi_current: float) -> str:
    """格式化RSI数据"""
    arrow = '↑' if rsi_current > rsi_prev else ('↓' if rsi_current < rsi_prev else '→')
    return f'RSI: {rsi_prev:.1f} <span class="rsi-arrow">{arrow}</span> {rsi_current:.1f}'


def format_macd(dif: float, dea: float, slope: float) -> str:
    """格式化MACD数据"""
    slope_sign = '+' if slope >= 0 else ''
    return f'DIF: {dif:6.2f} DEA: {dea:6.2f} 斜率: {slope_sign}{slope:.2f}'


def format_signal(score_buy: float, score_sell: float, backtest_str: str = '') -> str:
    """格式化交易信号"""
    signals = []
    
    if score_buy >= 3:
        signals.append(f'<span class="signal-badge signal-buy">Buy {score_buy:.1f}</span>')
    elif score_buy >= 2.4:
        signals.append(f'Buy {score_buy:.1f}')
    
    if score_sell >= 3:
        signals.append(f'<span class="signal-badge signal-sell">Sell {score_sell:.1f}</span>')
    elif score_sell >= 2.4:
        signals.append(f'Sell {score_sell:.1f}')
    
    if backtest_str:
        signals.append(backtest_str)
    
    return ' | '.join(signals) if signals else ''


def prepare_report_data(stocks_data: List[dict], market_info: dict, stats: dict, 
                        blacklist_info: dict, config: dict) -> dict:
    """
    准备报告数据
    
    Args:
        stocks_data: 股票数据列表，每个元素包含股票信息
        market_info: 市场状态信息
        stats: 统计信息
        blacklist_info: 黑名单信息
        config: 配置参数
        
    Returns:
        dict: 格式化后的报告数据
    """
    
    # 格式化股票数据
    formatted_stocks = []
    for stock in stocks_data:
        formatted_stocks.append({
            'symbol': stock['symbol'],
            'price_change': format_price_change(stock['price'], stock['change_pct']),
            'volume_ratio': f"量比: {stock['volume_ratio']:7.1f}%",
            'rsi': format_rsi(stock['rsi_prev'], stock['rsi_current']),
            'macd': format_macd(stock['dif'], stock['dea'], stock['macd_slope']),
            'signal': format_signal(stock.get('score_buy', 0), stock.get('score_sell', 0), 
                                   stock.get('backtest_str', '')),
            'is_watchlist': stock.get('is_watchlist', False)
        })
    
    # 确定市场状态样式
    status = market_info['status']
    if '盘前' in status:
        status_class = 'status-premarket'
    elif '盘后' in status:
        status_class = 'status-afterhours'
    else:
        status_class = 'status-open'
    
    return {
        'market_info': {
            'status': status,
            'status_class': status_class,
            'update_time': market_info['current_time'],
            'mode': market_info['mode'],
            'indicators': f"RSI{config['rsi_period']} | MACD({config['macd_fast']},{config['macd_slow']},{config['macd_signal']})",
            'rsi_period': config['rsi_period'],
            'macd_params': f"{config['macd_fast']},{config['macd_slow']},{config['macd_signal']}"
        },
        'stats': {
            'total_scanned': stats['total_scanned'],
            'success_count': stats['success_count'],
            'signal_count': stats['signal_count'],
            'blacklist_count': stats.get('blacklist_filtered', 0)
        },
        'stocks': formatted_stocks,
        'blacklist': {
            'summary': blacklist_info['summary']
        },
        'generation_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

