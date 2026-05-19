#!/usr/bin/env python3
"""探测 akshare 能否为「回撤预警」拉取：入队日起最高价 + 最新价。

运行（项目根目录）:
  python scripts/test_akshare_rebound_quote.py
  python scripts/test_akshare_rebound_quote.py --symbol 002930.SZ --since 2026-05-07
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "indicator"))

from rebound_ak_quote import akshare_available, fetch_rebound_quote  # noqa: E402

QUEUE_FILE = ROOT / "indicator" / "runtime" / "a_share_high_build_alerts.json"


def probe(symbol: str, since: str) -> dict[str, Any]:
    since_d = datetime.strptime(since[:10], "%Y-%m-%d").date()
    result: dict[str, Any] = {
        "symbol": symbol,
        "since": since_d.isoformat(),
        "ok": False,
        "akshare_import": akshare_available(),
    }
    if not result["akshare_import"]:
        result["error"] = "import akshare 失败"
        return result

    quote = fetch_rebound_quote(symbol, since_d)
    if not quote:
        result["error"] = "fetch_rebound_quote 返回 None"
        return result

    peak = float(quote["peak_high"])
    current = float(quote["current_price"])
    hist = quote["hist"]
    drop_pct = (peak - current) / peak * 100.0 if peak > 0 else 0.0
    result.update(
        {
            "ok": True,
            "bars": len(hist),
            "last_date": str(hist.iloc[-1]["date"]),
            "peak_high_since_alert": round(peak, 4),
            "current_price": round(current, 4),
            "price_source": quote.get("price_source"),
            "drop_from_peak_pct": round(drop_pct, 2),
            "meets_drop_4pct": drop_pct >= 4.0,
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="akshare 回撤预警行情探测")
    parser.add_argument("--symbol", default=None, help="如 002930.SZ")
    parser.add_argument("--since", default=None, help="入队预警日 YYYY-MM-DD")
    args = parser.parse_args()

    symbol = args.symbol
    since = args.since
    if not symbol or not since:
        if not QUEUE_FILE.exists():
            print(f"队列不存在: {QUEUE_FILE}")
            sys.exit(1)
        queue = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        if not queue:
            print("队列为空")
            sys.exit(1)
        entry = queue[0]
        symbol = symbol or entry["symbol"]
        since = since or entry["first_alert_date"]

    print(f"探测 {symbol} 自 {since} …")
    res = probe(symbol, since)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    sys.exit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
