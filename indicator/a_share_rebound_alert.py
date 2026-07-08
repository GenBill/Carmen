"""
A 股「主力建仓后洗盘低吸」策略：
- 建仓强度 >= 8.0、信号触发后 3-14 日的窗口内观察；
- 阶段高点回落（落入 [(3L-H)/2, (H+L)/2) 区间）+ 量能 5/10 死叉或即将死叉时预警；
- 提示「当日收盘买入 或 次日开盘买入」；
- 支持外部 on_signal 回调接入下游执行。
"""
from __future__ import annotations

import json
import html
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd
import pytz

from a_share_st_filter import is_st_or_delisting_name
from rebound_ak_quote import fetch_rebound_quote
from telegram_notifier import append_signal_audit, carmen_alerts_muted

try:
    from stocks_list.get_all_stock import load_manual_exclude_symbols
except Exception:
    def load_manual_exclude_symbols() -> set:
        return set()

HIGH_BUILD_SCORE_THRESHOLD = 8.0
HISTORY_RETENTION_DAYS = 14
MIN_DAYS_AFTER_FIRST_ALERT = 3

QUEUE_FILE = Path(__file__).resolve().parent / "runtime" / "a_share_high_build_alerts.json"
BEIJING_TZ = pytz.timezone("Asia/Shanghai")
_QUEUE_LOCK = threading.RLock()


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
    manual_excludes = load_manual_exclude_symbols()
    kept: List[Dict[str, Any]] = []
    for item in items:
        symbol = str(item.get("symbol") or "").upper()
        if symbol in manual_excludes:
            continue
        if is_st_or_delisting_name(item.get("stock_cn_name")):
            continue
        first_d = _parse_date(item.get("first_alert_date"))
        if first_d is None or first_d < cutoff:
            continue
        kept.append(item)
    return kept


def maybe_record_high_build_alert(
    symbol: str,
    alert_date: str,
    position_build_score: float,
    stock_cn_name: Optional[str] = None,
) -> None:
    """
    记录建仓强度 >= HIGH_BUILD_SCORE_THRESHOLD 的 A 股预警；同一标的保留首次预警日期。
    """
    upper = (symbol or "").upper()
    if not (upper.endswith(".SS") or upper.endswith(".SZ")):
        return
    if upper in load_manual_exclude_symbols():
        return
    if is_st_or_delisting_name(stock_cn_name):
        return
    if float(position_build_score or 0) < HIGH_BUILD_SCORE_THRESHOLD:
        return
    first_d = _parse_date(alert_date)
    if first_d is None:
        return

    with _QUEUE_LOCK:
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
                "position_build_score": round(float(position_build_score), 2),
            }
        )
        _save_queue(queue)


def _ma_pair_df(short: pd.Series, long: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"short": short, "long": long}).dropna()


def _just_cross_down(pair: pd.DataFrame) -> bool:
    """仅判断最后两根：上一根 short >= long，当前根 short < long（今日刚死叉）。"""
    if len(pair) < 2:
        return False
    prev, curr = pair.iloc[-2], pair.iloc[-1]
    return prev["short"] >= prev["long"] and curr["short"] < curr["long"]


def _has_imminent_cross_down(pair: pd.DataFrame) -> bool:
    """仅判断最后两根：当前仍在上方但斜率向下，外推一根将翻下。"""
    if len(pair) < 2:
        return False
    prev, curr = pair.iloc[-2], pair.iloc[-1]
    gap_prev = float(prev["short"] - prev["long"])
    gap_now = float(curr["short"] - curr["long"])
    slope = gap_now - gap_prev
    return gap_now > 0 and gap_now + 2 * slope < 0


def _volume_cross_signal(vol_sma5: pd.Series, vol_sma10: pd.Series) -> Tuple[bool, Optional[str]]:
    """量能 5/10 均线信号：仅看最后两根日线，判定"今日刚死叉"或"即将死叉"。"""
    pair = _ma_pair_df(vol_sma5, vol_sma10)
    if _just_cross_down(pair):
        return True, "量能5/10死叉"
    if _has_imminent_cross_down(pair):
        return True, "量能5/10即将死叉"
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


def _hist_row_for_date(hist: pd.DataFrame, target_date: date) -> Optional[pd.Series]:
    """返回指定自然日的日线行；取不到返回 None。"""
    if hist is None or hist.empty:
        return None
    if "date" in hist.columns:
        dates = pd.to_datetime(hist["date"]).dt.date
    else:
        idx = pd.to_datetime(hist.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        dates = idx.date
    matched = hist.loc[dates == target_date]
    if matched.empty:
        return None
    return matched.iloc[-1]


def _first_alert_support_low(entry: Dict[str, Any], hist: pd.DataFrame, first_d: date, low_col: str) -> Optional[float]:
    """建仓日支撑低点。优先用队列快照；老队列从历史日线回填。"""
    raw = entry.get("first_alert_low") or entry.get("support_low")
    if raw is not None:
        try:
            value = float(raw)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass

    row = _hist_row_for_date(hist, first_d)
    if row is None or low_col not in row:
        return None
    try:
        value = float(row[low_col])
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def check_rebound_conditions(
    entry: Dict[str, Any],
    hist: pd.DataFrame,
    current_price: float,
    today: Optional[date] = None,
) -> Tuple[bool, Optional[str], Optional[float], Optional[float]]:
    """
    返回 (ok, ma_trigger, peak_high, peak_low)。

    触发要件：
    1) 距首次信号日 >= MIN_DAYS_AFTER_FIRST_ALERT 且 <= HISTORY_RETENTION_DAYS；
    2) 阶段高低区间：取信号日之后的窗口，H = window.High.max()、L = window.Low.min()，
       触发区间为 [max(建仓日低点, (3L-H)/2), (H+L)/2)，落到区间内视为「主力建仓后回落但未撤退」；
       若现价跌破建仓日低点，视为破位，不再按洗盘低吸处理；
    3) 量能 MA5/MA10 在整段 hist 上滚动计算，仅判断最后两根：
       「今日刚死叉」或「即将死叉」。
    """
    first_d = _parse_date(entry.get("first_alert_date"))
    if first_d is None:
        return False, None, None, None

    today = today or _today_beijing()
    days_after = (today - first_d).days
    if days_after < MIN_DAYS_AFTER_FIRST_ALERT or days_after > HISTORY_RETENTION_DAYS:
        return False, None, None, None

    if hist is None or len(hist) < 11:
        return False, None, None, None

    vol_col = "Volume" if "Volume" in hist.columns else "成交量"
    high_col = "High" if "High" in hist.columns else "最高"
    low_col = "Low" if "Low" in hist.columns else "最低"
    if vol_col not in hist.columns or high_col not in hist.columns or low_col not in hist.columns:
        return False, None, None, None

    support_low = _first_alert_support_low(entry, hist, first_d, low_col)
    price = float(current_price)
    if support_low is not None and price < support_low:
        return False, None, None, None

    window = _slice_hist_after_first_alert(hist, first_d)
    if window is None or len(window) < 2:
        return False, None, None, None

    peak_high = float(window[high_col].max())
    peak_low = float(window[low_col].min())
    hl_range = peak_high - peak_low
    if hl_range <= 0:
        return False, None, peak_high, peak_low

    upper_bound = (peak_high + peak_low) / 2.0
    lower_bound = peak_low - hl_range / 2.0
    if support_low is not None:
        lower_bound = max(lower_bound, support_low)
    if not (lower_bound <= price < upper_bound):
        return False, None, peak_high, peak_low

    vol_sma5 = hist[vol_col].rolling(window=5, min_periods=5).mean()
    vol_sma10 = hist[vol_col].rolling(window=10, min_periods=10).mean()
    ok, ma_trigger = _volume_cross_signal(vol_sma5, vol_sma10)
    return ok, ma_trigger, peak_high, peak_low


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
    peak_high: Optional[float],
    peak_low: Optional[float],
    scan_price: Optional[float],
    ak_quote: Optional[Dict[str, Any]] = None,
) -> str:
    symbol = entry.get("symbol", "")
    split_symbol = str(symbol).split(".")
    split_symbol_0 = split_symbol[0]
    split_symbol_1 = f"[{split_symbol[1]}]" if len(split_symbol) == 2 else ""
    cn = (entry.get("stock_cn_name") or "").strip()
    cn_suffix = f" {html.escape(cn)}" if cn else ""
    first_d = entry.get("first_alert_date", "")
    pbs = float(entry.get("position_build_score") or 0)
    now_text = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M")
    ma_line = ma_trigger or "量能5/10死叉"
    stock_line = f"股票: <code>{html.escape(split_symbol_0)}</code>{split_symbol_1}{cn_suffix}"

    body = [
        "📉 A股洗盘低吸预警",
        f"时间: {now_text}",
        stock_line,
        f"首次建仓信号日: {first_d}",
        f"建仓强度(首次): {pbs:.1f}",
        f"当前价格: {float(scan_price):.2f}",
        "",
        f"触发: {html.escape(ma_line)}（洗盘接近尾声）",
        "建议: 当日收盘买入 或 次日开盘买入",
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
    on_signal: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> int:
    """
    遍历高建仓队列，按「主力建仓后洗盘低吸」策略扫描：
    - 信号后 3-14 日窗口；
    - 现价处于 [(3L-H)/2, (H+L)/2) 阶段回落区间；
    - 量能 5/10 死叉或即将死叉。

    满足条件时推送预警；同一标的每个交易日最多推送一次（按日去重）。
    若提供 on_signal 回调，则在推送成功后以 payload 形式触达下游（如下单接口）。
    akshare 跌幅仅写入预警正文展示，不参与过滤。
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
    today_iso = today.isoformat()
    updated = False

    for entry in queue:
        if entry.get("last_rebound_notified_date") == today_iso:
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
            print(f"⚠️  洗盘低吸扫描 {symbol} 取数失败: {e}")
            continue
        if not stock_data:
            continue

        hist = stock_data.get("hist")
        scan_price = float(stock_data.get("close") or 0)
        if hist is None or scan_price <= 0:
            continue

        ok, ma_trigger, peak_high, peak_low = check_rebound_conditions(
            entry, hist, scan_price, today=today
        )
        if not ok:
            continue

        muted, reason = carmen_alerts_muted()
        if muted:
            print(f"🔕 Carmen 洗盘低吸预警已静音，跳过 {symbol}: {reason or 'no reason'}")
            append_signal_audit(
                {
                    "event": "muted_rebound_skipped",
                    "symbol": symbol,
                    "first_alert_date": entry.get("first_alert_date"),
                    "ma_trigger": ma_trigger,
                    "reason": reason,
                }
            )
            continue

        ak_quote = fetch_rebound_quote(symbol, first_d)
        if not ak_quote:
            print(f"⚠️  {symbol} akshare 跌幅展示不可用，仍按策略条件推送")
        msg = _format_rebound_message(
            entry,
            ma_trigger,
            peak_high=peak_high,
            peak_low=peak_low,
            scan_price=scan_price,
            ak_quote=ak_quote,
        )
        signal_id = f"rebound:{symbol}:{entry.get('first_alert_date')}:{today_iso}"
        sent = notifier.send_message(msg, reply_markup=None, parse_mode="HTML")
        if sent:
            entry["last_rebound_notified_date"] = today_iso
            entry["rebound_notified_at"] = datetime.now(BEIJING_TZ).isoformat()
            triggered += 1
            updated = True

            payload: Dict[str, Any] = {
                "signal_id": signal_id,
                "symbol": symbol,
                "stock_cn_name": entry.get("stock_cn_name"),
                "first_alert_date": entry.get("first_alert_date"),
                "position_build_score": float(entry.get("position_build_score") or 0),
                "current_price": scan_price,
                "peak_high": peak_high,
                "peak_low": peak_low,
                "ma_trigger": ma_trigger,
                "action_hint": "当日收盘买入 或 次日开盘买入",
                "notified_at": entry["rebound_notified_at"],
            }
            if on_signal is not None:
                try:
                    on_signal(payload)
                except Exception as e:
                    print(f"⚠️  {symbol} on_signal 回调异常: {e}")

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
            print(f"📉 {symbol} 洗盘低吸预警已推送 ({ma_trigger})")
        else:
            print(f"⚠️  {symbol} 洗盘低吸预警推送失败")

    if updated:
        _save_queue(queue)
    if triggered:
        print(f"📉 本轮洗盘低吸预警: {triggered} 条")
    return triggered
