"""
A 股高建仓强度（>=10.0）30 日动态队列，及「回撤后均线」二次预警。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pytz

from rebound_ak_quote import fetch_rebound_quote

HIGH_BUILD_SCORE_THRESHOLD = 10.0
HISTORY_RETENTION_DAYS = 30
MIN_DAYS_AFTER_FIRST_ALERT = 7

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
    记录建仓强度 >= 10.0 的 A 股预警；同一标的保留首次预警日期与当日收盘价。
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


def _ma_pair_df(short: pd.Series, long: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"short": short, "long": long}).dropna()


def _has_cross_down(pair: pd.DataFrame) -> bool:
    for i in range(1, len(pair)):
        prev = pair.iloc[i - 1]
        curr = pair.iloc[i]
        if prev["short"] >= prev["long"] and curr["short"] < curr["long"]:
            return True
    return False


def _has_cross_up(pair: pd.DataFrame) -> bool:
    for i in range(1, len(pair)):
        prev = pair.iloc[i - 1]
        curr = pair.iloc[i]
        if prev["short"] <= prev["long"] and curr["short"] > curr["long"]:
            return True
    return False


def _has_imminent_cross_down(pair: pd.DataFrame) -> bool:
    if len(pair) < 2:
        return False
    prev, curr = pair.iloc[-2], pair.iloc[-1]
    gap_prev = float(prev["short"] - prev["long"])
    gap_now = float(curr["short"] - curr["long"])
    slope = gap_now - gap_prev
    return gap_now > 0 and gap_now + 2 * slope < 0


def _has_imminent_cross_up(pair: pd.DataFrame) -> bool:
    if len(pair) < 2:
        return False
    prev, curr = pair.iloc[-2], pair.iloc[-1]
    gap_prev = float(prev["short"] - prev["long"])
    gap_now = float(curr["short"] - curr["long"])
    slope = gap_now - gap_prev
    return gap_now < 0 and gap_now + 2 * slope > 0


def _ma_eight_pick_one(
    vol_sma5: pd.Series, vol_sma10: pd.Series, price_sma5: pd.Series, price_sma10: pd.Series
) -> Tuple[bool, Optional[str]]:
    vol_pair = _ma_pair_df(vol_sma5, vol_sma10)
    price_pair = _ma_pair_df(price_sma5, price_sma10)
    checks = [
        ("量能死叉", _has_cross_down(vol_pair)),
        ("量能即将死叉", _has_imminent_cross_down(vol_pair)),
        ("量能金叉", _has_cross_up(vol_pair)),
        ("量能即将金叉", _has_imminent_cross_up(vol_pair)),
        ("均价死叉", _has_cross_down(price_pair)),
        ("均价即将死叉", _has_imminent_cross_down(price_pair)),
        ("均价金叉", _has_cross_up(price_pair)),
        ("均价即将金叉", _has_imminent_cross_up(price_pair)),
    ]
    for name, ok in checks:
        if ok:
            return True, name
    return False, None


def _slice_hist_after_first_alert(hist: pd.DataFrame, first_alert_date: date) -> pd.DataFrame:
    """取首次预警日次日至今的 K 线（含当日）。"""
    if hist is None or hist.empty:
        return hist
    start = first_alert_date + timedelta(days=1)
    idx = pd.to_datetime(hist.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    if "date" in hist.columns:
        mask = pd.to_datetime(hist["date"]).dt.date >= start
    else:
        mask = idx.date >= start
    return hist.loc[mask]


def check_rebound_conditions(
    entry: Dict[str, Any],
    hist: pd.DataFrame,
    current_price: float,
    today: Optional[date] = None,
) -> Tuple[bool, Optional[str]]:
    first_d = _parse_date(entry.get("first_alert_date"))
    alert_close = float(entry.get("alert_close") or 0)
    if first_d is None or alert_close <= 0:
        return False, None

    today = today or _today_beijing()
    if (today - first_d).days < MIN_DAYS_AFTER_FIRST_ALERT:
        return False, None

    if float(current_price) >= alert_close:
        return False, None

    window = _slice_hist_after_first_alert(hist, first_d)
    if window is None or len(window) < 12:
        return False, None

    vol_col = "Volume" if "Volume" in window.columns else "成交量"
    close_col = "Close" if "Close" in window.columns else "收盘"
    vol_sma5 = window[vol_col].rolling(window=5, min_periods=5).mean()
    vol_sma10 = window[vol_col].rolling(window=10, min_periods=10).mean()
    price_sma5 = window[close_col].rolling(window=5, min_periods=5).mean()
    price_sma10 = window[close_col].rolling(window=10, min_periods=10).mean()

    return _ma_eight_pick_one(vol_sma5, vol_sma10, price_sma5, price_sma10)


def _drop_display_lines(
    ak_quote: Optional[Dict[str, Any]],
    scan_price: Optional[float] = None,
) -> List[str]:
    """akshare 跌幅仅展示；取不到则输出警告，不参与过滤。"""
    if ak_quote:
        peak = float(ak_quote.get("peak_high") or 0)
        current = float(ak_quote.get("current_price") or 0)
        if peak > 0 and current > 0:
            drop_pct = (peak - current) / peak * 100.0
            return [
                f"入队以来最高: {peak:.2f}",
                f"当前价格(akshare): {current:.2f}",
                f"较入队以来最高跌幅: {drop_pct:.2f}%",
            ]
    lines = ["⚠️ 跌幅数据暂不可用（akshare 未取到入队以来行情，不影响本次触发）"]
    if scan_price and float(scan_price) > 0:
        lines.append(f"扫描现价(参考): {float(scan_price):.2f}")
    return lines


def _format_rebound_message(
    entry: Dict[str, Any],
    ma_trigger: Optional[str],
    ak_quote: Optional[Dict[str, Any]] = None,
    scan_price: Optional[float] = None,
) -> str:
    symbol = entry.get("symbol", "")
    cn = entry.get("stock_cn_name") or ""
    cn_suffix = f" {cn}" if cn else ""
    first_d = entry.get("first_alert_date", "")
    alert_close = float(entry.get("alert_close") or 0)
    pbs = float(entry.get("position_build_score") or 0)
    now_text = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    ma_line = ma_trigger or "均线信号"
    body = [
        "📉 A股回撤均线金叉预警",
        f"时间: {now_text}",
        f"股票: {symbol}{cn_suffix}",
        f"首次预警日: {first_d}",
        f"预警日收盘: {alert_close:.2f}",
        f"建仓强度(首次): {pbs:.1f}",
        *_drop_display_lines(ak_quote, scan_price),
        f"触发: {ma_line}",
        "条件: 入队>=7日 | 现价低于预警日收盘 | 量/价5/10均线八选一",
    ]
    return "\n".join(body)


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
    遍历 30 日高建仓队列，满足「入队>=7日 + 现价低于预警日收盘 + 均线八选一」则推送。
    akshare 跌幅仅写入预警正文，不参与过滤。
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
        first_d = _parse_date(entry.get("first_alert_date"))
        if not symbol or first_d is None:
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
        scan_price = float(stock_data.get("close") or 0)
        if hist is None or scan_price <= 0:
            continue

        ok, ma_trigger = check_rebound_conditions(entry, hist, scan_price, today=today)
        if not ok:
            continue

        ak_quote = fetch_rebound_quote(symbol, first_d)
        if not ak_quote:
            print(f"⚠️  {symbol} akshare 跌幅展示不可用，仍按均线条件推送")
        msg = _format_rebound_message(entry, ma_trigger, ak_quote=ak_quote, scan_price=scan_price)
        signal_id = f"rebound:{symbol}:{entry.get('first_alert_date')}"
        sent = notifier.send_message(msg, reply_markup=None, parse_mode=None)
        if sent:
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
                        "ma_trigger": ma_trigger,
                    }
                )
            except Exception:
                pass
            print(f"📉 {symbol} 回撤均线预警已推送 ({ma_trigger})")
        else:
            print(f"⚠️  {symbol} 回撤均线预警推送失败")

    if updated:
        _save_queue(queue)
    if triggered:
        print(f"📉 本轮回撤均线预警: {triggered} 条")
    return triggered
