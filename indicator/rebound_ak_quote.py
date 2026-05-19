"""
A 股回撤预警展示：经 akshare 拉取入队日（含）以来最高价与现价，仅用于 Telegram 文案。
不参与触发过滤；调用期临时直连，避开代理。
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date
from typing import Any, Dict, Optional

import pandas as pd

_AKSHARE_AVAILABLE: Optional[bool] = None


@contextmanager
def without_proxy():
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


def symbol_to_code(symbol: str) -> str:
    return str(symbol or "").strip().upper().split(".")[0]


def akshare_available() -> bool:
    global _AKSHARE_AVAILABLE
    if _AKSHARE_AVAILABLE is not None:
        return _AKSHARE_AVAILABLE
    try:
        import akshare as ak  # noqa: F401

        _AKSHARE_AVAILABLE = True
    except ImportError:
        _AKSHARE_AVAILABLE = False
    return _AKSHARE_AVAILABLE


def fetch_daily_hist(code: str, start_date: date) -> pd.DataFrame:
    import akshare as ak

    with without_proxy():
        raw = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date.strftime("%Y%m%d"),
            adjust="qfq",
        )
    if raw is None or raw.empty:
        raise ValueError("akshare 日线为空")

    out = raw.copy()
    out["date"] = pd.to_datetime(out["日期"]).dt.date
    out = out.rename(
        columns={
            "开盘": "Open",
            "收盘": "Close",
            "最高": "High",
            "最低": "Low",
            "成交量": "Volume",
        }
    )
    out = out.sort_values("date").reset_index(drop=True)
    out.index = pd.to_datetime(out["date"])
    return out


def _latest_price_em(code: str) -> Optional[float]:
    try:
        from akshare.stock.stock_ask_bid_em import stock_bid_ask_em

        with without_proxy():
            snap = stock_bid_ask_em(symbol=code)
        if not isinstance(snap, dict):
            return None
        for key in ("最新", "最新价"):
            val = snap.get(key)
            if val in (None, "", "-"):
                continue
            price = float(val)
            if price > 0:
                return price
    except Exception:
        return None
    return None


def fetch_rebound_quote(symbol: str, since_date: date) -> Optional[Dict[str, Any]]:
    """
    返回 dict: peak_high、current_price、price_source（及 hist，供调试）；
    失败返回 None。仅用于预警文案展示。
    """
    if not akshare_available():
        return None
    code = symbol_to_code(symbol)
    if len(code) != 6:
        return None
    try:
        hist = fetch_daily_hist(code, since_date)
        sub = hist[hist["date"] >= since_date]
        if sub.empty:
            return None
        peak_high = float(sub["High"].max())
        em_price = _latest_price_em(code)
        last_close = float(hist.iloc[-1]["Close"])
        if em_price and em_price > 0:
            current_price = em_price
            price_source = "akshare_em_latest"
        else:
            current_price = last_close
            price_source = "akshare_hist_close"
        return {
            "hist": hist,
            "peak_high": peak_high,
            "current_price": current_price,
            "price_source": price_source,
        }
    except Exception:
        return None
