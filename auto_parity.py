import math
import requests
from io import StringIO
import csv

def get_current_risk_free_rate():
    """
    从FRED自动获取最新1年期美国国债收益率（转换为小数）。
    如果失败，返回默认值0.0393。
    """
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS1"
    try:
        response = requests.get(url)
        response.raise_for_status()  # 检查请求成功
        data = StringIO(response.text)
        reader = csv.reader(data)
        next(reader)  # 跳过表头
        last_row = None
        for row in reader:
            if len(row) >= 2 and row[1] != '.':
                last_row = row
        if last_row:
            yield_value = float(last_row[1]) / 100  # 百分比转小数
            print(f"获取最新r: {yield_value} (日期: {last_row[0]})")
            return yield_value
    except Exception as e:
        print(f"获取r失败: {e}. 使用默认0.0393。")
    return 0.0393  # fallback

def calculate_parity_hanging_prices(S, K, Td, put_ask, threshold=0.5):
    """
    计算put-call parity理论值，并建议挂单价格以捕捉call高估。
    自动获取r。
    
    参数:
    - S: 当前股价 (e.g., 329.31)
    - K: 行权价 (e.g., 330)
    - Td: 到期时间 (天, e.g., 2)
    - put_ask: 当前put的ask价格 (作为参考买入价)
    - threshold: 偏差阈值 (美元, 默认0.5)
    
    返回: 打印结果
    """
    r = get_current_risk_free_rate()  # 自动获取r
    
    Ty = Td / 365
    # 计算K的现值
    pv_k = K * math.exp(-r * Ty)
    
    # 理论C - P
    theoretical_diff = S - pv_k
    
    # 理论call价格 (基于当前put_ask)
    theoretical_call = put_ask + theoretical_diff
    
    # 建议卖call限价: 理论call + threshold (只在高估时成交)
    suggested_call_sell_limit = theoretical_call + threshold
    
    # 理论组合净成本 (S - C + P ≈ pv_k)
    theoretical_net_cost = pv_k
    
    # 建议组合挂单净debit限价
    suggested_net_debit_limit = theoretical_net_cost - threshold
    
    # 输出结果
    print(f"当前r (无风险利率): {r:.4f}")
    print(f"理论K现值 (PV_K): {pv_k:.2f}")
    print(f"理论C - P: {theoretical_diff:.2f}")
    print(f"理论call价格 (基于put_ask={put_ask}): {theoretical_call:.2f}")
    print(f"建议卖call限价 (最低卖出价): >= {suggested_call_sell_limit:.2f} (挂单只在call高估时成交)")
    print(f"理论组合净成本: {theoretical_net_cost:.2f}")
    print(f"建议组合挂单净debit限价: <= {suggested_net_debit_limit:.2f} (以锁定超额利润)")
    print("\n解释: 在富途组合挂单中，设置卖call限价 >= 建议值，买入put限价 <= put_ask，买入正股市价。")
    print("如果市场call报价 > 建议限价，表明违反parity，可自动成交实现套利。")
    print("监控财报前IV上升时使用，调整threshold根据流动性（小=0.2，大=1.0）。")


if __name__ == "__main__":
    # 示例使用 (基于2025-08-20数据: S=329.31, K=330, Td=2, put_ask=6.06)
    # 注意: 实际运行时替换为实时数据
    calculate_parity_hanging_prices(
        S=329.31, K=330, 
        Td=2, put_ask=6.06, 
        threshold=1.0
    )


