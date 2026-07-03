"""
多市场每日板块轮动分析：累积 fast scan pre_candidate 信号，收盘后 OpenClaw 汇总分析。
支持 A股 / 港股 / 美股。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytz
import requests

from scan_signal_eval import ScanSignalState
from serenity_analysis import _extract_openclaw_reply, _extract_telegram_message
from telegram_notifier import (
    append_signal_audit,
    build_telegram_request_kwargs,
    load_telegram_token,
    parse_telegram_chat_ids,
)

BEIJING_TZ = pytz.timezone("Asia/Shanghai")
RUNTIME_DIR = Path(__file__).resolve().parent / "runtime"
REPORT_SIGNAL_TYPES = frozenset({"carmen_buy", "rsi_rebound"})

_SIGNALS_LOCKS: Dict[str, threading.RLock] = {m: threading.RLock() for m in ("A", "HK", "US")}
_STATE_LOCKS: Dict[str, threading.RLock] = {m: threading.RLock() for m in ("A", "HK", "US")}
_REPORT_LOCKS: Dict[str, threading.RLock] = {m: threading.RLock() for m in ("A", "HK", "US")}
_REPORT_THREADS: Dict[str, Optional[threading.Thread]] = {m: None for m in ("A", "HK", "US")}


def _normalize_a_code(symbol: str) -> str:
    upper = (symbol or "").upper()
    if upper.endswith(".SS") or upper.endswith(".SZ"):
        return upper.split(".", 1)[0]
    return symbol or ""


def _normalize_hk_code(symbol: str) -> str:
    upper = (symbol or "").upper()
    if upper.endswith(".HK"):
        return upper.split(".", 1)[0]
    return symbol or ""


def _normalize_us_code(symbol: str) -> str:
    return (symbol or "").strip().upper()


def _match_a(symbol: str) -> bool:
    upper = (symbol or "").upper()
    return upper.endswith(".SS") or upper.endswith(".SZ")


def _match_hk(symbol: str) -> bool:
    return (symbol or "").upper().endswith(".HK")


def _match_us(symbol: str) -> bool:
    upper = (symbol or "").upper().strip()
    if not upper:
        return False
    if upper.endswith((".SS", ".SZ", ".HK")):
        return False
    return True


MARKET_CONFIGS: Dict[str, Dict[str, Any]] = {
    "A": {
        "label": "A股",
        "emoji": "🇨🇳",
        "signals_file": RUNTIME_DIR / "a_share_daily_pre_candidates.json",
        "state_file": RUNTIME_DIR / "a_share_sector_rotation_state.json",
        "report_hour_beijing": 16,
        "match_symbol": _match_a,
        "normalize_code": _normalize_a_code,
        "code_hint": "A股代码显示纯6位数字，用 Telegram HTML <code> 包裹",
        "session_prefix": "tmp-carmen-sector-rotation-a",
    },
    "HK": {
        "label": "港股",
        "emoji": "🇭🇰",
        "signals_file": RUNTIME_DIR / "hk_daily_pre_candidates.json",
        "state_file": RUNTIME_DIR / "hk_sector_rotation_state.json",
        "report_hour_beijing": 17,
        "match_symbol": _match_hk,
        "normalize_code": _normalize_hk_code,
        "code_hint": "港股代码显示纯数字（去掉 .HK 后缀），用 Telegram HTML <code> 包裹",
        "session_prefix": "tmp-carmen-sector-rotation-hk",
    },
    "US": {
        "label": "美股",
        "emoji": "🇺🇸",
        "signals_file": RUNTIME_DIR / "us_daily_pre_candidates.json",
        "state_file": RUNTIME_DIR / "us_sector_rotation_state.json",
        "report_hour_beijing": 10,
        "match_symbol": _match_us,
        "normalize_code": _normalize_us_code,
        "code_hint": "美股 ticker 用 Telegram HTML <code> 包裹",
        "session_prefix": "tmp-carmen-sector-rotation-us",
    },
}


def sector_rotation_enabled(market: str = "A") -> bool:
    market = _normalize_market(market)
    global_key = os.environ.get("CARMEN_SECTOR_ROTATION_ENABLED", "1").strip().lower()
    if global_key in {"0", "false", "no", "off"}:
        return False
    market_key = os.environ.get(f"CARMEN_{market}_SECTOR_ROTATION_ENABLED", "1").strip().lower()
    return market_key not in {"0", "false", "no", "off"}


def _normalize_market(market: str) -> str:
    m = (market or "A").strip().upper()
    if m not in MARKET_CONFIGS:
        raise ValueError(f"unsupported market: {market}")
    return m


def _openclaw_timeout() -> int:
    try:
        return max(60, int(os.environ.get("CARMEN_SECTOR_ROTATION_OPENCLAW_TIMEOUT", "420") or 420))
    except Exception:
        return 420


def _beijing_now(when: Optional[datetime] = None) -> datetime:
    if when is None:
        return datetime.now(BEIJING_TZ)
    if when.tzinfo is None:
        return BEIJING_TZ.localize(when)
    return when.astimezone(BEIJING_TZ)


def _today_beijing(when: Optional[datetime] = None) -> date:
    return _beijing_now(when).date()


def _now_beijing_iso() -> str:
    return _beijing_now().replace(microsecond=0).isoformat()


def session_date_for_market(market: str, when: Optional[datetime] = None) -> date:
    """各市场信号桶 / 报告日统一用北京时间日历日。"""
    _normalize_market(market)
    return _today_beijing(when)


def _load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if data is not None else default
    except Exception as e:
        print(f"⚠️  读取 {path.name} 失败: {e}")
        return default


def _save_json_file(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _build_signal_types(scan_state: ScanSignalState) -> List[str]:
    types: List[str] = []
    score = scan_state.score or [0.0, 0.0]
    if float(score[0] or 0) >= 2.0:
        types.append("carmen_buy")
    if float(score[1] or 0) >= 2.0:
        types.append("carmen_sell")
    if scan_state.rsi_oversold_today:
        types.append("rsi_oversold")
    if scan_state.rsi_rebound_setup:
        types.append("rsi_rebound")
    return types


def record_pre_candidate(
    market: str,
    symbol: str,
    stock_data: Dict[str, Any],
    scan_state: ScanSignalState,
    names_map: Optional[Dict[str, str]] = None,
) -> None:
    """记录 fast scan 阶段 pre_candidate 信号（按北京时间日历日去重）。"""
    del stock_data
    market = _normalize_market(market)
    cfg = MARKET_CONFIGS[market]
    if not cfg["match_symbol"](symbol):
        return
    if not scan_state.pre_candidate:
        return

    now = _beijing_now()
    day_key = now.date().isoformat()
    now_iso = now.replace(microsecond=0).isoformat()
    names_map = names_map or {}
    display_name = (
        names_map.get(symbol)
        or names_map.get((symbol or "").strip())
        or names_map.get((symbol or "").upper())
        or ""
    )
    entry = {
        "symbol": symbol,
        "name": display_name,
        "signal_types": _build_signal_types(scan_state),
        "first_seen": now_iso,
        "last_seen": now_iso,
        "scan_count": 1,
    }

    with _SIGNALS_LOCKS[market]:
        store = _load_json_file(cfg["signals_file"], {})
        if not isinstance(store, dict):
            store = {}
        day_items = list(store.get(day_key) or [])
        for idx, item in enumerate(day_items):
            if item.get("symbol") == symbol:
                merged = dict(item)
                merged.update(
                    {
                        "name": display_name or item.get("name"),
                        "signal_types": sorted(set((item.get("signal_types") or []) + entry["signal_types"])),
                        "last_seen": now_iso,
                        "scan_count": int(item.get("scan_count") or 0) + 1,
                    }
                )
                day_items[idx] = merged
                store[day_key] = day_items
                _save_json_file(cfg["signals_file"], store)
                return
        day_items.append(entry)
        store[day_key] = day_items
        _save_json_file(cfg["signals_file"], store)


def load_daily_signals(market: str, day: Optional[date] = None) -> List[Dict[str, Any]]:
    market = _normalize_market(market)
    day_key = (day or session_date_for_market(market)).isoformat()
    store = _load_json_file(MARKET_CONFIGS[market]["signals_file"], {})
    items = store.get(day_key) if isinstance(store, dict) else None
    return list(items) if isinstance(items, list) else []


def filter_signals_for_report(
    market: str,
    signals: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """仅保留 carmen_buy / rsi_rebound，输出 OpenClaw 用的精简字段。"""
    market = _normalize_market(market)
    normalize_code: Callable[[str], str] = MARKET_CONFIGS[market]["normalize_code"]
    out: List[Dict[str, Any]] = []
    for item in signals:
        types = sorted({t for t in (item.get("signal_types") or []) if t in REPORT_SIGNAL_TYPES})
        if not types:
            continue
        out.append(
            {
                "code": normalize_code(str(item.get("symbol") or "")),
                "name": str(item.get("name") or "").strip(),
                "signal_types": types,
            }
        )
    out.sort(key=lambda x: (x["code"], x["name"]))
    return out


def build_sector_rotation_title(market: str, report_date: str) -> str:
    market = _normalize_market(market)
    cfg = MARKET_CONFIGS[market]
    return f"📊 板块轮动分析 · {cfg['emoji']} {cfg['label']} · {report_date}"


def build_sector_rotation_body_template(market: str, report_date: str) -> str:
    title = build_sector_rotation_title(market, report_date)
    return (
        f"{title}\n"
        "结论：\n"
        "\n"
        "Cluster 1：<板块主题>，优先级 S\n"
        "判断：\n"
        "\n"
        "Cluster 2：<板块主题>，优先级 A\n"
        "判断：\n"
        "\n"
        "边缘信号：\n"
        "重点观察方向："
    )


def build_sector_rotation_prompt(
    market: str,
    report_date: str,
    signals: List[Dict[str, Any]],
    bot_token: str,
    chat_id: str,
) -> str:
    market = _normalize_market(market)
    cfg = MARKET_CONFIGS[market]
    label = cfg["label"]
    body_template = build_sector_rotation_body_template(market, report_date)
    request = {
        "market": market,
        "task": f"{label}即将启动的行业板块聚类分析",
        "report_date": report_date,
        "background": (
            "Carmen 用 RSI/MACD/量能捕捉个股启动信号。"
            "若同一行业或近似板块多只股票同日出现 carmen_buy 或 rsi_rebound，通常意味着共识资金流入、板块即将轮动。"
        ),
        "signal_total": len(signals),
        "startup_signals": signals,
        "analysis_requirements": {
            "language": "zh-CN",
            "must_use_live_search": True,
            "must_infer_industry_from_web": True,
            "focus": [
                "根据 code/name 联网检索所属行业或主题",
                "识别当日是否存在板块/主题 cluster 异动",
                "输出 1-3 个 Cluster，按优先级 S / A / B / C / D / E 排序",
                "边缘信号列未形成 cluster 的零散标的",
            ],
            "constraints": [
                "不给确定性买卖指令",
                "Cluster 行格式：Cluster N：<板块主题>，优先级 <等级>",
                "判断行需写清依据，可引用代表 <code>",
                cfg["code_hint"],
            ],
        },
        "telegram_output": {
            "parse_mode": "HTML",
            "body_template": body_template,
            "return_blocks": True,
            "block_start": "BEGIN_TELEGRAM_MESSAGE",
            "block_end": "END_TELEGRAM_MESSAGE",
            "also_send_via_bot_api": False,
            "bot_token": bot_token,
            "chat_id": chat_id,
        },
    }
    return (
        f"你在为 Carmen Telegram bot 执行 {label} 每日板块轮动一次性分析任务。\n"
        "下方 startup_signals 仅含 code、name、signal_types（carmen_buy / rsi_rebound）。"
        "请自行联网检索每只股票所属行业/概念/板块，再做 cluster 与轮动判断。\n"
        "Telegram 正文必须严格按 telegram_output.body_template 输出。\n"
        "不要自行调用 Telegram Bot API；只返回 BEGIN_TELEGRAM_MESSAGE 与 END_TELEGRAM_MESSAGE 包裹的正文，"
        "由 Carmen 统一发送。\n"
        "不要写入长期记忆；不要输出调试日志。\n\n"
        + json.dumps(request, ensure_ascii=False, indent=2)
    )


def _call_openclaw_sector_rotation(market: str, prompt: str, timeout_seconds: int) -> str:
    market = _normalize_market(market)
    cfg = MARKET_CONFIGS[market]
    openclaw_bin = os.environ.get(
        "CARMEN_OPENCLAW_BIN",
        "/home/serv/.nvm/versions/node/v22.22.0/bin/openclaw",
    )
    agent_id = os.environ.get("CARMEN_SECTOR_ROTATION_OPENCLAW_AGENT", "main")
    model = os.environ.get("CARMEN_SECTOR_ROTATION_OPENCLAW_MODEL", "").strip()
    session_prefix = (
        os.environ.get("CARMEN_SECTOR_ROTATION_OPENCLAW_SESSION_PREFIX", cfg["session_prefix"]).strip()
        or cfg["session_prefix"]
    )
    prompt_hash = hashlib.sha1(prompt.encode("utf-8", errors="ignore")).hexdigest()[:10]
    session_id = f"{session_prefix}-{int(time.time())}-{prompt_hash}"
    cmd = [
        openclaw_bin,
        "agent",
        "--agent",
        agent_id,
        "--session-id",
        session_id,
        "--message",
        prompt,
        "--json",
        "--timeout",
        str(timeout_seconds),
    ]
    if model:
        cmd.extend(["--model", model])
    cp = subprocess.run(
        cmd,
        cwd="/home/serv/.openclaw/workspace",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds + 15,
        check=False,
    )
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or "").strip().splitlines()[-1:]
        raise RuntimeError(detail[0] if detail else f"openclaw agent exited {cp.returncode}")
    reply = _extract_openclaw_reply(cp.stdout)
    if not reply:
        raise RuntimeError("openclaw agent returned empty reply")
    return reply


def send_telegram_html(message: str) -> None:
    bot_token, chat_id_text = load_telegram_token()
    chat_ids = parse_telegram_chat_ids(chat_id_text)
    if not chat_ids:
        raise RuntimeError("no Telegram chat ids configured")
    request_kwargs = build_telegram_request_kwargs(timeout=15)
    for idx, chat_id in enumerate(chat_ids):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                **request_kwargs,
            )
            resp.raise_for_status()
        except Exception:
            if idx == 0:
                raise
            print(f"⚠️  板块轮动报告转发失败 chat_id={chat_id}")


def _load_state(market: str) -> Dict[str, Any]:
    market = _normalize_market(market)
    data = _load_json_file(MARKET_CONFIGS[market]["state_file"], {})
    return data if isinstance(data, dict) else {}


def _save_state(market: str, state: Dict[str, Any]) -> None:
    market = _normalize_market(market)
    _save_json_file(MARKET_CONFIGS[market]["state_file"], state)


def should_run_sector_rotation_report(
    market: str,
    day: Optional[date] = None,
    *,
    force: bool = False,
) -> bool:
    market = _normalize_market(market)
    if not sector_rotation_enabled(market):
        return False
    day = day or session_date_for_market(market)
    if day.weekday() >= 5:
        return False
    if force:
        return True
    state = _load_state(market)
    if state.get("last_report_date") == day.isoformat() and state.get("status") == "sent":
        return False
    return len(filter_signals_for_report(market, load_daily_signals(market, day))) >= 1


def mark_report_success(market: str, day: date, signal_count: int, status: str = "sent") -> None:
    market = _normalize_market(market)
    with _STATE_LOCKS[market]:
        state = _load_state(market)
        state.update(
            {
                "last_report_date": day.isoformat(),
                "last_signal_count": signal_count,
                "status": status,
                "last_sent_at": _now_beijing_iso(),
            }
        )
        _save_state(market, state)


def is_post_close_scan(market: str) -> bool:
    """是否处于该市场配置的北京时间发送窗口（整点后 30 分钟内）。"""
    market = _normalize_market(market)
    hour = MARKET_CONFIGS[market]["report_hour_beijing"]
    now = _beijing_now()
    return now.hour == hour and now.minute < 30


def run_daily_sector_rotation_report(
    market: str = "A",
    *,
    force: bool = False,
    dry_run: bool = False,
) -> bool:
    market = _normalize_market(market)
    label = MARKET_CONFIGS[market]["label"]
    day = session_date_for_market(market)
    if not should_run_sector_rotation_report(market, day, force=force):
        print(f"ℹ️  跳过 {label} 板块轮动报告 ({day.isoformat()})")
        return False

    report_signals = filter_signals_for_report(market, load_daily_signals(market, day))
    if not report_signals:
        print(f"ℹ️  当日无 carmen_buy/rsi_rebound 信号，跳过 {label} 板块轮动报告 ({day.isoformat()})")
        return False

    bot_token, chat_id = load_telegram_token()
    prompt = build_sector_rotation_prompt(
        market,
        day.isoformat(),
        report_signals,
        bot_token,
        chat_id,
    )

    if dry_run:
        print(prompt)
        return True

    append_signal_audit(
        {
            "event": "sector_rotation_started",
            "market": market,
            "report_date": day.isoformat(),
            "signal_count": len(report_signals),
        }
    )

    try:
        reply = _call_openclaw_sector_rotation(market, prompt, _openclaw_timeout())
        body = _extract_telegram_message(reply).strip()
        if not body:
            raise RuntimeError("OpenClaw 返回空 Telegram 正文")
        send_telegram_html(body)
        mark_report_success(market, day, len(report_signals), status="sent")
        append_signal_audit(
            {
                "event": "sector_rotation_sent",
                "market": market,
                "report_date": day.isoformat(),
                "signal_count": len(report_signals),
            }
        )
        print(f"✅ {label}板块轮动报告已发送 ({day.isoformat()}) signals={len(report_signals)}")
        return True
    except Exception as e:
        append_signal_audit(
            {
                "event": "sector_rotation_failed",
                "market": market,
                "report_date": day.isoformat(),
                "signal_count": len(report_signals),
                "error": str(e),
            }
        )
        print(f"⚠️  {label}板块轮动报告失败: {e}")
        return False


def maybe_run_daily_sector_rotation_report(market: str, bot_notifier: Any = None) -> None:
    """到达发送窗口后异步触发（不阻塞扫描主流程）。"""
    del bot_notifier
    market = _normalize_market(market)
    if not is_post_close_scan(market):
        return
    if not should_run_sector_rotation_report(market):
        return

    def _worker() -> None:
        run_daily_sector_rotation_report(market)

    with _REPORT_LOCKS[market]:
        thread = _REPORT_THREADS.get(market)
        if thread is not None and thread.is_alive():
            return
        thread = threading.Thread(
            target=_worker,
            name=f"sector-rotation-{market.lower()}-{uuid.uuid4().hex[:8]}",
            daemon=True,
        )
        _REPORT_THREADS[market] = thread
        thread.start()
