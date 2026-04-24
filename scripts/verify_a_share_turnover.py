#!/usr/bin/env python3
"""
本机/生产自检：A 股换手率从哪来、接口字段是什么。

数据链：akshare.stock_zh_a_spot_em() → 东财 clist 接口；列名「换手率」为当日换手（%）；
      fetch_a_share_data 在 agent/deepseek.py 内用「代码」6 位对齐，并对换手率做有限浮点清洗。

用法（需在能访问东财 API 的环境，必要时设 NO_PROXY=1 或走可用代理）：
  python3 scripts/verify_a_share_turnover.py 603976
  python3 scripts/verify_a_share_turnover.py 000001 300750
"""
import os
import sys

# 项目根
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.deepseek import (  # noqa: E402
    _em_code_to_six,
    _coerce_eastmoney_turnover_pct,
    fetch_a_share_data,
)


def _diagnose_why_no_fetch(want: str) -> str:
    """当 fetch 返回 {} 时，单独拉一次 spot 说明是网络/表空/无匹配，避免误以为接口逻辑错了。"""
    try:
        import akshare as ak
    except ImportError as e:
        return f"无法 import akshare: {e}"
    try:
        spot = ak.stock_zh_a_spot_em()
    except Exception as e:
        return f"stock_zh_a_spot_em 失败（多为网络/代理/东财断连）: {type(e).__name__}: {e}"
    if spot is None or len(spot) == 0:
        return "spot 表无行数据"
    if "代码" not in spot.columns:
        return f"列名异常: 无「代码」, 前若干列: {list(spot.columns)[:12]}"
    key = spot["代码"].map(_em_code_to_six)
    n_match = int((key == want).sum())
    return f"spot 行数={len(spot)} | 6 位匹配 {want!r} 行数={n_match}"


def _main():
    args = [a.strip() for a in (sys.argv[1:] or ["603976", "000001"]) if a.strip()]
    print("数据接口: akshare.stock_zh_a_spot_em() / 东财 clist; 主逻辑见 agent/deepseek.fetch_a_share_data")
    print("判读: 仅当「fetch 有数据: True」且换手率为 float 时，才表示**真实行情已通**。\n")
    for code in args:
        want = _em_code_to_six(code)
        d = fetch_a_share_data(code)
        t = d.get("换手率") if d else None
        ok = bool(d)
        print(
            f"代码 {code!r} → 规范化键 {want!r} | fetch 有数据: {ok} | "
            f"换手率(清洗后)={t!r} (type {type(t).__name__})"
        )
        if not ok and want and len(want) == 6:
            print(f"  说明: { _diagnose_why_no_fetch(want) }")
    print("\n(以下为本地**无网络**数学探针，与上面是否连上东财无关)")
    print("清洗函数探针: _coerce_eastmoney_turnover_pct(3.2)=", _coerce_eastmoney_turnover_pct(3.2))
    print("清洗函数探针: _coerce_eastmoney_turnover_pct('4.1%')=", _coerce_eastmoney_turnover_pct("4.1%"))


if __name__ == "__main__":
    _main()
