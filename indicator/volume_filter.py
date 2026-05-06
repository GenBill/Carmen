"""
低成交量股票过滤系统
基于过去5日平均成交量过滤掉成交量小于100万美元的股票
"""

import os
import json
import math
from pathlib import Path
from datetime import datetime
from typing import Set, Dict, List
from tqdm import tqdm
import yfinance as yf
import pandas as pd

class VolumeFilter:
    """低成交量股票过滤器"""
    
    def __init__(self, blacklist_file: str = "low_volume_blacklist.json", min_volume_usd: float = 10000000,
                 update_cycle_days: int = 30, removal_multiplier: float = 2.0):
        """
        初始化成交量过滤器
        
        Args:
            blacklist_file: 黑名单文件路径
            min_volume_usd: 最小成交量阈值（美元），默认1000万
            update_cycle_days: 黑名单完全更新周期（天），默认30天
            removal_multiplier: 移除倍数，成交量需达到此倍数才能移除，默认2.0
        """
        self.blacklist_file = Path(blacklist_file)
        self.min_volume_usd = min_volume_usd
        self.update_cycle_days = update_cycle_days
        self.removal_multiplier = removal_multiplier  # 新增：移除倍数
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
    
    def add_to_blacklist(self, symbol: str, avg_volume: int, avg_price: float = None, reason: str = None):
        """
        将股票添加到黑名单
        
        Args:
            symbol: 股票代码
            avg_volume: 平均成交量（股数）
            avg_price: 平均价格（美元），用于计算成交金额
            reason: 自定义原因，不传则使用低成交量原因
        """
        symbol = symbol.upper()
        if symbol not in self.blacklist:
            # Sanitize inputs to ensure JSON compliance (no NaN)
            if avg_price is None or (isinstance(avg_price, float) and math.isnan(avg_price)):
                avg_price = 0.0
            if avg_volume is None or (isinstance(avg_volume, float) and math.isnan(avg_volume)):
                avg_volume = 0
            
            # 计算成交金额
            volume_usd = avg_volume * avg_price
            reason_text = reason or f'平均成交量 {avg_volume:,} 股，成交金额约 ${volume_usd:,.0f}'
            
            self.blacklist.add(symbol)
            self.blacklist_metadata[symbol] = {
                'added_date': datetime.now().isoformat(),
                'last_checked_date': datetime.now().date().isoformat(),  # 添加上次检查日期
                'avg_volume': avg_volume,
                'avg_price': avg_price,
                'volume_usd': volume_usd,
                'reason': reason_text
            }
            
            # print(f"🚫 已加入黑名单: {symbol} - {self.blacklist_metadata[symbol]['reason']}")
    
    def remove_from_blacklist(self, symbol: str):
        """从黑名单中移除股票"""
        symbol = symbol.upper()
        if symbol in self.blacklist:
            self.blacklist.remove(symbol)
            if symbol in self.blacklist_metadata:
                del self.blacklist_metadata[symbol]
            # print(f"✅ 已从黑名单移除: {symbol}")
    
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
        检查股票是否应该因为成交量过低而被过滤（加入黑名单）
        
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
    
    def should_remove_from_blacklist(self, stock_data: dict) -> bool:
        """
        检查股票是否应该从黑名单中移除（需要达到更高的阈值）
        
        使用 removal_multiplier 倍数的阈值，避免股票反复横跳
        例如：加入黑名单阈值是400万，移除阈值是800万（2倍）
        
        Args:
            stock_data: 股票数据字典，包含 avg_volume 和 close 字段
            
        Returns:
            True表示应该从黑名单移除
        """
        if not stock_data:
            return False
        
        avg_volume = stock_data.get('avg_volume', 0)
        close_price = stock_data.get('close', 0)
        
        # 如果没有成交量或价格数据，不移除
        if avg_volume <= 0 or close_price <= 0:
            return False
        
        # 计算成交金额
        volume_usd = avg_volume * close_price
        
        # 需要达到 removal_multiplier 倍的阈值才能移除
        removal_threshold = self.min_volume_usd * self.removal_multiplier
        
        # 如果成交金额达到移除阈值，应该被移除
        return volume_usd >= removal_threshold
    
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
        today = datetime.now().date().isoformat()
        checked_today = 0
        
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
            
            # 统计今日已检查数量
            if metadata.get('last_checked_date', '') == today:
                checked_today += 1
        
        avg_volume_usd = total_volume_usd / total_symbols if total_symbols > 0 else 0
        removal_threshold = self.min_volume_usd * self.removal_multiplier
        
        return (f"📋 黑名单摘要: {total_symbols} 只股票 | "
                f"最近7天新增: {recent_added} | "
                f"今日已检查: {checked_today} | "
                f"平均成交金额: ${avg_volume_usd:,.0f} | "
                f"移除阈值: ${removal_threshold:,.0f} ({self.removal_multiplier}x)")
    
    def clear_blacklist(self):
        """清空黑名单"""
        self.blacklist.clear()
        self.blacklist_metadata.clear()
        print("🗑️  黑名单已清空")
    
    def get_daily_check_progress(self) -> dict:
        """
        获取今日检查进度
        
        Returns:
            dict: 包含今日检查进度的字典
        """
        today = datetime.now().date().isoformat()
        checked_today = 0
        unchecked_today = 0
        
        for symbol, metadata in self.blacklist_metadata.items():
            if metadata.get('last_checked_date', '') == today:
                checked_today += 1
            else:
                unchecked_today += 1
        
        total = len(self.blacklist)
        progress_pct = (checked_today / total * 100) if total > 0 else 0
        
        return {
            'total': total,
            'checked_today': checked_today,
            'unchecked_today': unchecked_today,
            'progress_pct': progress_pct,
            'date': today
        }
    
    def calculate_daily_update_quota(self) -> int:
        """
        计算今日需要更新的股票数量
        
        Returns:
            int: 今日需要更新的股票数量
        """
        if not self.blacklist:
            return 0
        
        # 获取黑名单中最早的添加日期
        earliest_date = None
        for symbol, metadata in self.blacklist_metadata.items():
            added_date_str = metadata.get('added_date', '')
            if added_date_str:
                try:
                    added_date = datetime.fromisoformat(added_date_str)
                    if earliest_date is None or added_date < earliest_date:
                        earliest_date = added_date
                except:
                    pass
        
        if earliest_date is None:
            # 如果没有日期信息，按添加顺序处理（先进先出）
            return max(1, len(self.blacklist) // self.update_cycle_days)
        
        # 计算从最早日期到今天的天数
        days_since_earliest = (datetime.now() - earliest_date).days
        
        # 计算更新进度
        update_progress = days_since_earliest / self.update_cycle_days
        
        total_stocks = len(self.blacklist)
        
        if update_progress >= 1.0:
            # 超过更新周期，按正常周期分配每日配额（避免一次更新所有）
            # 即使超过周期，每天也只更新总股票数的 1/更新周期天数
            daily_quota = max(1, total_stocks // self.update_cycle_days)
            return daily_quota * 2
        
        # 计算剩余需要更新的股票数量
        remaining_stocks = int(total_stocks * (1 - update_progress))
        remaining_days = self.update_cycle_days - days_since_earliest
        
        # 计算每日更新配额
        daily_quota = max(1, remaining_stocks // remaining_days)
        
        return min(daily_quota, remaining_stocks)
    
    def get_candidates_for_update(self) -> List[str]:
        """
        获取需要重新验证的股票候选列表（按添加时间排序，先进先出）
        只返回今天还没检查过的股票
        
        Returns:
            List[str]: 需要重新验证的股票代码列表
        """
        if not self.blacklist:
            return []
        
        today = datetime.now().date().isoformat()
        
        # 过滤出今天还没检查过的股票
        unchecked_today = []
        for symbol, metadata in self.blacklist_metadata.items():
            last_checked = metadata.get('last_checked_date', '1970-01-01')
            if last_checked != today:
                unchecked_today.append((symbol, metadata))
        
        # 按添加时间排序，最早添加的优先更新
        sorted_candidates = sorted(
            unchecked_today,
            key=lambda x: x[1].get('added_date', '1970-01-01')
        )
        
        return [symbol for symbol, _ in sorted_candidates]
    
    def daily_update_blacklist(self, stock_data_func=None, batch_size: int = 50, avg_volume_days: int = 8):
        """
        每日更新黑名单：重新验证部分股票，移除满足条件的股票
        每只股票每天只检查一次
        使用 yf.download 批量下载，多线程加速
        
        Args:
            stock_data_func: 获取股票数据的函数（保留参数兼容性，实际不再使用）
            batch_size: 批量下载时每批股票数量，默认50
            avg_volume_days: 平均成交量计算天数，默认8
        """
        if not self.blacklist:
            return
        
        # 获取今天还没检查过的股票
        candidates = self.get_candidates_for_update()
        
        if not candidates:
            print(f"✅ 黑名单中所有股票今天都已检查过")
            return
        
        daily_quota = self.calculate_daily_update_quota()
        if daily_quota <= 0:
            return
        
        update_count = min(daily_quota, len(candidates))
        symbols_to_check = candidates[:update_count]
        
        print(f"🔄 开始每日黑名单更新: 计划更新 {update_count}/{len(self.blacklist)} 只股票 (今日待检查: {len(candidates)})")
        
        # ========== 批量下载股票数据（多线程加速） ==========
        stock_data_map = {}  # symbol -> stock_data dict
        total_batches = (len(symbols_to_check) + batch_size - 1) // batch_size
        
        # print(f"📥 批量下载 {len(symbols_to_check)} 只股票数据 (共 {total_batches} 批)")
        
        batch_iter = tqdm(
            range(0, len(symbols_to_check), batch_size),
            desc="下载数据",
            total=total_batches,
            unit="batch",
            ncols=100
        )
        
        for i in batch_iter:
            batch = symbols_to_check[i:i + batch_size]
            if not batch:
                continue
            
            try:
                # 使用 yf.download 批量下载，自动多线程加速
                hist_batch = yf.download(
                    batch, 
                    period="1mo",  # 黑名单检查只需近期数据计算平均成交量
                    progress=False, 
                    auto_adjust=False, 
                    threads=True, 
                    group_by='ticker'
                )
                
                if hist_batch.empty:
                    continue
                
                # 处理返回的数据格式
                if isinstance(hist_batch.columns, pd.MultiIndex):
                    # MultiIndex：按 ticker 拆分
                    tickers_in_data = hist_batch.columns.get_level_values(0).unique().tolist()
                    for symbol in batch:
                        if symbol in tickers_in_data:
                            try:
                                hist = hist_batch[symbol].copy()
                                if not hist.empty and len(hist) >= avg_volume_days:
                                    # 计算平均成交量和收盘价
                                    avg_volume = hist['Volume'].tail(avg_volume_days).mean()
                                    close_price = hist['Close'].iloc[-1]
                                    
                                    # Sanitize NaN
                                    if pd.isna(avg_volume):
                                        avg_volume = 0
                                    if pd.isna(close_price):
                                        close_price = 0.0
                                    
                                    stock_data_map[symbol] = {
                                        'avg_volume': avg_volume,
                                        'close': close_price
                                    }
                            except Exception:
                                continue
                else:
                    # 单层索引：只有一只股票的情况
                    if len(batch) == 1:
                        symbol = batch[0]
                        if not hist_batch.empty and len(hist_batch) >= avg_volume_days:
                            avg_volume = hist_batch['Volume'].tail(avg_volume_days).mean()
                            close_price = hist_batch['Close'].iloc[-1]
                            
                            if pd.isna(avg_volume):
                                avg_volume = 0
                            if pd.isna(close_price):
                                close_price = 0.0
                            
                            stock_data_map[symbol] = {
                                'avg_volume': avg_volume,
                                'close': close_price
                            }
            except Exception as e:
                continue
        
        # ========== 处理已下载的数据 ==========
        updated_count = 0
        removed_count = 0
        today = datetime.now().date().isoformat()

        with tqdm(total=len(symbols_to_check), desc="更新黑名单", unit="iter", ncols=100) as pbar:
            for symbol in symbols_to_check:
                stock_data = stock_data_map.get(symbol)
                
                # Sanitize stock_data to prevent NaN values in JSON
                if stock_data:
                    val_vol = stock_data.get('avg_volume')
                    if val_vol is None or (isinstance(val_vol, float) and math.isnan(val_vol)):
                        stock_data['avg_volume'] = 0
                        
                    val_close = stock_data.get('close')
                    if val_close is None or (isinstance(val_close, float) and math.isnan(val_close)):
                        stock_data['close'] = 0.0
                
                # 使用更严格的移除条件（需要达到2倍阈值）
                if stock_data and self.should_remove_from_blacklist(stock_data):
                    # 股票成交量达到移除阈值，从黑名单中移除
                    volume_usd = stock_data.get('avg_volume', 0) * stock_data.get('close', 0)
                    self.remove_from_blacklist(symbol)
                    removed_count += 1
                    # 更新进度条显示移除信息
                    pbar.set_postfix_str(f"Removed: {removed_count} | {symbol} ${volume_usd:,.0f}")
                else:
                    # 股票仍然不满足条件，更新元数据和检查日期
                    if stock_data:
                        self.blacklist_metadata[symbol] = {
                            'added_date': self.blacklist_metadata[symbol].get('added_date', datetime.now().isoformat()),
                            'last_checked_date': today,  # 更新上次检查日期
                            'last_checked': datetime.now().isoformat(),  # 详细时间戳
                            'avg_volume': stock_data.get('avg_volume', 0),
                            'avg_price': stock_data.get('close', 0),
                            'volume_usd': stock_data.get('avg_volume', 0) * stock_data.get('close', 0),
                            'reason': f'平均成交量 {stock_data.get("avg_volume", 0):,} 股，成交金额约 ${(stock_data.get("avg_volume", 0) * stock_data.get("close", 0)):,.0f}'
                        }
                    else:
                        # 即使获取数据失败，也标记为已检查（避免重复失败）
                        if symbol in self.blacklist_metadata:
                            self.blacklist_metadata[symbol]['last_checked_date'] = today
                            self.blacklist_metadata[symbol]['last_checked'] = datetime.now().isoformat()
                
                updated_count += 1
                pbar.update(1)
        
        # 统计今天已检查的总数
        checked_today = sum(1 for meta in self.blacklist_metadata.values() 
                           if meta.get('last_checked_date', '') == today)
        remaining_today = len(self.blacklist) - checked_today
        
        print(f"📊 每日更新完成: 本轮检查 {updated_count} 只，移除 {removed_count} 只")
        print(f"📈 今日进度: 已检查 {checked_today}/{len(self.blacklist)} 只，剩余 {remaining_today} 只")
        
        if updated_count > 0 or removed_count > 0:
            self.save_blacklist()

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
                f.write(f"更新周期: {self.update_cycle_days} 天\n")
                f.write(f"今日更新配额: {self.calculate_daily_update_quota()} 只\n")
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
min_volume_usd = 1000 * 10000
removal_multiplier = 2.0  # 移除需要达到2倍阈值（避免反复横跳）
volume_filter = VolumeFilter(min_volume_usd=min_volume_usd, removal_multiplier=removal_multiplier)

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
