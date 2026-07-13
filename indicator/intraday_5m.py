"""按需拉取 5 分钟 K 线（仅 Pin Bar 前置命中后调用）。"""
from __future__ import annotations

import threading
import time
from typing import Optional

import pandas as pd

from yf_safe import yf_download

_CACHE_LOCK = threading.Lock()
_CACHE: dict[tuple[str, str], pd.DataFrame] = {}
_LAST_FETCH_TS = 0.0
_MIN_FETCH_INTERVAL_SEC = 0.35


def _normalize_5m_df(df: Optional[pd.DataFrame], symbol: str) -> Optional[pd.DataFrame]:
    if df is None or getattr(df, 'empty', True):
        return None
    out = df.copy()
    sym_u = str(symbol).strip().upper()
    if isinstance(out.columns, pd.MultiIndex):
        try:
            level = out.columns.get_level_values(-1)
            tickers = [str(x).upper() for x in level.unique()]
        except Exception:
            tickers = []
        if sym_u in tickers:
            out = out.xs(sym_u, axis=1, level=-1, drop_level=True)
        elif len(tickers) == 1:
            out = out.xs(out.columns.levels[-1][0], axis=1, level=-1, drop_level=True)
        else:
            return None

    rename = {}
    for col in out.columns:
        key = str(col).strip().lower()
        if key == 'open':
            rename[col] = 'Open'
        elif key == 'high':
            rename[col] = 'High'
        elif key == 'low':
            rename[col] = 'Low'
        elif key == 'close':
            rename[col] = 'Close'
        elif key == 'volume':
            rename[col] = 'Volume'
    if rename:
        out = out.rename(columns=rename)

    need = {'Open', 'High', 'Low', 'Close', 'Volume'}
    if not need.issubset(set(out.columns)):
        return None
    return out[list(need)].dropna(how='all')


def fetch_5m_hist(symbol: str, trade_date: Optional[str] = None, period: str = "5d") -> Optional[pd.DataFrame]:
    """
    懒加载 5m K。同进程按 (symbol, trade_date) 缓存，请求间强制间隔。
    """
    global _LAST_FETCH_TS
    cache_key = (str(symbol).strip().upper(), str(trade_date or '')[:10])
    with _CACHE_LOCK:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            return cached.copy()

    with _CACHE_LOCK:
        elapsed = time.monotonic() - _LAST_FETCH_TS
        if elapsed < _MIN_FETCH_INTERVAL_SEC:
            time.sleep(_MIN_FETCH_INTERVAL_SEC - elapsed)

    try:
        raw = yf_download(
            symbol,
            period=period,
            interval="5m",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
    except Exception:
        return None
    finally:
        with _CACHE_LOCK:
            _LAST_FETCH_TS = time.monotonic()

    hist = _normalize_5m_df(raw, symbol)
    if hist is None or hist.empty:
        return None

    with _CACHE_LOCK:
        _CACHE[cache_key] = hist.copy()
    return hist


def clear_5m_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
