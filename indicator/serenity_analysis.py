"""
OpenClaw/Wyrd Serenity-skill post-alert analysis for Carmen Telegram buy signals.

Carmen only builds a structured request and invokes OpenClaw agent runtime.
The Serenity perspective itself is supplied by the OpenClaw AgentSkill layer.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional


HK_TZ = timezone(timedelta(hours=8))
STATE_FILE = Path(__file__).resolve().parent / "runtime" / "serenity_daily_state.json"
CACHE_FILE = Path(__file__).resolve().parent / "runtime" / "serenity_analysis_cache.json"
DEFAULT_CACHE_TTL_DAYS = 3
_STATE_LOCK = threading.Lock()
_CACHE_LOCK = threading.Lock()


def serenity_analysis_enabled() -> bool:
    return os.environ.get("CARMEN_SERENITY_ANALYSIS_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _compact_text(text: Optional[str], limit: int = 2600) -> str:
    s = str(text or "").strip()
    if len(s) <= limit:
        return s
    return s[:limit].rstrip() + "\n...[truncated]"


def _today_hk() -> str:
    return datetime.now(HK_TZ).strftime("%Y-%m-%d")


def _load_state() -> Dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠️ 读取 Serenity 每日状态失败: {e}")
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(STATE_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        print(f"⚠️ 保存 Serenity 每日状态失败: {e}")



def _cache_ttl_days() -> int:
    try:
        ttl = int(os.environ.get("CARMEN_SERENITY_CACHE_TTL_DAYS", str(DEFAULT_CACHE_TTL_DAYS)))
    except Exception:
        ttl = DEFAULT_CACHE_TTL_DAYS
    return max(1, ttl)


def _parse_hk_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=HK_TZ)
    return dt.astimezone(HK_TZ)


def _load_cache_pool() -> Dict[str, Any]:
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠️ 读取 Serenity 缓存池失败: {e}")
        return {}


def _save_cache_pool(pool: Dict[str, Any]) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(CACHE_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(pool, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, CACHE_FILE)
    except Exception as e:
        print(f"⚠️ 保存 Serenity 缓存池失败: {e}")


def _prune_cache_pool(pool: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(HK_TZ)
    max_age = timedelta(days=max(_cache_ttl_days(), 7))
    entries = pool.get("entries") if isinstance(pool.get("entries"), dict) else {}
    kept = {}
    for sym, entry in entries.items():
        if not isinstance(sym, str) or not isinstance(entry, dict):
            continue
        created_at = _parse_hk_datetime(entry.get("created_at"))
        msg = entry.get("message")
        if created_at and isinstance(msg, str) and msg.strip() and now - created_at <= max_age:
            kept[sym] = entry
    pool["entries"] = kept
    pool["updated_at"] = now.isoformat(timespec="seconds")
    pool["ttl_days"] = _cache_ttl_days()
    return pool


def read_serenity_cache_entry(symbol: str, max_age_days: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Return a recent Serenity analysis for the same symbol.

    Fundamentals and chokepoint positioning are intentionally reused for a few
    days to avoid repeated simulated-persona analysis on the same stock.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    ttl_days = max_age_days or _cache_ttl_days()
    now = datetime.now(HK_TZ)
    with _CACHE_LOCK:
        pool = _prune_cache_pool(_load_cache_pool(), now=now)
        _save_cache_pool(pool)
        entry = (pool.get("entries") or {}).get(sym)
        if not isinstance(entry, dict):
            return None
        created_at = _parse_hk_datetime(entry.get("created_at"))
        msg = entry.get("message")
        if not created_at or not isinstance(msg, str) or not msg.strip():
            return None
        if now - created_at > timedelta(days=ttl_days):
            return None
        out = dict(entry)
        out["symbol"] = sym
        out["age_seconds"] = int((now - created_at).total_seconds())
        return out


def save_serenity_cache_entry(
    symbol: str,
    message: str,
    *,
    model: Optional[str] = None,
    market: Optional[str] = None,
    stock_cn_name: Optional[str] = None,
) -> None:
    sym = (symbol or "").strip().upper()
    msg = (message or "").strip()
    if not sym or not msg:
        return
    now = datetime.now(HK_TZ)
    with _CACHE_LOCK:
        pool = _prune_cache_pool(_load_cache_pool(), now=now)
        entries = pool.setdefault("entries", {})
        entries[sym] = {
            "symbol": sym,
            "message": msg,
            "created_at": now.isoformat(timespec="seconds"),
            "model": model or os.environ.get("CARMEN_SERENITY_OPENCLAW_MODEL", "").strip() or "agent-default",
            "market": market or "",
            "stock_cn_name": stock_cn_name or "",
        }
        _save_cache_pool(pool)


def claim_serenity_daily_slot(symbol: str, day: Optional[str] = None) -> bool:
    """
    Return True only once per symbol per HK day.

    The slot is claimed before LLM generation so repeated alerts do not trigger
    repeated simulated-persona analysis or API spend. Keeps only recent days.
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return False
    day = day or _today_hk()
    with _STATE_LOCK:
        state = _load_state()
        days = state.get("days") if isinstance(state.get("days"), dict) else {}
        # Keep today + recent history for simple audit, drop stale entries.
        keep = {day}
        try:
            today_dt = datetime.strptime(day, "%Y-%m-%d")
            keep.update((today_dt - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 8))
        except Exception:
            pass
        days = {d: v for d, v in days.items() if d in keep and isinstance(v, dict)}
        today_symbols = days.setdefault(day, {})
        if sym in today_symbols:
            state["days"] = days
            _save_state(state)
            return False
        today_symbols[sym] = {
            "claimed_at": datetime.now(HK_TZ).isoformat(timespec="seconds"),
        }
        state["days"] = days
        _save_state(state)
        return True


def build_serenity_title_line(symbol: str, stock_cn_name: Optional[str] = None) -> str:
    split_symbol = symbol.split(".")
    split_symbol_0 = split_symbol[0]
    split_symbol_1 = f"[{split_symbol[1]}]" if len(split_symbol) == 2 else ""
    extras_suffix = ""
    upper_sym = symbol.upper()
    cn = (stock_cn_name or "").strip()
    if cn and (upper_sym.endswith(".SS") or upper_sym.endswith(".SZ")):
        extras_suffix = f" {html.escape(cn)}"
    stock_line = f"<code>{html.escape(split_symbol_0)}</code>{split_symbol_1}{extras_suffix}"
    return f"🧠 Serenity 模拟分析｜{stock_line}"


def build_serenity_prompt(
    *,
    symbol: str,
    market: str,
    stock_cn_name: Optional[str],
) -> str:
    target_context = [
        f"标的: {symbol}" + (f" / {stock_cn_name}" if stock_cn_name else ""),
        f"市场: {market}",
    ]
    request = {
        "task": "调用 serenity-skill。仅对标的做基本面联网搜索验证，生成长版 Serenity 深度分析，再压缩成紧跟 Carmen 买入预警发送的 Telegram 短消息。",
        "workflow_requirements": {
            "step_1": "先生成长版深度分析，必须按 Serenity workflow 走：产业链层级、稀缺层/行业chokepoint、公司所在位置、联网证据、证据强弱、反方/失效条件、下一步验证。",
            "step_2": "再只基于长版分析，整理成 Telegram 短消息。",
            "must_use_live_search": True,
            "must_state_if_industry_chokepoint": True,
            "do_not_fabricate_unprovided_fundamentals": True,
            "fundamentals_only": True,
            "do_not_use_technical_analysis": True,
            "do_not_reference_kline_or_price_action": True,
        },
        "long_analysis_requirements": {
            "language": "zh-CN",
            "format": "plain_text",
            "include_sections": [
                "一句话介绍公司业务",
                "结论",
                "产业链位置",
                "是否行业chokepoint",
                "联网证据",
                "证据强弱",
                "反方/失效条件",
                "下一步验证",
            ],
            "exclude": [
                "目标价",
                "止损",
                "RSI",
                "MACD",
            ],
        },
        "telegram_message_requirements": {
            "language": "zh-CN",
            "min_chars": 240,
            "max_chars": 360,
            "do_not_include_title": True,
            "disclaimer": "",
            "no_markdown_table": True,
            "style": "结论优先，保留产业链/chokepoint判断、1-2条关键联网证据；只做基本面分析，不要做任何技术面分析。",
        },
        "output_contract": {
            "return_both_blocks": True,
            "long_block_start": "BEGIN_SERENITY_LONG_ANALYSIS",
            "long_block_end": "END_SERENITY_LONG_ANALYSIS",
            "telegram_block_start": "BEGIN_TELEGRAM_MESSAGE",
            "telegram_block_end": "END_TELEGRAM_MESSAGE",
            "telegram_bot_will_send_only": "BEGIN_TELEGRAM_MESSAGE 和 END_TELEGRAM_MESSAGE 中间的内容",
        },
        "target_context": target_context,
    }
    return "请调用 serenity-skill 处理以下结构化请求；Carmen 只提供标的识别信息，不提供技术面数据或人格提示词：\n" + json.dumps(
        request,
        ensure_ascii=False,
        indent=2,
    )


def _extract_openclaw_reply(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""

    def pick(obj: Dict[str, Any]) -> str:
        for key in (
            "finalAssistantVisibleText",
            "finalAssistantRawText",
            "reply",
            "message",
            "text",
            "output",
            "content",
            "assistantReply",
        ):
            v = obj.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
        payloads = obj.get("payloads")
        if isinstance(payloads, list):
            for item in payloads:
                if isinstance(item, dict):
                    v = item.get("text")
                    if isinstance(v, str) and v.strip():
                        return v.strip()
        for key in ("result", "data"):
            v = obj.get(key)
            if isinstance(v, dict):
                picked = pick(v)
                if picked:
                    return picked
        return ""

    # `openclaw agent --json` usually emits pretty-printed JSON.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            picked = pick(obj)
            if picked:
                return picked
    except Exception:
        pass

    # Be tolerant of diagnostic prefixes by parsing the last JSON-looking line.
    for line in reversed(text.splitlines()):
        s = line.strip()
        if not (s.startswith("{") and s.endswith("}")):
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if isinstance(obj, dict):
            picked = pick(obj)
            if picked:
                return picked

    # Fallback: if a non-JSON success ever prints plain text, use it.
    if not text.startswith("{"):
        return text
    return ""


def _extract_telegram_message(reply: str) -> str:
    text = (reply or "").strip()
    if not text:
        return ""

    start = "BEGIN_TELEGRAM_MESSAGE"
    end = "END_TELEGRAM_MESSAGE"
    if start in text and end in text:
        chunk = text.split(start, 1)[1].split(end, 1)[0].strip()
        if chunk:
            return chunk

    if start in text:
        chunk = text.split(start, 1)[1].strip()
        if chunk:
            return chunk

    # Backward-compatible fallback for older or malformed agent replies.
    return text


def _call_openclaw_serenity_skill(prompt: str, timeout_seconds: int) -> str:
    openclaw_bin = os.environ.get(
        "CARMEN_OPENCLAW_BIN",
        "/home/serv/.nvm/versions/node/v22.22.0/bin/openclaw",
    )
    agent_id = os.environ.get("CARMEN_SERENITY_OPENCLAW_AGENT", "main")
    model = os.environ.get("CARMEN_SERENITY_OPENCLAW_MODEL", "").strip()
    session_prefix = os.environ.get("CARMEN_SERENITY_OPENCLAW_SESSION_PREFIX", "tmp-carmen-serenity").strip() or "tmp-carmen-serenity"
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


def generate_serenity_analysis(
    *,
    symbol: str,
    market: str,
    stock_cn_name: Optional[str] = None,
) -> str:
    if not serenity_analysis_enabled():
        return ""
    prompt = build_serenity_prompt(
        symbol=symbol,
        market=market,
        stock_cn_name=stock_cn_name,
    )
    try:
        body = _call_openclaw_serenity_skill(
            prompt,
            timeout_seconds=int(os.environ.get("CARMEN_SERENITY_OPENCLAW_TIMEOUT", "300")),
        ).strip()
        body = _extract_telegram_message(body).strip()
        if not body:
            return ""
        title_line = build_serenity_title_line(symbol, stock_cn_name)
        message = f"{title_line}\n{html.escape(body)}"
        save_serenity_cache_entry(
            symbol,
            message,
            model=os.environ.get("CARMEN_SERENITY_OPENCLAW_MODEL", "").strip() or "agent-default",
            market=market,
            stock_cn_name=stock_cn_name,
        )
        return message
    except Exception as e:
        print(f"⚠️ {symbol} OpenClaw Serenity skill 调用失败: {e}")
        return ""
