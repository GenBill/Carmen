import json
import os
from datetime import datetime
from typing import Dict, Any, Optional

class StateManager:
    """状态管理器 - 保存和恢复系统状态"""
    
    def __init__(self, state_file="trading_state.json"):
        self.state_file = state_file
        self.state = self._load_state()
    
    def _load_state(self) -> Dict[str, Any]:
        """从文件加载状态"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载状态文件失败: {e}")
                return self._get_default_state()
        else:
            return self._get_default_state()
    
    def _get_default_state(self) -> Dict[str, Any]:
        """获取默认状态"""
        return {
            "start_time": datetime.now().isoformat(),
            "initial_account_value": 10000.0,  # 默认起始资金1万USDT
            "invocation_count": 0,
            "total_trades": 0,
            "successful_trades": 0,
            "failed_trades": 0,
            "total_pnl": 0.0,
            "session_count": 1,
            "last_session_end": None,
            "trading_history": [],
            "performance_metrics": {
                "max_drawdown": 0.0,
                "best_trade": 0.0,
                "worst_trade": 0.0,
                "win_rate": 0.0,
                "sharpe_ratio": 0.0
            }
        }
    
    def save_state(self):
        """保存状态到文件"""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存状态文件失败: {e}")
    
    def get_start_time(self) -> datetime:
        """获取起始时间"""
        return datetime.fromisoformat(self.state["start_time"])
    
    def get_initial_account_value(self) -> float:
        """获取起始账户价值"""
        return self.state["initial_account_value"]
    
    def get_invocation_count(self) -> int:
        """获取调用次数"""
        return self.state["invocation_count"]
    
    def increment_invocation_count(self):
        """增加调用次数"""
        self.state["invocation_count"] += 1
        self.save_state()
    
    def get_session_count(self) -> int:
        """获取会话次数"""
        return self.state["session_count"]
    
    def start_new_session(self):
        """开始新会话"""
        self.state["last_session_end"] = datetime.now().isoformat()
        self.state["session_count"] += 1
        self.save_state()
    
    def add_trade_record(self, trade_info: Dict[str, Any]):
        """添加交易记录"""
        trade_record = {
            "timestamp": datetime.now().isoformat(),
            "session": self.state["session_count"],
            "invocation": self.state["invocation_count"],
            **trade_info
        }
        self.state["trading_history"].append(trade_record)
        
        # 更新统计信息
        self.state["total_trades"] += 1
        if trade_info.get("success", False):
            self.state["successful_trades"] += 1
        else:
            self.state["failed_trades"] += 1
        
        # 更新PnL
        pnl = trade_info.get("pnl", 0.0)
        self.state["total_pnl"] += pnl
        
        # 更新性能指标
        self._update_performance_metrics(trade_record)
        
        self.save_state()
    
    def _update_performance_metrics(self, trade_record: Dict[str, Any]):
        """更新性能指标"""
        pnl = trade_record.get("pnl", 0.0)
        
        # 更新最佳/最差交易
        if pnl > self.state["performance_metrics"]["best_trade"]:
            self.state["performance_metrics"]["best_trade"] = pnl
        if pnl < self.state["performance_metrics"]["worst_trade"]:
            self.state["performance_metrics"]["worst_trade"] = pnl
        
        # 更新最大回撤
        if pnl < 0:
            drawdown = abs(pnl)
            if drawdown > self.state["performance_metrics"]["max_drawdown"]:
                self.state["performance_metrics"]["max_drawdown"] = drawdown
        
        # 更新胜率
        if self.state["total_trades"] > 0:
            self.state["performance_metrics"]["win_rate"] = (
                self.state["successful_trades"] / self.state["total_trades"]
            )
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """获取性能摘要"""
        elapsed_time = datetime.now() - self.get_start_time()
        
        return {
            "start_time": self.state["start_time"],
            "initial_value": self.state["initial_account_value"],
            "total_pnl": self.state["total_pnl"],
            "total_return_pct": (
                self.state["total_pnl"] / self.state["initial_account_value"] * 100
                if self.state["initial_account_value"] > 0 else 0
            ),
            "total_trades": self.state["total_trades"],
            "successful_trades": self.state["successful_trades"],
            "failed_trades": self.state["failed_trades"],
            "win_rate": self.state["performance_metrics"]["win_rate"],
            "max_drawdown": self.state["performance_metrics"]["max_drawdown"],
            "best_trade": self.state["performance_metrics"]["best_trade"],
            "worst_trade": self.state["performance_metrics"]["worst_trade"],
            "session_count": self.state["session_count"],
            "invocation_count": self.state["invocation_count"],
            "elapsed_time": str(elapsed_time),
            "elapsed_days": elapsed_time.days,
            "elapsed_hours": elapsed_time.total_seconds() / 3600
        }
    
    def reset_state(self, initial_value: Optional[float] = None):
        """重置状态（可选设置新的起始资金）"""
        self.state = self._get_default_state()
        if initial_value is not None:
            self.state["initial_account_value"] = initial_value
        self.save_state()
    
    def set_initial_account_value(self, value: float):
        """设置起始账户价值"""
        self.state["initial_account_value"] = value
        self.save_state()
    
    def get_recent_trades(self, count: int = 10) -> list:
        """获取最近的交易记录"""
        return self.state["trading_history"][-count:]
    
    def export_trading_history(self, export_file: str = "trading_history_export.json"):
        """导出交易历史"""
        try:
            with open(export_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "state": self.state,
                    "performance_summary": self.get_performance_summary(),
                    "export_time": datetime.now().isoformat()
                }, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"导出交易历史失败: {e}")
            return False
