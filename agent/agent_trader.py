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
    ):
        """初始化交易agent"""
        self.okx = OKXTrader(okx_token_path)
        # 新：设置全仓模式
        try:
            self.okx.exchange.set_margin_mode("cross", "USDT")
            self.logger.info("设置margin mode为cross（全仓）")
        except Exception as e:
            self.logger.error(f"设置margin mode失败: {e}")

        # 构建系统提示词
        self.system_prompt = build_system_prompt()
        self.deepseek = DeepSeekAPI(deepseek_token_path, self.system_prompt)

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

        # 添加控制台处理器作为回退
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(console_handler)

        self.logger = logger

        # Prompt日志开关
        self.enable_prompt_log = enable_prompt_log
        if self.enable_prompt_log:
            self.prompt_logger = logging.getLogger("prompt_logger")
            self.prompt_logger.setLevel(getattr(logging, log_level.upper()))

            # 创建专门的prompt日志旋转处理器
            prompt_handler = RotatingFileHandler(
                prompt_log_file,
                maxBytes=5 * 1024 * 1024,  # 5MB
                backupCount=3,
                encoding="utf-8",
            )
            prompt_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
            self.prompt_logger.addHandler(prompt_handler)

            # 添加控制台处理器作为回退
            self.prompt_logger.addHandler(console_handler)

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
                    if current_coin and "%" in line:
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

                    # 解析数量 - 改进正则以处理更多变体（如 "Quantity = 0.1")
                    if current_coin and re.search(r"quantity", line, re.IGNORECASE):
                        try:
                            quantity_match = re.search(
                                r"(?:quantity)?\s*[:=]?\s*(\d+(?:\.\d+)?)",
                                line,
                                re.IGNORECASE,
                            )
                            if quantity_match:
                                quantity = float(quantity_match.group(1))
                                if quantity > 0:
                                    decisions[current_coin]["quantity"] = quantity
                                    self.logger.debug(
                                        f"解析到 {current_coin} 数量: {quantity}"
                                    )
                                else:
                                    self.logger.warning(f"数量超出合理范围: {quantity}")
                        except Exception as e:
                            self.logger.warning(
                                f"解析数量失败: {original_line}, 错误: {e}"
                            )
                        continue

                    # 解析止盈点 - 处理 "TAKE_PROFIT: 50000" 格式
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

                    # 解析止损点 - 处理 "STOP_LOSS: 45000" 格式
                    if current_coin and re.search(r"stop_loss", line, re.IGNORECASE):
                        try:
                            sl_match = re.search(
                                r"(?:stop_loss)?\s*[:=]?\s*(\d+(?:\.\d+)?)",
                                line,
                                re.IGNORECASE,
                            )
                            if sl_match:
                                stop_loss = float(sl_match.group(1))
                                if stop_loss > 0:
                                    decisions[current_coin]["stop_loss"] = stop_loss
                                    self.logger.debug(
                                        f"解析到 {current_coin} 止损点: {stop_loss}"
                                    )
                        except Exception as e:
                            self.logger.warning(
                                f"解析止损点失败: {original_line}, 错误: {e}"
                            )
                        continue

                    # 杠杆固定为10倍，不需要解析
                    # 所有交易都使用10倍杠杆

            return decisions

        except Exception as e:
            self.logger.error(f"解析交易决策失败: {e}")
            self.logger.error(f"AI响应: {response}")
            return {}

    def execute_trading_decisions(self, decisions, open_gate=0.7, action_gate=0.5):
        """执行交易决策"""
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
            pos.get("position_value", 0) / pos.get("leverage", 10)
            for pos in current_positions.values()
        )

        # 先处理所有CLOSE以降低风险
        for coin, decision in decisions.items():
            if (
                decision.get("signal") == "CLOSE"
                and coin in current_positions
                and decision.get("confidence", 0.0) >= action_gate
            ):
                coin_symbol = f"{coin}/USDT:USDT"
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
                    self.logger.info(f"成功平仓 {coin} - 订单ID: {order['id']}")

                    # 更新total_margin_used（减去该仓的margin）
                    closed_margin = (
                        current_positions[coin].get("position_value", 0) / 10
                    )
                    total_margin_used -= closed_margin
                    self.logger.info(
                        f"CLOSE {coin} 后，总margin used降至 {total_margin_used:.2f}"
                    )
                else:
                    self.logger.error(f"平仓 {coin} 失败")

        # 然后处理其他决策
        for coin, decision in decisions.items():
            try:
                signal = decision.get("signal")
                confidence = decision.get("confidence", 0.0)
                quantity = decision.get("quantity", 0)
                coin_symbol = f"{coin}/USDT:USDT"

                # 验证（添加'CLOSE'支持，但CLOSE已处理）
                if not signal or signal not in ["BUY", "SELL", "HOLD", "CLOSE"]:
                    self.logger.error(f"无效的交易信号: {signal}")
                    continue

                if signal in ["BUY", "SELL"] and (
                    quantity <= 0 or confidence < open_gate
                ):
                    self.logger.info(f"跳过 {signal} {coin}: 无效参数或置信度不足")
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
                        self.logger.info(f"持有 {coin}")
                        executed_trades.append(
                            {"coin": coin, "action": "hold", "confidence": confidence}
                        )
                    continue

                if signal in ["BUY", "SELL"]:
                    new_side = "long" if signal == "BUY" else "short"
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
                            self.logger.info(
                                f"成功关闭冲突仓位 {coin} - 订单ID: {order['id']}"
                            )
                        else:
                            self.logger.error(f"关闭冲突仓位 {coin} 失败")
                        continue  # 跳过新开仓

                    # 计算所需保证金并检查后总used（已考虑CLOSE）
                    current_price = self.okx.get_current_price(coin_symbol)
                    if not current_price:
                        continue
                    new_margin = (quantity * current_price) / 10  # 10x
                    projected_used = total_margin_used + new_margin
                    if projected_used > account_info["total_usdt"] * 0.8:
                        self.logger.warning(
                            f"{coin} 开仓后总保证金使用过高 ({projected_used:.2f} > {account_info['total_usdt'] * 0.8:.2f})，跳过"
                        )
                        continue

                    # 执行开仓
                    order = self.okx.place_order(
                        coin_symbol,
                        signal.lower(),
                        quantity,
                        order_type="market",
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

                        # 更新仓位管理器中的止盈止损点
                        take_profit = decision.get("take_profit", 0.0)
                        stop_loss = decision.get("stop_loss", 0.0)
                        if take_profit > 0 or stop_loss > 0:
                            # 获取当前仓位信息并添加止盈止损点
                            current_positions = self.okx.get_positions()
                            if coin in current_positions:
                                position_data = current_positions[coin].copy()
                                position_data["take_profit"] = take_profit
                                position_data["stop_loss"] = stop_loss
                                self.positions_manager.update_position(
                                    coin, position_data
                                )
                                self.logger.info(
                                    f"设置 {coin} 止盈止损: TP={take_profit}, SL={stop_loss}"
                                )

                        self.logger.info(
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

            # 构建提示词
            prompt = build_trading_prompt(
                market_data,
                self.state_manager,
                account_info,
                positions,
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
                if self.invocation_count % 10 == 0:
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
