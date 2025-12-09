"""
QQ消息推送模块
参考 auto_Qmsg.py 的接口实现
"""
import requests
import os
import time
from typing import Optional, Tuple

# 模块级全局缓存：{symbol: last_push_timestamp}
# 使用全局变量确保跨 QQNotifier 实例共享缓存
_global_push_cache = {}


class QQNotifier:
    """QQ消息推送器"""
    
    def __init__(self, key: str, qq: str):
        """
        初始化QQ推送器
        
        Args:
            key: Qmsg酱的KEY，在Qmsg酱官网登录后，在控制台可以获取KEY
            qq: 接收消息的QQ号
        """
        self.key = key
        self.qq = qq
        # 私聊消息推送接口
        self.url = f'https://qmsg.zendee.cn/send/{key}'
        # 群消息推送接口（备用）
        # self.url = f'https://qmsg.zendee.cn/group/{key}'
        # 使用全局缓存，避免重复推送（跨实例共享）
        self.cache_hours = 2  # 缓存时间（小时）
        
        # 指数退避重试配置
        self.max_retries = 3  # 最大重试次数
        self.initial_wait = 0.5  # 初始等待时间（秒）
        self.max_wait = 30  # 最大等待时间（秒）
        self.backoff_multiplier = 2  # 退避倍数
    
    def send_message(self, msg: str) -> bool:
        """
        发送QQ消息（带指数退避重试机制）
        
        Args:
            msg: 要发送的消息内容
            
        Returns:
            bool: 是否发送成功
        """
        wait_time = self.initial_wait
        if msg == "":
            print("⚠️  QQ推送消息为空，跳过")
            return False
        
        for attempt in range(self.max_retries + 1):  # 0到max_retries，共max_retries+1次尝试
            try:
                data = {
                    "msg": msg,
                    "qq": self.qq,
                }
                response = requests.post(self.url, data=data, timeout=10)
                response.raise_for_status()
                
                # 如果之前有重试，打印成功信息
                if attempt > 0:
                    print(f"✅ QQ推送成功（第{attempt + 1}次尝试）")
                
                return True
            except Exception as e:
                # 获取服务器返回的详细错误信息
                error_detail = ""
                if 'response' in locals() and hasattr(response, 'text'):
                    error_detail = f" Server response: {response.text}"

                # 如果是最后一次尝试，打印失败信息并返回
                if attempt == self.max_retries:
                    print(f"⚠️  QQ推送失败（已重试{self.max_retries}次）: {e}{error_detail}")
                    return False
                
                # 不是最后一次尝试，等待后重试
                print(f"⚠️  QQ推送失败（第{attempt + 1}次尝试）: {e}{error_detail}，{wait_time}秒后重试...")
                time.sleep(wait_time)
                
                # 指数退避：等待时间翻倍，但不超过最大等待时间
                wait_time = min(wait_time * self.backoff_multiplier, self.max_wait)
        
        return False
    
    def send_sell_signal(self, symbol: str, price: float, score: float, backtest_str: str, 
                       rsi: Optional[float] = None, volume_ratio: Optional[float] = None) -> bool:
        """
        发送卖出信号通知（带缓存，避免重复推送）
        
        Args:
            symbol: 股票代码
            price: 当前价格
            score: 卖出评分
            backtest_str: 回测胜率
            rsi: RSI值（可选）
            volume_ratio: 量比（可选）
            
        Returns:
            bool: 是否发送成功（如果缓存时间内已推送过，返回False）
        """
        # 检查全局缓存，避免缓存时间内重复推送
        current_time = time.time()
        if symbol in _global_push_cache:
            last_push_time = _global_push_cache[symbol]
            hours_passed = (current_time - last_push_time) / 3600
            if hours_passed < self.cache_hours:
                print(f"⏭️  {symbol} 在 {hours_passed:.1f} 小时前已推送过，跳过")
                return False
        
        # 构建消息内容
        safe_symbol = symbol.replace(".SS", "[SS]").replace(".SZ", "[SZ]").replace(".HK", "[HK]")
        msg_parts = [
            f"📉 卖出信号提醒",
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
        
        # 如果发送成功，更新全局缓存
        if success:
            _global_push_cache[symbol] = current_time
        
        return success

    def send_buy_signal(self, symbol: str, price: float, score: float, backtest_str: str, 
                       rsi: Optional[float] = None, volume_ratio: Optional[float] = None,
                       max_buy_price: Optional[float] = None, ai_win_rate: Optional[float] = None) -> bool:
        """
        发送买入信号通知（带缓存，避免重复推送）
        
        Args:
            symbol: 股票代码
            price: 当前价格
            score: 买入评分
            rsi: RSI值（可选）
            volume_ratio: 量比（可选）
            backtest_str: 回测胜率（可选）
            max_buy_price: AI建议的最高买入价（可选）
            ai_win_rate: AI预估的胜率（可选，0-1之间）
            
        Returns:
            bool: 是否发送成功（如果缓存时间内已推送过，返回False）
        """
        # 检查全局缓存，避免缓存时间内重复推送
        current_time = time.time()
        if symbol in _global_push_cache:
            last_push_time = _global_push_cache[symbol]
            hours_passed = (current_time - last_push_time) / 3600
            if hours_passed < self.cache_hours:
                print(f"⏭️  {symbol} 在 {hours_passed:.1f} 小时前已推送过，跳过")
                return False
        
        # 构建消息内容
        safe_symbol = symbol.replace(".SS", "[SS]").replace(".SZ", "[SZ]").replace(".HK", "[HK]")
        msg_parts = [
            f"📈 买入信号提醒",
            f"股票: {safe_symbol}",
            f"当前价格: {price:.2f}",
            f"评分: {score:.2f}",
            f"回测胜率: {backtest_str[1:-1]}",
        ]
        
        # 添加AI提炼的信息
        if max_buy_price is not None:
            msg_parts.append(f"AI买入价: {max_buy_price:.2f}")
            msg_parts.append(f"最高买入价: {max_buy_price*1.02:.2f}")
        
        if ai_win_rate is not None:
            msg_parts.append(f"AI预估胜率: {ai_win_rate*100:.1f}%")
        
        if rsi is not None:
            msg_parts.append(f"RSI: {rsi:.2f}")
        
        if volume_ratio is not None:
            msg_parts.append(f"量比: {volume_ratio:.1f}%")
        
        msg = "\n".join(msg_parts)
        success = self.send_message(msg)
        
        # 如果发送成功，更新全局缓存
        if success:
            _global_push_cache[symbol] = current_time
        
        return success


def load_qq_token(token_path: str = None) -> Tuple[str, str]:
    """
    从token文件加载QQ配置
    
    Args:
        token_path: token文件路径，默认为 indicator/qq.token
        
    Returns:
        Tuple[str, str]: (key, qq_number)
        
    Raises:
        FileNotFoundError: token文件不存在
        ValueError: token文件格式不正确
    """
    if token_path is None:
        # 默认路径：indicator/qq.token
        current_dir = os.path.dirname(os.path.abspath(__file__))
        token_path = os.path.join(current_dir, 'qq.token')
    
    if not os.path.exists(token_path):
        raise FileNotFoundError(f"QQ token文件不存在: {token_path}")
    
    with open(token_path, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    
    if len(lines) < 2:
        raise ValueError(f"QQ token文件格式不正确，需要两行：第一行是KEY，第二行是QQ号")
    
    return lines[0], lines[1]

