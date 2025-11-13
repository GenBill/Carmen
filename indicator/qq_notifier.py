"""
QQ消息推送模块
参考 auto_Qmsg.py 的接口实现
"""
import requests
import os
from typing import Optional, Tuple


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
    
    def send_message(self, msg: str) -> bool:
        """
        发送QQ消息
        
        Args:
            msg: 要发送的消息内容
            
        Returns:
            bool: 是否发送成功
        """
        try:
            data = {
                "msg": msg,
                "qq": self.qq,
            }
            response = requests.post(self.url, data=data, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"⚠️  QQ推送失败: {e}")
            return False
    
    def send_buy_signal(self, symbol: str, price: float, score: float, backtest_str: str, 
                       rsi: Optional[float] = None, volume_ratio: Optional[float] = None,
                       max_buy_price: Optional[float] = None, ai_win_rate: Optional[float] = None) -> bool:
        """
        发送买入信号通知
        
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
            bool: 是否发送成功
        """
        # 构建消息内容
        msg_parts = [
            f"🔔 买入信号提醒",
            f"股票: {symbol}",
            f"当前价格: ${price:.2f}",
            f"评分: {score:.2f}",
            f"回测胜率: {backtest_str}",
        ]
        
        # 添加AI提炼的信息
        if max_buy_price is not None:
            msg_parts.append(f"最高买入价: ${max_buy_price:.2f}")
        
        if ai_win_rate is not None:
            msg_parts.append(f"AI预估胜率: {ai_win_rate*100:.1f}%")
        
        if rsi is not None:
            msg_parts.append(f"RSI: {rsi:.2f}")
        
        if volume_ratio is not None:
            msg_parts.append(f"量比: {volume_ratio:.1f}%")
        
        msg = "\n".join(msg_parts)
        return self.send_message(msg)


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

