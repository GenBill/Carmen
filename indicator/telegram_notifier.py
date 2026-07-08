"""
Telegram 消息推送模块
与 QQNotifier 接口兼容，使用 Telegram Bot API 发送消息
"""
import requests
import os
import time
import html
import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, List

from earnings_proximity import earnings_proximity_note
from scan_ai_common import MIN_POSITION_BUILD_SCORE, evaluate_duanxian_tuo_gates, format_duanxian_tuo_display

# 模块级全局缓存：{symbol: last_push_timestamp}
_global_push_cache = {}


QUEUE_FILE = Path(__file__).resolve().parent / 'runtime' / 'telegram_pending_queue.json'
AUDIT_FILE = Path(__file__).resolve().parent / 'runtime' / 'telegram_signal_audit.jsonl'
ALERT_STATE_FILE = Path(__file__).resolve().parent / 'runtime' / 'carmen_alert_state.json'
DEFAULT_TELEGRAM_PROXY = os.environ.get('TELEGRAM_PROXY_URL', 'http://127.0.0.1:7890')
HK_TZ = timezone(timedelta(hours=8))


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    value = (value or '').strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=HK_TZ)
    return parsed.astimezone(HK_TZ)


def load_alert_state() -> Dict:
    if not ALERT_STATE_FILE.exists():
        return {}
    try:
        with open(ALERT_STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠️  读取 Carmen 预警状态失败: {e}")
        return {}


def carmen_alerts_muted() -> Tuple[bool, Optional[str]]:
    state = load_alert_state()
    muted_until = _parse_iso_datetime(str(state.get('muted_until', '') or ''))
    if not muted_until:
        return False, None
    now = datetime.now(HK_TZ)
    if now < muted_until:
        reason = str(state.get('reason', '') or '').strip() or None
        return True, reason
    return False, None


def build_telegram_request_kwargs(timeout: int = 10) -> Dict:
    proxy = os.environ.get('TELEGRAM_PROXY_URL', DEFAULT_TELEGRAM_PROXY).strip()
    kwargs: Dict = {'timeout': timeout}
    if proxy:
        kwargs['proxies'] = {
            'http': proxy,
            'https': proxy,
        }
    return kwargs


def format_signal_snapshot(
    title: str,
    symbol: str,
    price: float,
    score: float,
    backtest_text: Optional[str] = None,
    min_buy_price: Optional[float] = None,
    max_buy_price: Optional[float] = None,
    buy_time: Optional[str] = None,
    target_price: Optional[float] = None,
    stop_loss: Optional[float] = None,
    ai_win_rate: Optional[float] = None,
    rsi_prev: Optional[float] = None,
    rsi: Optional[float] = None,
    dif: Optional[float] = None,
    dea: Optional[float] = None,
    dif_dea_slope: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    turnover_rate: Optional[float] = None,
    recent_crosses: Optional[List[str]] = None,
    volume_spike_text: Optional[str] = None,
    position_build_score: Optional[float] = None,
    duanxian_tuo_text: Optional[str] = None,
    now_text: Optional[str] = None,
    telegram_html: bool = False,
    stock_cn_name: Optional[str] = None,
    opening_uncertain_warning: bool = False,
    earnings_note: Optional[str] = None,
    stock_character_info: Optional[Dict] = None,
    rsi_rebound_volatility: Optional[Dict] = None,
) -> str:
    
    split_symbol = symbol.split('.')
    split_symbol_0 = split_symbol[0]
    split_symbol_1 = f"[{split_symbol[1]}]" if len(split_symbol)==2 else ""
    sym_display = f"{split_symbol_0}{split_symbol_1}"
    extras_suffix = ""
    upper_sym = symbol.upper()
    cn = (stock_cn_name or "").strip()
    if cn and (upper_sym.endswith('.SS') or upper_sym.endswith('.SZ')):
        extras_suffix = f" {html.escape(cn)}" if telegram_html else f" {cn}"
    if telegram_html:
        stock_line = f"股票: <code>{html.escape(split_symbol_0)}</code>{split_symbol_1}{extras_suffix}"
    else:
        stock_line = f"股票: {sym_display}{extras_suffix}"
    parts: List[str] = [title]
    if opening_uncertain_warning:
        warn_line = "⚠️ 开盘价可能不准确，请核实"
        parts.append(html.escape(warn_line) if telegram_html else warn_line)
    parts.extend([
        f"时间: {now_text or datetime.now().strftime('%Y-%m-%d %H:%M')}",
        stock_line,
        f"当前价格: {price:.2f}",
        f"评分: {score:.2f}",
    ])
    if backtest_text:
        parts.append(f"回测胜率: {backtest_text}")

    refined_lines: List[str] = []
    if min_buy_price is not None and max_buy_price is not None:
        refined_lines.append(f"买入区间: {min_buy_price:.2f}-{max_buy_price:.2f}")
    elif max_buy_price is not None:
        refined_lines.append(f"最高买入价: {max_buy_price:.2f}")
    elif min_buy_price is not None:
        refined_lines.append(f"最低买入价: {min_buy_price:.2f}")
    if buy_time:
        bt = html.escape(buy_time) if telegram_html else buy_time
        refined_lines.append(f"买入时间: {bt}")
    if target_price is not None:
        refined_lines.append(f"目标价位: {target_price:.2f}")
    if stop_loss is not None:
        refined_lines.append(f"止损位: {stop_loss:.2f}")
    if ai_win_rate is not None:
        refined_lines.append(f"AI预估胜率: {ai_win_rate*100:.1f}%")

    tech_lines: List[str] = []
    if rsi_prev is not None and rsi is not None:
        rsi_span = f"{rsi_prev:.2f} -> {rsi:.2f}"
        if telegram_html:
            rsi_span = html.escape(rsi_span)
        tech_lines.append(f"RSI: {rsi_span}")
    elif rsi is not None:
        tech_lines.append(f"RSI: {rsi:.2f}")
    if isinstance(rsi_rebound_volatility, dict):
        try:
            elasticity_line = (
                f"弹性评分: {float(rsi_rebound_volatility.get('rebound_elasticity_score') or 0):.1f} | "
                f"6个月平均 +{float(rsi_rebound_volatility.get('avg_up_pct') or 0):.1f}%/"
                f"-{float(rsi_rebound_volatility.get('avg_down_pct') or 0):.1f}% | "
                f"上下比 {float(rsi_rebound_volatility.get('up_down_ratio') or 0):.2f}"
            )
            if telegram_html:
                elasticity_line = html.escape(elasticity_line)
            tech_lines.append(elasticity_line)
        except (TypeError, ValueError):
            pass
    if dif is not None and dea is not None and dif_dea_slope is not None:
        tech_lines.append(f"MACD: DIF {dif:.2f} | DEA {dea:.2f} | 斜率 {dif_dea_slope:.2f}")
    if volume_ratio is not None:
        tech_lines.append(f"量比: {volume_ratio:.2f}")
    if turnover_rate is not None:
        tech_lines.append(f"换手率: {turnover_rate:.2f}%")
    if isinstance(stock_character_info, dict):
        sc_status = stock_character_info.get('status') or '未知'
        sc_score = stock_character_info.get('score')
        sc_score_text = f"{float(sc_score):.1f}" if isinstance(sc_score, (int, float)) else 'N/A'
        sc_reasons = stock_character_info.get('reasons') or stock_character_info.get('risk_reasons') or []
        sc_prefix = '辅助否决项' if stock_character_info.get('reasons') else '观察项'
        sc_line = f"股性: {sc_status}({sc_score_text})"
        if sc_reasons:
            sc_line += f" | {sc_prefix}: {'；'.join(str(x) for x in sc_reasons[:2])}"
        if telegram_html:
            sc_line = html.escape(sc_line)
        tech_lines.append(sc_line)

    cross_text = ' / '.join(recent_crosses or []) if recent_crosses else '无'
    if telegram_html:
        cross_text = html.escape(cross_text)
    vs = volume_spike_text or '暂无'
    if telegram_html:
        vs = html.escape(vs)
    footer_lines = [
        f"近7日量能金叉: {cross_text}",
        f"异常爆量: {vs}",
    ]
    if position_build_score is not None:
        footer_lines.append(f"建仓强度: {position_build_score:.1f}")
    if duanxian_tuo_text:
        footer_lines.append(f"短线是银托形态: {duanxian_tuo_text}")

    if refined_lines:
        parts.append("")
        parts.extend(refined_lines)
    if tech_lines:
        if refined_lines:
            parts.append("")
        parts.extend(tech_lines)
    parts.append("")
    parts.extend(footer_lines)
    if earnings_note:
        note_line = html.escape(earnings_note) if telegram_html else earnings_note
        parts.append(note_line)
    return "\n".join(parts)


def append_signal_audit(event: Dict) -> None:
    try:
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(event)
        payload.setdefault('ts', datetime.now().isoformat())
        with open(AUDIT_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"⚠️  写入 Telegram 审计日志失败: {e}")


class TelegramNotifier:
    """Telegram 消息推送器（与 QQNotifier 接口兼容）"""

    def __init__(self, bot_token: str, chat_id: str):
        """
        初始化 Telegram 推送器

        Args:
            bot_token: Telegram Bot API Token（从 @BotFather 获取）
            chat_id: 接收消息的 Chat ID（私聊或群组）
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.chat_ids = parse_telegram_chat_ids(chat_id)
        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.request_kwargs = build_telegram_request_kwargs(timeout=10)
        self.cache_hours = 2

        self.max_retries = 4
        self.initial_wait = 2.0
        self.max_wait = 30
        self.backoff_multiplier = 4
        QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)

    def _load_pending_queue(self) -> List[Dict]:
        if not QUEUE_FILE.exists():
            return []
        try:
            with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"⚠️  读取 Telegram 待发送队列失败: {e}")
            return []

    def _save_pending_queue(self, queue: List[Dict]) -> None:
        try:
            with open(QUEUE_FILE, 'w', encoding='utf-8') as f:
                json.dump(queue, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️  保存 Telegram 待发送队列失败: {e}")

    def _queue_pending_message(
        self,
        symbol: str,
        msg: str,
        reply_markup: Optional[Dict] = None,
        signal_id: Optional[str] = None,
        parse_mode: Optional[str] = 'HTML',
    ) -> None:
        queue = self._load_pending_queue()
        item = {
            'symbol': symbol,
            'signal_id': signal_id,
            'msg': msg,
            'reply_markup': reply_markup,
            'parse_mode': parse_mode,
            'created_at': time.time(),
            'attempts': 0,
        }
        queue = [x for x in queue if not ((signal_id and x.get('signal_id') == signal_id) or (x.get('symbol') == symbol and x.get('msg') == msg))]
        queue.append(item)
        self._save_pending_queue(queue)
        append_signal_audit({'event': 'queued', 'symbol': symbol, 'signal_id': signal_id})
        print(f"📝 {symbol} 已写入 Telegram 待发送队列")

    def flush_pending_queue(self, max_items: int = 20) -> int:
        muted, reason = carmen_alerts_muted()
        if muted:
            append_signal_audit({'event': 'flush_skipped_muted', 'reason': reason})
            return 0

        queue = self._load_pending_queue()
        if not queue:
            return 0

        sent = 0
        kept = []
        for idx, item in enumerate(queue):
            if idx >= max_items:
                kept.extend(queue[idx:])
                break
            symbol = item.get('symbol', 'UNKNOWN')
            signal_id = item.get('signal_id')
            parse_mode = item.get('parse_mode', 'HTML')
            if parse_mode is None:
                ok = self.send_plain_text_message(item.get('msg', ''))
            else:
                ok = self.send_message(
                    item.get('msg', ''),
                    item.get('reply_markup'),
                    parse_mode=parse_mode,
                )
            if ok:
                _global_push_cache[symbol] = time.time()
                sent += 1
                append_signal_audit({'event': 'replayed_sent', 'symbol': symbol, 'signal_id': signal_id})
                print(f"✅ {symbol} 待发送 Telegram 已补发成功")
            else:
                item['attempts'] = int(item.get('attempts', 0)) + 1
                append_signal_audit({'event': 'replayed_failed', 'symbol': symbol, 'signal_id': signal_id, 'attempts': item['attempts']})
                kept.append(item)
        self._save_pending_queue(kept)
        return sent

    def send_plain_text_message(self, msg: str) -> bool:
        wait_time = self.initial_wait
        if msg == "":
            print("⚠️  Telegram 纯文本消息为空，跳过")
            return False

        for attempt in range(self.max_retries + 1):
            try:
                response = None
                primary_ok = False
                for idx, target_chat_id in enumerate(self.chat_ids):
                    data = {
                        "chat_id": target_chat_id,
                        "text": msg,
                        "disable_web_page_preview": True,
                    }
                    try:
                        response = requests.post(self.api_url, data=data, **self.request_kwargs)
                        response.raise_for_status()
                        if idx == 0:
                            primary_ok = True
                    except Exception as extra_e:
                        if idx == 0:
                            raise
                        print(f"⚠️  Telegram 额外转发失败 chat_id={target_chat_id}: {extra_e}")
                if not primary_ok:
                    raise RuntimeError("primary Telegram target not sent")

                if attempt > 0:
                    print(f"✅ Telegram 纯文本推送成功（第{attempt + 1}次尝试）")

                return True
            except Exception as e:
                error_detail = ""
                if "response" in locals() and hasattr(response, "text"):
                    error_detail = f" Server response: {response.text}"

                if attempt == self.max_retries:
                    print(f"⚠️  Telegram 纯文本推送失败（已重试{self.max_retries}次）: {e}{error_detail}")
                    return False

                print(f"⚠️  Telegram 纯文本推送失败（第{attempt + 1}次尝试）: {e}{error_detail}，{wait_time}秒后重试...")
                time.sleep(wait_time)
                wait_time = min(wait_time * self.backoff_multiplier, self.max_wait)

        return False

    def send_message(
        self,
        msg: str,
        reply_markup: Optional[Dict] = None,
        parse_mode: Optional[str] = 'HTML',
    ) -> bool:
        """
        发送 Telegram 消息（带指数退避重试机制）

        Args:
            msg: 要发送的消息内容
            reply_markup: 可选按钮/键盘配置
            parse_mode: Telegram parse_mode（默认 HTML）；传入 None 则不发 parse_mode（纯文本）

        Returns:
            bool: 是否发送成功
        """
        wait_time = self.initial_wait
        if msg == "":
            print("⚠️  Telegram 推送消息为空，跳过")
            return False

        for attempt in range(self.max_retries + 1):
            try:
                response = None
                primary_ok = False
                for idx, target_chat_id in enumerate(self.chat_ids):
                    data = {
                        "chat_id": target_chat_id,
                        "text": msg,
                        "disable_web_page_preview": True,
                    }
                    if parse_mode is not None:
                        data["parse_mode"] = parse_mode
                    if reply_markup:
                        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
                    try:
                        response = requests.post(self.api_url, data=data, **self.request_kwargs)
                        response.raise_for_status()
                        if idx == 0:
                            primary_ok = True
                    except Exception as extra_e:
                        if idx == 0:
                            raise
                        print(f"⚠️  Telegram 额外转发失败 chat_id={target_chat_id}: {extra_e}")
                if not primary_ok:
                    raise RuntimeError("primary Telegram target not sent")

                if attempt > 0:
                    print(f"✅ Telegram 推送成功（第{attempt + 1}次尝试）")

                return True
            except Exception as e:
                error_detail = ""
                if "response" in locals() and hasattr(response, "text"):
                    error_detail = f" Server response: {response.text}"

                if attempt == self.max_retries:
                    print(f"⚠️  Telegram 推送失败（已重试{self.max_retries}次）: {e}{error_detail}")
                    return False

                print(f"⚠️  Telegram 推送失败（第{attempt + 1}次尝试）: {e}{error_detail}，{wait_time}秒后重试...")
                time.sleep(wait_time)
                wait_time = min(wait_time * self.backoff_multiplier, self.max_wait)

        return False

    def send_serenity_analysis(
        self,
        symbol: str,
        msg: str,
        queue_on_fail: bool = True,
        signal_id: Optional[str] = None,
    ) -> bool:
        """发送买入信号后的 Serenity 模拟人格分析（第二条消息）。"""
        muted, reason = carmen_alerts_muted()
        if muted:
            print(f"🔕 Carmen Telegram Serenity 分析已静音，跳过 {symbol}: {reason or 'no reason'}")
            append_signal_audit({'event': 'muted_serenity_skipped', 'symbol': symbol, 'signal_id': signal_id, 'reason': reason})
            return False

        text = (msg or '').strip()
        if not text:
            append_signal_audit({'event': 'serenity_empty_skipped', 'symbol': symbol, 'signal_id': signal_id})
            return False

        append_signal_audit({'event': 'serenity_send_attempt', 'symbol': symbol, 'signal_id': signal_id})
        success = self.send_message(text, parse_mode='HTML')
        if success:
            append_signal_audit({'event': 'serenity_sent', 'symbol': symbol, 'signal_id': signal_id})
        elif queue_on_fail:
            append_signal_audit({'event': 'serenity_send_failed', 'symbol': symbol, 'signal_id': signal_id})
            self._queue_pending_message(symbol, text, signal_id=signal_id, parse_mode='HTML')
        return success

    def send_sell_signal(
        self,
        symbol: str,
        price: float,
        score: float,
        backtest_str: str,
        rsi: Optional[float] = None,
        volume_ratio: Optional[float] = None,
    ) -> bool:
        """发送卖出信号通知（与 QQNotifier 接口兼容）"""
        muted, reason = carmen_alerts_muted()
        if muted:
            print(f"🔕 Carmen Telegram 卖出预警已静音，跳过 {symbol}: {reason or 'no reason'}")
            append_signal_audit({'event': 'muted_sell_skipped', 'symbol': symbol, 'reason': reason})
            return False

        current_time = time.time()
        is_rsi_rebound_signal = str(backtest_str or '').startswith('(RSI')
        if symbol in _global_push_cache:
            last_push_time = _global_push_cache[symbol]
            hours_passed = (current_time - last_push_time) / 3600
            if hours_passed < self.cache_hours:
                print(f"⏭️  {symbol} 在 {hours_passed:.1f} 小时前已推送过，跳过")
                return False

        split_symbol = symbol.split('.')
        split_symbol_0 = split_symbol[0]
        split_symbol_1 = f"[{split_symbol[1]}]" if len(split_symbol) == 2 else ""
        msg_parts = [
            "📉 卖出信号提醒",
            f"股票: <code>{html.escape(split_symbol_0)}</code>{split_symbol_1}",
            f"当前价格: {price:.2f}",
            f"评分: {score:.2f}",
            f"回测胜率: {backtest_str[1:-1]}",
        ]
        if rsi is not None:
            msg_parts.append(f"RSI: {rsi:.2f}")
        if volume_ratio is not None:
            msg_parts.append(f"量比: {volume_ratio:.1f}%")

        msg = "\n".join(msg_parts)
        success = self.send_message(msg)

        if success:
            _global_push_cache[symbol] = current_time

        return success

    def send_buy_signal(
        self,
        symbol: str,
        price: float,
        score: float,
        backtest_str: str,
        rsi: Optional[float] = None,
        volume_ratio: Optional[float] = None,
        min_buy_price: Optional[float] = None,
        max_buy_price: Optional[float] = None,
        buy_time: Optional[str] = None,
        target_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        ai_win_rate: Optional[float] = None,
        refined_text: Optional[str] = None,
        bowl_score: Optional[float] = None,
        volume_ma_info: Optional[Dict] = None,
        duanxian_tuo_info: Optional[Dict] = None,
        duanxian_tuo_text: Optional[str] = None,
        turnover_rate: Optional[float] = None,
        turnover_warning: Optional[str] = None,
        queue_on_fail: bool = True,
        signal_id: Optional[str] = None,
        rsi_prev: Optional[float] = None,
        dif: Optional[float] = None,
        dea: Optional[float] = None,
        dif_dea_slope: Optional[float] = None,
        stock_cn_name: Optional[str] = None,
        opening_uncertain: bool = False,
        stock_character_info: Optional[Dict] = None,
        signal_title: Optional[str] = None,
        rsi_rebound_volatility: Optional[Dict] = None,
    ) -> bool:
        """发送买入信号通知（与 QQNotifier 接口兼容）"""
        muted, reason = carmen_alerts_muted()
        if muted:
            print(f"🔕 Carmen Telegram 买入预警已静音，跳过 {symbol}: {reason or 'no reason'}")
            append_signal_audit({'event': 'muted_buy_skipped', 'symbol': symbol, 'signal_id': signal_id, 'reason': reason})
            return False

        current_time = time.time()
        is_rsi_rebound_signal = str(backtest_str or '').startswith('(RSI')
        append_signal_audit({'event': 'send_attempt', 'symbol': symbol, 'signal_id': signal_id, 'price': price, 'score': score})
        if symbol in _global_push_cache:
            last_push_time = _global_push_cache[symbol]
            hours_passed = (current_time - last_push_time) / 3600
            if hours_passed < self.cache_hours:
                print(f"⏭️  {symbol} 在 {hours_passed:.1f} 小时前已推送过，跳过")
                append_signal_audit({'event': 'deduped', 'symbol': symbol, 'signal_id': signal_id, 'hours_passed': round(hours_passed, 2)})
                return False

        recent_crosses = []
        volume_spike_text = None
        position_build_score = None
        tuo_gates = evaluate_duanxian_tuo_gates(volume_ma_info, duanxian_tuo_info)
        duanxian_tuo_text = duanxian_tuo_text or tuo_gates.display_text
        if volume_ma_info:
            recent_golden_crosses = volume_ma_info.get('recent_golden_crosses') or []
            current_above_ma = volume_ma_info.get('current_above_ma') or []
            current_multiple_vs_ma = volume_ma_info.get('current_multiple_vs_ma') or {}
            volume_spike_threshold = volume_ma_info.get('volume_spike_threshold', 4.0)
            position_build_score = volume_ma_info.get('position_build_score', 0)
            has_recent_golden_cross = volume_ma_info.get('has_recent_golden_cross', False)
            recent_cross_window_days = volume_ma_info.get('recent_cross_window_days', 7)

            volume_gate_ok = tuo_gates.volume_gate_ok
            if not is_rsi_rebound_signal and not tuo_gates.secondary_gate_ok:
                print(
                    f"⏭️  {symbol} 建仓评分不足(<{MIN_POSITION_BUILD_SCORE:g})，且未出现完整托或左侧托预确认（{duanxian_tuo_text}），跳过 Telegram 买入推送"
                )
                append_signal_audit({'event': 'gate_blocked', 'symbol': symbol, 'signal_id': signal_id, 'position_build_score': position_build_score, 'has_recent_golden_cross': has_recent_golden_cross, 'duanxian_tuo': duanxian_tuo_text})
                return False

            recent_crosses = [cross.replace('上穿', 'x') for cross in recent_golden_crosses]
            if current_above_ma:
                detail = ", ".join(
                    f"{label}日({current_multiple_vs_ma.get(label, 0):.2f}x)"
                    for label in current_above_ma
                )
                volume_spike_text = f"现量≥{volume_spike_threshold:.1f}x {detail}"
            else:
                volume_spike_text = "暂无"

        earn_note = earnings_proximity_note(symbol)
        msg = format_signal_snapshot(
            title=signal_title or ("📈反弹抄底信号" if is_rsi_rebound_signal else "📈 买入信号提醒"),
            symbol=symbol,
            price=price,
            score=score,
            backtest_text=backtest_str[1:-1] if backtest_str else None,
            min_buy_price=min_buy_price,
            max_buy_price=max_buy_price,
            buy_time=buy_time,
            target_price=target_price,
            stop_loss=stop_loss,
            ai_win_rate=ai_win_rate,
            rsi_prev=rsi_prev,
            rsi=rsi,
            dif=dif,
            dea=dea,
            dif_dea_slope=dif_dea_slope,
            volume_ratio=(volume_ratio / 100.0) if volume_ratio is not None else None,
            turnover_rate=turnover_rate,
            recent_crosses=recent_crosses,
            volume_spike_text=volume_spike_text,
            position_build_score=position_build_score,
            duanxian_tuo_text=duanxian_tuo_text,
            telegram_html=True,
            stock_cn_name=stock_cn_name,
            opening_uncertain_warning=opening_uncertain,
            earnings_note=earn_note,
            stock_character_info=stock_character_info,
            rsi_rebound_volatility=rsi_rebound_volatility,
        )
        reply_markup = {
            "inline_keyboard": [
                [{"text": "🤖 AI分析", "callback_data": f"ai_analysis:{symbol}"}],
                [{"text": "📊 查基本面", "callback_data": f"fundamental:{symbol}"}]
            ]
        }
        success = self.send_message(msg, reply_markup=reply_markup)

        if success:
            _global_push_cache[symbol] = current_time
            append_signal_audit({'event': 'sent', 'symbol': symbol, 'signal_id': signal_id})
        elif queue_on_fail:
            append_signal_audit({'event': 'send_failed', 'symbol': symbol, 'signal_id': signal_id})
            self._queue_pending_message(symbol, msg, reply_markup, signal_id=signal_id, parse_mode='HTML')

        return success


def parse_telegram_chat_ids(chat_id: str) -> List[str]:
    """Parse one or more Telegram chat IDs. First ID is primary; rest are best-effort forwards."""
    out = []
    for item in re.split(r"[\s,;]+", str(chat_id or "")):
        item = item.strip()
        if item and item not in out:
            out.append(item)
    return out or [str(chat_id).strip()]


def load_telegram_token(token_path: str = None) -> Tuple[str, str]:
    """
    从 token 文件加载 Telegram 配置

    Args:
        token_path: token 文件路径，默认为 indicator/telegram.token

    Returns:
        Tuple[str, str]: (bot_token, chat_id)

    Raises:
        FileNotFoundError: token 文件不存在
        ValueError: token 文件格式不正确
    """
    if token_path is None:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        token_path = os.path.join(current_dir, "telegram.token")

    if not os.path.exists(token_path):
        raise FileNotFoundError(f"Telegram token 文件不存在: {token_path}")

    with open(token_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]

    if len(lines) < 2:
        raise ValueError("Telegram token 文件格式不正确，需要两行：第一行是 Bot Token，第二行是 Chat ID")

    chat_ids = parse_telegram_chat_ids(" ".join(lines[1:]))
    return lines[0], " ".join(chat_ids)
