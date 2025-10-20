import logging
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class Position:
    """持仓信息"""
    coin: str
    size: float
    entry_price: float
    current_price: float
    leverage: int
    side: str  # 'long' or 'short'
    unrealized_pnl: float
    risk_usd: float

@dataclass
class RiskMetrics:
    """风险指标"""
    total_exposure: float
    max_drawdown: float
    sharpe_ratio: float
    var_95: float  # 95% VaR
    portfolio_beta: float

class RiskManager:
    """风险管理器"""
    
    def __init__(self, max_risk_per_trade: float = 0.05, max_positions: int = 6):
        self.max_risk_per_trade = max_risk_per_trade
        self.max_positions = max_positions
        self.logger = logging.getLogger(__name__)
        
        # 风险记录
        self.daily_pnl_history = []
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0
        
    def calculate_position_size(self, 
                              account_value: float, 
                              entry_price: float, 
                              stop_loss_price: float, 
                              leverage: int) -> float:
        """计算合适的仓位大小"""
        try:
            # 计算风险金额
            risk_amount = account_value * self.max_risk_per_trade
            
            # 计算价格风险
            price_risk = abs(entry_price - stop_loss_price)
            if price_risk == 0:
                return 0
            
            # 计算基础仓位大小
            base_size = risk_amount / price_risk
            
            # 考虑杠杆
            position_size = base_size * leverage
            
            # 确保不超过最大仓位限制
            max_size = account_value * 0.5 / entry_price  # 最大50%资金
            position_size = min(position_size, max_size)
            
            return round(position_size, 4)
            
        except Exception as e:
            self.logger.error(f"计算仓位大小失败: {e}")
            return 0
    
    def validate_trade(self, 
                      coin: str, 
                      side: str, 
                      quantity: float, 
                      entry_price: float,
                      current_positions: Dict[str, Position],
                      account_value: float) -> bool:
        """验证交易是否合规"""
        try:
            # 检查是否已有该币种持仓
            if coin in current_positions:
                existing_pos = current_positions[coin]
                # 如果是相反方向，允许平仓后开仓
                if existing_pos.side != side:
                    return True
            
            # 检查持仓数量限制
            if len(current_positions) >= self.max_positions:
                self.logger.warning(f"已达到最大持仓数量限制: {self.max_positions}")
                return False
            
            # 检查单笔交易风险
            position_value = quantity * entry_price
            risk_ratio = position_value / account_value
            
            if risk_ratio > self.max_risk_per_trade * 2:  # 允许2倍风险用于杠杆交易
                self.logger.warning(f"交易风险过大: {risk_ratio:.2%}")
                return False
            
            # 检查总敞口
            total_exposure = self.calculate_total_exposure(current_positions, account_value)
            new_exposure = total_exposure + position_value
            
            if new_exposure > account_value * 2:  # 最大2倍杠杆
                self.logger.warning("总敞口过大")
                return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"验证交易失败: {e}")
            return False
    
    def calculate_total_exposure(self, positions: Dict[str, Position], account_value: float) -> float:
        """计算总敞口"""
        total_exposure = 0
        for pos in positions.values():
            position_value = abs(pos.size * pos.current_price)
            total_exposure += position_value
        
        return total_exposure
    
    def calculate_portfolio_metrics(self, positions: Dict[str, Position], account_value: float) -> RiskMetrics:
        """计算投资组合风险指标"""
        try:
            # 计算总敞口
            total_exposure = self.calculate_total_exposure(positions, account_value)
            
            # 计算未实现盈亏
            total_unrealized_pnl = sum(pos.unrealized_pnl for pos in positions.values())
            
            # 计算当前回撤
            current_return = total_unrealized_pnl / account_value
            if current_return > 0:
                self.max_drawdown = max(self.max_drawdown, current_return)
                self.current_drawdown = 0
            else:
                self.current_drawdown = abs(current_return)
            
            # 简化的夏普比率计算（实际需要历史数据）
            sharpe_ratio = 0.0
            if self.daily_pnl_history:
                avg_return = sum(self.daily_pnl_history[-30:]) / len(self.daily_pnl_history[-30:])
                volatility = 0.02  # 假设2%的日波动率
                sharpe_ratio = avg_return / volatility if volatility > 0 else 0
            
            # VaR计算（简化版）
            var_95 = total_exposure * 0.05  # 假设5%的95% VaR
            
            return RiskMetrics(
                total_exposure=total_exposure,
                max_drawdown=self.max_drawdown,
                sharpe_ratio=sharpe_ratio,
                var_95=var_95,
                portfolio_beta=1.0  # 简化假设
            )
            
        except Exception as e:
            self.logger.error(f"计算风险指标失败: {e}")
            return RiskMetrics(0, 0, 0, 0, 0)
    
    def check_stop_loss_trigger(self, position: Position, stop_loss_price: float) -> bool:
        """检查是否触发止损"""
        if position.side == 'long':
            return position.current_price <= stop_loss_price
        else:
            return position.current_price >= stop_loss_price
    
    def check_take_profit_trigger(self, position: Position, take_profit_price: float) -> bool:
        """检查是否触发止盈"""
        if position.side == 'long':
            return position.current_price >= take_profit_price
        else:
            return position.current_price <= take_profit_price
    
    def should_reduce_position(self, position: Position, risk_metrics: RiskMetrics) -> bool:
        """判断是否应该减仓"""
        # 如果当前回撤过大
        if self.current_drawdown > 0.1:  # 10%回撤
            return True
        
        # 如果单个持仓亏损过大
        if position.unrealized_pnl < -position.risk_usd * 2:
            return True
        
        # 如果总敞口过大
        if risk_metrics.total_exposure > 100000:  # 假设账户价值
            return True
        
        return False
    
    def update_daily_pnl(self, daily_pnl: float):
        """更新日盈亏记录"""
        self.daily_pnl_history.append(daily_pnl)
        # 只保留最近100天的记录
        if len(self.daily_pnl_history) > 100:
            self.daily_pnl_history = self.daily_pnl_history[-100:]
    
    def get_risk_report(self, positions: Dict[str, Position], account_value: float) -> str:
        """生成风险报告"""
        metrics = self.calculate_portfolio_metrics(positions, account_value)
        
        report = f"""
=== 风险管理报告 ===
总敞口: ${metrics.total_exposure:,.2f}
最大回撤: {metrics.max_drawdown:.2%}
当前回撤: {self.current_drawdown:.2%}
夏普比率: {metrics.sharpe_ratio:.2f}
95% VaR: ${metrics.var_95:,.2f}
当前持仓数: {len(positions)}
最大持仓数: {self.max_positions}
"""
        
        if positions:
            report += "\n=== 持仓详情 ===\n"
            for coin, pos in positions.items():
                pnl_pct = pos.unrealized_pnl / (pos.size * pos.entry_price) * 100
                report += f"{coin}: {pos.side} {pos.size} @ {pos.entry_price}, "
                report += f"当前: {pos.current_price}, PnL: ${pos.unrealized_pnl:.2f} ({pnl_pct:.2f}%)\n"
        
        return report
