"""
Telegram 消息推送模块
与 QQNotifier 接口兼容，使用 Telegram Bot API 发送消息
"""
import requests
import os
import time
import html
import json
from typing import Optional, Tuple, Dict

# 模块级全局缓存：{symbol: last_push_timestamp}
_global_push_cache = {}


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
        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.cache_hours = 2

        self.max_retries = 3
        self.initial_wait = 1.0
        self.max_wait = 30
        self.backoff_multiplier = 2

    def send_message(self, msg: str, reply_markup: Optional[Dict] = None) -> bool:
        """
        发送 Telegram 消息（带指数退避重试机制）

        Args:
            msg: 要发送的消息内容
            reply_markup: 可选按钮/键盘配置

        Returns:
            bool: 是否发送成功
        """
        wait_time = self.initial_wait
        if msg == "":
            print("⚠️  Telegram 推送消息为空，跳过")
            return False

        for attempt in range(self.max_retries + 1):
            try:
                data = {
                    "chat_id": self.chat_id,
                    "text": msg,
                    "disable_web_page_preview": True,
                    "parse_mode": "HTML",
                }
                if reply_markup:
                    data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
                response = requests.post(self.api_url, data=data, timeout=10)
                response.raise_for_status()

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
        current_time = time.time()
        if symbol in _global_push_cache:
            last_push_time = _global_push_cache[symbol]
            hours_passed = (current_time - last_push_time) / 3600
            if hours_passed < self.cache_hours:
                print(f"⏭️  {symbol} 在 {hours_passed:.1f} 小时前已推送过，跳过")
                return False

        safe_symbol = html.escape(symbol.replace('.SS', '[SS]').replace('.SZ', '[SZ]').replace('.HK', '[HK]'))
        msg_parts = [
            "📉 卖出信号提醒",
            f"股票: {safe_symbol}",
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
    ) -> bool:
        """发送买入信号通知（与 QQNotifier 接口兼容）"""
        current_time = time.time()
        if symbol in _global_push_cache:
            last_push_time = _global_push_cache[symbol]
            hours_passed = (current_time - last_push_time) / 3600
            if hours_passed < self.cache_hours:
                print(f"⏭️  {symbol} 在 {hours_passed:.1f} 小时前已推送过，跳过")
                return False

        safe_symbol = html.escape(symbol.replace('.SS', '[SS]').replace('.SZ', '[SZ]').replace('.HK', '[HK]'))
        pure_symbol = html.escape(symbol.replace('.SS', '').replace('.SZ', '').replace('.HK', ''))
        msg_parts = [
            "📈 买入信号提醒",
            f"股票: {safe_symbol}",
            f"代码: <code>{pure_symbol}</code>",
            f"当前价格: {price:.2f}",
            f"评分: {score:.2f}",
            f"回测胜率: {backtest_str[1:-1]}",
        ]

        if min_buy_price is not None and max_buy_price is not None:
            msg_parts.append(f"买入区间: {min_buy_price:.2f}-{max_buy_price:.2f}")
        elif max_buy_price is not None:
            msg_parts.append(f"最高买入价: {max_buy_price:.2f}")
        elif min_buy_price is not None:
            msg_parts.append(f"最低买入价: {min_buy_price:.2f}")

        if buy_time is not None:
            msg_parts.append(f"买入时间: {buy_time}")
        if target_price is not None:
            msg_parts.append(f"目标价位: {target_price:.2f}")
        if stop_loss is not None:
            msg_parts.append(f"止损位: {stop_loss:.2f}")
        if ai_win_rate is not None:
            msg_parts.append(f"AI预估胜率: {ai_win_rate*100:.1f}%")
        if rsi is not None:
            msg_parts.append(f"RSI: {rsi:.2f}")
        if volume_ratio is not None:
            msg_parts.append(f"量比: {volume_ratio:.1f}%")
        if bowl_score is not None:
            msg_parts.append(f"碗口指标: {bowl_score:.2f}")

        if volume_ma_info:
            recent_golden_crosses = volume_ma_info.get('recent_golden_crosses') or []
            current_above_ma = volume_ma_info.get('current_above_ma') or []
            current_multiple_vs_ma = volume_ma_info.get('current_multiple_vs_ma') or {}
            volume_spike_threshold = volume_ma_info.get('volume_spike_threshold', 4.0)
            build_strength = volume_ma_info.get('build_position_strength', 0)
            has_recent_golden_cross = volume_ma_info.get('has_recent_golden_cross', False)
            recent_cross_window_days = volume_ma_info.get('recent_cross_window_days', 7)

            if (not has_recent_golden_cross) or build_strength < 6:
                print(f"⏭️  {symbol} 近{recent_cross_window_days}日内未出现量能金叉或建仓强度不足，跳过 Telegram 买入推送")
                return False

            if recent_golden_crosses:
                compact_crosses = []
                for cross in recent_golden_crosses:
                    compact_crosses.append(cross.replace('上穿', 'x'))
                msg_parts.append(f"近{recent_cross_window_days}日量能金叉: {' / '.join(compact_crosses)}")
            else:
                msg_parts.append(f"近{recent_cross_window_days}日量能金叉: 暂无")

            if current_above_ma:
                detail = ", ".join(
                    f"{label}日({current_multiple_vs_ma.get(label, 0):.2f}x)"
                    for label in current_above_ma
                )
                msg_parts.append(f"异常爆量: 现量≥{volume_spike_threshold:.1f}x {detail}")
            else:
                msg_parts.append("异常爆量: 暂无")

            if build_strength >= 6:
                msg_parts.append("建仓强度: 很强")
            elif build_strength >= 4:
                msg_parts.append("建仓强度: 中等偏强")
            elif build_strength >= 2:
                msg_parts.append("建仓强度: 初步抬升")
            else:
                msg_parts.append("建仓强度: 暂不明显")

        msg = "\n".join(msg_parts)
        reply_markup = {
            "inline_keyboard": [[
                {"text": "🤖 AI分析", "callback_data": f"ai_analysis:{symbol}"}
            ]]
        }
        success = self.send_message(msg, reply_markup=reply_markup)

        if success:
            _global_push_cache[symbol] = current_time

        return success


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

    return lines[0], lines[1]
