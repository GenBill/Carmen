"""A 股回撤预警展示使用的同花顺日线与实时行情。"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

import pandas as pd

from hithink_finance import get_hithink_client


def fetch_daily_hist(symbol: str, start_date: date) -> pd.DataFrame:
    rows = get_hithink_client().get_historical(
        symbol,
        start=start_date,
        end=date.today() + timedelta(days=1),
        adjust="forward",
    )
    if not rows:
        raise ValueError("同花顺日线为空")
    frame = pd.DataFrame(rows)
    frame["date"] = (
        pd.to_datetime(frame["date_ms"], unit="ms", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.date
    )
    frame = frame.rename(
        columns={
            "open_price": "Open",
            "close_price": "Close",
            "high_price": "High",
            "low_price": "Low",
            "volume": "Volume",
        }
    )
    frame = frame[["date", "Open", "Close", "High", "Low", "Volume"]]
    frame = frame.sort_values("date").reset_index(drop=True)
    frame.index = pd.to_datetime(frame["date"])
    return frame


def fetch_rebound_quote(symbol: str, since_date: date) -> Optional[Dict[str, Any]]:
    """返回入队以来最高价和同花顺最新价；失败返回 None。"""
    try:
        hist = fetch_daily_hist(symbol, since_date)
        sub = hist[hist["date"] >= since_date]
        if sub.empty:
            return None
        peak_high = float(sub["High"].max())
        snapshots = get_hithink_client().get_snapshot([symbol])
        latest = snapshots[0].get("last_price") if snapshots else None
        current_price = float(latest) if latest is not None else float(hist.iloc[-1]["Close"])
        source = "hithink_snapshot" if latest is not None else "hithink_hist_close"
        return {
            "hist": hist,
            "peak_high": peak_high,
            "current_price": current_price,
            "price_source": source,
        }
    except Exception:
        return None