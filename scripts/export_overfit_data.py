#!/usr/bin/env python3
"""Export A-share signal records into ML-friendly overfit_data files.

The exporter intentionally uses only local runtime artifacts. It does not fetch
market data, so every generated row reflects information already captured by the
monitoring system.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "indicator" / "runtime"
OUT_DIR = ROOT / "overfit_data"
QUEUE_FILE = RUNTIME_DIR / "a_share_high_build_alerts.json"
AUDIT_FILE = RUNTIME_DIR / "telegram_signal_audit.jsonl"

A_SHARE_RE = re.compile(r"^\d{6}\.(SS|SZ)$")
AI_SIGNAL_RE = re.compile(
    r"^(?P<symbol>\d{6}\.(?:SS|SZ))\|(?P<date>\d{4}-\d{2}-\d{2})\|(?P<side>[^|]+)\|(?P<hash>[^|:]+)"
)
REBOUND_SIGNAL_RE = re.compile(
    r"^rebound:(?P<symbol>\d{6}\.(?:SS|SZ)):(?P<first_date>\d{4}-\d{2}-\d{2}):(?P<rebound_date>\d{4}-\d{2}-\d{2})$"
)


def is_a_share(symbol: Any) -> bool:
    return bool(A_SHARE_RE.match(str(symbol or "").upper()))


def parse_ts(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text


def date_part(value: Any) -> str:
    if not value:
        return ""
    return str(value)[:10]


def load_queue() -> List[Dict[str, Any]]:
    if not QUEUE_FILE.exists():
        return []
    data = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def iter_audit() -> Iterable[Dict[str, Any]]:
    if not AUDIT_FILE.exists():
        return []
    with AUDIT_FILE.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                yield {"event": "json_decode_error", "line_no": line_no, "raw": line}
                continue
            item["_line_no"] = line_no
            yield item


def write_csv(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_queue_rows(queue: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in queue:
        symbol = str(item.get("symbol") or "").upper()
        if not is_a_share(symbol):
            continue
        first_date = date_part(item.get("first_alert_date"))
        rows.append(
            {
                "sample_id": f"high_build:{symbol}:{first_date}",
                "symbol": symbol,
                "stock_cn_name": item.get("stock_cn_name") or "",
                "first_alert_date": first_date,
                "position_build_score": item.get("position_build_score", ""),
                "last_rebound_notified_date": date_part(item.get("last_rebound_notified_date")),
                "rebound_notified_at": parse_ts(item.get("rebound_notified_at")),
                "has_rebound_notification": int(bool(item.get("last_rebound_notified_date"))),
                "source_file": str(QUEUE_FILE.relative_to(ROOT)),
            }
        )
    return sorted(rows, key=lambda r: (r["first_alert_date"], r["symbol"]))


def build_audit_rows(audit_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in audit_items:
        symbol = str(item.get("symbol") or "").upper()
        signal_id = str(item.get("signal_id") or "")
        if not is_a_share(symbol):
            continue
        ai_match = AI_SIGNAL_RE.match(signal_id)
        rebound_match = REBOUND_SIGNAL_RE.match(signal_id)
        signal_family = ""
        signal_date = ""
        side = ""
        first_alert_date = date_part(item.get("first_alert_date"))
        rebound_date = ""
        if ai_match:
            signal_family = "ai_buy"
            signal_date = ai_match.group("date")
            side = ai_match.group("side")
        elif rebound_match:
            signal_family = "rebound"
            signal_date = rebound_match.group("rebound_date")
            first_alert_date = rebound_match.group("first_date")
            rebound_date = rebound_match.group("rebound_date")
        else:
            signal_family = "a_share_misc"
            signal_date = date_part(item.get("ts"))

        rows.append(
            {
                "line_no": item.get("_line_no", ""),
                "event": item.get("event", ""),
                "signal_family": signal_family,
                "symbol": symbol,
                "signal_id": signal_id,
                "signal_date": signal_date,
                "side": side,
                "first_alert_date": first_alert_date,
                "rebound_date": rebound_date,
                "ma_trigger": item.get("ma_trigger", ""),
                "price": item.get("price", ""),
                "score": item.get("score", ""),
                "position_build_score": item.get("position_build_score", ""),
                "market": item.get("market", ""),
                "status": item.get("status", ""),
                "hours_passed": item.get("hours_passed", ""),
                "ts": parse_ts(item.get("ts")),
            }
        )
    return rows


def build_event_samples(
    queue_rows: List[Dict[str, Any]], audit_rows: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    name_by_symbol = {r["symbol"]: r.get("stock_cn_name", "") for r in queue_rows}
    pbs_by_key = {
        (r["symbol"], r["first_alert_date"]): r.get("position_build_score", "")
        for r in queue_rows
    }
    rebound_counts = Counter(
        (r["symbol"], r["first_alert_date"])
        for r in audit_rows
        if r["event"] == "rebound_alert_sent"
    )

    samples: Dict[str, Dict[str, Any]] = {}
    for row in queue_rows:
        sample_id = row["sample_id"]
        samples[sample_id] = {
            "sample_id": sample_id,
            "sample_type": "high_build_queue",
            "symbol": row["symbol"],
            "stock_cn_name": row.get("stock_cn_name", ""),
            "signal_date": row["first_alert_date"],
            "first_alert_date": row["first_alert_date"],
            "event_ts": "",
            "source_event": "high_build_queue",
            "signal_id": "",
            "price": "",
            "ai_score": "",
            "position_build_score": row.get("position_build_score", ""),
            "ma_trigger": "",
            "rebound_date": "",
            "rebound_notification_count": rebound_counts[(row["symbol"], row["first_alert_date"])],
            "is_sent": "",
            "is_deduped": "",
        }

    grouped: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for row in audit_rows:
        if row["signal_family"] == "ai_buy" and row["event"] in {"send_attempt", "sent", "deduped"}:
            key = row["signal_id"] or f"ai_buy:{row['symbol']}:{row['signal_date']}"
            g = grouped[key]
            g.update({k: v for k, v in row.items() if v not in ("", None)})
            g["sent_count"] = int(g.get("sent_count", 0)) + int(row["event"] == "sent")
            g["deduped_count"] = int(g.get("deduped_count", 0)) + int(row["event"] == "deduped")
            if row["event"] == "send_attempt":
                g["attempt_ts"] = row["ts"]
                g["attempt_price"] = row["price"]
                g["attempt_score"] = row["score"]

    for key, row in grouped.items():
        symbol = row.get("symbol", "")
        signal_date = row.get("signal_date", "")
        sample_id = f"ai_buy:{symbol}:{signal_date}:{key.rsplit('|', 1)[-1]}"
        samples[sample_id] = {
            "sample_id": sample_id,
            "sample_type": "ai_buy_signal",
            "symbol": symbol,
            "stock_cn_name": name_by_symbol.get(symbol, ""),
            "signal_date": signal_date,
            "first_alert_date": "",
            "event_ts": row.get("attempt_ts") or row.get("ts", ""),
            "source_event": "send_attempt/sent/deduped",
            "signal_id": key,
            "price": row.get("attempt_price", row.get("price", "")),
            "ai_score": row.get("attempt_score", row.get("score", "")),
            "position_build_score": "",
            "ma_trigger": "",
            "rebound_date": "",
            "rebound_notification_count": "",
            "is_sent": int(int(row.get("sent_count", 0)) > 0),
            "is_deduped": int(int(row.get("deduped_count", 0)) > 0),
        }

    for row in audit_rows:
        if row["event"] != "rebound_alert_sent":
            continue
        sample_id = f"rebound:{row['symbol']}:{row['first_alert_date']}:{row['rebound_date']}"
        samples[sample_id] = {
            "sample_id": sample_id,
            "sample_type": "rebound_alert",
            "symbol": row["symbol"],
            "stock_cn_name": name_by_symbol.get(row["symbol"], ""),
            "signal_date": row["rebound_date"] or row["signal_date"],
            "first_alert_date": row["first_alert_date"],
            "event_ts": row["ts"],
            "source_event": "rebound_alert_sent",
            "signal_id": row["signal_id"],
            "price": "",
            "ai_score": "",
            "position_build_score": pbs_by_key.get((row["symbol"], row["first_alert_date"]), ""),
            "ma_trigger": row["ma_trigger"],
            "rebound_date": row["rebound_date"],
            "rebound_notification_count": rebound_counts[(row["symbol"], row["first_alert_date"])],
            "is_sent": 1,
            "is_deduped": 0,
        }

    return sorted(samples.values(), key=lambda r: (r["signal_date"], r["symbol"], r["sample_type"]))


def build_label_template(samples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    labels: List[Dict[str, Any]] = []
    for row in samples:
        labels.append(
            {
                "sample_id": row["sample_id"],
                "sample_type": row["sample_type"],
                "symbol": row["symbol"],
                "stock_cn_name": row.get("stock_cn_name", ""),
                "signal_date": row["signal_date"],
                "entry_price": row.get("price", ""),
                "future_max_return_20d": "",
                "future_max_return_60d": "",
                "future_max_return_120d": "",
                "future_max_drawdown_20d": "",
                "future_max_drawdown_60d": "",
                "future_max_drawdown_120d": "",
                "label_double_60d": "",
                "label_double_120d": "",
                "label_bucket": "",
                "label_notes": "",
            }
        )
    return labels


def build_summary(
    queue_rows: List[Dict[str, Any]], audit_rows: List[Dict[str, Any]], samples: List[Dict[str, Any]]
) -> Dict[str, Any]:
    by_event = Counter(r["event"] for r in audit_rows)
    by_sample_type = Counter(r["sample_type"] for r in samples)
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_files": [
            str(QUEUE_FILE.relative_to(ROOT)),
            str(AUDIT_FILE.relative_to(ROOT)),
        ],
        "high_build_queue_rows": len(queue_rows),
        "a_share_audit_rows": len(audit_rows),
        "event_sample_rows": len(samples),
        "unique_symbols": len({r["symbol"] for r in samples}),
        "audit_event_counts": dict(sorted(by_event.items())),
        "sample_type_counts": dict(sorted(by_sample_type.items())),
    }


def write_readme(path: Path, summary: Dict[str, Any]) -> None:
    text = f"""# overfit_data

This directory contains normalized local exports for later attribution analysis of A-share monitoring signals.

Generated at UTC: `{summary["generated_at_utc"]}`

## Files

- `high_build_queue.csv`: current high-position-build queue from `indicator/runtime/a_share_high_build_alerts.json`.
- `a_share_audit_events.csv`: A-share rows extracted from `indicator/runtime/telegram_signal_audit.jsonl`.
- `a_share_event_samples.csv`: event-level sample table combining high-build queue, AI buy signals, and rebound alerts.
- `label_template.csv`: blank forward-return label sheet. Fill these columns after adding market data.
- `a_share_filtered_audit.jsonl`: raw filtered A-share audit events for reproducibility.
- `summary.json`: row counts and event counts for sanity checks.

## Suggested sample unit

Use `sample_id` as the join key. The recommended modeling unit is one row in `a_share_event_samples.csv`, especially `high_build_queue` and `rebound_alert` rows.

## Labeling rule suggestion

Only compute labels from prices after `signal_date`.

- `label_double_60d`: 1 if max high within 60 trading days after signal_date is at least +100%; otherwise 0.
- `label_double_120d`: same rule using 120 trading days.
- `label_bucket`: optional ordinal label such as `<20%`, `20-50%`, `50-100%`, `>=100%`.

Keep all non-doubling rows. Dropping dull or failed signals will create survivor bias.
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    queue = load_queue()
    audit_items = list(iter_audit())
    queue_rows = build_queue_rows(queue)
    audit_rows = build_audit_rows(audit_items)
    samples = build_event_samples(queue_rows, audit_rows)
    labels = build_label_template(samples)
    summary = build_summary(queue_rows, audit_rows, samples)

    write_csv(
        OUT_DIR / "high_build_queue.csv",
        queue_rows,
        [
            "sample_id",
            "symbol",
            "stock_cn_name",
            "first_alert_date",
            "position_build_score",
            "last_rebound_notified_date",
            "rebound_notified_at",
            "has_rebound_notification",
            "source_file",
        ],
    )
    write_csv(
        OUT_DIR / "a_share_audit_events.csv",
        audit_rows,
        [
            "line_no",
            "event",
            "signal_family",
            "symbol",
            "signal_id",
            "signal_date",
            "side",
            "first_alert_date",
            "rebound_date",
            "ma_trigger",
            "price",
            "score",
            "position_build_score",
            "market",
            "status",
            "hours_passed",
            "ts",
        ],
    )
    write_csv(
        OUT_DIR / "a_share_event_samples.csv",
        samples,
        [
            "sample_id",
            "sample_type",
            "symbol",
            "stock_cn_name",
            "signal_date",
            "first_alert_date",
            "event_ts",
            "source_event",
            "signal_id",
            "price",
            "ai_score",
            "position_build_score",
            "ma_trigger",
            "rebound_date",
            "rebound_notification_count",
            "is_sent",
            "is_deduped",
        ],
    )
    write_csv(
        OUT_DIR / "label_template.csv",
        labels,
        [
            "sample_id",
            "sample_type",
            "symbol",
            "stock_cn_name",
            "signal_date",
            "entry_price",
            "future_max_return_20d",
            "future_max_return_60d",
            "future_max_return_120d",
            "future_max_drawdown_20d",
            "future_max_drawdown_60d",
            "future_max_drawdown_120d",
            "label_double_60d",
            "label_double_120d",
            "label_bucket",
            "label_notes",
        ],
    )
    write_jsonl(OUT_DIR / "a_share_filtered_audit.jsonl", audit_rows)
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_readme(OUT_DIR / "README.md", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
