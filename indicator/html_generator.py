"""
HTML报告生成器
将股票数据转换为美观的静态HTML页面
"""

import json
from datetime import datetime
from typing import List, Dict, Any
import hashlib
import os
import html

def calculate_content_hash(data: dict) -> str:
    """
    计算数据内容的哈希值，用于检测内容是否变化
    
    只对股票数据本身计算哈希，忽略：
    - 时间戳
    - 市场状态消息（避免状态变化触发推送）
    - 终端输出
    """
    # 规范化股票数据，统一浮点数精度（避免精度差异）
    stocks = data.get('stocks', [])
    normalized_stocks = []
    for stock in stocks:
        # 只保留核心字段，并规范化数值精度到合理位数
        normalized_stock = {
            'symbol': stock.get('symbol', ''),
            'price': stock.get('price', 0), 
            'change_pct': stock.get('change_pct', 0), 
            'volume_ratio': stock.get('volume_ratio', 0), 
            'rsi_prev': stock.get('rsi_prev', 0), 
            'rsi_current': stock.get('rsi_current', 0), 
            'dif': stock.get('dif', 0), 
            'dea': stock.get('dea', 0), 
            'dif_dea_slope': stock.get('dif_dea_slope', 0), 
            'score_buy': stock.get('score_buy', 0), 
            'score_sell': stock.get('score_sell', 0), 
            'backtest_str': stock.get('backtest_str', ''), 
            'is_watchlist': stock.get('is_watchlist', False)
        }
        normalized_stocks.append(normalized_stock)
    
    # 只对股票数据和统计信息计算哈希，不包含市场状态
    key_data = {
        'stocks': normalized_stocks,
        'stats': data.get('stats', {})
    }
    content_str = json.dumps(key_data, sort_keys=True)
    return hashlib.md5(content_str.encode()).hexdigest()


def generate_html_report(report_data: dict, output_file: str = 'docs/index.html', market_type: str = 'US', is_hka_market: bool = None) -> bool:
    """
    生成HTML报告（纯文本终端风格）
    
    Args:
        report_data: 包含股票数据、市场状态等信息的字典
        output_file: 输出HTML文件路径
        market_type: 市场类型 ('US', 'HK', 'A', 'HKA')
        is_hka_market: (Deprecated) 兼容旧代码，如果为True则market_type='HKA'
        
    Returns:
        bool: 是否生成新内容（内容有变化）
    """
    
    # 兼容旧代码
    if is_hka_market is not None:
        market_type = 'HKA' if is_hka_market else 'US'
    
    # 检查文件是否存在
    file_exists = os.path.exists(output_file)
    
    # if not file_exists:
    #     print(f"💡 HTML文件不存在，将强制生成: {output_file}")
    
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
    
    # 获取上传时间
    upload_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    # 从report_data中获取缓存的终端输出
    terminal_output = report_data.get('terminal_output', '暂无输出')
    
    # 获取AI分析结果
    ai_analysis_results = report_data.get('ai_analysis_results', [])
    
    # HTML转义，但保留ANSI代码
    import html
    escaped_output = html.escape(terminal_output)
    
    # 生成HTML（使用ansi_up.js渲染ANSI颜色）
    
    # 确定页面标题
    titles = {
        'US': '美股监控',
        'HK': '港股监控',
        'A': 'A股监控',
        'HKA': '港A股监控'
    }
    page_title = titles.get(market_type, '股票监控')
    
    # 生成导航栏HTML
    # 定义导航链接
    nav_links = [
        {'type': 'US', 'text': '🇺🇸 美股', 'href': 'index.html'},
        {'type': 'HK', 'text': '🇭🇰 港股', 'href': 'index_hk.html'},
        {'type': 'A', 'text': '🇨🇳 A股', 'href': 'index_a.html'}
    ]
    
    nav_items_html = []
    for link in nav_links:
        # 只有当不是HKA模式，或者当前就是HKA模式时才显示HKA链接（避免混乱，或者全部显示）
        # 这里全部显示，方便跳转
        
        is_active = (link['type'] == market_type)
        bg_color = '#238636' if is_active else '#21262d'
        text_color = '#ffffff' if is_active else '#8b949e' # active时白色，inactive时灰色
        if is_active:
             # active link style
             style = f"color: #58a6ff; text-decoration: none; padding: 8px 16px; background: {bg_color}; border-radius: 4px;"
        else:
             style = f"color: {text_color}; text-decoration: none; padding: 8px 16px; background: {bg_color}; border-radius: 4px;"
             
        nav_items_html.append(f'<a href="{link["href"]}" style="{style}">{link["text"]}</a>')
    
    nav_html = f"""
        <nav style="background: #0d1117; padding: 10px 0; margin-bottom: 20px; border-bottom: 1px solid #30363d;">
            <div style="max-width: 1800px; margin: 0 auto; padding: 0 20px; display: flex; gap: 10px;">
                {''.join(nav_items_html)}
            </div>
        </nav>
        """
    
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta data-hash="{new_hash}">
    <title>Carmen Stock Scanner - {page_title}</title>
    <script src="https://cdn.jsdelivr.net/npm/ansi_up@5.2.1/ansi_up.min.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Courier New', Courier, Monaco, monospace;
            background: #0d1117;
            color: #c9d1d9;
            padding: 20px;
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1800px;
            margin: 0 auto;
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 20px;
        }}
        
        .header {{
            color: #58a6ff;
            border-bottom: 1px solid #30363d;
            padding-bottom: 10px;
            margin-bottom: 20px;
            font-weight: bold;
        }}
        
        #output {{
            white-space: pre;
            overflow-x: auto;
            font-family: inherit;
            margin: 0;
        }}
        
        .upload-time {{
            color: #8b949e;
            font-size: 0.9em;
            margin-top: 20px;
            padding-top: 10px;
            border-top: 1px solid #30363d;
            text-align: right;
        }}
        
        /* 滚动条样式 */
        ::-webkit-scrollbar {{
            height: 10px;
            width: 10px;
        }}
        
        ::-webkit-scrollbar-track {{
            background: #0d1117;
        }}
        
        ::-webkit-scrollbar-thumb {{
            background: #30363d;
            border-radius: 5px;
        }}
        
        ::-webkit-scrollbar-thumb:hover {{
            background: #484f58;
        }}
        
        /* AI分析结果样式 */
        .ai-analysis-section {{
            margin-top: 30px;
            border-top: 2px solid #30363d;
            padding-top: 20px;
        }}
        
        .ai-analysis-header {{
            color: #58a6ff;
            font-size: 1.2em;
            font-weight: bold;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
        }}
        
        .ai-analysis-header::before {{
            content: "🤖";
            margin-right: 8px;
        }}
        
        .ai-analysis-item {{
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            margin-bottom: 15px;
            overflow: hidden;
        }}
        
        .ai-analysis-header-item {{
            background: #161b22;
            padding: 12px 15px;
            border-bottom: 1px solid #30363d;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .ai-analysis-symbol {{
            color: #58a6ff;
            font-weight: bold;
            font-size: 1.1em;
        }}
        
        .ai-analysis-score {{
            background: #238636;
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.9em;
        }}
        
        .ai-analysis-content {{
            padding: 15px;
            white-space: pre-wrap;
            line-height: 1.6;
            max-height: 400px;
            overflow-y: auto;
        }}
        
        .ai-analysis-price {{
            color: #8b949e;
            font-size: 0.9em;
        }}
    </style>
</head>
<body>
    {nav_html}
    <div class="container">
        <div class="header">Carmen Stock Scanner - {page_title}</div>
        <pre id="output"></pre>
        
        <!-- AI分析结果部分 -->
        {generate_ai_analysis_html(ai_analysis_results)}
        
        <div class="upload-time">📤 上传时间: {upload_time}</div>
    </div>
    <script>
        // 使用ansi_up将ANSI颜色代码转换为HTML
        const ansi_up = new AnsiUp();
        const terminalOutput = `{escaped_output}`;
        const html = ansi_up.ansi_to_html(terminalOutput);
        document.getElementById('output').innerHTML = html;
    </script>
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
    
    # 确定meta文件路径（与HTML同目录）
    html_dir = os.path.dirname(html_file) if os.path.dirname(html_file) else '.'
    
    # 根据HTML文件名生成meta文件名
    # index.html -> meta.json
    # index_a.html -> meta_a.json
    # index_hk.html -> meta_hk.json
    # index_hka.html -> meta_hka.json
    basename = os.path.basename(html_file)
    if basename.startswith('index'):
        meta_basename = basename.replace('index', 'meta', 1).replace('.html', '.json')
    else:
        meta_basename = 'meta.json'
        
    meta_file = os.path.join(html_dir, meta_basename)
    
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
    
    # 保存meta文件
    try:
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(meta_info, f, ensure_ascii=False, indent=2)
        # print(f"📝 Meta信息已保存: {meta_file}")
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
    elif score_buy >= 2.0:
        signals.append(f'Buy {score_buy:.1f}')
    
    if score_sell >= 3:
        signals.append(f'<span class="signal-badge signal-sell">Sell {score_sell:.1f}</span>')
    elif score_sell >= 2.0:
        signals.append(f'Sell {score_sell:.1f}')
    
    if backtest_str:
        signals.append(backtest_str)
    
    return ' | '.join(signals) if signals else ''


def prepare_report_data(stocks_data: List[dict], market_info: dict, stats: dict, 
                        blacklist_info: dict, config: dict, terminal_output: str = '', 
                        ai_analysis_results: List[dict] = None) -> dict:
    """
    准备报告数据
    
    Args:
        stocks_data: 股票数据列表，每个元素包含股票信息
        market_info: 市场状态信息
        stats: 统计信息
        blacklist_info: 黑名单信息
        config: 配置参数
        terminal_output: 终端输出内容（包含ANSI颜色代码）
        
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
            'macd': format_macd(stock['dif'], stock['dea'], stock['dif_dea_slope']),
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
        'generation_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'terminal_output': terminal_output,
        'ai_analysis_results': ai_analysis_results or []
    }


def generate_ai_analysis_html(ai_analysis_results: List[dict]) -> str:
    """
    生成AI分析结果的HTML
    
    Args:
        ai_analysis_results: 由 analysis.ai_result_to_html_row / build_ai_analysis_results_for_html 组装的行列表
        
    Returns:
        str: HTML字符串
    """
    if not ai_analysis_results:
        return ""

    def _display_from_ai_result(row_symbol: str, ai_result: dict) -> str:
        if not ai_result or ai_result.get('symbol') != row_symbol:
            return '分析结果 symbol 校验失败，已拒绝展示。'
        st = ai_result.get('status') or ''
        if st == 'completed':
            text = (ai_result.get('summary_analysis') or ai_result.get('full_analysis') or ai_result.get('analysis') or '').strip()
            return text if text else '（completed 但正文为空）'
        if st == 'partial':
            base = (ai_result.get('summary_analysis') or ai_result.get('full_analysis') or '').strip()
            err = ai_result.get('error') or ''
            return (base + '\n\n' if base else '') + f'[partial] {err}'.strip()
        if st == 'pending':
            return 'AI 分析进行中或尚未写入缓存，请稍后刷新。'
        if st == 'failed':
            return f"分析失败: {ai_result.get('error', 'unknown')}"
        if st in ('skipped', 'missing'):
            return f"暂无有效分析: {ai_result.get('error', st)}"
        return ai_result.get('error') or '暂无分析内容'

    html_parts = ['<div class="ai-analysis-section">']
    html_parts.append('<div class="ai-analysis-header">AI深度分析报告</div>')

    for result in ai_analysis_results:
        symbol = result.get('symbol', 'Unknown')
        score_buy = result.get('score_buy', 0)
        price = result.get('price', 0)
        ai_result = result.get('ai_result')
        if ai_result is None and result.get('analysis') is not None:
            legacy = result.get('analysis')
            display = legacy if isinstance(legacy, str) else str(legacy)
        elif isinstance(ai_result, dict) and ai_result.get('symbol') != symbol:
            display = 'AI 结果包 symbol 与行不一致，已拒绝展示。'
        else:
            display = _display_from_ai_result(symbol, ai_result if isinstance(ai_result, dict) else {})

        escaped_analysis = html.escape(display)

        html_parts.append(f'''
        <div class="ai-analysis-item">
            <div class="ai-analysis-header-item">
                <div>
                    <span class="ai-analysis-symbol">{html.escape(str(symbol))}</span>
                    <span class="ai-analysis-price">当前价格: ${price:.2f}</span>
                </div>
                <span class="ai-analysis-score">买入评分: {score_buy:.1f}</span>
            </div>
            <div class="ai-analysis-content">{escaped_analysis}</div>
        </div>
        ''')

    html_parts.append('</div>')
    return ''.join(html_parts)

