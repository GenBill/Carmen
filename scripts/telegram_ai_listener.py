#!/usr/bin/env python3
"""Telegram callback listener for Carmen.
Thin listener only: receive callback, ack fast, launch one-shot worker.
AI 分析仅读统一磁盘缓存，不现场调用模型。
"""
import html
import json
import os
import re
import subprocess
import sys
import time
from typing import Optional, Tuple, List, Dict

import requests

sys.stdout = sys.__stdout__
sys.stderr = sys.__stderr__

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CARMEN_ROOT = os.path.dirname(SCRIPT_DIR)
INDICATOR_DIR = os.path.join(CARMEN_ROOT, 'indicator')
RUNTIME_DIR = os.path.join(CARMEN_ROOT, 'runtime')
OFFSET_FILE = os.path.join(RUNTIME_DIR, 'telegram_listener.offset')
TIMEOUT_SECONDS = 15
POLL_INTERVAL_SECONDS = 1
QUEUE_RETRY_INTERVAL_SECONDS = 180
LAST_QUEUE_RETRY_TS = 0.0
AUDIT_FILE = os.path.join(INDICATOR_DIR, 'runtime', 'telegram_signal_audit.jsonl')
WATCHLIST_FILE = os.path.join(INDICATOR_DIR, 'daily_watchlist.json')
AVERAGE_DOWN_SCRIPT = os.path.join(SCRIPT_DIR, 'average_down_calc.py')

if INDICATOR_DIR not in sys.path:
    sys.path.insert(0, INDICATOR_DIR)

from telegram_notifier import load_telegram_token, TelegramNotifier, format_signal_snapshot, build_telegram_request_kwargs, parse_telegram_chat_ids  # noqa: E402
from analysis import (  # noqa: E402
    get_analysis_context,
    read_analysis_cache_entry,
    validate_cache_for_use,
)
from get_stock_price import get_stock_data  # noqa: E402
from stock_character_filter import evaluate_stock_character  # noqa: E402
from indicators import carmen_indicator, vegas_indicator, silver_indicator  # noqa: E402

TELEGRAM_REQUEST_KWARGS = build_telegram_request_kwargs(timeout=30)
TELEGRAM_REQUEST_KWARGS_FAST = build_telegram_request_kwargs(timeout=15)


def ensure_runtime_dir():
    os.makedirs(RUNTIME_DIR, exist_ok=True)


def load_offset() -> int:
    ensure_runtime_dir()
    if not os.path.exists(OFFSET_FILE):
        return 0
    try:
        with open(OFFSET_FILE, 'r', encoding='utf-8') as f:
            return int(f.read().strip() or '0')
    except Exception:
        return 0


def save_offset(offset: int):
    ensure_runtime_dir()
    with open(OFFSET_FILE, 'w', encoding='utf-8') as f:
        f.write(str(offset))


def normalize_symbol(raw: str) -> str:
    value = raw.strip().upper()
    value = value.replace('[', '').replace(']', '')
    value = value.replace(' ', '').replace('-', '').replace('_', '')

    if value.endswith('.HK') or value.endswith('.SS') or value.endswith('.SZ'):
        return value
    if value.endswith('HK') and '.' not in value and value[:-2].isdigit():
        return f"{value[:-2]}.HK"
    if value.endswith('SS') and '.' not in value and value[:-2].isdigit():
        return f"{value[:-2]}.SS"
    if value.endswith('SZ') and '.' not in value and value[:-2].isdigit():
        return f"{value[:-2]}.SZ"
    if value.isdigit():
        if len(value) == 6:
            if value.startswith(('5', '6', '9')):
                return f"{value}.SS"
            return f"{value}.SZ"
        if len(value) == 4:
            return f"{value}.HK"
    if value.isalpha():
        return value
    return value


def send_message(
    bot_token: str,
    chat_id: str,
    text: str,
    reply_to_message_id: Optional[int] = None,
    parse_mode: Optional[str] = None,
):
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = [text[i:i + 3800] for i in range(0, len(text), 3800)] or ['']
    for index, chunk in enumerate(chunks):
        data = {
            'chat_id': chat_id,
            'text': chunk,
            'disable_web_page_preview': True,
        }
        if parse_mode:
            data['parse_mode'] = parse_mode
        if reply_to_message_id and index == 0:
            data['reply_parameters'] = json.dumps({'message_id': reply_to_message_id}, ensure_ascii=False)
        response = requests.post(api_url, data=data, **TELEGRAM_REQUEST_KWARGS)
        response.raise_for_status()


def answer_callback(bot_token: str, callback_query_id: str, text: str = '已收到，开始分析…'):
    api_url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    response = requests.post(api_url, data={'callback_query_id': callback_query_id, 'text': text}, **TELEGRAM_REQUEST_KWARGS_FAST)
    response.raise_for_status()


def register_bot_commands(bot_token: str):
    api_url = f"https://api.telegram.org/bot{bot_token}/setMyCommands"
    commands = [
        {'command': 'help', 'description': '查看 Carmen Telegram 指令'},
        {'command': 'ai_analysis', 'description': '仅读缓存：/ai_analysis 600519SS'},
        {'command': 'score', 'description': '实时评分+股性：/score 002930'},
        {'command': 'stock_character', 'description': '股性评分：/stock_character 002930'},
        {'command': 'duanxian', 'description': '短线是银分析：/duanxian 002930'},
        {'command': 'audit', 'description': '审计链：/audit 002930'},
        {'command': 'call', 'description': '加仓表：/call 116.8 60000'}
    ]
    response = requests.post(api_url, data={'commands': json.dumps(commands, ensure_ascii=False)}, **TELEGRAM_REQUEST_KWARGS_FAST)
    response.raise_for_status()


def extract_symbol_from_message(text: str, command: str = 'ai_analysis') -> Optional[str]:
    match = re.match(rf'^/{command}(?:@\w+)?\s+(.+?)\s*$', text.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    return normalize_symbol(match.group(1))


def extract_call_args(text: str) -> Optional[Tuple[float, float]]:
    match = re.match(
        r'^/call(?:@\w+)?\s+([0-9]+(?:\.[0-9]+)?)\s+([0-9]+(?:\.[0-9]+)?)\s*$',
        text.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def extract_duanxian_symbol_from_message(text: str) -> Optional[str]:
    value = text.strip()
    patterns = [
        r'^/duanxian(?:@\w+)?\s+(.+?)\s*$',
        r'^短线是银分析\s+(.+?)\s*$',
        r'^短线是银\s+(.+?)\s*$',
        r'^唐能通模式\s+(.+?)\s*$',
        r'^唐能通分析\s+(.+?)\s*$',
    ]
    for pattern in patterns:
        match = re.match(pattern, value, flags=re.IGNORECASE)
        if match:
            return normalize_symbol(match.group(1))
    return None


def extract_stock_character_symbol_from_message(text: str) -> Optional[str]:
    value = text.strip()
    patterns = [
        r'^/股性(?:@\w+)?\s+(.+?)\s*$',
        r'^/stock_character(?:@\w+)?\s+(.+?)\s*$',
        r'^/character(?:@\w+)?\s+(.+?)\s*$',
        r'^股性\s+(.+?)\s*$',
        r'^股性检查\s+(.+?)\s*$',
    ]
    for pattern in patterns:
        match = re.match(pattern, value, flags=re.IGNORECASE)
        if match:
            return normalize_symbol(match.group(1))
    return None


def _fmt_yuan_amount(value) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 'N/A'
    if x >= 1e8:
        return f'{x / 1e8:.2f}亿'
    if x >= 1e4:
        return f'{x / 1e4:.0f}万'
    return f'{x:.0f}'


def format_stock_character_report(symbol: str, stock_data: dict, info: dict, telegram_html: bool = True) -> str:
    display_code = symbol.split('.')[0] if symbol.upper().endswith(('.SZ', '.SS', '.HK')) else symbol
    safe_symbol = html.escape(display_code if telegram_html else symbol)
    status = info.get('status') or '未知'
    score = info.get('score')
    score_text = f'{float(score):.1f}/100' if isinstance(score, (int, float)) else 'N/A'
    passed = bool(info.get('passed', True))
    if passed and status == '差':
        conclusion = '通过；低分观察'
    else:
        conclusion = '通过' if passed else '辅助否决'
    warning = info.get('warning')
    reasons = info.get('reasons') or []
    risk_reasons = info.get('risk_reasons') or []
    metrics = info.get('metrics') or {}
    amount_currency = metrics.get('amount_currency') or ''

    code_text = f'<code>{safe_symbol}</code>' if telegram_html else safe_symbol
    lines = [
        '🧬 股性评分',
        f'股票: {code_text}',
        f'日期: {html.escape(str(stock_data.get("date") or "N/A"))}',
        f'状态: {html.escape(status)} | 评分: {html.escape(score_text)} | 结论: {html.escape(conclusion)}',
    ]
    if warning:
        lines.append(f'⚠️ {html.escape(str(warning))}')
    if reasons:
        lines.append('辅助否决项:')
        lines.extend(f'- {html.escape(str(reason))}' for reason in reasons[:5])
    else:
        lines.append('辅助否决项: 无')
    if risk_reasons:
        lines.append('扣分/观察项:')
        lines.extend(f'- {html.escape(str(reason))}' for reason in risk_reasons[:5])

    lines.extend([
        '',
        '核心统计:',
        f'- 20日均额: {html.escape(_fmt_yuan_amount(metrics.get("avg_amount_20")))} {html.escape(str(amount_currency))}',
        f'- 60日均额: {html.escape(_fmt_yuan_amount(metrics.get("avg_amount_60")))} {html.escape(str(amount_currency))}',
        f'- 1日游冲高回落(破位): 20日{metrics.get("pump_fade_20", metrics.get("upper_shadow_exhaust_20", "N/A"))}次'
        f'(当日{metrics.get("pump_fade_same_day_20", "N/A")}/阴跌未收回{metrics.get("pump_fade_next_day_20", "N/A")})'
        f' / 60日{metrics.get("pump_fade_60", metrics.get("upper_shadow_exhaust_60", "N/A"))}次'
        f'(当日{metrics.get("pump_fade_same_day_60", "N/A")}/阴跌未收回{metrics.get("pump_fade_next_day_60", "N/A")})'
        f' / 1年{metrics.get("pump_fade_1y", metrics.get("upper_shadow_exhaust_1y", "N/A"))}次'
        f'(当日{metrics.get("pump_fade_same_day_1y", "N/A")}/阴跌未收回{metrics.get("pump_fade_next_day_1y", "N/A")})',
        f'- 假突破: 60日{metrics.get("false_breakout_60", "N/A")}次 / 1年{metrics.get("false_breakout_1y", "N/A")}次',
        f'- 杀跌: 20日{metrics.get("large_down_20", "N/A")}次 / 60日{metrics.get("large_down_60", "N/A")}次 / 1年{metrics.get("large_down_1y", "N/A")}次',
        f'- 放量阴线: 60日{metrics.get("bearish_volume_60", "N/A")}次 / 1年{metrics.get("bearish_volume_1y", "N/A")}次',
        f'- 1年均线交叉: {metrics.get("ma_cross_count_1y", "N/A")}次',
        f'- MA20斜率20日: {metrics.get("ma20_slope_20d_pct", "N/A")}%',
        f'- MA60斜率20日: {metrics.get("ma60_slope_20d_pct", "N/A")}%',
    ])
    return '\n'.join(lines)


def query_stock_character(symbol: str) -> Tuple[str, Optional[str]]:
    try:
        stock_data = get_stock_data(
            symbol,
            rsi_period=8,
            macd_fast=8,
            macd_slow=17,
            macd_signal=9,
            avg_volume_days=8,
            use_cache=True,
            cache_minutes=15,
        )
    except Exception as e:
        return f'股性评分失败: {symbol} | {e}', None

    if not stock_data:
        return f'未获取到 {symbol} 行情/指标数据', None

    info = evaluate_stock_character(stock_data)
    return format_stock_character_report(symbol, stock_data, info, telegram_html=True), 'HTML'


def query_realtime_score(symbol: str) -> Tuple[str, Optional[str]]:
    try:
        stock_data = get_stock_data(
            symbol,
            rsi_period=8,
            macd_fast=8,
            macd_slow=17,
            macd_signal=9,
            avg_volume_days=8,
            use_cache=True,
            cache_minutes=15,
        )
    except Exception as e:
        return f'实时评分失败: {symbol} | {e}', None

    if not stock_data:
        return f'未获取到 {symbol} 行情/指标数据', None

    score_carmen = carmen_indicator(stock_data)
    score_vegas = vegas_indicator(stock_data)
    score_silver = silver_indicator(stock_data)
    score_buy = round(score_carmen[0] * score_vegas[0] * score_silver, 2)
    score_sell = round(score_carmen[1] * score_vegas[1], 2)
    entry = read_analysis_cache_entry(symbol) or {}
    refined = entry.get('refined_info') or {}
    v = stock_data.get('volume_ma_info') or {}
    recent_crosses = v.get('recent_golden_crosses') or []
    cross_text = ' / '.join(c.replace('上穿', 'x') for c in recent_crosses) if recent_crosses else '无'
    volume_ratio = (stock_data.get('estimated_volume', 0) / stock_data.get('avg_volume', 1) * 100) if stock_data.get('avg_volume') else 0
    stock_cn_name = None
    turnover_rate = None

    current_above_ma = v.get('current_above_ma') or []
    current_multiple_vs_ma = v.get('current_multiple_vs_ma') or {}
    if current_above_ma:
        detail = ', '.join(f"{label}日({current_multiple_vs_ma.get(label, 0):.2f}x)" for label in current_above_ma)
        volume_spike_text = f"现量≥{v.get('volume_spike_threshold', 4.0):.1f}x {detail}"
    else:
        volume_spike_text = '暂无'

    stock_character_info = evaluate_stock_character(stock_data)
    score_text = format_signal_snapshot(
            title='📊 实时评分',
            symbol=symbol,
            price=float(stock_data.get('close') or 0),
            score=score_buy,
            backtest_text=None,
            min_buy_price=refined.get('min_buy_price'),
            max_buy_price=refined.get('max_buy_price'),
            buy_time=refined.get('buy_time'),
            target_price=refined.get('target_price'),
            stop_loss=refined.get('stop_loss'),
            ai_win_rate=refined.get('win_rate'),
            rsi_prev=float(stock_data.get('rsi_prev')) if stock_data.get('rsi_prev') is not None else None,
            rsi=float(stock_data.get('rsi')) if stock_data.get('rsi') is not None else None,
            dif=float(stock_data.get('dif')) if stock_data.get('dif') is not None else None,
            dea=float(stock_data.get('dea')) if stock_data.get('dea') is not None else None,
            dif_dea_slope=float(stock_data.get('dif_dea_slope')) if stock_data.get('dif_dea_slope') is not None else None,
            volume_ratio=(volume_ratio / 100.0),
            turnover_rate=turnover_rate,
            recent_crosses=[c.replace('上穿', 'x') for c in recent_crosses],
            volume_spike_text=volume_spike_text,
            position_build_score=v.get('position_build_score', 0),
            now_text=time.strftime('%Y-%m-%d %H:%M'),
            telegram_html=True,
            stock_cn_name=stock_cn_name,
            opening_uncertain_warning=False,
        )
    score_text += '\n\n' + format_stock_character_report(symbol, stock_data, stock_character_info, telegram_html=True)
    return (
        score_text,
        'HTML',
    )


def query_audit_chain(symbol: str) -> str:
    if not os.path.exists(AUDIT_FILE):
        return f'未找到审计日志: {symbol}'
    rows = []
    try:
        with open(AUDIT_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line=line.strip()
                if not line:
                    continue
                try:
                    obj=json.loads(line)
                except Exception:
                    continue
                if normalize_symbol(obj.get('symbol','')) == symbol:
                    rows.append(obj)
    except Exception as e:
        return f'读取审计日志失败: {e}'
    rows = rows[-20:]
    if not rows:
        return f'未找到 {symbol} 审计链'
    parts=[f'🧾 审计链 {symbol}']
    for r in rows:
        parts.append(f"{r.get('ts','')} | {r.get('signal_id','-')} | {r.get('event','-')}")
    return '\n'.join(parts)


def query_average_down_call(price: float, funds: float) -> str:
    if price <= 0 or funds <= 0:
        return '用法: /call 116.8 60000\n现价和资金都必须大于 0'
    try:
        result = subprocess.run(
            [
                sys.executable,
                AVERAGE_DOWN_SCRIPT,
                '--price',
                str(price),
                '--funds',
                str(funds),
                '--tg',
            ],
            cwd=CARMEN_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            check=False,
        )
    except Exception as e:
        return f'/call 执行失败: {e}'
    if result.returncode != 0:
        err = (result.stderr or result.stdout or '').strip()
        return f'/call 执行失败: {err or result.returncode}'
    return result.stdout.strip()


def build_help_text() -> str:
    return (
        "🤖 Carmen Telegram 指令\n"
        "/help 查看帮助\n"
        "/ai_analysis 002930 读取已缓存 AI 分析\n"
        "/score 002930 实时计算当前评分 + 股性评分\n"
        "/股性 002930 只看股性评分\n"
        "/stock_character 002930 只看股性评分\n"
        "/duanxian 002930 OpenClaw 短线是银 AI 分析\n"
        "短线是银分析 002930 自然语言触发\n"
        "/audit 002930 查看最近审计链\n"
        "/call 116.8 60000 计算加仓下单价和股数"
    )


def flush_pending_telegram_queue(bot_token: str, chat_id: str):
    global LAST_QUEUE_RETRY_TS
    now = time.time()
    if now - LAST_QUEUE_RETRY_TS < QUEUE_RETRY_INTERVAL_SECONDS:
        return
    LAST_QUEUE_RETRY_TS = now
    try:
        notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
        replayed = notifier.flush_pending_queue()
        if replayed > 0:
            print(f'🔁 listener 补发 Telegram 待发送消息 {replayed} 条')
    except Exception as e:
        print(f'⚠️ listener 补发队列失败: {e}')


def compose_telegram_cached_body(entry: dict) -> str:
    """
    把「结构化提炼」（refine_analysis）与「全文」（full_analysis）一并塞进会话；无全文时退回 summary_analysis。
    """
    full = (entry.get('full_analysis') or '').strip()
    refined = (entry.get('refine_analysis') or '').strip()
    summ = (entry.get('summary_analysis') or '').strip()

    if refined and full:
        sep = '\n\n' + ('─' * 18) + '\n\n'
        return f"【总结·提炼】\n{refined}{sep}【完整分析】\n{full}"
    if full:
        return full
    return summ


def resolve_cached_ai_text(symbol: str) -> Tuple[Optional[str], str]:
    """
    仅从统一缓存读取；返回 (正文, 说明)。
    先按 entry.status 分支；仅 completed 才做 validate_cache_for_use（需拉行情算 hash）。
    """
    entry = read_analysis_cache_entry(symbol)
    if not entry:
        return None, '暂无 AI 分析缓存'

    if entry.get('symbol') != symbol:
        return None, '缓存 symbol 与请求不一致，已拒绝。'

    st = entry.get('status') or ''

    if st == 'pending':
        return None, '分析进行中（pending）'

    if st == 'partial':
        body = compose_telegram_cached_body(entry).strip()
        if body:
            return body, '分析未完成（partial），以下为已生成的摘要/正文'
        return None, '分析未完成（partial）'

    if st == 'failed':
        return None, f"最近分析失败: {entry.get('error', '')}"

    if st == 'skipped':
        return None, '该股未触发后台 AI 条件（skipped）'

    if st == 'missing':
        return None, '暂无 AI 分析缓存'

    if st == 'completed':
        text = compose_telegram_cached_body(entry).strip()
        if not text:
            return None, 'completed 缓存中文本为空'

        ctx = get_analysis_context(symbol)
        if ctx is None:
            # yfinance/网络异常时无法做 hash/价格校验；仍展示缓存正文并标明未校验，避免「完全不可用」
            return text, (
                '缓存命中（completed）；当前无法拉取行情做一致性校验，若与实时价偏离以市场为准'
            )
        if not validate_cache_for_use(
            entry, symbol, ctx['data_hash'], ctx['current_price'],
        ):
            return None, '缓存与当前行情不一致或已过期（data_hash/价格/脏标记），请等待新一轮扫描。'

        return text, '缓存命中（completed）'

    return None, f"未知缓存状态: {st}"


def build_analysis_message(symbol: str, body: str, subtitle: str) -> str:
    safe_symbol = html.escape(symbol.replace('.SS', '[SS]').replace('.SZ', '[SZ]').replace('.HK', '[HK]'))
    header = html.escape(subtitle)
    return f"{header}\n股票: {safe_symbol}\n\n{html.escape(body)}"


def build_status_only_message(symbol: str, reason: str) -> str:
    safe_symbol = html.escape(symbol.replace('.SS', '[SS]').replace('.SZ', '[SZ]').replace('.HK', '[HK]'))
    return f"📭 无可用 AI 展示\n股票: {safe_symbol}\n\n{html.escape(reason)}"


def process_symbol(bot_token: str, chat_id: str, symbol: str, reply_to_message_id: Optional[int] = None):
    text, note = resolve_cached_ai_text(symbol)
    if text:
        msg = build_analysis_message(symbol, text, f'♻️ {note}')
    else:
        msg = build_status_only_message(symbol, note or '未知原因')
    send_message(bot_token, chat_id, msg, reply_to_message_id=reply_to_message_id)


def spawn_fundamental_worker(symbol: str, bot_token: str, chat_id: str, reply_to_message_id: Optional[int] = None) -> bool:
    ensure_runtime_dir()
    log_path = os.path.join(RUNTIME_DIR, f"fundamental_{symbol.replace('.', '_')}_{int(time.time())}.log")
    worker_script = os.path.join(SCRIPT_DIR, 'handle_fundamental_click.py')
    env = os.environ.copy()
    env.setdefault('PYTHONUNBUFFERED', '1')
    try:
        with open(log_path, 'w', encoding='utf-8') as log_file:
            subprocess.Popen(
                [
                    sys.executable, '-u', worker_script,
                    '--symbol', symbol,
                    '--bot-token', bot_token,
                    '--chat-id', str(chat_id),
                    '--reply-to-message-id', str(reply_to_message_id or ''),
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=CARMEN_ROOT,
                env=env,
                start_new_session=True,
            )
        print(f"🚀 worker spawned: symbol={symbol} log={log_path}")
        return True
    except Exception as e:
        print(f"⚠️ spawn worker failed: {e}")
        return False


def spawn_duanxian_worker(symbol: str, bot_token: str, chat_id: str, reply_to_message_id: Optional[int] = None) -> bool:
    ensure_runtime_dir()
    log_path = os.path.join(RUNTIME_DIR, f"duanxian_{symbol.replace('.', '_')}_{int(time.time())}.log")
    worker_script = os.path.join(SCRIPT_DIR, 'duanxian_shiyin_analysis.py')
    env = os.environ.copy()
    env.setdefault('PYTHONUNBUFFERED', '1')
    try:
        with open(log_path, 'w', encoding='utf-8') as log_file:
            subprocess.Popen(
                [
                    sys.executable, '-u', worker_script,
                    '--symbol', symbol,
                    '--bot-token', bot_token,
                    '--chat-id', str(chat_id),
                    '--reply-to-message-id', str(reply_to_message_id or ''),
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                cwd=CARMEN_ROOT,
                env=env,
                start_new_session=True,
            )
        print(f"🚀 duanxian worker spawned: symbol={symbol} log={log_path}")
        return True
    except Exception as e:
        print(f"⚠️ spawn duanxian worker failed: {e}")
        return False


def handle_update(bot_token: str, expected_chat_id: str, update: dict):
    if 'callback_query' in update:
        query = update['callback_query']
        data = query.get('data', '')
        message = query.get('message', {})
        chat_id = str(message.get('chat', {}).get('id', ''))
        if chat_id != str(expected_chat_id):
            answer_callback(bot_token, query['id'], '未授权的聊天来源')
            return
        if data.startswith('ai_analysis:'):
            symbol = normalize_symbol(data.split(':', 1)[1])
            answer_callback(bot_token, query['id'], '已收到（仅读缓存）')
            process_symbol(bot_token, chat_id, symbol, reply_to_message_id=message.get('message_id'))
        elif data.startswith('fundamental:'):
            symbol = normalize_symbol(data.split(':', 1)[1])
            ok = spawn_fundamental_worker(symbol, bot_token, chat_id, reply_to_message_id=message.get('message_id'))
            answer_callback(bot_token, query['id'], '已收到，正在查询基本面…' if ok else '启动查询失败')
        return

    if 'message' in update:
        message = update['message']
        chat_id = str(message.get('chat', {}).get('id', ''))
        if chat_id != str(expected_chat_id):
            return
        text = message.get('text', '')
        if re.match(r'^/help(?:@\w+)?\s*$', text.strip(), flags=re.IGNORECASE):
            send_message(bot_token, chat_id, build_help_text(), reply_to_message_id=message.get('message_id'))
            return

        call_args = extract_call_args(text)
        if call_args:
            body = query_average_down_call(*call_args)
            send_message(bot_token, chat_id, body, reply_to_message_id=message.get('message_id'))
            return
        if re.match(r'^/call(?:@\w+)?(?:\s+.*)?$', text.strip(), flags=re.IGNORECASE):
            send_message(
                bot_token,
                chat_id,
                '用法: /call 116.8 60000',
                reply_to_message_id=message.get('message_id'),
            )
            return

        symbol = extract_symbol_from_message(text, 'ai_analysis')
        if symbol:
            send_message(
                bot_token,
                chat_id,
                f"🧠 已收到 /ai_analysis {html.escape(symbol)}（仅读缓存，不现场生成）",
                reply_to_message_id=message.get('message_id'),
            )
            process_symbol(bot_token, chat_id, symbol, reply_to_message_id=message.get('message_id'))
            return

        symbol = extract_symbol_from_message(text, 'score')
        if symbol:
            score_body, score_mode = query_realtime_score(symbol)
            send_message(
                bot_token,
                chat_id,
                score_body,
                reply_to_message_id=message.get('message_id'),
                parse_mode=score_mode,
            )
            return

        symbol = extract_stock_character_symbol_from_message(text)
        if symbol:
            body, mode = query_stock_character(symbol)
            send_message(
                bot_token,
                chat_id,
                body,
                reply_to_message_id=message.get('message_id'),
                parse_mode=mode,
            )
            return

        symbol = extract_duanxian_symbol_from_message(text)
        if symbol:
            ok = spawn_duanxian_worker(symbol, bot_token, chat_id, reply_to_message_id=message.get('message_id'))
            send_message(
                bot_token,
                chat_id,
                f"📘 已收到 短线是银 AI 分析 {html.escape(symbol)}，正在启动 OpenClaw 临时 session…"
                if ok else f"📘 短线是银分析启动失败: {html.escape(symbol)}",
                reply_to_message_id=message.get('message_id'),
            )
            return

        symbol = extract_symbol_from_message(text, 'audit')
        if symbol:
            send_message(bot_token, chat_id, html.escape(query_audit_chain(symbol)), reply_to_message_id=message.get('message_id'))
            return


def main():
    bot_token, configured_chat_id = load_telegram_token()
    chat_id = parse_telegram_chat_ids(configured_chat_id)[0]
    offset = load_offset()
    api_url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    register_bot_commands(bot_token)
    print(f"🤖 Telegram AI listener 启动，chat_id={chat_id}")

    while True:
        try:
            response = requests.get(
                api_url,
                params={'timeout': TIMEOUT_SECONDS, 'offset': offset, 'allowed_updates': json.dumps(['message', 'callback_query'])},
                timeout=TIMEOUT_SECONDS + 10,
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get('ok'):
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            flush_pending_telegram_queue(bot_token, configured_chat_id)
            for update in payload.get('result', []):
                offset = max(offset, update['update_id'] + 1)
                handle_update(bot_token, chat_id, update)
                save_offset(offset)
        except requests.exceptions.SSLError:
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ Telegram listener 异常: {e}")
            time.sleep(3)


if __name__ == '__main__':
    main()
