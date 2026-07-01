"""Upcoming earnings proximity text for Telegram buy-signal footer."""
from __future__ import annotations

import re
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutTimeout
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import pytz
import requests

_FETCH_TIMEOUT_SEC = 14.0
_CACHE_TTL_SEC = 6 * 3600
_CACHE: Dict[str, Tuple[float, Optional["EarningsSnapshot"]]] = {}

MAX_PROXIMITY_DAYS = 14
EARNINGS_LOOKUP_ENABLED = str(os.getenv("CARMEN_EARNINGS_LOOKUP_ENABLED", "0")).strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

NASDAQ_CALENDAR_URL = "https://api.nasdaq.com/api/calendar/earnings"
NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}


@dataclass(frozen=True)
class EarningsSnapshot:
    """Next earnings row (market-local calendar date + optional Chinese timing hint)."""

    earnings_date: date
    timing_zh: Optional[str]


def _local_today(symbol: str) -> date:
    u = symbol.upper()
    if u.endswith(".HK"):
        tz = pytz.timezone("Asia/Hong_Kong")
    elif u.endswith(".SS") or u.endswith(".SZ"):
        tz = pytz.timezone("Asia/Shanghai")
    else:
        tz = pytz.timezone("America/New_York")
    return datetime.now(tz).date()


def _market_tz(symbol: str):
    u = symbol.upper()
    if u.endswith(".HK"):
        return pytz.timezone("Asia/Hong_Kong")
    if u.endswith(".SS") or u.endswith(".SZ"):
        return pytz.timezone("Asia/Shanghai")
    return pytz.timezone("America/New_York")


def _normalize_yfinance_ticker(symbol: str) -> Optional[str]:
    s = symbol.strip().upper()
    if not s:
        return None
    if s.endswith(".SS") or s.endswith(".SZ") or s.endswith(".HK"):
        return s
    if "." in s:
        return s.replace(".", "-")
    return s


def _is_us_equity(symbol: str) -> bool:
    u = symbol.upper()
    return not (u.endswith(".HK") or u.endswith(".SS") or u.endswith(".SZ"))


def _norm_cmp_symbol(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _plain_us_symbol_for_nasdaq(symbol: str, ysym: str) -> str:
    """Nasdaq calendar rows use tickers like BRK/B — compare via _norm_cmp_symbol."""
    base = symbol.strip().upper()
    if base.endswith(".HK") or base.endswith(".SS") or base.endswith(".SZ"):
        return ""
    if base:
        return base.replace("-", ".").replace("/", ".")
    return ysym.replace("-", ".").replace("/", ".")


def _calendar_earnings_dates(cal: Optional[dict]) -> List[date]:
    if not cal or not isinstance(cal, dict):
        return []
    raw = cal.get("Earnings Date")
    if raw is None:
        return []
    if isinstance(raw, date):
        return [raw]
    if not isinstance(raw, list):
        return []
    out: List[date] = []
    for x in raw:
        if isinstance(x, date):
            out.append(x)
        elif hasattr(x, "date"):
            try:
                d = x.date()
                if isinstance(d, date):
                    out.append(d)
            except Exception:
                pass
    return out


def _nasdaq_slot_zh(code: Optional[str]) -> Optional[str]:
    """Return 盘前/盘后/盘中, or None if unknown / not supplied."""
    if not code:
        return None
    value = str(code).strip().lower()
    mapping = {
        "time-not-supplied": None,
        "amc": "盘后",
        "bmo": "盘前",
        "dmh": "盘中",
    }
    return mapping.get(value)


def _fetch_nasdaq_earnings_rows(report_date: date) -> List[dict]:
    date_str = report_date.strftime("%Y-%m-%d")
    for _ in range(2):
        try:
            resp = requests.get(
                NASDAQ_CALENDAR_URL,
                params={"date": date_str},
                headers=NASDAQ_HEADERS,
                timeout=8,
            )
            resp.raise_for_status()
            payload = resp.json()
            rows = payload.get("data", {}).get("rows", [])
            return rows if isinstance(rows, list) else []
        except Exception:
            continue
    return []


def _nasdaq_timing_label(us_plain: str, report_date: date) -> Optional[str]:
    if not us_plain:
        return None
    want = _norm_cmp_symbol(us_plain)
    if not want:
        return None
    rows = _fetch_nasdaq_earnings_rows(report_date)
    for row in rows:
        sym = str(row.get("symbol", "")).strip()
        if _norm_cmp_symbol(sym) != want:
            continue
        slot = _nasdaq_slot_zh(row.get("time"))
        if slot:
            return f"美股{slot}披露"
        return "美股财报披露时段未标注"
    return None


def _timing_from_local_dt(symbol: str, local_dt: datetime) -> str:
    u = symbol.upper()
    h, m = local_dt.hour, local_dt.minute
    hm = f"{h}:{m:02d}"
    if u.endswith(".HK"):
        return f"港股 {hm}（港时）披露"

    if u.endswith(".SS") or u.endswith(".SZ"):
        segment = ""
        if h >= 18:
            segment = "盘后 · "
        elif 12 <= h < 18:
            segment = "午后 · "
        elif h < 12:
            segment = "午前 · "
        return f"A股 {segment}北京时间 {hm} 披露"

    mins = h * 60 + m
    open_m = 9 * 60 + 30
    close_m = 16 * 60
    if mins < open_m:
        return "美股盘前披露"
    if mins >= close_m:
        return "美股盘后披露"
    return "美股盘中披露"


def _snapshot_from_yahoo_earnings_dates(symbol: str, ysym: str) -> Optional[EarningsSnapshot]:
    import pandas as pd
    import yfinance as yf

    df = yf.Ticker(ysym).get_earnings_dates(limit=25)
    if df is None or getattr(df, "empty", True):
        return None

    idx = df.index
    if idx is None or len(idx) == 0:
        return None

    now_ts = pd.Timestamp.now(tz="UTC")
    future_mask = idx >= now_ts
    if not future_mask.any():
        return None

    next_ts = idx[future_mask].min()
    try:
        ts_py = next_ts.to_pydatetime()
    except Exception:
        return None

    if ts_py.tzinfo is None:
        ts_py = pytz.UTC.localize(ts_py)

    mtz = _market_tz(symbol)
    local = ts_py.astimezone(mtz)
    ed = local.date()
    timing = _timing_from_local_dt(symbol, local)
    return EarningsSnapshot(earnings_date=ed, timing_zh=timing)


def _snapshot_from_calendar_fallback(symbol: str, ysym: str) -> Optional[EarningsSnapshot]:
    import yfinance as yf

    cal = yf.Ticker(ysym).calendar
    dates = _calendar_earnings_dates(cal if isinstance(cal, dict) else {})
    today = _local_today(symbol)
    upcoming = [d for d in dates if d >= today]
    if not upcoming:
        return None
    next_d = min(upcoming)

    timing: Optional[str] = None
    if _is_us_equity(symbol):
        plain = _plain_us_symbol_for_nasdaq(symbol, ysym)
        timing = _nasdaq_timing_label(plain, next_d)

    return EarningsSnapshot(earnings_date=next_d, timing_zh=timing)


def _fetch_snapshot_uncached(symbol: str) -> Optional[EarningsSnapshot]:
    ysym = _normalize_yfinance_ticker(symbol)
    if not ysym:
        return None

    snap = _snapshot_from_yahoo_earnings_dates(symbol, ysym)
    if snap is not None:
        return snap

    return _snapshot_from_calendar_fallback(symbol, ysym)


def get_earnings_snapshot(symbol: str) -> Optional[EarningsSnapshot]:
    if not EARNINGS_LOOKUP_ENABLED:
        return None

    ysym = _normalize_yfinance_ticker(symbol)
    key = ysym or symbol.strip().upper()
    now_m = time.monotonic()
    if key in _CACHE:
        ts, cached = _CACHE[key]
        if now_m - ts < _CACHE_TTL_SEC:
            return cached

    snap: Optional[EarningsSnapshot] = None
    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(_fetch_snapshot_uncached, symbol)
    try:
        snap = fut.result(timeout=_FETCH_TIMEOUT_SEC)
    except FutTimeout:
        fut.cancel()
        snap = None
    except Exception:
        snap = None
    finally:
        # Do not wait for a stuck yfinance earnings request.  This function is
        # best-effort footer decoration and must never block market scans.
        pool.shutdown(wait=False, cancel_futures=True)

    _CACHE[key] = (now_m, snap)
    return snap


def earnings_proximity_note(symbol: str, max_days: int = MAX_PROXIMITY_DAYS) -> Optional[str]:
    """One-line Chinese note for Telegram footer, or None if not within window / unknown."""
    snap = get_earnings_snapshot(symbol)
    if snap is None:
        return None

    today = _local_today(symbol)
    delta = (snap.earnings_date - today).days
    if delta < 0 or delta > max_days:
        return None

    if delta == 0:
        base = "📅 财报当天"
        if snap.timing_zh:
            return f"{base} · {snap.timing_zh}"
        return base

    return f"⏳ 距离财报披露仅剩{delta}天"
