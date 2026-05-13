#!/usr/bin/env python3
"""随机抽取 A 股，对比 akshare / yfinance 的今日开盘价。

运行：
  cd /home/serv/Carmen
  source /home/serv/.zshrc && conda run -n Quant python scripts/compare_a_open_prices.py
"""

from __future__ import annotations

import argparse
import os
import random
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd
import pytz
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
A_LIST = ROOT / "stocks_list" / "cache" / "china_screener_A.csv"
CN_TZ = pytz.timezone("Asia/Shanghai")


def normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper()


def symbol_to_code(symbol: str) -> str:
    return normalize_symbol(symbol).split(".")[0]


def load_a_share_pool() -> pd.DataFrame:
    if not A_LIST.exists():
        raise FileNotFoundError(f"A股列表不存在: {A_LIST}")
    df = pd.read_csv(A_LIST, dtype=str)
    if "Symbol" not in df.columns:
        raise ValueError(f"A股列表缺少 Symbol 列: {A_LIST}")
    if "Name" not in df.columns:
        df["Name"] = ""
    df = df[["Symbol", "Name"]].dropna(subset=["Symbol"]).copy()
    df["Symbol"] = df["Symbol"].map(normalize_symbol)
    df["Code"] = df["Symbol"].map(symbol_to_code)
    return df.drop_duplicates("Symbol")


@contextmanager
def without_proxy():
    """部分国内行情源经本机代理会断连；akshare 调用期间临时直连。"""
    keys = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
    old = {k: os.environ.get(k) for k in keys}
    try:
        for k in keys:
            os.environ.pop(k, None)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def get_akshare_open_map() -> dict[str, Any]:
    """用新浪实时 A 股接口取今日今开；一次性拉全市场，避免逐只请求。

    备注：EastMoney 的 stock_zh_a_spot_em 在本机网络路径偶发断连；
    stock_zh_a_spot 更慢但当前更稳定。
    """
    spot = ak.stock_zh_a_spot()
    code_col = "代码"
    open_col = "今开"
    if code_col not in spot.columns or open_col not in spot.columns:
        raise ValueError(f"akshare 返回列异常: {list(spot.columns)}")
    tmp = spot[[code_col, open_col]].copy()
    tmp[code_col] = tmp[code_col].astype(str).str.extract(r"(\d{6})", expand=False)
    return dict(zip(tmp[code_col], tmp[open_col]))


def get_yfinance_today_open(symbol: str, today: str) -> tuple[Any, str]:
    """返回 (open, note)。yfinance 日线在非交易日/未更新时可能没有 today 行。"""
    try:
        hist = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=False, timeout=15)
    except Exception as exc:  # noqa: BLE001 - quick diagnostic script
        return None, f"yf_error: {type(exc).__name__}: {exc}"

    if hist is None or hist.empty:
        return None, "yf_empty"

    for idx, row in hist.iterrows():
        idx_date = idx.tz_convert(CN_TZ).strftime("%Y-%m-%d") if getattr(idx, "tzinfo", None) else idx.strftime("%Y-%m-%d")
        if idx_date == today:
            val = row.get("Open")
            return (None if pd.isna(val) else float(val)), ""

    last_idx = hist.index[-1]
    last_date = last_idx.tz_convert(CN_TZ).strftime("%Y-%m-%d") if getattr(last_idx, "tzinfo", None) else last_idx.strftime("%Y-%m-%d")
    val = hist.iloc[-1].get("Open")
    return (None if pd.isna(val) else float(val)), f"yf_latest_not_today:{last_date}"


def fmt_price(x: Any) -> str:
    if x is None or pd.isna(x):
        return "NA"
    try:
        return f"{float(x):.3f}"
    except Exception:  # noqa: BLE001
        return str(x)


def main() -> None:
    parser = argparse.ArgumentParser(description="随机抽取 A 股，对比 akshare / yfinance 今日开盘价")
    parser.add_argument("-n", "--count", type=int, default=10, help="抽样数量，默认 10")
    parser.add_argument("--seed", type=int, default=None, help="随机种子；不填则真随机")
    args = parser.parse_args()

    today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    pool = load_a_share_pool()
    if len(pool) < args.count:
        raise ValueError(f"股票池不足 {args.count} 只: {len(pool)}")

    rng = random.Random(args.seed)
    sample = pool.sample(n=args.count, random_state=rng.randrange(2**32) if args.seed is not None else None)

    ak_open = get_akshare_open_map()

    rows = []
    for _, item in sample.iterrows():
        symbol = item["Symbol"]
        code = item["Code"]
        yf_open, note = get_yfinance_today_open(symbol, today)
        ak_val = ak_open.get(code)
        diff = None
        if ak_val is not None and yf_open is not None and not pd.isna(ak_val):
            diff = float(ak_val) - float(yf_open)
        rows.append(
            {
                "symbol": symbol,
                "name": item.get("Name", ""),
                "akshare_open": fmt_price(ak_val),
                "yfinance_open": fmt_price(yf_open),
                "diff_ak_minus_yf": "NA" if diff is None else f"{diff:.3f}",
                "note": note,
            }
        )

    out = pd.DataFrame(rows)
    print(f"A股随机抽样今日开盘价对比 | date={today} | n={len(out)}")
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
