"""
港股市场扫描主程序
专用于港股市场扫描，每天北京时间12:05、15:30和16:10运行
"""

import sys
import os
sys.path.append('..')
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import warnings
warnings.filterwarnings('ignore', message='.*gzip.*content-length.*')

from auto_proxy import setup_proxy_if_needed
setup_proxy_if_needed(7897)

from get_stock_price import get_stock_data, get_stock_data_offline, batch_download_stocks, enrich_stock_data_detail
from stocks_list.get_all_stock import get_stock_list, append_manual_exclude_symbols
from indicators import backtest_carmen_indicator
from scan_signal_eval import (
    confirm_rsi_pin_bar_after_5m,
    evaluate_scan_signals,
    evaluate_tuo_signals,
)
from sector_rotation import maybe_run_daily_sector_rotation_report, record_pre_candidate
from intraday_5m import fetch_5m_hist
import math
import hashlib
from bowl_filter import bowl_rebound_indicator
from display_utils import print_stock_info, print_header, get_output_buffer, capture_output, clear_output_buffer
from volume_filter import get_volume_filter, should_filter_stock
from html_generator import generate_html_report, prepare_report_data
from git_publisher import GitPublisher
from alert_system import add_to_watchlist, print_watchlist_summary
from qq_notifier import QQNotifier, load_qq_token
from telegram_notifier import TelegramNotifier, load_telegram_token
from scheduler import MarketScheduler
from concurrent.futures import ThreadPoolExecutor, as_completed
from async_ai import process_ai_task
from scan_ai_common import (
    OPEN_DROP_FILTER_PCT,
    MIN_POSITION_BUILD_SCORE,
    apply_duanxian_tuo_gate_metadata,
    build_scan_backtest_str,
    evaluate_duanxian_tuo_gates,
    is_buy_blocked_by_open_gap,
    resolve_opening_price_context_for_filter,
    scan_post_backtest_pipeline_active,
    should_submit_scan_ai,
    skip_gate_log_suffix,
)

import time
import pytz
from datetime import datetime
import sys
import traceback

FAST_SCAN_WORKERS = max(1, int(os.getenv("CARMEN_HK_FAST_SCAN_WORKERS", os.getenv("CARMEN_FAST_SCAN_WORKERS", "4")) or 4))
AI_FUTURE_TIMEOUT_SEC = float(os.getenv("CARMEN_AI_FUTURE_TIMEOUT_SEC", "180") or 180)

HK_RSI_REBOUND_THRESHOLD = 18.0
HK_RSI_REBOUND_TOP_N = 0
HK_RSI_PIN_BAR_ENABLED = False  # 港股不做 RSI+Pin Bar
HK_RSI_PIN_BAR_HOUR = 17  # 北京/香港时间 >= 17:00（启用时生效）
HK_RSI_REBOUND_LOOKBACK_DAYS = 126
HK_RSI_REBOUND_MIN_AVG_UP_PCT = 3.0
HK_RSI_REBOUND_MIN_AVG_DOWN_PCT = 1.5
HK_RSI_REBOUND_MIN_AVG_RANGE_PCT = 5.0
HK_RSI_REBOUND_MIN_UP_DOWN_RATIO = 0.75


def _hk_rsi_pin_bar_scan_allowed(now=None) -> bool:
    if not HK_RSI_PIN_BAR_ENABLED:
        return False
    tz = pytz.timezone("Asia/Hong_Kong")
    dt = now or datetime.now(tz)
    if dt.tzinfo is None:
        dt = tz.localize(dt)
    else:
        dt = dt.astimezone(tz)
    return dt.hour >= HK_RSI_PIN_BAR_HOUR


def _hk_rsi_elasticity_score(avg_up_pct, avg_down_pct, avg_range_pct, up_down_ratio) -> float:
    positive_bias = max(float(avg_up_pct) - float(avg_down_pct), 0.0)
    return (
        float(avg_up_pct) * 2.0
        + float(avg_range_pct)
        + min(float(up_down_ratio), 2.0) * 2.0
        + positive_bias
    )


def _hk_rsi_rebound_volatility_ok(stock_data: dict):
    info = {
        'lookback_days': HK_RSI_REBOUND_LOOKBACK_DAYS,
        'avg_up_pct': None,
        'avg_down_pct': None,
        'avg_range_pct': None,
        'up_down_ratio': None,
        'rebound_elasticity_score': None,
        'passed': False,
        'reason': '',
    }
    hist = (stock_data or {}).get('hist')
    required_cols = {'Open', 'High', 'Low'}
    if hist is None or getattr(hist, 'empty', True) or not required_cols.issubset(set(hist.columns)):
        info['reason'] = '无历史OHLC数据'
        return False, info['reason'], info
    window = hist.tail(HK_RSI_REBOUND_LOOKBACK_DAYS).copy()
    if len(window) < 40:
        info['reason'] = f'6个月波动样本不足({len(window)}/40)'
        return False, info['reason'], info
    open_ = window['Open'].astype(float)
    high = window['High'].astype(float)
    low = window['Low'].astype(float)
    valid = open_.gt(0) & high.gt(0) & low.gt(0)
    if int(valid.sum()) < 40:
        info['reason'] = f'有效OHLC样本不足({int(valid.sum())}/40)'
        return False, info['reason'], info
    open_, high, low = open_[valid], high[valid], low[valid]
    up_pct = ((high - open_) / open_ * 100.0).clip(lower=0)
    down_pct = ((open_ - low) / open_ * 100.0).clip(lower=0)
    avg_up_pct = float(up_pct.mean())
    avg_down_pct = float(down_pct.mean())
    avg_range_pct = avg_up_pct + avg_down_pct
    up_down_ratio = avg_up_pct / max(avg_down_pct, 1e-9)
    rebound_elasticity_score = _hk_rsi_elasticity_score(avg_up_pct, avg_down_pct, avg_range_pct, up_down_ratio)
    info.update({
        'avg_up_pct': avg_up_pct,
        'avg_down_pct': avg_down_pct,
        'avg_range_pct': avg_range_pct,
        'up_down_ratio': up_down_ratio,
        'rebound_elasticity_score': rebound_elasticity_score,
    })
    if avg_up_pct < HK_RSI_REBOUND_MIN_AVG_UP_PCT:
        info['reason'] = f'反弹弹性不足(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info
    if avg_down_pct < HK_RSI_REBOUND_MIN_AVG_DOWN_PCT:
        info['reason'] = f'波动不足(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info
    if avg_range_pct < HK_RSI_REBOUND_MIN_AVG_RANGE_PCT:
        info['reason'] = f'总振幅不足(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info
    if up_down_ratio < HK_RSI_REBOUND_MIN_UP_DOWN_RATIO:
        info['reason'] = f'单边下跌强、反弹弱(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info
    info['passed'] = True
    info['reason'] = (
        f'6个月弹性合格(评分={rebound_elasticity_score:.1f}, '
        f'平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%, 上下比={up_down_ratio:.2f})'
    )
    return True, info['reason'], info


def _confirm_hk_rsi_pin_bar(symbol: str, stock_data: dict):
    hist_5m = fetch_5m_hist(symbol, trade_date=stock_data.get('date'))
    if hist_5m is None or getattr(hist_5m, 'empty', True):
        return False, '5m拉取失败或为空', {}
    return confirm_rsi_pin_bar_after_5m(stock_data, hist_5m)


def _select_top_hk_rsi_candidates(candidates, limit: int = HK_RSI_REBOUND_TOP_N):
    if not candidates:
        return []
    ordered = sorted(
        candidates,
        key=lambda x: (
            float(x.get('rebound_elasticity_score') or 0.0),
            float((x.get('rsi_rebound_volatility') or {}).get('up_down_ratio') or 0.0),
        ),
        reverse=True,
    )
    if limit is None or int(limit) <= 0:
        return ordered
    return ordered[: int(limit)]


def _build_hk_signal_id(symbol: str, stock_data: dict, score_buy: float, kind: str = '') -> str:
    date = stock_data.get('date', 'unknown')
    close = stock_data.get('close', 0)
    base = f"{symbol}|{date}|{close:.2f}|{score_buy:.2f}|{kind}"
    digest = hashlib.md5(base.encode('utf-8')).hexdigest()[:8]
    tag = kind or 'buy'
    return f"sig_{tag}_{digest}"


def get_stock_list_from_csv(stock_path: str):
    """
    从CSV文件获取股票列表
    
    Args:
        stock_path: 股票列表CSV文件路径
        
    Returns:
        list: 股票代码列表
    """
    try:
        import pandas as pd
        df = pd.read_csv(stock_path)
        
        # 从Symbol列提取股票代码
        if 'Symbol' in df.columns:
            symbols = df['Symbol'].dropna().tolist()
            names = df['Name'].dropna().tolist() if 'Name' in df.columns else []
            return symbols, names
        else:
            print(f"⚠️ CSV文件中没有找到Symbol列")
            return [], []
    except Exception as e:
        print(f"⚠️ 读取股票列表失败: {e}")
        return [], []

def main_hk(stock_path: str = 'stocks_list/cache/china_screener_HK.csv', 
             rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, 
             avg_volume_days=8, enable_github_pages=True, github_branch='gh-pages',
             enable_qq_notify=False, qq_key='', qq_number='',
             enable_telegram_notify=False, telegram_bot_token='', telegram_chat_id=''):
    """
    港股市场扫描主函数
    
    Args:
        stock_path: 港股列表文件路径
        rsi_period: RSI 周期，默认 8
        macd_fast: MACD 快线周期，默认 8
        macd_slow: MACD 慢线周期，默认 17
        macd_signal: MACD 信号线周期，默认 9
        avg_volume_days: 平均成交量计算天数，默认 8
        enable_github_pages: 是否启用GitHub Pages自动推送，默认True
        github_branch: GitHub Pages分支名，默认gh-pages
        enable_qq_notify: 是否启用QQ推送，默认False
        qq_key: Qmsg酱的KEY，在Qmsg酱官网登录后，在控制台可以获取KEY
        qq_number: 接收消息的QQ号
        enable_telegram_notify: 是否启用Telegram推送，默认False（可替代QQ）
        telegram_bot_token: Telegram Bot API Token
        telegram_chat_id: 接收消息的 Chat ID
    """
    
    # 初始化Git推送器
    git_publisher = GitPublisher(gh_pages_dir=github_branch, force_push=True) if enable_github_pages else None
    
    # 初始化消息推送器：优先 Telegram，否则 QQ
    if enable_telegram_notify and telegram_bot_token and telegram_chat_id:
        bot_notifier = TelegramNotifier(bot_token=telegram_bot_token, chat_id=telegram_chat_id)
    elif enable_qq_notify and qq_key and qq_number:
        bot_notifier = QQNotifier(key=qq_key, qq=qq_number)
    else:
        bot_notifier = None
    
    # 初始化线程池（限制并发数，避免API速率限制）
    executor = ThreadPoolExecutor(max_workers=3)

    # 清空输出缓冲区
    clear_output_buffer()
    
    # 获取当前时间（北京/香港时间）
    beijing_tz = pytz.timezone('Asia/Shanghai')
    now_beijing = datetime.now(beijing_tz)
    current_time_str = now_beijing.strftime('%Y-%m-%d %H:%M:%S')
    
    # 获取港股列表
    stock_symbols, stock_names = get_stock_list_from_csv(stock_path)
    stock_symbols = [s.strip() for s in stock_symbols if s.strip()]
    hk_names_map = {}
    if stock_names and len(stock_names) == len(stock_symbols):
        hk_names_map = {
            str(sym).strip(): str(name).strip()
            for sym, name in zip(stock_symbols, stock_names)
            if sym and name
        }
    
    # 获取自选股列表（用于显示判断）
    watchlist_stocks = set(get_stock_list('my_stock_symbols_HKA.txt'))
    
    # 限制扫描数量
    max_stocks = 0  
    if len(stock_symbols) > max_stocks and max_stocks > 0:
        print(f"⚠️ 股票数量过多({len(stock_symbols)}只)，限制为前{max_stocks}只")
        stock_symbols = stock_symbols[:max_stocks]
    
    # 打印状态栏
    print(f"\n{'='*120}")
    capture_output(f"⏰ 港股市场扫描 | {current_time_str} CST")
    capture_output(f"查询 {len(stock_symbols)} 只股票 | RSI{rsi_period} | MACD({macd_fast},{macd_slow},{macd_signal}) | 港股市场")
    
    flush_output()
    
    # 打印表头
    print_header()
    flush_output()

    # 批量下载股票数据（多线程加速）
    batch_result = batch_download_stocks(
        stock_symbols, 
        use_cache=True, 
        cache_minutes=20,
        batch_size=50,
        period="1y"
    )
    missing_delisted = sorted(set(batch_result.get('missing_delisted', [])))
    if missing_delisted:
        added = append_manual_exclude_symbols(missing_delisted)
        if added:
            capture_output(f"🚫 已将 {added} 只疑似退市/无历史数据股票加入永久排除列表")
    flush_output()

    fast_scan_results = {}
    fast_scan_symbols = [s for s in stock_symbols if s and '.' in s]

    def load_fast_scan(symbol: str):
        data = get_stock_data_offline(
            symbol,
            rsi_period=rsi_period,
            macd_fast=macd_fast,
            macd_slow=macd_slow,
            macd_signal=macd_signal,
            avg_volume_days=avg_volume_days,
            use_cache=True,
            cache_minutes=20,
            fast_scan=True,
        )
        return symbol, data

    if fast_scan_symbols:
        workers = min(FAST_SCAN_WORKERS, len(fast_scan_symbols))
        with ThreadPoolExecutor(max_workers=workers) as scan_executor:
            futures = {scan_executor.submit(load_fast_scan, symbol): symbol for symbol in fast_scan_symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    result_symbol, data = future.result()
                    fast_scan_results[result_symbol] = data
                except Exception as e:
                    fast_scan_results[symbol] = None
                    print(f"⚠️  {symbol} fast_scan离线初筛失败: {e}")
    
    # 扫描股票
    alert_count = 0
    failed_count = 0
    stocks_data_for_html = []
    hk_rsi_pin_candidates = []

    for symbol in stock_symbols:
        try:
            # 跳过明显无法获取的数据
            if not symbol or '.' not in symbol:
                failed_count += 1
                continue
            
            stock_data = fast_scan_results.get(symbol)
            
            if stock_data:
                # 检查成交量过滤条件
                if should_filter_stock(symbol, stock_data):
                    failed_count += 1
                    continue
                
                rsi_track_on = _hk_rsi_pin_bar_scan_allowed()
                rsi_pin_bar_pre = False
                rsi_signal_active = False
                scan_state = evaluate_scan_signals(
                    stock_data,
                    rsi_threshold=HK_RSI_REBOUND_THRESHOLD if rsi_track_on else None,
                    volatility_ok_fn=_hk_rsi_rebound_volatility_ok if rsi_track_on else None,
                    silver_on_sell=False,
                    rsi_mode="pin_bar",
                    rsi_period=rsi_period,
                )
                score = scan_state.score
                rsi_pin_bar_pre = scan_state.rsi_pin_bar_pre
                rsi_signal_active = scan_state.rsi_signal_active
                carmen_candidate = scan_state.carmen_candidate
                tuo_signal_active = False
                pre_candidate = scan_state.pre_candidate
                if pre_candidate:
                    record_pre_candidate("HK", symbol, stock_data, scan_state, hk_names_map)
                # 碗口指标已临时停用，跳过计算以节省算力
                # bowl_score = bowl_rebound_indicator(stock_data)
                bowl_score = None
                if pre_candidate:
                    enriched = enrich_stock_data_detail(stock_data, avg_volume_days=avg_volume_days)
                    if not enriched:
                        full_stock_data = get_stock_data_offline(
                            symbol,
                            rsi_period=rsi_period,
                            macd_fast=macd_fast,
                            macd_slow=macd_slow,
                            macd_signal=macd_signal,
                            avg_volume_days=avg_volume_days,
                            use_cache=True,
                            cache_minutes=20,
                            fast_scan=False,
                        )
                        if full_stock_data:
                            stock_data = full_stock_data
                            scan_state = evaluate_scan_signals(
                                stock_data,
                                rsi_threshold=HK_RSI_REBOUND_THRESHOLD if rsi_track_on else None,
                                volatility_ok_fn=_hk_rsi_rebound_volatility_ok if rsi_track_on else None,
                                silver_on_sell=False,
                                rsi_mode="pin_bar",
                                rsi_period=rsi_period,
                            )
                            score = scan_state.score
                            rsi_pin_bar_pre = scan_state.rsi_pin_bar_pre
                            rsi_signal_active = scan_state.rsi_signal_active
                            carmen_candidate = scan_state.carmen_candidate
                            pre_candidate = scan_state.pre_candidate
                        else:
                            pre_candidate = False

                if pre_candidate:
                    tuo_state = evaluate_tuo_signals(stock_data, carmen_candidate=carmen_candidate)
                    tuo_signal_active = tuo_state.tuo_signal_active
                
                # 进行回测
                backtest_result = None
                backtest_str = ''
                confidence = 0.0
                if pre_candidate:
                    try:
                        backtest_result = backtest_carmen_indicator(
                            symbol, score, stock_data, 
                            gate=2.0, 
                            rsi_period=rsi_period, 
                            macd_fast=macd_fast, 
                            macd_slow=macd_slow, 
                            macd_signal=macd_signal, 
                            avg_volume_days=avg_volume_days
                        )
                        rsi_pipeline = bool(rsi_signal_active or rsi_pin_bar_pre)
                        if scan_post_backtest_pipeline_active(
                            backtest_result,
                            rsi_signal_active=rsi_pipeline,
                            tuo_signal_active=tuo_signal_active,
                            carmen_candidate=carmen_candidate,
                        ):
                            backtest_str, confidence = build_scan_backtest_str(
                                backtest_result,
                                rsi_signal_active=rsi_pipeline,
                                rsi_threshold=HK_RSI_REBOUND_THRESHOLD,
                                tuo_signal_active=tuo_signal_active,
                                duanxian_tuo_info=stock_data.get('duanxian_tuo_info'),
                                left_tuo_candidate=bool(stock_data.get('_duanxian_left_tuo_candidate')),
                            )

                            volume_ma_info = stock_data.get('volume_ma_info') or {}
                            duanxian_tuo_info = stock_data.get('duanxian_tuo_info') or {}
                            if rsi_pipeline:
                                signal_ok = True
                                submit_ai = True
                                position_build_score = float(volume_ma_info.get('position_build_score', 0) or 0)
                                has_recent_golden_cross = bool(volume_ma_info.get('has_recent_golden_cross', False))
                                gate_blocked = False
                            else:
                                submit_ai_vol, signal_ok, position_build_score, has_recent_golden_cross = (
                                    should_submit_scan_ai(
                                        score[0],
                                        confidence,
                                        volume_ma_info,
                                        duanxian_tuo_info,
                                        tuo_signal_active=tuo_signal_active,
                                    )
                                )
                                submit_ai = submit_ai_vol
                                gate_blocked = signal_ok and not submit_ai_vol

                            if submit_ai and not rsi_pipeline:
                                apply_duanxian_tuo_gate_metadata(
                                    stock_data,
                                    volume_ma_info,
                                    mark_imminent_pass=True,
                                )

                            opening_ctx = None
                            if submit_ai:
                                opening_ctx = resolve_opening_price_context_for_filter(symbol, stock_data)
                                price_chk = stock_data.get('close', 0)
                                if (
                                    not rsi_pipeline
                                    and opening_ctx.open_drop_filter_enabled
                                    and is_buy_blocked_by_open_gap(price_chk, opening_ctx.open_for_filter)
                                ):
                                    submit_ai = False
                                    print(
                                        f"⏭️  {symbol} 当前价较开盘价跌幅≥{OPEN_DROP_FILTER_PCT:g}%，跳过买入/后台分析"
                                    )

                            if submit_ai and opening_ctx is not None:
                                price = stock_data.get('close', 0)
                                rsi = stock_data.get('rsi')
                                estimated_volume = stock_data.get('estimated_volume', 0)
                                avg_volume = stock_data.get('avg_volume', 1)
                                volume_ratio = (estimated_volume / avg_volume * 100) if avg_volume > 0 else None

                                rsi_enqueued = False
                                if rsi_pin_bar_pre:
                                    pin_ok, pin_reason, shadow_info = _confirm_hk_rsi_pin_bar(symbol, stock_data)
                                    if pin_ok:
                                        rsi_signal_active = True
                                        _, _, rsi_vol = _hk_rsi_rebound_volatility_ok(stock_data)
                                        rebound_score = float((rsi_vol or {}).get('rebound_elasticity_score') or 0.0)
                                        pin_payload = {
                                            'symbol': symbol,
                                            'market': "HKA",
                                            'bot_notifier': bot_notifier,
                                            'price': price,
                                            'score': score[0],
                                            'backtest_str': f"(RSI{HK_RSI_REBOUND_THRESHOLD:g})",
                                            'rsi': rsi,
                                            'volume_ratio': volume_ratio,
                                            'bowl_score': bowl_score,
                                            'volume_ma_info': stock_data.get('volume_ma_info'),
                                            'duanxian_tuo_info': stock_data.get('duanxian_tuo_info'),
                                            'rsi_prev': stock_data.get('rsi_prev'),
                                            'dif': stock_data.get('dif'),
                                            'dea': stock_data.get('dea'),
                                            'dif_dea_slope': stock_data.get('dif_dea_slope'),
                                            'open_for_gap_filter': opening_ctx.open_for_filter,
                                            'opening_uncertain': opening_ctx.opening_uncertain,
                                            'open_gap_filter_enabled': opening_ctx.open_drop_filter_enabled,
                                            'signal_id': _build_hk_signal_id(symbol, stock_data, score[0], 'rsi_pin_bar'),
                                            'signal_title': "📉RSI超跌+Pin Bar",
                                            'rsi_rebound_volatility': rsi_vol,
                                        }
                                        stock_data['rebound_elasticity_score'] = rebound_score
                                        stock_data['rsi_rebound_volatility'] = rsi_vol
                                        stock_data['_rsi_pin_bar_shadow'] = shadow_info
                                        hk_rsi_pin_candidates.append({
                                            'symbol': symbol,
                                            'stock_data': stock_data,
                                            'ai_payload': pin_payload,
                                            'rebound_elasticity_score': rebound_score,
                                            'rsi_rebound_volatility': rsi_vol,
                                            'signal_label': 'HK RSI+PinBar',
                                        })
                                        print(f"🧺 {symbol} HK RSI+Pin Bar候选入队：{pin_reason}")
                                        rsi_enqueued = True
                                    else:
                                        print(f"⏭️  {symbol} HK RSI+Pin Bar未入候选池：{pin_reason}")

                                if (not rsi_pipeline) or (rsi_pipeline and not rsi_enqueued and not rsi_pin_bar_pre):
                                    print(f"🤖 {symbol} 触发信号，后台启动AI分析...")
                                    if not bot_notifier:
                                        print(f"ℹ️  {symbol} 未配置 Telegram/QQ：后台 AI 仍会继续生成缓存，但不发送推送")
                                    future = executor.submit(
                                        process_ai_task,
                                        symbol=symbol,
                                        market="HKA",
                                        bot_notifier=bot_notifier,
                                        price=price,
                                        score=score[0],
                                        backtest_str=backtest_str,
                                        rsi=rsi,
                                        volume_ratio=volume_ratio,
                                        bowl_score=bowl_score,
                                        volume_ma_info=stock_data.get('volume_ma_info'),
                                        duanxian_tuo_info=stock_data.get('duanxian_tuo_info'),
                                        duanxian_tuo_text=stock_data.get('_duanxian_tuo_display_text'),
                                        rsi_prev=stock_data.get('rsi_prev'),
                                        dif=stock_data.get('dif'),
                                        dea=stock_data.get('dea'),
                                        dif_dea_slope=stock_data.get('dif_dea_slope'),
                                        open_for_gap_filter=opening_ctx.open_for_filter,
                                        opening_uncertain=opening_ctx.opening_uncertain,
                                        open_gap_filter_enabled=opening_ctx.open_drop_filter_enabled,
                                    )
                                    stock_data['_ai_future'] = future

                            elif gate_blocked:
                                print(f"⏭️  {symbol} {skip_gate_log_suffix(position_build_score, has_recent_golden_cross, stock_data.get('duanxian_tuo_info'))}")
                            elif (symbol in watchlist_stocks) and score[1] >= 2.0:
                                # 按需求关闭自选股卖出信号推送：保留内部评分，但不发Telegram/QQ
                                pass
                    
                    except Exception as e:
                        print(f"⚠️  处理 {symbol} 回测时出错:")
                        traceback.print_exc()
                
                # 打印股票信息
                is_watchlist = symbol in watchlist_stocks
                print_success = print_stock_info(stock_data, score, is_watchlist, backtest_result, bowl_score=bowl_score)
                
                if not print_success:
                    failed_count += 1
                else:
                    # 统计信号 (无论盘中盘后都统计，以便CLI显示)
                    if score[0] >= 2.0 or rsi_signal_active or tuo_signal_active:
                        alert_count += 1
                    
                    if not pre_candidate:
                        flush_output()
                        continue

                    # 收集数据用于HTML生成
                    price = stock_data.get('close', 0)
                    open_price = stock_data.get('open', 0)
                    estimated_volume = stock_data.get('estimated_volume', 0)
                    avg_volume = stock_data.get('avg_volume', 1)
                    
                    change_pct = ((price - open_price) / open_price * 100) if open_price > 0 else 0
                    volume_ratio = (estimated_volume / avg_volume * 100) if avg_volume > 0 else 0
                    volume_ma_info = stock_data.get('volume_ma_info') or {}
                    duanxian_tuo_info = stock_data.get('duanxian_tuo_info') or {}
                    if not tuo_signal_active:
                        tuo_gates = evaluate_duanxian_tuo_gates(volume_ma_info, duanxian_tuo_info)
                        if volume_ma_info and not tuo_gates.secondary_gate_ok:
                            continue
                    op_ctx = resolve_opening_price_context_for_filter(symbol, stock_data)
                    if op_ctx.open_drop_filter_enabled and is_buy_blocked_by_open_gap(price, op_ctx.open_for_filter):
                        continue
                    
                    stocks_data_for_html.append({
                        'symbol': symbol,
                        'price': price,
                        'change_pct': change_pct,
                        'volume_ratio': volume_ratio,
                        'rsi_prev': stock_data.get('rsi_prev', 0),
                        'rsi_current': stock_data.get('rsi', 0),
                        'dif': stock_data.get('dif', 0),
                        'dea': stock_data.get('dea', 0),
                        'dif_dea_slope': stock_data.get('dif_dea_slope', 0),
                        'score_buy': score[0],
                        'score_sell': score[1],
                        'backtest_str': backtest_str,
                        'confidence': confidence,
                        'is_watchlist': False,
                        # 保存Future供后续获取结果
                        '_ai_future': stock_data.get('_ai_future'),
                        '_ai_result': None,
                        'volume_ma_info': volume_ma_info,
                        'duanxian_tuo_info': duanxian_tuo_info,
                    })
                
                flush_output()
            else:
                failed_count += 1
                
        except KeyboardInterrupt:
            print("\n\n⚠️  用户中断程序...")
            raise
        except Exception as e:
            failed_count += 1
            print(f"⚠️  处理 {symbol} 时出错: {e}")
            continue
    

    row_by_symbol = {row.get('symbol'): row for row in stocks_data_for_html}
    if hk_rsi_pin_candidates:
        selected = _select_top_hk_rsi_candidates(hk_rsi_pin_candidates, HK_RSI_REBOUND_TOP_N)
        selected_ids = {id(x) for x in selected}
        print(
            f"\n📊 HK RSI+Pin Bar 候选 {len(hk_rsi_pin_candidates)} 只，"
            f"{'全部播报' if HK_RSI_REBOUND_TOP_N <= 0 else f'按弹性评分选 Top{min(HK_RSI_REBOUND_TOP_N, len(selected))} 播报'}"
        )
        for item in selected:
            symbol = item.get('symbol')
            stock_data = item.get('stock_data') or {}
            payload = item.get('ai_payload') or {}
            print(f"🤖 {symbol} HK RSI+PinBar 候选，后台启动AI分析")
            if not bot_notifier:
                print(f"ℹ️  {symbol} 未配置 Telegram/QQ：后台 AI 仍会继续生成缓存，但不发送推送")
            future = executor.submit(process_ai_task, **payload)
            stock_data['_ai_future'] = future
            row = row_by_symbol.get(symbol)
            if row is not None:
                row['_ai_future'] = future
        for item in hk_rsi_pin_candidates:
            if id(item) in selected_ids:
                continue
            print(f"⏭️  {item.get('symbol')} HK RSI+PinBar 未入Top{HK_RSI_REBOUND_TOP_N}")

    # 打印分隔线
    capture_output(f"{'='*120}")
    
    # 显示统计
    success_count = len(stock_symbols) - failed_count
    capture_output(f"⚠️ 本轮查询: 成功 {success_count} | 失败 {failed_count}")
    capture_output(f"🔔 本次扫描发现 {alert_count} 个信号！")
    print_watchlist_summary()

    # 显示成交量过滤器状态
    volume_filter = get_volume_filter()
    blacklist_summary = volume_filter.get_blacklist_summary()
    capture_output(f"\n{blacklist_summary}")
    
    # 保存黑名单（如果有新增）
    volume_filter.save_blacklist()
    
    # 等待所有后台AI任务完成并回填数据
    pending_ai_stocks = [s for s in stocks_data_for_html if s.get('_ai_future')]
    if pending_ai_stocks:
        print(f"\n⏳ 等待 {len(pending_ai_stocks)} 个后台AI任务完成...")
        for stock in pending_ai_stocks:
            try:
                future = stock.get('_ai_future')
                symbol = stock['symbol']
                res = future.result(timeout=AI_FUTURE_TIMEOUT_SEC)
                if isinstance(res, dict) and res.get('symbol') == symbol:
                    stock['_ai_result'] = res
                    print(f"✅ {symbol} 后台AI分析完成 (status={res.get('status')})")
                else:
                    print(f"⚠️ {symbol} 异步AI结果symbol不匹配，丢弃结果")
                    stock['_ai_result'] = None
            except Exception as e:
                print(f"⚠️ 获取 {stock.get('symbol')} AI结果失败: {e}")
                stock['_ai_result'] = None

    # 关闭线程池
    executor.shutdown(wait=False, cancel_futures=True)

    try:
        maybe_run_daily_sector_rotation_report("HK", bot_notifier)
    except Exception as e:
        print(f"⚠️  港股板块轮动报告触发失败: {e}")
        traceback.print_exc()
    
    # 生成HTML报告并推送到GitHub Pages
    if git_publisher and stocks_data_for_html:
        try:
            terminal_output = get_output_buffer()
            
            # 筛选买入评分>=2.0 且 胜率>=0.5 的股票，复用已有的AI分析结果
            buy_signal_stocks = [
                stock for stock in stocks_data_for_html 
                if stock.get('score_buy', 0) >= 2.0 and stock.get('confidence', 0) >= 0.5
            ]
            ai_analysis_results = []
            
            if buy_signal_stocks:
                print(f"\n🔍 发现 {len(buy_signal_stocks)} 只买入信号股票，组装AI展示数据（仅缓存/任务结果）...")
                from analysis import build_ai_analysis_results_for_html

                ai_analysis_results = build_ai_analysis_results_for_html(buy_signal_stocks)
            
            # 准备报告数据
            report_data = prepare_report_data(
                stocks_data=stocks_data_for_html,
                market_info={
                    'status': '港股市场扫描',
                    'current_time': current_time_str,
                    'mode': '港股市场模式'
                },
                stats={
                    'total_scanned': len(stock_symbols),
                    'success_count': success_count,
                    'signal_count': alert_count,
                    'blacklist_filtered': 0
                },
                blacklist_info={
                    'summary': ''
                },
                config={
                    'rsi_period': rsi_period,
                    'macd_fast': macd_fast,
                    'macd_slow': macd_slow,
                    'macd_signal': macd_signal
                },
                terminal_output=terminal_output,
                ai_analysis_results=ai_analysis_results
            )
            
            # 生成HTML
            output_file = 'docs/index_hk.html'
            content_changed = generate_html_report(report_data, output_file, market_type="HK")
            
            if content_changed:
                if git_publisher.publish(): 
                    pages_url = git_publisher.get_pages_url()
                    if pages_url:
                        print(f"🌐 访问港股页面: {pages_url}index_hk.html")
                else: 
                    print("⚠️  推送失败，请检查Git配置")
            else:
                print("ℹ️  HTML内容无变化，跳过推送")
                
        except Exception as e:
            print(f"⚠️  生成HTML或推送时出错: {e}")
            traceback.print_exc()

def flush_output():
    """强制刷新所有输出缓冲区"""
    sys.stdout.flush()
    sys.stderr.flush()


if __name__ == "__main__":
    
    # 配置参数
    stock_pathHK = 'stocks_list/cache/china_screener_HK.csv'  # 港股列表文件路径
    
    # 技术指标参数（与美股保持一致）
    RSI_PERIOD = 8
    MACD_FAST = 8
    MACD_SLOW = 17
    MACD_SIGNAL = 9
    AVG_VOLUME_DAYS = 8
    
    # GitHub Pages 配置
    ENABLE_GITHUB_PAGES = True
    GITHUB_BRANCH = 'gh-pages'
    
    # 消息推送配置（二选一，Telegram 优先）
    ENABLE_QQ_NOTIFY = False
    ENABLE_TELEGRAM_NOTIFY = True
    try:
        TELEGRAM_TOKEN, TELEGRAM_CHAT_ID = load_telegram_token()
    except (FileNotFoundError, ValueError) as e:
        print(f"⚠️  无法加载Telegram token: {e}")
        print("⚠️  Telegram推送功能已禁用")
        ENABLE_TELEGRAM_NOTIFY = False
        TELEGRAM_TOKEN = ''
        TELEGRAM_CHAT_ID = ''
    try:
        QQ_KEY, QQ_NUMBER = load_qq_token()
    except (FileNotFoundError, ValueError) as e:
        QQ_KEY, QQ_NUMBER = '', ''
    
    # 初始化调度器
    # 港股运行节点: 12:05(午休), 15:30(收盘前30分钟), 16:10(收盘)
    scheduler = MarketScheduler(
        market='HK',
        run_nodes_cfg=[
            {'hour': 12, 'minute': 10},
            {'hour': 17, 'minute': 0},  # RSI+Pin Bar 窗口
        ]
    )

    while True:
        try:
            if scheduler.check_should_run():
                main_hk(
                    stock_path=stock_pathHK,
                    rsi_period=RSI_PERIOD,
                    macd_fast=MACD_FAST,
                    macd_slow=MACD_SLOW,
                    macd_signal=MACD_SIGNAL,
                    avg_volume_days=AVG_VOLUME_DAYS,
                    enable_github_pages=ENABLE_GITHUB_PAGES,
                    github_branch=GITHUB_BRANCH,
                    enable_qq_notify=ENABLE_QQ_NOTIFY,
                    qq_key=QQ_KEY,
                    qq_number=QQ_NUMBER,
                    enable_telegram_notify=ENABLE_TELEGRAM_NOTIFY,
                    telegram_bot_token=TELEGRAM_TOKEN,
                    telegram_chat_id=TELEGRAM_CHAT_ID
                )

        except KeyboardInterrupt:
            print("\n⚠️  终止运行")
            break
        except Exception as e:
            print(f'❌ 程序运行失败: {e}')
            traceback.print_exc()

        # 每 10 分钟检查一次
        time.sleep(600)
