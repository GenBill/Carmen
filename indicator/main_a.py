"""
A股市场扫描主程序
专用于A股市场扫描，每天北京时间11:35、14:30和15:10运行
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
from stocks_list.get_all_stock import get_stock_list, append_manual_exclude_symbols, apply_manual_excludes
from indicators import backtest_carmen_indicator
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
    buy_signal_ok,
    apply_duanxian_tuo_gate_metadata,
    build_scan_backtest_str,
    evaluate_duanxian_tuo_gates,
    is_buy_blocked_by_open_gap,
    resolve_opening_price_context_for_filter,
    scan_buy_signal_ok,
    scan_post_backtest_pipeline_active,
    should_submit_scan_ai,
    skip_gate_log_suffix,
)
from stock_character_filter import evaluate_stock_character
from scan_signal_eval import (
    confirm_rsi_pin_bar_after_5m,
    evaluate_scan_signals,
    evaluate_tuo_signals,
)
from intraday_5m import fetch_5m_hist
from a_share_st_filter import is_st_or_delisting_name
from a_share_rebound_alert import (
    run_rebound_alert_scan,
)
from sector_rotation import maybe_run_daily_sector_rotation_report, record_pre_candidate
from agent.deepseek import fetch_a_share_turnover_rate

import time
import math
import pytz
from datetime import datetime
import sys
import traceback
from typing import Optional
import hashlib

# A 股：仅当东财/ak 返回「有效」换手率(%) 且 <= 本阈值时，关闭后台 AI/买入推送；不挡终端/列表打印
# 北京时间：10:00 前 2%，10:00–12:00 前 5%，下午盘 10%
A_SHARE_MIN_TURNOVER_PCT_EARLY_AM = 2.0
A_SHARE_MIN_TURNOVER_PCT_AM = 5.0
A_SHARE_MIN_TURNOVER_PCT_PM = 10.0
RSI_REBOUND_THRESHOLD = 18.0
RSI_REBOUND_LOOKBACK_DAYS = 126
RSI_REBOUND_MIN_AVG_UP_PCT = 3.0
RSI_REBOUND_MIN_AVG_DOWN_PCT = 1.5
RSI_REBOUND_MIN_AVG_RANGE_PCT = 5.0
RSI_REBOUND_MIN_UP_DOWN_RATIO = 0.75
RSI_REBOUND_TOP_N = 0  # A 股暂不做 RSI+Pin Bar；保留常量供日后启用
A_SHARE_RSI_BOTTOM_ALERTS_ENABLED = False  # A 股关闭 RSI+Pin Bar
A_SHARE_RSI_PIN_BAR_HOUR_BJ = 16  # 北京时间 >= 16:00 才跑 RSI+Pin Bar（启用时生效）

PERF_LOG_MODE = str(os.getenv("CARMEN_PERF_LOG", "")).strip().lower()
PERF_LOG_ENABLED = PERF_LOG_MODE in ("1", "true", "yes", "all", "debug")
PERF_LOG_ALL_STEPS = PERF_LOG_MODE in ("all", "debug")
PERF_SLOW_MS = float(os.getenv("CARMEN_PERF_SLOW_MS", "200") or 200)
A_FAST_SCAN_WORKERS = max(1, int(os.getenv("CARMEN_A_FAST_SCAN_WORKERS", os.getenv("CARMEN_FAST_SCAN_WORKERS", "4")) or 4))
AI_FUTURE_TIMEOUT_SEC = float(os.getenv("CARMEN_AI_FUTURE_TIMEOUT_SEC", "180") or 180)


def _perf_record(records, name: str, started_at: float) -> float:
    now = time.perf_counter()
    elapsed_ms = (now - started_at) * 1000.0
    records.append((name, elapsed_ms))
    if PERF_LOG_ENABLED and (PERF_LOG_ALL_STEPS or elapsed_ms >= PERF_SLOW_MS):
        print(f"⏱️  PERF step {name}: {elapsed_ms:.1f}ms")
    return now


def _perf_summary(symbol: str, records, started_at: float, status: str = "ok") -> None:
    if not PERF_LOG_ENABLED:
        return
    total_ms = (time.perf_counter() - started_at) * 1000.0
    slow_parts = [
        f"{name}={ms:.0f}ms"
        for name, ms in sorted(records, key=lambda x: x[1], reverse=True)[:6]
        if PERF_LOG_ALL_STEPS or ms >= PERF_SLOW_MS
    ]
    detail = " | " + ", ".join(slow_parts) if slow_parts else ""
    print(f"⏱️  PERF {symbol} total={total_ms:.0f}ms status={status}{detail}")


def _a_share_min_turnover_pct_now() -> float:
    tz = pytz.timezone("Asia/Shanghai")
    h = datetime.now(tz).hour
    if h < 10:
        return A_SHARE_MIN_TURNOVER_PCT_EARLY_AM
    if h < 12:
        return A_SHARE_MIN_TURNOVER_PCT_AM
    return A_SHARE_MIN_TURNOVER_PCT_PM


def _a_share_turnover_effective(raw) -> Optional[float]:
    """
    仅当东财/ak 成功给出有限浮点(0~100)换手率(%) 时用于过滤/拦截；
    None/NaN/越界/拉取失败 一律视为「未知」，不拦截、不挡打印。
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        import pandas as pd
        if pd.isna(raw):
            return None
    except Exception:
        pass
    try:
        x = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x < 0.0 or x > 100.0:
        return None
    return x


def _a_share_rsi_pin_bar_scan_allowed(now=None) -> bool:
    """A 股 RSI+Pin Bar 仅北京时间 >= 16:00。"""
    if not A_SHARE_RSI_BOTTOM_ALERTS_ENABLED:
        return False
    tz = pytz.timezone("Asia/Shanghai")
    dt = now or datetime.now(tz)
    if dt.tzinfo is None:
        dt = tz.localize(dt)
    else:
        dt = dt.astimezone(tz)
    return dt.hour >= A_SHARE_RSI_PIN_BAR_HOUR_BJ


def _is_rsi_oversold_candidate(stock_data: dict) -> bool:
    """A股 RSI+Pin Bar 已确认候选（含下影量门）。"""
    if not A_SHARE_RSI_BOTTOM_ALERTS_ENABLED:
        return False
    return bool((stock_data or {}).get('_rsi_pin_bar_setup'))


def _confirm_a_share_rsi_pin_bar(symbol: str, stock_data: dict) -> tuple[bool, str, dict]:
    hist_5m = fetch_5m_hist(symbol, trade_date=stock_data.get('date'))
    if hist_5m is None or getattr(hist_5m, 'empty', True):
        return False, '5m拉取失败或为空', {}
    return confirm_rsi_pin_bar_after_5m(stock_data, hist_5m)



def _rsi_rebound_volume(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or x <= 0:
        return None
    return x


def _rsi_rebound_elasticity_score(
    avg_up_pct: float,
    avg_down_pct: float,
    avg_range_pct: float,
    up_down_ratio: float,
) -> float:
    """正弹性评分：偏好反弹有力，且下跌侧不是唯一波动来源。"""
    positive_bias = max(float(avg_up_pct) - float(avg_down_pct), 0.0)
    return (
        float(avg_up_pct) * 2.0
        + float(avg_range_pct)
        + min(float(up_down_ratio), 2.0) * 2.0
        + positive_bias
    )


def _select_top_rsi_rebound_candidates(candidates, limit: int = RSI_REBOUND_TOP_N):
    """按弹性评分选出本轮 RSI 抄底；limit<=0 表示全部播报。"""
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


def _rsi_candidate_volatility_info(stock_data: dict) -> dict:
    rsi_vol = (
        (stock_data or {}).get('rsi_rebound_volatility')
        or (stock_data or {}).get('_rsi_rebound_volatility')
    )
    if isinstance(rsi_vol, dict) and rsi_vol.get('rebound_elasticity_score') is not None:
        return rsi_vol

    _, _, rsi_vol = _rsi_rebound_volatility_ok(stock_data)
    if rsi_vol:
        stock_data['_rsi_rebound_volatility'] = rsi_vol
    return rsi_vol or {}


def _format_rsi_candidate_elasticity(item: dict) -> str:
    rsi_vol = item.get('rsi_rebound_volatility') or {}
    return (
        f"弹性评分={float(item.get('rebound_elasticity_score') or 0):.1f}，"
        f"6个月平均+{float(rsi_vol.get('avg_up_pct') or 0):.1f}%/"
        f"-{float(rsi_vol.get('avg_down_pct') or 0):.1f}%，"
        f"上下比={float(rsi_vol.get('up_down_ratio') or 0):.2f}"
    )


def _should_submit_regular_ai_after_rsi_queue(rsi_signal_active: bool, rsi_enqueued: bool) -> bool:
    return (not rsi_signal_active) and (not rsi_enqueued)


def _rsi_rebound_volatility_ok(stock_data: dict) -> tuple[bool, str, dict]:
    """RSI 抢反弹要求过去 6 个月涨跌两侧都有足够弹性，且反弹侧不能明显弱于下跌侧。"""
    info = {
        'lookback_days': RSI_REBOUND_LOOKBACK_DAYS,
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

    window = hist.tail(RSI_REBOUND_LOOKBACK_DAYS).copy()
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

    open_ = open_[valid]
    high = high[valid]
    low = low[valid]
    up_pct = ((high - open_) / open_ * 100.0).clip(lower=0)
    down_pct = ((open_ - low) / open_ * 100.0).clip(lower=0)
    avg_up_pct = float(up_pct.mean())
    avg_down_pct = float(down_pct.mean())
    avg_range_pct = avg_up_pct + avg_down_pct
    up_down_ratio = avg_up_pct / max(avg_down_pct, 1e-9)
    rebound_elasticity_score = _rsi_rebound_elasticity_score(
        avg_up_pct,
        avg_down_pct,
        avg_range_pct,
        up_down_ratio,
    )
    info.update({
        'avg_up_pct': avg_up_pct,
        'avg_down_pct': avg_down_pct,
        'avg_range_pct': avg_range_pct,
        'up_down_ratio': up_down_ratio,
        'rebound_elasticity_score': rebound_elasticity_score,
    })

    if avg_up_pct < RSI_REBOUND_MIN_AVG_UP_PCT:
        info['reason'] = f'反弹弹性不足(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info
    if avg_down_pct < RSI_REBOUND_MIN_AVG_DOWN_PCT:
        info['reason'] = f'波动不足(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info
    if avg_range_pct < RSI_REBOUND_MIN_AVG_RANGE_PCT:
        info['reason'] = f'总振幅不足(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info
    if up_down_ratio < RSI_REBOUND_MIN_UP_DOWN_RATIO:
        info['reason'] = f'单边下跌强、反弹弱(平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%)'
        return False, info['reason'], info

    info['passed'] = True
    info['reason'] = (
        f'6个月弹性合格(评分={rebound_elasticity_score:.1f}, '
        f'平均+{avg_up_pct:.2f}%/-{avg_down_pct:.2f}%, 上下比={up_down_ratio:.2f})'
    )
    return True, info['reason'], info

def _a_share_scan_signal_ok(
    score_buy: float,
    confidence: float,
    rsi_signal_active: bool,
    tuo_signal_active: bool = False,
) -> bool:
    return scan_buy_signal_ok(
        score_buy,
        confidence,
        tuo_signal_active=tuo_signal_active,
    )


def _a_share_should_submit_scan_ai(
    score_buy: float,
    confidence: float,
    volume_ma_info: Optional[dict],
    duanxian_tuo_info: Optional[dict],
    rsi_signal_active: bool,
    tuo_signal_active: bool = False,
):
    """
    A 股常规 Carmen 买入链路闸门；RSI+Pin Bar 在调用方单独放行。
    Returns:
        (submit_background_ai, signal_ok, position_build_score, has_recent_golden_cross)
    """
    submit_ai, signal_ok, position_build_score, has_recent_golden_cross = should_submit_scan_ai(
        score_buy,
        confidence,
        volume_ma_info,
        duanxian_tuo_info,
        tuo_signal_active=tuo_signal_active,
    )
    return submit_ai, signal_ok, position_build_score, has_recent_golden_cross


def get_stock_list_from_csv(stock_path: str):
    """
    从CSV文件获取股票列表
    
    Args:
        stock_path: 股票列表CSV文件路径
        
    Returns:
        tuple: (股票代码列表, symbol -> 中文名称)
    """
    try:
        import pandas as pd
        df = pd.read_csv(stock_path)
        
        # 从Symbol列提取股票代码
        if 'Symbol' in df.columns:
            if 'Name' in df.columns:
                st_mask = df['Name'].apply(is_st_or_delisting_name)
                removed = int(st_mask.sum())
                if removed > 0:
                    df = df[~st_mask].copy()
                    print(f"🚫 已过滤 ST/退市风险股票 {removed} 只")
            symbol_to_name = {}
            if 'Name' in df.columns:
                for _, row in df.iterrows():
                    sym = row['Symbol']
                    if pd.isna(sym):
                        continue
                    sk = str(sym).strip()
                    nv = row['Name']
                    if pd.notna(nv) and str(nv).strip():
                        symbol_to_name[sk] = str(nv).strip()
            symbols = [str(x).strip() for x in df['Symbol'].dropna().tolist()]
            return symbols, symbol_to_name
        else:
            print(f"⚠️ CSV文件中没有找到Symbol列")
            return [], {}
    except Exception as e:
        print(f"⚠️ 读取股票列表失败: {e}")
        return [], {}

def _build_signal_id(symbol: str, stock_data: dict, score_buy: float, kind: str = '') -> str:
    date = stock_data.get('date', 'unknown')
    close = stock_data.get('close', 0)
    base = f"{symbol}|{date}|{close:.2f}|{score_buy:.2f}|{kind}"
    digest = hashlib.md5(base.encode('utf-8')).hexdigest()[:8]
    tag = kind or 'buy'
    return f"{symbol}|{date}|{tag}|{digest}"


def main_a(stock_path: str = 'stocks_list/cache/china_screener_A.csv', 
             rsi_period=8, macd_fast=8, macd_slow=17, macd_signal=9, 
             avg_volume_days=8, enable_github_pages=True, github_branch='gh-pages',
             enable_qq_notify=False, qq_key='', qq_number='',
             enable_telegram_notify=False, telegram_bot_token='', telegram_chat_id=''):
    """
    A股市场扫描主函数
    
    Args:
        stock_path: A股列表文件路径
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
        try:
            replayed = bot_notifier.flush_pending_queue()
            if replayed > 0:
                print(f"🔁 启动时补发 Telegram 待发送消息 {replayed} 条")
        except Exception as e:
            print(f"⚠️  启动补发 Telegram 待发送消息失败: {e}")
    elif enable_qq_notify and qq_key and qq_number:
        bot_notifier = QQNotifier(key=qq_key, qq=qq_number)
    else:
        bot_notifier = None
    
    # 初始化线程池（限制并发数，避免API速率限制）
    executor = ThreadPoolExecutor(max_workers=3)
    
    # 清空输出缓冲区
    clear_output_buffer()
    
    # 获取当前时间（北京时间）
    beijing_tz = pytz.timezone('Asia/Shanghai')
    now_beijing = datetime.now(beijing_tz)
    current_time_str = now_beijing.strftime('%Y-%m-%d %H:%M:%S')
    
    # 获取A股列表
    stock_symbols, a_share_names_map = get_stock_list_from_csv(stock_path)
    stock_symbols = [s.strip() for s in stock_symbols if s.strip()]
    stock_symbols = apply_manual_excludes(stock_symbols)
    if a_share_names_map:
        stock_symbol_set = set(stock_symbols)
        a_share_names_map = {
            symbol: name
            for symbol, name in a_share_names_map.items()
            if symbol in stock_symbol_set
        }
    
    # 获取自选股列表（用于显示判断）
    # 注意：这里我们仍然可以加载HKA的自选股，或者新建一个A股自选列表。暂时复用HKA。
    watchlist_stocks = set(get_stock_list('my_stock_symbols_HKA.txt'))
    
    # 限制扫描数量
    max_stocks = 0  
    if len(stock_symbols) > max_stocks and max_stocks > 0:
        print(f"⚠️ 股票数量过多({len(stock_symbols)}只)，限制为前{max_stocks}只")
        stock_symbols = stock_symbols[:max_stocks]
    
    # 打印状态栏
    print(f"\n{'='*120}")
    capture_output(f"⏰ A股市场扫描 | {current_time_str} CST")
    capture_output(f"查询 {len(stock_symbols)} 只股票 | RSI{rsi_period} | MACD({macd_fast},{macd_slow},{macd_signal}) | A股市场")
    
    flush_output()
    
    # 打印表头
    print_header()
    flush_output()

    # 批量下载股票数据（多线程加速）
    perf_batch_started = time.perf_counter()
    batch_result = batch_download_stocks(
        stock_symbols, 
        use_cache=True, 
        cache_minutes=5,
        batch_size=50,
        period="1y"
    )
    missing_delisted = sorted(set(batch_result.get('missing_delisted', [])))
    if missing_delisted:
        added = append_manual_exclude_symbols(missing_delisted)
        if added:
            capture_output(f"🚫 已将 {added} 只疑似退市/无历史数据股票加入永久排除列表")
    flush_output()
    if PERF_LOG_ENABLED:
        print(f"⏱️  PERF batch_download total={(time.perf_counter() - perf_batch_started) * 1000.0:.0f}ms symbols={len(stock_symbols)}")

    fast_scan_results = {}
    fast_scan_timings = {}
    fast_scan_started = time.perf_counter()
    fast_scan_symbols = [s for s in stock_symbols if s and '.' in s]

    def load_fast_scan(symbol: str):
        started = time.perf_counter()
        data = get_stock_data_offline(
            symbol,
            rsi_period=rsi_period,
            macd_fast=macd_fast,
            macd_slow=macd_slow,
            macd_signal=macd_signal,
            avg_volume_days=avg_volume_days,
            use_cache=True,
            cache_minutes=5,
            fast_scan=True,
        )
        return symbol, data, (time.perf_counter() - started) * 1000.0

    if fast_scan_symbols:
        workers = min(A_FAST_SCAN_WORKERS, len(fast_scan_symbols))
        if PERF_LOG_ENABLED:
            print(f"⏱️  PERF fast_scan preload start workers={workers} symbols={len(fast_scan_symbols)}")
        with ThreadPoolExecutor(max_workers=workers) as scan_executor:
            futures = {scan_executor.submit(load_fast_scan, symbol): symbol for symbol in fast_scan_symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    result_symbol, data, elapsed_ms = future.result()
                    fast_scan_results[result_symbol] = data
                    fast_scan_timings[result_symbol] = elapsed_ms
                except Exception as e:
                    fast_scan_results[symbol] = None
                    fast_scan_timings[symbol] = 0.0
                    print(f"⚠️  {symbol} fast_scan离线初筛失败: {e}")
        if PERF_LOG_ENABLED:
            print(
                f"⏱️  PERF fast_scan preload total={(time.perf_counter() - fast_scan_started) * 1000.0:.0f}ms "
                f"workers={workers} symbols={len(fast_scan_symbols)}"
            )
    
    # 扫描股票
    alert_count = 0
    failed_count = 0
    stocks_data_for_html = []
    rsi_rebound_candidates = []
    rsi_oversold_candidates = []

    for symbol in stock_symbols:
        symbol_perf_started = time.perf_counter()
        symbol_perf_records = []
        symbol_perf_mark = symbol_perf_started
        try:
            # 跳过明显无法获取的数据
            if not symbol or '.' not in symbol:
                failed_count += 1
                _perf_summary(symbol or '<empty>', symbol_perf_records, symbol_perf_started, 'invalid_symbol')
                continue
            
            stock_data = fast_scan_results.get(symbol)
            symbol_perf_records.append(('fast_scan_preload', fast_scan_timings.get(symbol, 0.0)))
            symbol_perf_mark = _perf_record(symbol_perf_records, 'load_fast_result', symbol_perf_mark)
            
            if stock_data:
                # 检查成交量过滤条件
                if should_filter_stock(symbol, stock_data):
                    failed_count += 1
                    symbol_perf_mark = _perf_record(symbol_perf_records, 'volume_filter', symbol_perf_mark)
                    _perf_summary(symbol, symbol_perf_records, symbol_perf_started, 'filtered_low_volume')
                    continue
                symbol_perf_mark = _perf_record(symbol_perf_records, 'volume_filter', symbol_perf_mark)

                # 每只股票独立初始化，避免沿用上一只股票的状态
                turnover_rate = None
                turnover_warning = None
                signal_ok = False
                position_build_score = 0
                has_recent_golden_cross = False
                gate_blocked = False
                ai_launched = False
                stock_character_info = None
                turnover_blocked = False
                rsi_pin_bar_pre = False
                rsi_oversold_today = False
                rsi_rebound_setup = False
                rsi_signal_active = False

                def get_stock_character_info():
                    nonlocal stock_character_info
                    if stock_character_info is None:
                        stock_character_info = stock_data.get('stock_character_info')
                    if stock_character_info is None:
                        stock_character_started = time.perf_counter()
                        stock_character_info = evaluate_stock_character(stock_data)
                        _perf_record(symbol_perf_records, 'stock_character', stock_character_started)
                        stock_data['stock_character_info'] = stock_character_info
                    return stock_character_info
                
                rsi_track_on = _a_share_rsi_pin_bar_scan_allowed()
                scan_state = evaluate_scan_signals(
                    stock_data,
                    rsi_threshold=RSI_REBOUND_THRESHOLD if rsi_track_on else None,
                    volatility_ok_fn=_rsi_rebound_volatility_ok if rsi_track_on else None,
                    silver_on_sell=False,
                    rsi_mode="pin_bar",
                    rsi_period=rsi_period,
                )
                score = scan_state.score
                rsi_oversold_today = scan_state.rsi_oversold_today
                rsi_rebound_setup = scan_state.rsi_rebound_setup
                rsi_pin_bar_pre = scan_state.rsi_pin_bar_pre
                rsi_signal_active = scan_state.rsi_signal_active
                carmen_candidate = scan_state.carmen_candidate
                tuo_signal_active = False
                pre_candidate = scan_state.pre_candidate
                if pre_candidate:
                    record_pre_candidate("A", symbol, stock_data, scan_state, a_share_names_map)
                symbol_perf_mark = _perf_record(symbol_perf_records, 'score_rsi', symbol_perf_mark)
                # 碗口指标已临时停用，跳过计算以节省算力
                # bowl_score = bowl_rebound_indicator(stock_data)
                bowl_score = None

                if pre_candidate:
                    min_tp = _a_share_min_turnover_pct_now()
                    turnover_started = time.perf_counter()
                    try:
                        turnover_rate = _a_share_turnover_effective(
                            fetch_a_share_turnover_rate(symbol.split('.')[0])
                        )
                    except Exception as e:
                        print(
                            f"⚠️  {symbol} 东财/ak 换手率拉取失败（{e}），"
                            f"本标的换手不做 {min_tp:g}% 拦截，信号照常"
                        )
                        turnover_rate = None
                    _perf_record(symbol_perf_records, 'turnover_fetch', turnover_started)
                    if turnover_rate is None:
                        turnover_warning = (
                            f'A股换手率未获取到有效值，本次不执行换手率>{min_tp:g}% 过滤'
                        )
                    elif turnover_rate <= min_tp:
                        turnover_blocked = True
                        print(
                            f"⏭️  {symbol} A股换手率{turnover_rate:.2f}%，"
                            f"未超过{min_tp:g}%，跳过买入/后台分析"
                        )
                
                if pre_candidate and not turnover_blocked:
                    full_data_started = time.perf_counter()
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
                            cache_minutes=5,
                            fast_scan=False,
                        )
                        if full_stock_data:
                            stock_data = full_stock_data
                            scan_state = evaluate_scan_signals(
                                stock_data,
                                rsi_threshold=RSI_REBOUND_THRESHOLD if rsi_track_on else None,
                                volatility_ok_fn=_rsi_rebound_volatility_ok if rsi_track_on else None,
                                silver_on_sell=False,
                                rsi_mode="pin_bar",
                                rsi_period=rsi_period,
                            )
                            score = scan_state.score
                            rsi_oversold_today = scan_state.rsi_oversold_today
                            rsi_rebound_setup = scan_state.rsi_rebound_setup
                            rsi_pin_bar_pre = scan_state.rsi_pin_bar_pre
                            rsi_signal_active = scan_state.rsi_signal_active
                            carmen_candidate = scan_state.carmen_candidate
                            pre_candidate = scan_state.pre_candidate
                        else:
                            pre_candidate = False
                    _perf_record(symbol_perf_records, 'detail_enrich', full_data_started)

                if pre_candidate and not turnover_blocked:
                    tuo_state = evaluate_tuo_signals(stock_data, carmen_candidate=carmen_candidate)
                    tuo_signal_active = tuo_state.tuo_signal_active

                # 进行回测
                backtest_result = None
                backtest_str = ''
                confidence = 0.0
                if pre_candidate and not turnover_blocked:
                    try:
                        if carmen_candidate:
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
                                rsi_threshold=RSI_REBOUND_THRESHOLD,
                                tuo_signal_active=tuo_signal_active,
                                duanxian_tuo_info=stock_data.get('duanxian_tuo_info'),
                                left_tuo_candidate=bool(stock_data.get('_duanxian_left_tuo_candidate')),
                            )
                            
                            # 后台 AI（与是否配置 Telegram/QQ 解耦；闸门见 scan_ai_common）
                            volume_ma_info = stock_data.get('volume_ma_info') or {}
                            duanxian_tuo_info = stock_data.get('duanxian_tuo_info') or {}
                            if rsi_pipeline:
                                signal_ok = True
                                submit_ai = True
                                position_build_score = float(volume_ma_info.get('position_build_score', 0) or 0)
                                has_recent_golden_cross = bool(volume_ma_info.get('has_recent_golden_cross', False))
                                gate_blocked = False
                            else:
                                signal_ok = _a_share_scan_signal_ok(
                                    score[0],
                                    confidence,
                                    rsi_signal_active,
                                    tuo_signal_active=tuo_signal_active,
                                )
                                submit_ai, signal_ok, position_build_score, has_recent_golden_cross = (
                                    _a_share_should_submit_scan_ai(
                                        score[0],
                                        confidence,
                                        volume_ma_info,
                                        duanxian_tuo_info,
                                        rsi_signal_active,
                                        tuo_signal_active=tuo_signal_active,
                                    )
                                )
                                gate_blocked = signal_ok and not submit_ai
                            if submit_ai and not rsi_pipeline:
                                apply_duanxian_tuo_gate_metadata(
                                    stock_data,
                                    volume_ma_info,
                                    mark_imminent_pass=True,
                                )
                            opening_ctx = None
                            if submit_ai:
                                opening_started = time.perf_counter()
                                opening_ctx = resolve_opening_price_context_for_filter(symbol, stock_data)
                                _perf_record(symbol_perf_records, 'opening_context_signal', opening_started)
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
                                stock_character_info = (
                                    get_stock_character_info()
                                    if isinstance(bot_notifier, TelegramNotifier)
                                    else None
                                )
                                price = stock_data.get('close', 0)
                                rsi = stock_data.get('rsi')
                                estimated_volume = stock_data.get('estimated_volume', 0)
                                avg_volume = stock_data.get('avg_volume', 1)
                                volume_ratio = (estimated_volume / avg_volume * 100) if avg_volume > 0 else None

                                cn_name = a_share_names_map.get(symbol) or a_share_names_map.get(symbol.strip())
                                base_payload = {
                                    'symbol': symbol,
                                    'market': "HKA",
                                    'bot_notifier': bot_notifier,
                                    'price': price,
                                    'score': score[0],
                                    'backtest_str': backtest_str,
                                    'rsi': rsi,
                                    'volume_ratio': volume_ratio,
                                    'bowl_score': bowl_score,
                                    'volume_ma_info': stock_data.get('volume_ma_info'),
                                    'duanxian_tuo_info': stock_data.get('duanxian_tuo_info'),
                                    'turnover_rate': turnover_rate,
                                    'turnover_warning': turnover_warning,
                                    'rsi_prev': stock_data.get('rsi_prev'),
                                    'dif': stock_data.get('dif'),
                                    'dea': stock_data.get('dea'),
                                    'dif_dea_slope': stock_data.get('dif_dea_slope'),
                                    'open_for_gap_filter': opening_ctx.open_for_filter,
                                    'opening_uncertain': opening_ctx.opening_uncertain,
                                    'open_gap_filter_enabled': opening_ctx.open_drop_filter_enabled,
                                    'stock_cn_name': cn_name,
                                    'alert_date': stock_data.get('date'),
                                    'stock_character_info': stock_character_info,
                                }
                                rsi_enqueued = False
                                if rsi_pin_bar_pre:
                                    pin_ok, pin_reason, shadow_info = _confirm_a_share_rsi_pin_bar(symbol, stock_data)
                                    if pin_ok:
                                        rsi_signal_active = True
                                        rsi_vol = _rsi_candidate_volatility_info(stock_data)
                                        rebound_score = float(rsi_vol.get('rebound_elasticity_score') or 0.0)
                                        pin_payload = {
                                            **base_payload,
                                            'backtest_str': f"(RSI{RSI_REBOUND_THRESHOLD:g})",
                                            'signal_id': _build_signal_id(symbol, stock_data, score[0], 'rsi_pin_bar'),
                                            'signal_title': "📉RSI超跌+Pin Bar",
                                            'rsi_rebound_volatility': rsi_vol,
                                        }
                                        stock_data['rebound_elasticity_score'] = rebound_score
                                        stock_data['rsi_rebound_volatility'] = rsi_vol
                                        stock_data['_rsi_pin_bar_shadow'] = shadow_info
                                        rsi_oversold_candidates.append({
                                            'symbol': symbol,
                                            'stock_data': stock_data,
                                            'ai_payload': pin_payload,
                                            'rsi': rsi,
                                            'signal_label': 'RSI+PinBar',
                                            'rebound_elasticity_score': rebound_score,
                                            'rsi_rebound_volatility': rsi_vol,
                                        })
                                        print(
                                            f"🧺 {symbol} RSI+Pin Bar候选入队："
                                            f"RSI={float(rsi or 0):.1f}，{_format_rsi_candidate_elasticity(rsi_oversold_candidates[-1])}，{pin_reason}"
                                        )
                                        rsi_enqueued = True
                                    else:
                                        print(f"⏭️  {symbol} RSI+Pin Bar未入候选池：{pin_reason}")
                                if _should_submit_regular_ai_after_rsi_queue(rsi_pipeline, rsi_enqueued):
                                    ai_payload = {
                                        **base_payload,
                                        'signal_id': _build_signal_id(
                                            symbol,
                                            stock_data,
                                            score[0],
                                            'left_tuo' if stock_data.get('_duanxian_tuo_pass_tag') == '虚托' else '',
                                        ),
                                        'duanxian_tuo_text': stock_data.get('_duanxian_tuo_display_text'),
                                    }
                                    print(f"🤖 {symbol} 触发信号，后台启动AI分析...")
                                    if not bot_notifier:
                                        print(f"ℹ️  {symbol} 未配置 Telegram/QQ：后台 AI 仍会继续生成缓存，但不发送推送")

                                    future = executor.submit(process_ai_task, **ai_payload)
                                    stock_data['_ai_future'] = future
                                    ai_launched = True

                            elif gate_blocked:
                                print(f"⏭️  {symbol} {skip_gate_log_suffix(position_build_score, has_recent_golden_cross, stock_data.get('duanxian_tuo_info'))}")
                            elif (symbol in watchlist_stocks) and score[1] >= 2.0:
                                # 按需求关闭自选股卖出信号推送：保留内部评分，但不发Telegram/QQ
                                pass
                    
                    except Exception as e:
                        print(f"⚠️  处理 {symbol} 回测时出错:")
                        traceback.print_exc()
                symbol_perf_mark = _perf_record(symbol_perf_records, 'candidate_pipeline', symbol_perf_mark)
                
                # 不因换手低而跳过终端打印；未知换手一律照常打印
                # 打印股票信息
                is_watchlist = symbol in watchlist_stocks
                print_success = print_stock_info(stock_data, score, is_watchlist, backtest_result, bowl_score=bowl_score)
                symbol_perf_mark = _perf_record(symbol_perf_records, 'print_stock_info', symbol_perf_mark)
                
                if not print_success:
                    failed_count += 1
                    _perf_summary(symbol, symbol_perf_records, symbol_perf_started, 'print_failed')
                else:
                    # 统计信号 (仅统计实际展示/保留的信号)
                    if score[0] >= 2.0 or rsi_signal_active or tuo_signal_active:
                        alert_count += 1

                    if not pre_candidate or turnover_blocked:
                        flush_output()
                        _perf_summary(
                            symbol,
                            symbol_perf_records,
                            symbol_perf_started,
                            'turnover_blocked' if turnover_blocked else 'no_candidate',
                        )
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
                    if not rsi_signal_active and not tuo_signal_active:
                        tuo_gates = evaluate_duanxian_tuo_gates(volume_ma_info, duanxian_tuo_info)
                        if volume_ma_info and not tuo_gates.secondary_gate_ok:
                            _perf_summary(symbol, symbol_perf_records, symbol_perf_started, 'volume_gate_blocked_html')
                            continue
                    html_opening_started = time.perf_counter()
                    op_ctx = resolve_opening_price_context_for_filter(symbol, stock_data)
                    _perf_record(symbol_perf_records, 'opening_context_html', html_opening_started)
                    if (
                        not rsi_signal_active
                        and op_ctx.open_drop_filter_enabled
                        and is_buy_blocked_by_open_gap(price, op_ctx.open_for_filter)
                    ):
                        _perf_summary(symbol, symbol_perf_records, symbol_perf_started, 'open_gap_blocked_html')
                        continue
                    
                    html_collect_started = time.perf_counter()
                    stocks_data_for_html.append({
                        'symbol': symbol,
                        'price': price,
                        'change_pct': change_pct,
                        'volume_ratio': volume_ratio,
                        'turnover_rate': turnover_rate,
                        'turnover_warning': turnover_warning,
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
                        '_ai_launched': ai_launched,
                        'volume_ma_info': volume_ma_info,
                        'duanxian_tuo_info': duanxian_tuo_info,
                        '_rsi_oversold_candidate': rsi_signal_active or bool(stock_data.get('_rsi_pin_bar_setup')),
                        '_rsi_oversold_today': rsi_oversold_today,
                        '_rsi_rebound_setup': rsi_rebound_setup,
                        '_rsi_pin_bar_pre': rsi_pin_bar_pre,
                        '_rsi_pin_bar_setup': bool(stock_data.get('_rsi_pin_bar_setup')),
                        '_duanxian_tuo_candidate': tuo_signal_active,
                        'rsi_rebound_volatility': stock_data.get('rsi_rebound_volatility') or stock_data.get('_rsi_rebound_volatility'),
                        'rebound_elasticity_score': stock_data.get('rebound_elasticity_score'),
                    })
                    _perf_record(symbol_perf_records, 'html_collect', html_collect_started)
                
                flush_output()
                _perf_summary(symbol, symbol_perf_records, symbol_perf_started, 'ok')
            else:
                failed_count += 1
                _perf_summary(symbol, symbol_perf_records, symbol_perf_started, 'no_stock_data')
                
        except KeyboardInterrupt:
            print("\n\n⚠️  用户中断程序...")
            raise
        except Exception as e:
            failed_count += 1
            print(f"⚠️  处理 {symbol} 时出错: {e}")
            _perf_summary(symbol, symbol_perf_records, symbol_perf_started, 'exception')
            continue
    
    row_by_symbol = {row.get('symbol'): row for row in stocks_data_for_html}

    all_rsi_candidates = rsi_oversold_candidates + rsi_rebound_candidates
    if all_rsi_candidates:
        selected_rsi_candidates = _select_top_rsi_rebound_candidates(
            all_rsi_candidates,
            RSI_REBOUND_TOP_N,
        )
        selected_candidate_ids = {id(item) for item in selected_rsi_candidates}
        print(
            f"\n📊 RSI+Pin Bar 候选 {len(all_rsi_candidates)} 只，"
            f"{'全部播报' if RSI_REBOUND_TOP_N <= 0 else f'按弹性评分选 Top{min(RSI_REBOUND_TOP_N, len(selected_rsi_candidates))} 播报'}"
        )
        for item in selected_rsi_candidates:
            symbol = item.get('symbol')
            stock_data = item.get('stock_data') or {}
            payload = item.get('ai_payload') or {}
            signal_label = item.get('signal_label') or 'RSI候选'
            print(
                f"🤖 {symbol} {signal_label}候选，后台启动AI分析："
                f"{_format_rsi_candidate_elasticity(item)}"
            )
            if not bot_notifier:
                print(f"ℹ️  {symbol} 未配置 Telegram/QQ：后台 AI 仍会继续生成缓存，但不发送推送")
            future = executor.submit(process_ai_task, **payload)
            stock_data['_ai_future'] = future
            stock_data['_ai_launched'] = True
            row = row_by_symbol.get(symbol)
            if row is not None:
                row['_ai_future'] = future
                row['_ai_launched'] = True
        for item in all_rsi_candidates:
            if id(item) in selected_candidate_ids:
                continue
            symbol = item.get('symbol')
            signal_label = item.get('signal_label') or 'RSI候选'
            print(
                f"⏭️  {symbol} {signal_label}候选未入Top{RSI_REBOUND_TOP_N}，本轮不播报："
                f"{_format_rsi_candidate_elasticity(item)}"
            )

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
        run_rebound_alert_scan(
            bot_notifier,
            get_stock_data,
            rsi_period=rsi_period,
            macd_fast=macd_fast,
            macd_slow=macd_slow,
            macd_signal=macd_signal,
            avg_volume_days=avg_volume_days,
        )
    except Exception as e:
        print(f"⚠️  A股回撤均线金叉预警扫描失败: {e}")
        traceback.print_exc()

    try:
        maybe_run_daily_sector_rotation_report("A", bot_notifier)
    except Exception as e:
        print(f"⚠️  A股板块轮动报告触发失败: {e}")
        traceback.print_exc()
    
    # 生成HTML报告并推送到GitHub Pages
    if git_publisher and stocks_data_for_html:
        try:
            terminal_output = get_output_buffer()
            
            # 只展示本轮实际启动后台AI的买入信号，避免“暂无有效分析”的占位行
            buy_signal_stocks = [
                stock for stock in stocks_data_for_html 
                if (
                    (stock.get('score_buy', 0) >= 2.0 and stock.get('confidence', 0) >= 0.5)
                    or stock.get('_rsi_oversold_candidate')
                )
                and stock.get('symbol') and stock.get('_ai_launched')
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
                    'status': 'A股市场扫描',
                    'current_time': current_time_str,
                    'mode': 'A股市场模式'
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
            output_file = 'docs/index_a.html'
            content_changed = generate_html_report(report_data, output_file, market_type="A")
            
            if content_changed:
                if git_publisher.publish(): 
                    pages_url = git_publisher.get_pages_url()
                    if pages_url:
                        print(f"🌐 访问A股页面: {pages_url}index_a.html")
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
    stock_pathA = 'stocks_list/cache/china_screener_A.csv'  # A股列表文件路径
    
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
    # A股运行节点: 11:35(午休), 14:30(收盘前30分钟), 15:10(收盘)
    scheduler = MarketScheduler(
        market='A',
        run_nodes_cfg=[
            {'hour': 8, 'minute': 00},
            {'hour': 9, 'minute': 40},
            {'hour': 10, 'minute': 10},
            {'hour': 10, 'minute': 40},
            {'hour': 11, 'minute': 10},
            {'hour': 12, 'minute': 10},
            {'hour': 13, 'minute': 10},
            {'hour': 13, 'minute': 40},
            {'hour': 14, 'minute': 10},
            {'hour': 14, 'minute': 40},
            {'hour': 15, 'minute': 30},
            {'hour': 16, 'minute': 0},  # RSI+Pin Bar 窗口
        ]
    )

    while True:
        try:
            if scheduler.check_should_run():
                main_a(
                    stock_path=stock_pathA,
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
