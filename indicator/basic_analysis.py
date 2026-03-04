import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import json
from typing import Tuple, Dict, Any

from agent.deepseek import DeepSeekAPI, fetch_a_share_data

# ================== 配置区 ==================
deepseek = DeepSeekAPI(token_path="agent/deepseek.token")
client = deepseek.client


def get_stock_data(code: str, name: str = None) -> Tuple[str, Dict[str, Any]]:
    """抓取 A 股数据（复用 deepseek.fetch_a_share_data）+ LLM 基本面分析"""
    try:
        code = str(code).strip()
        if code.endswith(".SS") or code.endswith(".SZ"):
            code = code[:6]
        if not code.isdigit() or len(code) != 6:
            return f"无效的 A 股代码: {code}", {}

        data_summary = fetch_a_share_data(code, name=name)
        if not data_summary:
            return f"未找到股票 {code} 的数据", {}

        # LLM 分析
        stock_name = name or data_summary.get("名称", code)
        prompt = f"""
你是一个A股量化分析师，基于以下数据，为股票{code} {stock_name} 生成**基本面分析报告**。
要求：
- 结构：1.基本面概况 2.近期走势&技术信号 3.多重过滤评估（量价/资金/技术/基本面/环境/风险，总分/100） 4.当前判断&建议
- 语气专业中性，突出"庄家建仓"残血信号、风险点、窗口期。
- 用表格展示过滤层级。

数据：
{json.dumps(data_summary, ensure_ascii=False, indent=2)}

输出纯Markdown。
"""
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1200,
        )
        analysis = response.choices[0].message.content
        return analysis, data_summary

    except Exception as e:
        return f"分析失败: {str(e)}", {}


# ================== 使用示例 ==================
if __name__ == "__main__":
    codes = ["300935", "603090"]
    for code in codes:
        analysis, raw = get_stock_data(code)
        print(f"\n=== {code} 基本面分析 ===\n")
        print(analysis)
        print("\n原始数据:", json.dumps(raw, ensure_ascii=False, indent=2))
