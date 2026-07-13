"""美股 RSI+Pin Bar 单次试跑：强制打开时间门，关闭推送/Git，打印总耗时。"""
from __future__ import annotations

import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "indicator"))
sys.path.insert(0, ROOT)

import main as us_main


def main() -> None:
    # 当前北京时间不在 06-10 窗口，试跑强制打开 Pin Bar 轨
    us_main._us_rsi_pin_bar_scan_allowed = lambda now=None: True  # type: ignore
    # 试跑打印全部候选（日常 main.py 仍为 Top3）
    us_main.US_RSI_REBOUND_TOP_N = 0

    print("=" * 80)
    print("美股单次试跑：强制 Pin Bar 时间门=ON，TOP_N=0（全部候选），Telegram/Git=OFF")
    print("=" * 80)

    t0 = time.perf_counter()
    us_main.main_us(
        stock_path="my_stock_symbols.txt",
        rsi_period=8,
        macd_fast=8,
        macd_slow=17,
        macd_signal=9,
        avg_volume_days=8,
        use_cache=True,
        cache_minutes=60,
        offline_mode=False,
        intraday_use_all_stocks=False,
        enable_github_pages=False,
        enable_qq_notify=False,
        enable_telegram_notify=False,
    )
    elapsed = time.perf_counter() - t0
    print("=" * 80)
    print(f"✅ 美股试跑结束 总耗时={elapsed:.1f}s ({elapsed/60.0:.1f} min)")
    print("=" * 80)


if __name__ == "__main__":
    main()
