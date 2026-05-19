"""
A 股高建仓强度（>=9.0）30 日动态队列，及「回撤后均线金叉」二次预警。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pytz

HIGH_BUILD_SCORE_THRESHOLD = 9.0
HISTORY_RETENTION_DAYS = 30
MIN_DAYS_AFTER_FIRST_ALERT = 7
PRICE_DROP_VS_ALERT_CLOSE_PCT = 4.0

QUEUE_FILE = Path(__file__).resolve().parent / "runtime" / "a_share_high_build_alerts.json"
BEIJING_TZ = pytz.timezone("Asia/Shanghai")


def _today_beijing() -> date:
    return datetime.now(BEIJING_TZ).date()


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _load_queue() -> List[Dict[str, Any]]:
    if not QUEUE_FILE.exists():
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"⚠️  读取 A 股高建仓队列失败: {e}")
        return []


def _save_queue(queue: List[Dict[str, Any]]) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def prune_old_alerts(queue: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """移除首次预警超过 HISTORY_RETENTION_DAYS 的记录。"""
    items = list(queue if queue is not None else _load_queue())
    cutoff = _today_beijing() - timedelta(days=HISTORY_RETENTION_DAYS)
    kept: List[Dict[str, Any]] = []
    for item in items:
        first_d = _parse_date(item.get("first_alert_date"))
        if first_d is None or first_d < cutoff:
            continue
        kept.append(item)
    return kept


def maybe_record_high_build_alert(
    symbol: str,
    alert_date: str,
    alert_close: float,
    position_build_score: float,
    stock_cn_name: Optional[str] = None,
) -> None:
    """
    记录建仓强度 >= 9.0 的 A 股预警；同一标的保留首次预警日期与当日收盘价。
    """
    upper = (symbol or "").upper()
    if not (upper.endswith(".SS") or upper.endswith(".SZ")):
        return
    if float(position_build_score or 0) < HIGH_BUILD_SCORE_THRESHOLD:
        return
    first_d = _parse_date(alert_date)
    if first_d is None or alert_close is None or float(alert_close) <= 0:
        return

    queue = prune_old_alerts()
    for item in queue:
        if item.get("symbol") == symbol:
            item["position_build_score"] = max(
                float(item.get("position_build_score") or 0),
                float(position_build_score),
            )
            if stock_cn_name and not item.get("stock_cn_name"):
                item["stock_cn_name"] = stock_cn_name
            _save_queue(queue)
            return

    queue.append(
        {
            "symbol": symbol,
            "stock_cn_name": (stock_cn_name or "").strip() or None,
            "first_alert_date": first_d.isoformat(),
            "alert_close": round(float(alert_close), 4),
            "position_build_score": round(float(position_build_score), 2),
            "rebound_notified": False,
        }
    )
    _save_queue(queue)


def has_death_cross_then_golden_cross(short: pd.Series, long: pd.Series) -> bool:
    """序列中是否先出现 short 下穿 long，再出现 short 上穿 long。"""
    pair = pd.DataFrame({"short": short, "long": long}).dropna()
    if len(pair) < 2:
        return False
    saw_death = False
    for i in range(1, len(pair)):
        prev = pair.iloc[i - 1]
        curr = pair.iloc[i]
        if prev["short"] >= prev["long"] and curr["short"] < curr["long"]:
            saw_death = True
        if saw_death and prev["short"] <= prev["long"] and curr["short"] > curr["long"]:
            return True
    return False


def _slice_hist_after_first_alert(hist: pd.DataFrame, first_alert_date: date) -> pd.DataFrame:
    """取首次预警日次日至今的 K 线（含当日）。"""
    if hist is None or hist.empty:
        return hist
    start = first_alert_date + timedelta(days=1)
    idx = pd.to_datetime(hist.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    mask = idx.date >= start
    return hist.loc[mask]


def check_rebound_conditions(
    entry: Dict[str, Any],
    hist: pd.DataFrame,
    current_close: float,
    today: Optional[date] = None,
) -> bool:
    first_d = _parse_date(entry.get("first_alert_date"))
    alert_close = float(entry.get("alert_close") or 0)
    if first_d is None or alert_close <= 0:
        return False

    today = today or _today_beijing()
    if today < first_d + timedelta(days=MIN_DAYS_AFTER_FIRST_ALERT):
        return False

    if float(current_close) > alert_close * (1 - PRICE_DROP_VS_ALERT_CLOSE_PCT / 100.0):
        return False

    window = _slice_hist_after_first_alert(hist, first_d)
    if window is None or len(window) < 12:
        return False

    vol_sma5 = window["Volume"].rolling(window=5, min_periods=5).mean()
    vol_sma10 = window["Volume"].rolling(window=10, min_periods=10).mean()
    price_sma5 = window["Close"].rolling(window=5, min_periods=5).mean()
    price_sma10 = window["Close"].rolling(window=10, min_periods=10).mean()

    if not has_death_cross_then_golden_cross(vol_sma5, vol_sma10):
        return False
    if not has_death_cross_then_golden_cross(price_sma5, price_sma10):
        return False
    return True


def _format_rebound_message(entry: Dict[str, Any], current_close: float, drop_pct: float) -> str:
    symbol = entry.get("symbol", "")
    cn = entry.get("stock_cn_name") or ""
    cn_suffix = f" {cn}" if cn else ""
    first_d = entry.get("first_alert_date", "")
    alert_close = float(entry.get("alert_close") or 0)
    pbs = float(entry.get("position_build_score") or 0)
    now_text = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    return "\n".join(
        [
            "📉 A股回撤均线金叉预警",
            f"时间: {now_text}",
            f"股票: {symbol}{cn_suffix}",
            f"首次预警日: {first_d}",
            f"预警日收盘: {alert_close:.2f}",
            f"建仓强度(首次): {pbs:.1f}",
            f"当前价格: {current_close:.2f}",
            f"较预警收盘跌幅: {drop_pct:.2f}%",
            "条件: 预警7日后 | 收盘低于预警日4%+ | 量能5/10先死叉再金叉 | 价格5/10先死叉再金叉",
        ]
    )


def run_rebound_alert_scan(
    notifier,
    get_stock_data_fn,
    rsi_period: int = 8,
    macd_fast: int = 8,
    macd_slow: int = 17,
    macd_signal: int = 9,
    avg_volume_days: int = 8,
) -> int:
    """
    遍历 30 日高建仓队列，满足回撤+双均线金叉条件则单独推送 Telegram。
    返回本轮触发条数。
    """
    if notifier is None:
        return 0

    queue = prune_old_alerts()
    _save_queue(queue)
    if not queue:
        return 0

    triggered = 0
    today = _today_beijing()
    updated = False

    for entry in queue:
        if entry.get("rebound_notified"):
            continue
        symbol = entry.get("symbol")
        if not symbol:
            continue
        try:
            stock_data = get_stock_data_fn(
                symbol,
                rsi_period=rsi_period,
                macd_fast=macd_fast,
                macd_slow=macd_slow,
                macd_signal=macd_signal,
                avg_volume_days=avg_volume_days,
                use_cache=True,
                cache_minutes=5,
            )
        except Exception as e:
            print(f"⚠️  回撤预警扫描 {symbol} 取数失败: {e}")
            continue
        if not stock_data:
            continue

        hist = stock_data.get("hist")
        current_close = float(stock_data.get("close") or 0)
        if hist is None or current_close <= 0:
            continue

        if not check_rebound_conditions(entry, hist, current_close, today=today):
            continue

        alert_close = float(entry.get("alert_close") or 0)
        drop_pct = (alert_close - current_close) / alert_close * 100.0 if alert_close > 0 else 0.0
        msg = _format_rebound_message(entry, current_close, drop_pct)
        signal_id = f"rebound:{symbol}:{entry.get('first_alert_date')}"
        ok = notifier.send_message(msg, reply_markup=None, parse_mode=None)
        if ok:
            entry["rebound_notified"] = True
            entry["rebound_notified_at"] = datetime.now(BEIJING_TZ).isoformat()
            triggered += 1
            updated = True
            try:
                from telegram_notifier import append_signal_audit

                append_signal_audit(
                    {
                        "event": "rebound_alert_sent",
                        "symbol": symbol,
                        "signal_id": signal_id,
                        "first_alert_date": entry.get("first_alert_date"),
                    }
                )
            except Exception:
                pass
            print(f"📉 {symbol} 回撤均线金叉预警已推送")
        else:
            print(f"⚠️  {symbol} 回撤均线金叉预警推送失败")

    if updated:
        _save_queue(queue)
    if triggered:
        print(f"📉 本轮回撤均线金叉预警: {triggered} 条")
    return triggered
