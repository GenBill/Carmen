#!/usr/bin/env python3
"""验证 Carmen 的同花顺 A 股换手率与基础数据链路。"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.deepseek import fetch_a_share_data, fetch_a_share_turnover_rate  # noqa: E402
from hithink_finance import normalize_thscode  # noqa: E402


def _main() -> None:
    args = [a.strip() for a in (sys.argv[1:] or ["603976", "000001"]) if a.strip()]
    print("数据接口: HiThink Financial API snapshot + auction snapshot")
    print("换手率公式: volume × last_price ÷ float_market_cap × 100\n")
    for code in args:
        thscode = normalize_thscode(code)
        turnover = fetch_a_share_turnover_rate(code)
        data = fetch_a_share_data(code)
        print(
            f"代码 {code!r} → {thscode!r} | 行情有效: {bool(data)} | "
            f"换手率={turnover!r} | 最新价={data.get('最新价') if data else None!r}"
        )


if __name__ == "__main__":
    _main()
