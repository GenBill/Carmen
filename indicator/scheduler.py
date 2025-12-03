import os
import pytz
from datetime import datetime

class MarketScheduler:
    def __init__(self, market, run_nodes_cfg=None, last_run_file=None):
        """
        初始化市场扫描调度器
        
        Args:
            market (str): 市场类型 ('HK', 'A', 'US')
            run_nodes_cfg (list): 运行时间节点配置，格式为 [{'hour': 11, 'minute': 35}, ...]
                                  如果为None，需手动指定或使用默认（如有）
            last_run_file (str): 存储上次运行时间的文件路径。若为None，根据市场自动生成。
        """
        self.market = market.upper()
        self.run_nodes_cfg = run_nodes_cfg if run_nodes_cfg is not None else []
        
        # 根据市场设置时区和默认文件
        if self.market == 'HK':
            self.tz = pytz.timezone('Asia/Hong_Kong')
            default_file = '.last_run_hk'
        elif self.market == 'A':
            self.tz = pytz.timezone('Asia/Shanghai')
            default_file = '.last_run_a'
        elif self.market == 'US':
            self.tz = pytz.timezone('America/New_York')
            default_file = '.last_run_us'
        else:
            # 默认使用上海时间
            self.tz = pytz.timezone('Asia/Shanghai')
            default_file = f'.last_run_{self.market.lower()}'
            
        self.last_run_file = last_run_file if last_run_file else default_file
        self.last_run_time = self._load_last_run_time()
        self.is_first_run = True

    def _load_last_run_time(self):
        """加载上次运行时间"""
        try:
            if os.path.exists(self.last_run_file):
                with open(self.last_run_file, 'r') as f:
                    timestamp = float(f.read().strip())
                    return datetime.fromtimestamp(timestamp, self.tz)
        except Exception:
            pass
        return None

    def _save_last_run_time(self, dt):
        """保存本次运行时间"""
        try:
            with open(self.last_run_file, 'w') as f:
                f.write(str(dt.timestamp()))
            self.last_run_time = dt
        except Exception:
            pass

    def check_should_run(self):
        """
        检查是否应该运行任务
        
        Returns:
            bool: True 表示应该运行，False 表示不运行
        """
        now = datetime.now(self.tz)
        should_run = False
        
        # 情况1: 首次运行 (First Run)
        # 即使是周末，如果是程序刚启动的第一次检查，也应该运行
        if self.is_first_run:
            self.is_first_run = False
            self._save_last_run_time(now)
            return True

        # 情况2: 周末不运行
        # 5=周六, 6=周日
        if now.weekday() >= 5:
            return False

        # 计算当天的目标时间节点
        nodes = []
        for cfg in self.run_nodes_cfg:
            node = now.replace(hour=cfg['hour'], minute=cfg['minute'], second=0, microsecond=0)
            nodes.append(node)
        
        # 找出已经过去的时间节点
        passed_nodes = [t for t in nodes if now >= t]
        last_node = max(passed_nodes) if passed_nodes else None
        
        # 情况3: 到了预定时间点，且上次运行时间在预定时间点之前
        if last_node is not None:
            if self.last_run_time is None or self.last_run_time < last_node:
                should_run = True
        
        if should_run:
            self._save_last_run_time(now)
            
        return should_run