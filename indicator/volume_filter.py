"""
低成交量股票过滤系统
基于过去5日平均成交量过滤掉成交量小于100万美元的股票
"""

import os
import json
from pathlib import Path
from datetime import datetime
from typing import Set, Dict, List

class VolumeFilter:
    """低成交量股票过滤器"""
    
    def __init__(self, blacklist_file: str = "low_volume_blacklist.json", min_volume_usd: float = 1000000):
        """
        初始化成交量过滤器
        
        Args:
            blacklist_file: 黑名单文件路径
            min_volume_usd: 最小成交量阈值（美元），默认100万
        """
        self.blacklist_file = Path(blacklist_file)
        self.min_volume_usd = min_volume_usd
        self.blacklist: Set[str] = set()
        self.blacklist_metadata: Dict[str, Dict] = {}
        self.load_blacklist()
    
    def load_blacklist(self):
        """从文件加载黑名单"""
        if self.blacklist_file.exists():
            try:
                with open(self.blacklist_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.blacklist = set(data.get('symbols', []))
                    self.blacklist_metadata = data.get('metadata', {})
                    print(f"📋 已加载低成交量黑名单: {len(self.blacklist)} 只股票")
            except Exception as e:
                print(f"⚠️  加载黑名单失败: {e}")
                self.blacklist = set()
                self.blacklist_metadata = {}
        else:
            print("📋 黑名单文件不存在，将创建新的黑名单")
    
    def save_blacklist(self):
        """保存黑名单到文件"""
        try:
            data = {
                'symbols': sorted(list(self.blacklist)),
                'metadata': self.blacklist_metadata,
                'last_updated': datetime.now().isoformat(),
                'min_volume_usd': self.min_volume_usd
            }
            
            with open(self.blacklist_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            print(f"💾 黑名单已保存: {len(self.blacklist)} 只股票 -> {self.blacklist_file}")
        except Exception as e:
            print(f"⚠️  保存黑名单失败: {e}")
    
    def is_blacklisted(self, symbol: str) -> bool:
        """检查股票是否在黑名单中"""
        return symbol.upper() in self.blacklist
    
    def add_to_blacklist(self, symbol: str, avg_volume: int, avg_price: float = None):
        """
        将股票添加到黑名单
        
        Args:
            symbol: 股票代码
            avg_volume: 平均成交量（股数）
            avg_price: 平均价格（美元），用于计算成交金额
        """
        symbol = symbol.upper()
        if symbol not in self.blacklist:
            # 计算成交金额
            volume_usd = avg_volume * avg_price if avg_price else 0
            
            self.blacklist.add(symbol)
            self.blacklist_metadata[symbol] = {
                'added_date': datetime.now().isoformat(),
                'avg_volume': avg_volume,
                'avg_price': avg_price,
                'volume_usd': volume_usd,
                'reason': f'平均成交量 {avg_volume:,} 股，成交金额约 ${volume_usd:,.0f}'
            }
            
            # print(f"🚫 已加入黑名单: {symbol} - {self.blacklist_metadata[symbol]['reason']}")
    
    def remove_from_blacklist(self, symbol: str):
        """从黑名单中移除股票"""
        symbol = symbol.upper()
        if symbol in self.blacklist:
            self.blacklist.remove(symbol)
            if symbol in self.blacklist_metadata:
                del self.blacklist_metadata[symbol]
            print(f"✅ 已从黑名单移除: {symbol}")
    
    def filter_stocks(self, stock_symbols: List[str]) -> List[str]:
        """
        过滤股票列表，移除黑名单中的股票
        
        Args:
            stock_symbols: 原始股票代码列表
            
        Returns:
            过滤后的股票代码列表
        """
        original_count = len(stock_symbols)
        filtered_symbols = [symbol for symbol in stock_symbols if not self.is_blacklisted(symbol)]
        filtered_count = original_count - len(filtered_symbols)
        
        if filtered_count > 0:
            print(f"🚫 黑名单过滤: {original_count} -> {len(filtered_symbols)} (-{filtered_count})")
        
        return filtered_symbols
    
    def should_filter_by_volume(self, stock_data: dict) -> bool:
        """
        检查股票是否应该因为成交量过低而被过滤
        
        Args:
            stock_data: 股票数据字典，包含 avg_volume 和 close 字段
            
        Returns:
            True表示应该过滤掉
        """
        if not stock_data:
            return True
        
        avg_volume = stock_data.get('avg_volume', 0)
        close_price = stock_data.get('close', 0)
        
        # 如果没有成交量或价格数据，过滤掉
        if avg_volume <= 0 or close_price <= 0:
            return True
        
        # 计算成交金额
        volume_usd = avg_volume * close_price
        
        # 如果成交金额小于阈值，应该被过滤
        return volume_usd < self.min_volume_usd
    
    def process_stock_data(self, symbol: str, stock_data: dict) -> bool:
        """
        处理股票数据，如果成交量过低则加入黑名单
        
        Args:
            symbol: 股票代码
            stock_data: 股票数据
            
        Returns:
            True表示股票数据有效，False表示应该被过滤
        """
        if self.should_filter_by_volume(stock_data):
            # 加入黑名单
            self.add_to_blacklist(
                symbol, 
                stock_data.get('avg_volume', 0),
                stock_data.get('close', 0)
            )
            return False
        
        return True
    
    def get_blacklist_summary(self) -> str:
        """获取黑名单摘要信息"""
        if not self.blacklist:
            return "📋 黑名单为空"
        
        total_symbols = len(self.blacklist)
        recent_added = 0
        total_volume_usd = 0
        
        for symbol, metadata in self.blacklist_metadata.items():
            if metadata.get('volume_usd'):
                total_volume_usd += metadata['volume_usd']
            
            # 检查是否是最近添加的（7天内）
            added_date_str = metadata.get('added_date', '')
            if added_date_str:
                try:
                    added_date = datetime.fromisoformat(added_date_str)
                    if (datetime.now() - added_date).days <= 7:
                        recent_added += 1
                except:
                    pass
        
        avg_volume_usd = total_volume_usd / total_symbols if total_symbols > 0 else 0
        
        return (f"📋 黑名单摘要: {total_symbols} 只股票 | "
                f"最近7天新增: {recent_added} | "
                f"平均成交金额: ${avg_volume_usd:,.0f}")
    
    def clear_blacklist(self):
        """清空黑名单"""
        self.blacklist.clear()
        self.blacklist_metadata.clear()
        print("🗑️  黑名单已清空")
    
    def export_blacklist_report(self, report_file: str = "volume_blacklist_report.txt"):
        """导出黑名单报告"""
        if not self.blacklist:
            print("📋 黑名单为空，无需导出报告")
            return
        
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(f"低成交量股票黑名单报告\n")
                f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"最小成交量阈值: ${self.min_volume_usd:,}\n")
                f.write(f"黑名单股票数量: {len(self.blacklist)}\n")
                f.write("=" * 80 + "\n\n")
                
                # 按成交金额排序
                sorted_metadata = sorted(
                    self.blacklist_metadata.items(),
                    key=lambda x: x[1].get('volume_usd', 0)
                )
                
                for symbol, metadata in sorted_metadata:
                    f.write(f"{symbol:8s} | {metadata.get('reason', 'N/A')}\n")
            
            print(f"📊 黑名单报告已导出: {report_file}")
        except Exception as e:
            print(f"⚠️  导出报告失败: {e}")


# 全局过滤器实例
volume_filter = VolumeFilter()

def get_volume_filter() -> VolumeFilter:
    """获取全局成交量过滤器实例"""
    return volume_filter

def filter_low_volume_stocks(stock_symbols: List[str]) -> List[str]:
    """过滤低成交量股票的便捷函数"""
    return volume_filter.filter_stocks(stock_symbols)

def should_filter_stock(symbol: str, stock_data: dict) -> bool:
    """检查股票是否应该被过滤的便捷函数"""
    return not volume_filter.process_stock_data(symbol, stock_data)

if __name__ == "__main__":
    # 测试代码
    filter_instance = VolumeFilter()
    
    # 测试添加股票到黑名单
    test_data = {
        'avg_volume': 50000,  # 5万股
        'close': 15.0  # $15
    }
    
    print("测试成交量过滤:")
    print(f"成交金额: ${test_data['avg_volume'] * test_data['close']:,}")
    print(f"是否应该过滤: {filter_instance.should_filter_by_volume(test_data)}")
    
    # 显示黑名单摘要
    print(filter_instance.get_blacklist_summary())
