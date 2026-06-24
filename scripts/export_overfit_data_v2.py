#!/usr/bin/env python3
"""Build clean A-share overfit samples from gh-pages HTML history.

Output shape:
- clean_signals.csv: one normalized signal event per symbol/date/signal.
- clean_samples.jsonl: same events with 250 daily OHLC bars and volume bars.
- clean_summary.json: sanity counts and fetch failures.

The HTML signal source is the full git history of origin/gh-pages, not the
current runtime queue.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "overfit_data"
CACHE_DIR = OUT_DIR / "market_cache_akshare"
NAME_FILE = ROOT / "stocks_list" / "cache" / "china_screener_A.csv"
GH_PAGES_REF = "origin/gh-pages"
HTML_PATHS = ("docs/index_a.html", "docs/index_hka.html")

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
A_SHARE_RE = re.compile(r"^\d{6}\.(SS|SZ)$")
TERMINAL_RE = re.compile(r"const\s+terminalOutput\s*=\s*`(?P<body>.*?)`;", re.S)
SCAN_TS_RE = re.compile(r"\|\s*(?P<ts>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+CST")
SIGNAL_LINE_RE = re.compile(
    r"^(?P<symbol>\d{6}\.(?:SS|SZ))\s*\|\s*"
    r"\$(?P<price>[-+]?\d+(?:\.\d+)?)\s*"
    r"(?P<change_pct>[-+]?\d+(?:\.\d+)?)%\s*\|\s*"
    r"量比:\s*(?P<volume_ratio>[-+]?\d+(?:\.\d+)?)%\s*\|\s*"
    r"RSI:\s*(?P<rsi_prev>[-+]?\d+(?:\.\d+)?)\s*[^\d+\-]*\s*(?P<rsi_current>[-+]?\d+(?:\.\d+)?)\s*\|\s*"
    r"DIF:\s*(?P<dif>[-+]?\d+(?:\.\d+)?)\s*"
    r"DEA:\s*(?P<dea>[-+]?\d+(?:\.\d+)?)\s*"
    r"斜率:\s*(?P<macd_slope>[-+]?\d+(?:\.\d+)?)\s*\|\s*"
    r"(?P<signal>.*Buy\s+(?P<buy_score>[-+]?\d+(?:\.\d+)?).*)$"
)


def run_git(args: List[str], text: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    return proc.stdout


def load_name_map() -> Dict[str, str]:
    names: Dict[str, str] = {}
    if not NAME_FILE.exists():
        return names
    with NAME_FILE.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            symbol = (row.get("Symbol") or "").strip().upper()
            name = (row.get("Name") or "").strip()
            if symbol and name:
                names[symbol] = name
    return names


def iter_commits(limit: Optional[int] = None) -> Iterable[Dict[str, str]]:
    fmt = "%H%x09%cI%x09%s"
    lines = run_git(["log", GH_PAGES_REF, f"--format={fmt}", "--", *HTML_PATHS]).splitlines()
    # git log is newest first; parse oldest first so first_seen is stable.
    if limit:
        lines = lines[:limit]
    for line in reversed(lines):
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        yield {"commit": parts[0], "commit_time": parts[1], "subject": parts[2]}


def get_file_at_commit(commit: str, path: str) -> Optional[str]:
    try:
        return run_git(["show", f"{commit}:{path}"])
    except subprocess.CalledProcessError:
        return None


def decode_terminal_output(html_text: str) -> str:
    match = TERMINAL_RE.search(html_text)
    if not match:
        return ""
    body = match.group("body")
    body = body.replace("\\`", "`").replace("\\\\", "\\")
    return html.unescape(body)


def clean_terminal_line(line: str) -> str:
    return ANSI_RE.sub("", line).replace("\r", "").strip()


def parse_scan_ts(output: str, commit_time: str) -> Tuple[str, str]:
    first_line = next((clean_terminal_line(line) for line in output.splitlines() if line.strip()), "")
    match = SCAN_TS_RE.search(first_line)
    if match:
        scan_ts = match.group("ts")
        return scan_ts, scan_ts[:10]
    return commit_time, commit_time[:10]


def parse_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("+", ""))
    except ValueError:
        return None


def parse_signals_from_output(
    output: str,
    commit: Dict[str, str],
    html_path: str,
    names: Dict[str, str],
) -> List[Dict[str, Any]]:
    scan_ts, signal_date = parse_scan_ts(output, commit["commit_time"])
    rows: List[Dict[str, Any]] = []
    for raw_line in output.splitlines():
        line = clean_terminal_line(raw_line)
        if "Buy" not in line or "|" not in line:
            continue
        match = SIGNAL_LINE_RE.match(line)
        if not match:
            continue
        gd = match.groupdict()
        symbol = gd["symbol"].upper()
        if not A_SHARE_RE.match(symbol):
            continue
        signal_text = " ".join((gd.get("signal") or "").split())
        sample_id = f"{symbol}:{signal_date}:buy:{gd.get('buy_score')}"
        rows.append(
            {
                "sample_id": sample_id,
                "symbol": symbol,
                "stock_cn_name": names.get(symbol, ""),
                "signal_date": signal_date,
                "scan_ts": scan_ts,
                "trigger_signal": signal_text,
                "signal_side": "buy",
                "buy_score": parse_float(gd.get("buy_score")),
                "scan_price": parse_float(gd.get("price")),
                "scan_change_pct": parse_float(gd.get("change_pct")),
                "scan_volume_ratio_pct": parse_float(gd.get("volume_ratio")),
                "scan_rsi_prev": parse_float(gd.get("rsi_prev")),
                "scan_rsi_current": parse_float(gd.get("rsi_current")),
                "scan_dif": parse_float(gd.get("dif")),
                "scan_dea": parse_float(gd.get("dea")),
                "scan_macd_slope": parse_float(gd.get("macd_slope")),
                "html_source": html_path,
                "first_seen_commit": commit["commit"],
                "first_seen_commit_time": commit["commit_time"],
                "raw_terminal_line": line,
            }
        )
    return rows


def extract_html_signals(limit_commits: Optional[int] = None) -> List[Dict[str, Any]]:
    names = load_name_map()
    deduped: Dict[str, Dict[str, Any]] = {}
    for commit in iter_commits(limit_commits):
        for html_path in HTML_PATHS:
            html_text = get_file_at_commit(commit["commit"], html_path)
            if not html_text:
                continue
            output = decode_terminal_output(html_text)
            if not output:
                continue
            for row in parse_signals_from_output(output, commit, html_path, names):
                # Keep the first signal seen for a symbol/date/score. Intraday
                # repeats are useful in raw logs, but poor ML rows.
                deduped.setdefault(row["sample_id"], row)
    return sorted(deduped.values(), key=lambda r: (r["signal_date"], r["symbol"], r["buy_score"] or 0))


def ak_symbol(symbol: str) -> str:
    return symbol.split(".", 1)[0]


def history_cache_file(symbol: str, signal_date: str) -> Path:
    return CACHE_DIR / f"{symbol}_{signal_date}_250d.json"


def normalize_akshare_hist(raw: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if raw is None or getattr(raw, "empty", True):
        return rows
    for _, item in raw.iterrows():
        date_value = item.get("日期")
        rows.append(
            {
                "date": str(date_value)[:10],
                "open": parse_float(item.get("开盘")),
                "high": parse_float(item.get("最高")),
                "low": parse_float(item.get("最低")),
                "close": parse_float(item.get("收盘")),
                "volume": parse_float(item.get("成交量")),
                "amount": parse_float(item.get("成交额")),
                "turnover_rate": parse_float(item.get("换手率")),
                "change_pct": parse_float(item.get("涨跌幅")),
            }
        )
    return rows


def fetch_akshare_history(symbol: str, signal_date: str, sleep_seconds: float = 0.2) -> Dict[str, Any]:
    cache_file = history_cache_file(symbol, signal_date)
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    import akshare as ak

    end_dt = datetime.strptime(signal_date, "%Y-%m-%d")
    start_dt = end_dt - timedelta(days=520)
    raw = ak.stock_zh_a_hist(
        symbol=ak_symbol(symbol),
        period="daily",
        start_date=start_dt.strftime("%Y%m%d"),
        end_date=end_dt.strftime("%Y%m%d"),
        adjust="",
    )
    rows = normalize_akshare_hist(raw)
    rows = [row for row in rows if row["date"] <= signal_date]
    rows = rows[-250:]
    payload = {
        "symbol": symbol,
        "signal_date": signal_date,
        "provider": "akshare.stock_zh_a_hist",
        "adjust": "",
        "bar_count": len(rows),
        "kline_250d": [
            {
                "date": row["date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
            }
            for row in rows
        ],
        "volume_250d": [
            {
                "date": row["date"],
                "volume": row["volume"],
                "amount": row["amount"],
                "turnover_rate": row["turnover_rate"],
            }
            for row in rows
        ],
        "raw_daily_250d": rows,
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if sleep_seconds > 0:
        time.sleep(sleep_seconds)
    return payload


def write_csv(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in columns})


def build_samples(signals: List[Dict[str, Any]], fetch_market: bool) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    samples: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for idx, signal in enumerate(signals, 1):
        sample = dict(signal)
        if fetch_market:
            try:
                hist = fetch_akshare_history(signal["symbol"], signal["signal_date"])
                sample["kline_250d"] = hist["kline_250d"]
                sample["volume_250d"] = hist["volume_250d"]
                sample["market_data_provider"] = hist["provider"]
                sample["market_data_adjust"] = hist["adjust"]
                sample["bar_count"] = hist["bar_count"]
            except Exception as exc:
                failures.append(
                    {
                        "sample_id": signal["sample_id"],
                        "symbol": signal["symbol"],
                        "signal_date": signal["signal_date"],
                        "error": str(exc),
                    }
                )
                sample["kline_250d"] = []
                sample["volume_250d"] = []
                sample["market_data_provider"] = "akshare.stock_zh_a_hist"
                sample["market_data_adjust"] = ""
                sample["bar_count"] = 0
        else:
            sample["kline_250d"] = []
            sample["volume_250d"] = []
            sample["market_data_provider"] = ""
            sample["market_data_adjust"] = ""
            sample["bar_count"] = ""
        samples.append(sample)
        if fetch_market and idx % 25 == 0:
            print(f"fetched {idx}/{len(signals)} samples")
    return samples, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parse-only", action="store_true", help="Do not fetch akshare market data")
    parser.add_argument("--limit-commits", type=int, default=None, help="Debug: only inspect newest N commits")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    signals = extract_html_signals(limit_commits=args.limit_commits)
    samples, failures = build_samples(signals, fetch_market=not args.parse_only)

    signal_columns = [
        "sample_id",
        "symbol",
        "stock_cn_name",
        "signal_date",
        "scan_ts",
        "trigger_signal",
        "signal_side",
        "buy_score",
        "scan_price",
        "scan_change_pct",
        "scan_volume_ratio_pct",
        "scan_rsi_prev",
        "scan_rsi_current",
        "scan_dif",
        "scan_dea",
        "scan_macd_slope",
        "html_source",
        "first_seen_commit",
        "first_seen_commit_time",
        "raw_terminal_line",
    ]
    write_csv(OUT_DIR / "clean_signals.csv", signals, signal_columns)

    with (OUT_DIR / "clean_samples.jsonl").open("w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False, separators=(",", ":")) + "\n")

    summary = {
        "generated_at": datetime.now().isoformat(),
        "source_ref": GH_PAGES_REF,
        "html_paths": list(HTML_PATHS),
        "signal_count": len(signals),
        "sample_count": len(samples),
        "unique_symbols": len({row["symbol"] for row in signals}),
        "date_min": min((row["signal_date"] for row in signals), default=""),
        "date_max": max((row["signal_date"] for row in signals), default=""),
        "market_data_fetched": not args.parse_only,
        "market_fetch_failures": failures,
        "market_fetch_failure_count": len(failures),
    }
    (OUT_DIR / "clean_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    readme = """# Clean Overfit Data

Generated from the full `origin/gh-pages` HTML history, not from the runtime queue.

Files:

- `clean_signals.csv`: one deduplicated A-share buy signal per `symbol + signal_date + buy_score`.
- `clean_samples.jsonl`: one JSON object per signal, with `kline_250d` and `volume_250d` arrays.
- `market_cache_akshare/`: cached per-symbol/per-date akshare history payloads.
- `clean_summary.json`: row counts and fetch failures.

Sample JSONL shape:

```json
{
  "symbol": "688010.SS",
  "stock_cn_name": "福光股份",
  "signal_date": "2026-06-12",
  "trigger_signal": "Buy 2.4 (...) vs Sell 0.0",
  "kline_250d": [{"date": "2025-06-10", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0}],
  "volume_250d": [{"date": "2025-06-10", "volume": 100000, "amount": 1000000, "turnover_rate": 1.2}]
}
```

Labels are intentionally omitted.
"""
    (OUT_DIR / "README_clean.md").write_text(readme, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
