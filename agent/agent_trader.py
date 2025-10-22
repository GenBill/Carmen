import time
import re
from datetime import datetime
from deepseek import DeepSeekAPI
from okx_api import OKXTrader
from state_manager import StateManager
from position_manager import PositionManager
import logging
import os
from logging.handlers import RotatingFileHandler

from prompts import build_system_prompt, build_trading_prompt


class TradingAgent:
    def __init__(
        self,
        deepseek_token_path="agent/deepseek.token",
        okx_token_path="agent/okx.token",
        enable_prompt_log=True,
        log_file="logs/trading_log.txt",
        prompt_log_file="logs/prompt_log.txt",
        log_level="INFO",
        contra_mode=False,
    ):
        """初始化交易agent"""
        self.okx = OKXTrader(okx_token_path)
        
        # 超级反指模式：AI 永远是错的，反着做
        self.contra_mode = contra_mode

        # 构建系统提示词
        self.system_prompt = build_system_prompt()
        self.deepseek = DeepSeekAPI(
            deepseek_token_path, self.system_prompt, "deepseek-chat"
        )

        # 设置日志
        # 转换为绝对路径
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_file = os.path.join(project_root, log_file)
        prompt_log_file = os.path.join(project_root, prompt_log_file)

        # 创建日志目录（如果不存在）
        log_dir = os.path.dirname(log_file)
        os.makedirs(log_dir, exist_ok=True)
        prompt_log_dir = os.path.dirname(prompt_log_file)
        os.makedirs(prompt_log_dir, exist_ok=True)

        # 设置常规日志
        logger = logging.getLogger(__name__)
        logger.setLevel(getattr(logging, log_level.upper()))

        # 添加旋转文件处理器
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)

        # 添加控制台处理器作为回退（带颜色）
        class _ColorFormatter(logging.Formatter):
            COLORS = {
                "DEBUG": "\x1b[37m",  # 白
                "INFO": "\x1b[36m",  # 青
                "WARNING": "\x1b[33m",  # 黄
                "ERROR": "\x1b[31m",  # 红
                "CRITICAL": "\x1b[41m",  # 红底
            }
            RESET = "\x1b[0m"

            def format(self, record):
                color = self.COLORS.get(record.levelname, "")
                message = super().format(record)
                return f"{color}{message}{self.RESET}"

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            _ColorFormatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        console_handler.setLevel(logging.WARNING)
        logger.addHandler(console_handler)

        self.logger = logger

        # Prompt日志开关
        self.enable_prompt_log = enable_prompt_log
        if self.enable_prompt_log:
            self.prompt_logger = logging.getLogger("prompt_logger")
            self.prompt_logger.setLevel(getattr(logging, log_level.upper()))
            # 阻止prompt日志传播到根日志器，避免输出到控制台
            self.prompt_logger.propagate = False

            # 创建专门的prompt日志旋转处理器
            prompt_handler = RotatingFileHandler(
                prompt_log_file,
                maxBytes=5 * 1024 * 1024,  # 5MB
                backupCount=3,
                encoding="utf-8",
            )
            prompt_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
            self.prompt_logger.addHandler(prompt_handler)

            # 不向控制台输出prompt，仅写入文件日志

        # 状态管理器
        self.state_manager = StateManager(okx_trader=self.okx)
        # 仓位管理器
        self.positions_manager = PositionManager(self.okx, self.logger)

        # 交易统计（从状态管理器获取）
        self.start_time = self.state_manager.get_start_time()
        self.invocation_count = self.state_manager.get_invocation_count()

        # 显示状态信息
        self.logger.info(
            f"系统状态: 会话 {self.state_manager.get_session_count()}, 调用次数 {self.invocation_count}"
        )
        self.logger.info(f"起始时间: {self.start_time}")
        self.logger.info(
            f"起始资金: ${self.state_manager.get_initial_account_value():,.2f}"
        )
        
        # 反指模式提醒
        if self.contra_mode:
            self.logger.warning("🔄 超级反指模式已启用！AI的所有决策将被反转执行！")

    def _parse_trading_decisions(self, response):
        """解析AI的交易决策"""
        try:
            decisions = {}
            lines = response.split("\n")

            # 查找TRADING_DECISIONS部分
            in_decisions = False
            current_coin = None

            for line in lines:
                original_line = line  # 保留原始用于日志
                line = line.strip().upper()  # 添加：规范化大小写和去除空格

                if line == "▶TRADING_DECISIONS":
                    in_decisions = True
                    continue

                if in_decisions:
                    # 跳过空行
                    if not line:
                        continue

                    # 检查是否是币种名称 - 添加 upper() 和简单正则以处理变体
                    coin_match = re.match(r"^([A-Z]{3,4})(?:[:\s-]*.*)?$", line)
                    if coin_match and coin_match.group(1) in [
                        "BTC",
                        "ETH",
                        "SOL",
                        "BNB",
                        "DOGE",
                        "XRP",
                    ]:
                        current_coin = coin_match.group(1)
                        continue

                    # 检查是否是交易信号 - 添加 upper() 和简单正则
                    signal_match = re.match(
                        r"^(BUY|SELL|HOLD|CLOSE)(?:[:\s-]*.*)?$", line
                    )
                    if current_coin and signal_match:
                        decisions[current_coin] = {
                            "signal": signal_match.group(1),
                            "confidence": 0.0,
                            "quantity": 0,
                            "leverage": 10,
                        }
                        continue

                    # 解析置信度 - 改进正则以处理更多变体（如 "Confidence: 85 %")
                    if current_coin and "%" in line and re.search(r"confidence", line, re.IGNORECASE):
                        try:
                            confidence_match = re.search(
                                r"(?:confidence)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*%",
                                line,
                                re.IGNORECASE,
                            )
                            if confidence_match:
                                confidence = float(confidence_match.group(1)) / 100
                                confidence = max(0.0, min(1.0, confidence))
                                decisions[current_coin]["confidence"] = confidence
                                self.logger.debug(
                                    f"解析到 {current_coin} 置信度: {confidence:.2%}"
                                )
                        except Exception as e:
                            self.logger.warning(
                                f"解析置信度失败: {original_line}, 错误: {e}"
                            )
                        continue

                    # 解析仓位大小 - 改进正则以处理更多变体（如 "POSITION_SIZE: 10%")
                    if current_coin and "%" in line and re.search(r"position_size", line, re.IGNORECASE):
                        try:
                            position_size_match = re.search(
                                r"(?:position_size)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*%",
                                line,
                                re.IGNORECASE,
                            )
                            if position_size_match:
                                position_size = float(position_size_match.group(1))
                                if position_size > 0:
                                    decisions[current_coin]["position_size"] = (
                                        position_size
                                    )
                                    self.logger.debug(
                                        f"解析到 {current_coin} 仓位大小: {position_size}%"
                                    )
                                else:
                                    self.logger.warning(
                                        f"仓位大小超出合理范围: {position_size}"
                                    )
                        except Exception as e:
                            self.logger.warning(
                                f"解析仓位大小失败: {original_line}, 错误: {e}"
                            )
                        continue

                    # 解析止盈点 - 重新启用自动止盈功能
                    if current_coin and re.search(r"take_profit", line, re.IGNORECASE):
                        try:
                            tp_match = re.search(
                                r"(?:take_profit)?\s*[:=]?\s*(\d+(?:\.\d+)?)",
                                line,
                                re.IGNORECASE,
                            )
                            if tp_match:
                                take_profit = float(tp_match.group(1))
                                if take_profit > 0:
                                    decisions[current_coin]["take_profit"] = take_profit
                                    self.logger.debug(
                                        f"解析到 {current_coin} 止盈点: {take_profit}"
                                    )
                        except Exception as e:
                            self.logger.warning(
                                f"解析止盈点失败: {original_line}, 错误: {e}"
                            )
                        continue

                    # 解析入场价 ENTRY_PRICE - 处理 "ENTRY_PRICE: 50000" 格式
                    if current_coin and re.search(r"entry_price", line, re.IGNORECASE):
                        try:
                            ep_match = re.search(
                                r"(?:entry_price)?\s*[:=]?\s*(\d+(?:\.\d+)?)",
                                line,
                                re.IGNORECASE,
                            )
                            if ep_match:
                                entry_price = float(ep_match.group(1))
                                if entry_price > 0:
                                    decisions[current_coin]["entry_price"] = entry_price
                                    self.logger.debug(
                                        f"解析到 {current_coin} 入场价: {entry_price}"
                                    )
                        except Exception as e:
                            self.logger.warning(
                                f"解析入场价失败: {original_line}, 错误: {e}"
                            )
                        continue

                    # 杠杆固定为10倍，不需要解析
                    # 所有交易都使用10倍杠杆

            return decisions

        except Exception as e:
            self.logger.error(f"解析交易决策失败: {e}")
            self.logger.error(f"AI响应: {response}")
            return {}

    def _reverse_positions(self, positions):
        """反转仓位信息（用于反指模式）"""
        if not self.contra_mode or not positions:
            return positions
        
        reversed_positions = {}
        for coin, pos in positions.items():
            reversed_pos = pos.copy()
            # 反转持仓方向
            if pos['side'] == 'long':
                reversed_pos['side'] = 'short'
            elif pos['side'] == 'short':
                reversed_pos['side'] = 'long'
            
            # 反转盈亏（让 AI 以为亏的是赚的，赚的是亏的）
            reversed_pos['unrealized_pnl'] = -pos['unrealized_pnl']
            reversed_pos['percentage'] = -pos.get('percentage', 0)
            
            reversed_positions[coin] = reversed_pos
            
        self.logger.debug(f"反指模式：已反转 {len(reversed_positions)} 个仓位信息")
        return reversed_positions

    def _reverse_decisions(self, decisions):
        """反转 AI 决策（用于反指模式）"""
        if not self.contra_mode or not decisions:
            return decisions
        
        reversed_decisions = {}
        for coin, decision in decisions.items():
            reversed_dec = decision.copy()
            signal = decision.get('signal', '')
            
            # 反转交易信号
            signal_map = {
                'BUY': 'SELL',
                'SELL': 'BUY',
                'CLOSE&BUY': 'CLOSE&SELL',
                'CLOSE&SELL': 'CLOSE&BUY',
                'HOLD': 'HOLD',  # HOLD 保持不变
                'CLOSE': 'CLOSE',  # CLOSE 保持不变
            }
            reversed_dec['signal'] = signal_map.get(signal, signal)
            
            # 互换止盈止损（AI 的止盈变我们的止损，AI 的止损变我们的止盈）
            # 注意：这里只是互换概念，实际上反指模式下我们不设置止损点
            if 'take_profit' in decision and 'stop_loss' in decision:
                reversed_dec['take_profit'] = decision.get('stop_loss', 0)
                reversed_dec['stop_loss'] = decision.get('take_profit', 0)
            
            reversed_decisions[coin] = reversed_dec
            
            if signal != 'HOLD':
                self.logger.warning(
                    f"🔄 反指模式：{coin} {signal} → {reversed_dec['signal']}"
                )
        
        return reversed_decisions

    def execute_trading_decisions(self, decisions, open_gate=0.75, action_gate=0.75):
        """执行交易决策"""
        # 反指模式：反转 AI 的决策
        decisions = self._reverse_decisions(decisions)
        
        executed_trades = []

        # 检查账户状态
        try:
            account_info = self.okx.get_account_info()
            if not account_info:
                self.logger.error("无法获取账户信息，跳过交易")
                return executed_trades

            # 检查账户余额
            if account_info["free_usdt"] < 10:  # 至少需要 10 USDT
                self.logger.error(f"账户余额不足: {account_info['free_usdt']} USDT")
                return executed_trades

            self.logger.info(
                f"账户状态正常: 可用余额 {account_info['free_usdt']:.2f} USDT"
            )
        except Exception as e:
            self.logger.error(f"检查账户状态失败: {e}")
            return executed_trades

        # 获取当前持仓
        current_positions = self.okx.get_positions()

        # 全局总margin used（现有）
        total_margin_used = sum(
            pos.get("margin_used", 0)
            for pos in current_positions.values()
        )

        # 先处理所有CLOSE以降低风险
        for coin, decision in decisions.items():
            signal = decision.get("signal")
            if (
                signal in ["CLOSE", "CLOSE&SELL", "CLOSE&BUY"]
                and coin in current_positions
                and decision.get("confidence", 0.0) >= action_gate
            ):
                coin_symbol = f"{coin}/USDT:USDT"

                # 在执行平仓前重新获取最新持仓信息
                self.logger.info(f"准备平仓 {coin}，重新获取最新持仓信息...")
                latest_positions = self.okx.get_positions(verbose=False)

                if coin not in latest_positions:
                    self.logger.warning(f"{coin} 在最新持仓中未找到，可能已经平仓")
                    continue

                latest_position = latest_positions[coin]
                self.logger.info(
                    f"{coin} 最新持仓: {latest_position.get('side', 'unknown')} {latest_position.get('size', 0)} @ {latest_position.get('entry_price', 0)}"
                )

                order = self.okx.close_position(coin_symbol)
                if order:
                    trade_record = {
                        "coin": coin,
                        "action": "close_position",
                        "quantity": 0,
                        "confidence": 1.0,
                        "order_id": order["id"],
                        "success": True,
                        "pnl": 0.0,
                    }
                    executed_trades.append(trade_record)
                    self.state_manager.add_trade_record(trade_record)
                    self.logger.warning(f"成功平仓 {coin} - 订单ID: {order['id']}")

                    # 更新total_margin_used（减去该仓的margin）
                    closed_margin = latest_position.get("margin_used", 0)
                    total_margin_used -= closed_margin
                    self.logger.info(
                        f"CLOSE {coin} 后，总margin used降至 {total_margin_used:.2f}"
                    )
                    
                    # 重新获取账户信息（平仓后used_usdt会变化）
                    account_info = self.okx.get_account_info()
                else:
                    self.logger.error(f"平仓 {coin} 失败")

        # 然后处理其他决策
        for coin, decision in decisions.items():
            try:
                signal = decision.get("signal")
                confidence = decision.get("confidence", 0.0)
                position_size = decision.get("position_size", 0)
                entry_price = decision.get("entry_price", 0)
                coin_symbol = f"{coin}/USDT:USDT"

                # 处理entry_price逻辑
                order_type = "limit"
                if entry_price <= 0:
                    # 如果AI没有提供entry_price或为0，使用市价单
                    order_type = "market"
                    current_price = self.okx.get_current_price(coin_symbol)
                    if current_price and current_price > 0:
                        entry_price = current_price
                        self.logger.debug(
                            f"AI未提供entry_price，使用当前价格: {entry_price}"
                        )
                    else:
                        self.logger.error(f"无法获取 {coin} 当前价格，跳过交易")
                        continue

                # 计算quantity（从POSITION_SIZE和ENTRY_PRICE）
                quantity = 0
                leverage = 10
                total_equity = account_info["total_usdt"]
                
                if signal in ["BUY", "SELL"] and position_size > 0 and entry_price > 0:
                    # QUANTITY = (POSITION_SIZE / 100) * TOTAL_EQUITY * LEVERAGE / ENTRY_PRICE
                    quantity = (
                        (position_size / 100) * total_equity * leverage / entry_price
                    )
                    self.logger.debug(
                        f"计算 {coin} quantity: {position_size}% * {total_equity} * {leverage} / {entry_price} = {quantity}"
                    )

                # 验证（添加'CLOSE&SELL'和'CLOSE&BUY'支持）
                if not signal or signal not in ["BUY", "SELL", "HOLD", "CLOSE", "CLOSE&SELL", "CLOSE&BUY"]:
                    self.logger.error(f"无效的交易信号: {signal}")
                    continue

                if signal in ["BUY", "SELL", "CLOSE&SELL", "CLOSE&BUY"] and (quantity <= 0):
                    self.logger.info(f"跳过 {signal} {coin}: 无效参数")

                    continue
                
                if signal in ["BUY", "SELL", "CLOSE&SELL", "CLOSE&BUY"] and (confidence < open_gate):
                    self.logger.info(f"跳过 {signal} {coin}: 置信度不足")
                    continue

                # per-coin处理
                has_position = coin in current_positions
                position_side = (
                    current_positions[coin]["side"] if has_position else None
                )

                if signal == "CLOSE":
                    continue  # 已在前循环处理

                if signal == "HOLD" and confidence >= action_gate:
                    if has_position:
                        # 重新启用自动止盈功能，只更新止盈点
                        take_profit = decision.get("take_profit", 0.0)
                        if take_profit > 0:
                            position_data = current_positions[coin].copy()
                            position_data["take_profit"] = take_profit
                            # 不更新止损点，让AI扛单
                            self.positions_manager.update_position(coin, position_data)
                            self.logger.info(
                                f"HOLD {coin} 更新止盈点: TP={take_profit}"
                            )
                        self.logger.info(f"持有 {coin}")
                        executed_trades.append(
                            {"coin": coin, "action": "hold", "confidence": confidence}
                        )
                    continue

                if signal in ["BUY", "CLOSE&BUY", "SELL", "CLOSE&SELL"]:
                    new_side = "long" if signal in ["BUY", "CLOSE&BUY"] else "short"
                    if has_position and position_side != new_side:
                        self.logger.warning(
                            f"{coin} 方向冲突 ({position_side} vs {new_side})，执行 CLOSE 以最小化风险"
                        )
                        order = self.okx.close_position(coin_symbol)
                        if order:
                            trade_record = {
                                "coin": coin,
                                "action": "close_position",
                                "quantity": 0,
                                "confidence": confidence,
                                "order_id": order["id"],
                                "success": True,
                                "pnl": 0.0,
                            }
                            executed_trades.append(trade_record)
                            self.state_manager.add_trade_record(trade_record)
                            self.logger.warning(
                                f"成功关闭冲突仓位 {coin} - 订单ID: {order['id']}"
                            )
                        else:
                            self.logger.error(f"关闭冲突仓位 {coin} 失败")
                        continue  # 跳过新开仓

                    # 计算所需保证金并检查后总used（已考虑CLOSE）
                    current_price = self.okx.get_current_price(coin_symbol)
                    if not current_price:
                        continue

                    # 简单的仓位占比检查：当前仓位占比 + 新仓位占比 < 90%
                    current_position_ratio = (account_info["used_usdt"] / account_info["total_usdt"]) * 100
                    total_ratio = current_position_ratio + position_size
                    
                    if total_ratio > 90:
                        self.logger.warning(f"{coin} 仓位占比超限: 当前{current_position_ratio:.1f}% + 新增{position_size}% = {total_ratio:.1f}% > 90%，跳过")
                        continue

                    # 计算新仓位的保证金（用于日志记录）
                    new_margin = (quantity * current_price) / 10
                    projected_used = total_margin_used + new_margin

                    # 执行开仓
                    order = self.okx.place_order(
                        coin_symbol,
                        signal.lower(),
                        quantity,
                        price=entry_price,
                        order_type=order_type,
                        leverage=10,
                    )
                    if order and "id" in order:
                        trade_record = {
                            "coin": coin,
                            "action": signal.lower(),
                            "quantity": quantity,
                            "confidence": confidence,
                            "order_id": order["id"],
                            "success": True,
                            "pnl": 0.0,
                        }
                        executed_trades.append(trade_record)
                        self.state_manager.add_trade_record(trade_record)

                        # 重新启用自动止盈功能，只设置止盈点
                        take_profit = decision.get("take_profit", 0.0)
                        if take_profit > 0:
                            # 获取当前仓位信息并添加止盈点
                            current_positions = self.okx.get_positions()
                            if coin in current_positions:
                                position_data = current_positions[coin].copy()
                                position_data["take_profit"] = take_profit
                                # 不设置止损点，让AI扛单
                                self.positions_manager.update_position(
                                    coin, position_data
                                )
                                self.logger.info(
                                    f"设置 {coin} 止盈点: TP={take_profit}"
                                )

                        self.logger.warning(
                            f"{signal} {coin} {quantity} (置信度: {confidence:.1%}) - 订单ID: {order['id']}"
                        )
                    else:
                        self.logger.error(f"{signal} {coin} 失败")
                        trade_record = {
                            "coin": coin,
                            "action": signal.lower(),
                            "quantity": quantity,
                            "confidence": confidence,
                            "order_id": None,
                            "success": False,
                            "pnl": 0.0,
                            "error": "订单创建失败",
                        }
                        executed_trades.append(trade_record)
                        self.state_manager.add_trade_record(trade_record)

            except Exception as e:
                self.logger.error(f"处理 {coin} 失败: {e}")
                trade_record = {
                    "coin": coin,
                    "action": signal,
                    "quantity": quantity,
                    "confidence": confidence,
                    "order_id": None,
                    "success": False,
                    "pnl": 0.0,
                    "error": str(e),
                }
                executed_trades.append(trade_record)
                self.state_manager.add_trade_record(trade_record)

        return executed_trades

    def show_performance_summary(self):
        """显示性能摘要"""
        summary = self.state_manager.get_performance_summary()

        self.logger.info("=" * 60)
        self.logger.info("交易性能摘要")
        self.logger.info("=" * 60)
        self.logger.info(f"起始时间: {summary['start_time']}")
        self.logger.info(f"起始资金: ${summary['initial_value']:,.2f}")
        self.logger.info(f"当前PnL: ${summary['total_pnl']:,.2f}")
        self.logger.info(f"总收益率: {summary['total_return_pct']:.2f}%")
        self.logger.info(f"总交易次数: {summary['total_trades']}")
        self.logger.info(f"成功交易: {summary['successful_trades']}")
        self.logger.info(f"失败交易: {summary['failed_trades']}")
        self.logger.info(f"胜率: {summary['win_rate']:.2%}")
        self.logger.info(f"最大回撤: ${summary['max_drawdown']:,.2f}")
        self.logger.info(f"最佳交易: ${summary['best_trade']:,.2f}")
        self.logger.info(f"最差交易: ${summary['worst_trade']:,.2f}")
        self.logger.info(f"会话次数: {summary['session_count']}")
        self.logger.info(f"总调用次数: {summary['invocation_count']}")
        self.logger.info(f"运行时间: {summary['elapsed_time']}")
        self.logger.info("=" * 60)

    def run_trading_cycle(self):
        """运行一个完整的交易周期"""
        try:
            # 获取市场数据
            market_data = self.okx.get_market_data()
            if not market_data:
                self.logger.error("获取市场数据失败")
                return

            # 获取账户信息
            account_info = self.okx.get_account_info()
            if not account_info:
                self.logger.error("获取账户信息失败")
                return

            # 获取当前持仓
            positions = self.okx.get_positions()
            
            # 反指模式：反转持仓信息后再传给 AI
            positions_for_ai = self._reverse_positions(positions)

            # 决策前：取消所有未成交挂单，避免旧挂单影响
            try:
                open_orders = []
                try:
                    open_orders = self.okx.exchange.fetch_open_orders()
                except Exception:
                    open_orders = []
                if open_orders:
                    cancelled = 0
                    for od in open_orders:
                        try:
                            oid = od.get("id")
                            sym = od.get("symbol")
                            if oid:
                                self.okx.exchange.cancel_order(oid, sym)
                                cancelled += 1
                        except Exception as e:
                            self.logger.error(
                                f"取消挂单失败: {od.get('id')} {od.get('symbol')} - {e}"
                            )
                    if cancelled > 0:
                        self.logger.warning(f"已取消未成交挂单 {cancelled} 个")
            except Exception as e:
                self.logger.error(f"检查/取消未成交挂单失败: {e}")

            # 构建提示词（反指模式下使用反转后的仓位信息）
            prompt = build_trading_prompt(
                market_data,
                self.state_manager,
                account_info,
                positions_for_ai,
                self.start_time,
                self.invocation_count,
            )

            # 记录prompt到专门的日志文件
            if self.enable_prompt_log:
                self.prompt_logger.info("=" * 80)
                self.prompt_logger.info(
                    f"第 {self.invocation_count} 次交易决策 - {datetime.now()}"
                )
                self.prompt_logger.info("=" * 80)
                self.prompt_logger.info("INPUT PROMPT:")
                self.prompt_logger.info(prompt)
                self.prompt_logger.info("=" * 80)

            # 获取AI决策
            self.logger.info(f"调用DeepSeek API进行交易决策...")
            response = self.deepseek(prompt)

            # 记录AI响应到专门的日志文件
            if self.enable_prompt_log:
                self.prompt_logger.info("AI RESPONSE:")
                self.prompt_logger.info(response)
                self.prompt_logger.info("=" * 80)

            # 解析决策
            decisions = self._parse_trading_decisions(response)

            if decisions:
                # 执行交易
                executed_trades = self.execute_trading_decisions(decisions)
                self.logger.info(f"交易周期完成，执行了 {len(executed_trades)} 个决策")
                return executed_trades
            else:
                self.logger.info("AI没有给出交易决策")
                return []

        except Exception as e:
            self.logger.error(f"交易周期执行失败: {e}")
            return []

    def start_trading(self, interval_minutes=1):
        """开始自动交易"""
        self.logger.info("开始自动交易...")

        # 显示性能摘要
        self.show_performance_summary()

        # 开始新会话
        self.state_manager.start_new_session()

        while True:
            try:
                self.logger.info(f"开始第 {self.invocation_count + 1} 次交易决策...")
                trades = self.run_trading_cycle()

                # 每10次交易显示一次性能摘要
                if (self.invocation_count + 1) % 10 == 0:
                    self.show_performance_summary()

                # 等待下次执行
                time.sleep(interval_minutes * 60)

            except KeyboardInterrupt:
                self.logger.info("收到停止信号，结束交易")
                # 显示最终性能摘要
                self.show_performance_summary()
                break
            except Exception as e:
                self.logger.error(f"交易循环异常: {e}")
                time.sleep(60)  # 出错时等待1分钟再继续


if __name__ == "__main__":
    agent = TradingAgent()
    agent.start_trading()
