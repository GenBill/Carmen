import time
import threading
from typing import Dict, Any, Optional


class PositionManager:
    """仓位管理器 - 管理当前仓位信息和止盈止损"""

    def __init__(self, okx_trader, logger):
        self.okx = okx_trader
        self.logger = logger
        self.positions = {}  # 存储仓位信息，包括止盈止损
        self.monitoring = False
        self.monitor_thread = None

    def update_position(self, coin: str, position_data: Dict[str, Any]):
        """更新仓位信息（包括止盈止损点）"""
        self.positions[coin] = position_data
        self.logger.info(
            f"更新 {coin} 仓位信息: 止盈={position_data.get('take_profit', 0)}, 止损={position_data.get('stop_loss', 0)}"
        )

    def remove_position(self, coin: str):
        """移除仓位信息"""
        if coin in self.positions:
            del self.positions[coin]
            self.logger.info(f"移除 {coin} 仓位信息")

    def start_monitoring(self):
        """启动止盈止损监控"""
        if not self.monitoring:
            self.monitoring = True
            self.monitor_thread = threading.Thread(
                target=self._monitor_loop, daemon=True
            )
            self.monitor_thread.start()
            self.logger.info("启动止盈止损监控")

    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1)
        self.logger.info("停止止盈止损监控")

    def _sync_positions_from_okx(self):
        """从OKX同步仓位数据到本地positions"""
        try:
            # 从OKX获取实际仓位数据
            okx_positions = self.okx.get_positions()

            # 清理本地positions中不存在的仓位
            local_coins = set(self.positions.keys())
            okx_coins = set(okx_positions.keys())

            # 移除OKX中不存在的仓位
            for coin in local_coins - okx_coins:
                self.logger.info(f"仓位 {coin} 在OKX中不存在，清理本地记录")
                del self.positions[coin]

            # 更新或添加OKX中的仓位
            for coin, okx_pos in okx_positions.items():
                if coin in self.positions:
                    # 更新现有仓位的基本信息（价格、PnL等）
                    self.positions[coin].update(
                        {
                            "current_price": okx_pos["current_price"],
                            "unrealized_pnl": okx_pos["unrealized_pnl"],
                            "size": okx_pos["size"],
                            "entry_price": okx_pos["entry_price"],
                            "side": okx_pos["side"],
                            "leverage": okx_pos["leverage"],
                            "position_value": okx_pos.get(
                                "position_value",
                                abs(okx_pos["size"]) * okx_pos["current_price"],
                            ),
                            "margin_used": okx_pos.get("margin_used", 0),
                        }
                    )
                else:
                    # 添加新仓位（保留止盈止损为0，需要后续手动设置）
                    self.positions[coin] = {
                        "current_price": okx_pos["current_price"],
                        "unrealized_pnl": okx_pos["unrealized_pnl"],
                        "size": okx_pos["size"],
                        "entry_price": okx_pos["entry_price"],
                        "side": okx_pos["side"],
                        "leverage": okx_pos["leverage"],
                        "position_value": okx_pos.get(
                            "position_value",
                            abs(okx_pos["size"]) * okx_pos["current_price"],
                        ),
                        "margin_used": okx_pos.get("margin_used", 0),
                        "take_profit": 0.0,
                        "stop_loss": 0.0,
                    }
                    self.logger.info(f"发现新仓位 {coin}，已添加到本地记录")

            self.logger.debug(
                f"仓位同步完成，当前本地仓位: {list(self.positions.keys())}"
            )

        except Exception as e:
            self.logger.error(f"同步仓位数据失败: {e}")

    def _monitor_loop(self):
        """监控循环 - 每30秒检查一次"""
        while self.monitoring:
            try:
                # 先同步仓位数据
                self._sync_positions_from_okx()
            except Exception as e:
                self.logger.error(f"同步仓位数据失败: {e}")

            try:
                # 然后检查止盈止损
                self._check_stop_loss_take_profit()
            except Exception as e:
                self.logger.error(f"止盈止损监控异常: {e}")

            time.sleep(30)

    def _check_stop_loss_take_profit(self):
        """检查止盈止损触发"""
        for coin, pos_data in self.positions.items():
            try:
                # 获取当前价格
                current_price = self.okx.get_current_price(f"{coin}/USDT:USDT")
                if not current_price:
                    continue

                take_profit = pos_data.get("take_profit", 0.0)
                stop_loss = pos_data.get("stop_loss", 0.0)
                side = pos_data.get("side", "long")  # 获取仓位方向

                # 根据仓位方向判断止盈止损触发条件
                if side == "long":
                    # 做多：价格上涨触发止盈，价格下跌触发止损
                    if take_profit > 0 and current_price >= take_profit:
                        self.logger.info(
                            f"{coin} 触发止盈: {current_price} >= {take_profit} (做多)"
                        )
                        self.okx.close_position(f"{coin}/USDT:USDT")
                        self.remove_position(coin)
                    elif stop_loss > 0 and current_price <= stop_loss:
                        self.logger.info(f"{coin} 触发止损: {current_price} <= {stop_loss} (做多)")
                        self.okx.close_position(f"{coin}/USDT:USDT")
                        self.remove_position(coin)
                elif side == "short":
                    # 做空：价格下跌触发止盈，价格上涨触发止损
                    if take_profit > 0 and current_price <= take_profit:
                        self.logger.info(
                            f"{coin} 触发止盈: {current_price} <= {take_profit} (做空)"
                        )
                        self.okx.close_position(f"{coin}/USDT:USDT")
                        self.remove_position(coin)
                    elif stop_loss > 0 and current_price >= stop_loss:
                        self.logger.info(f"{coin} 触发止损: {current_price} >= {stop_loss} (做空)")
                        self.okx.close_position(f"{coin}/USDT:USDT")
                        self.remove_position(coin)

            except Exception as e:
                self.logger.error(f"检查 {coin} 止盈止损失败: {e}")

    def get_positions(self) -> Dict[str, Any]:
        """获取所有仓位信息"""
        return self.positions.copy()
