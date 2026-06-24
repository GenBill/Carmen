#!/usr/bin/env python3
"""Label clean overfit signals with post-signal signed directional amplitude."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "overfit_data"
DEFAULT_SIGNALS_CSV = OUT_DIR / "clean_signals.csv"
DEFAULT_CACHE_DIR = OUT_DIR / "market_cache" / "yfinance"
DEFAULT_OUTPUT_CSV = OUT_DIR / "clean_directional_amp_labels.csv"
DEFAULT_WINDOWS = (7, 14, 28)


def parse_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def mean(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def window_mean(
    values: Sequence[float],
    window: int,
    allow_partial_window: bool,
) -> Optional[float]:
    if len(values) >= window:
        return mean(values[:window])
    if allow_partial_window and values:
        return mean(values)
    return None


def compute_directional_amp_label(
    rows: Iterable[Dict[str, Any]],
    signal_date: str,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    allow_partial_window: bool = False,
) -> Dict[str, Any]:
    sorted_rows = sorted(rows, key=lambda row: str(row.get("date") or ""))
    signal_row = next((row for row in sorted_rows if row.get("date") == signal_date), None)
    if signal_row is None:
        return empty_label(signal_date, "missing_signal_bar", windows)

    cost_price = parse_float(signal_row.get("high"))
    if cost_price is None or cost_price <= 0:
        return empty_label(signal_date, "invalid_cost_price", windows, cost_price=cost_price)

    forward_rows = [row for row in sorted_rows if str(row.get("date") or "") > signal_date]
    signed_amps: List[float] = []
    for row in forward_rows:
        close_price = parse_float(row.get("close"))
        if close_price is None:
            continue
        signed_amps.append((close_price - cost_price) / cost_price)

    label: Dict[str, Any] = {
        "signal_date": signal_date,
        "cost_price": cost_price,
        "forward_days_available": len(signed_amps),
        "allow_partial_window": allow_partial_window,
        "label_status": "ok",
    }
    window_values: List[Optional[float]] = []
    for window in windows:
        value = window_mean(signed_amps, window, allow_partial_window)
        label[f"A{window}"] = value
        window_values.append(value)

    if all(value is not None for value in window_values):
        label["score"] = mean([value for value in window_values if value is not None])
    else:
        label["score"] = None
        label["label_status"] = "partial_forward_window"
    return label


def empty_label(
    signal_date: str,
    status: str,
    windows: Sequence[int],
    cost_price: Optional[float] = None,
) -> Dict[str, Any]:
    label: Dict[str, Any] = {
        "signal_date": signal_date,
        "cost_price": cost_price,
        "forward_days_available": 0,
        "allow_partial_window": False,
        "label_status": status,
        "score": None,
    }
    for window in windows:
        label[f"A{window}"] = None
    return label


def load_signals(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_history(cache_dir: Path, symbol: str) -> List[Dict[str, Any]]:
    cache_file = cache_dir / f"{symbol}.json"
    if not cache_file.exists():
        return []
    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    return payload.get("raw_daily", [])


def format_csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float):
        return f"{value:.12g}"
    return value


def write_csv(path: Path, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({col: format_csv_value(row.get(col)) for col in columns})


def build_labels(
    signals: List[Dict[str, Any]],
    cache_dir: Path,
    windows: Sequence[int],
    allow_partial_window: bool,
) -> List[Dict[str, Any]]:
    history_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    labels: List[Dict[str, Any]] = []
    for signal in signals:
        symbol = signal.get("symbol", "")
        signal_date = signal.get("signal_date", "")
        if symbol not in history_by_symbol:
            history_by_symbol[symbol] = load_history(cache_dir, symbol)

        if not history_by_symbol[symbol]:
            label = empty_label(signal_date, "missing_history_cache", windows)
        else:
            label = compute_directional_amp_label(
                history_by_symbol[symbol],
                signal_date,
                windows=windows,
                allow_partial_window=allow_partial_window,
            )
            label["allow_partial_window"] = allow_partial_window

        labels.append(
            {
                "sample_id": signal.get("sample_id", ""),
                "symbol": symbol,
                "stock_cn_name": signal.get("stock_cn_name", ""),
                **label,
            }
        )
    return labels


def parse_windows(raw: str) -> List[int]:
    windows = [int(item.strip()) for item in raw.split(",") if item.strip()]
    if not windows:
        raise argparse.ArgumentTypeError("at least one window is required")
    if any(window <= 0 for window in windows):
        raise argparse.ArgumentTypeError("windows must be positive integers")
    return windows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signals-csv", type=Path, default=DEFAULT_SIGNALS_CSV)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--windows", type=parse_windows, default=list(DEFAULT_WINDOWS))
    parser.add_argument("--allow-partial-window", action="store_true")
    args = parser.parse_args()

    signals = load_signals(args.signals_csv)
    labels = build_labels(
        signals,
        args.cache_dir,
        args.windows,
        allow_partial_window=args.allow_partial_window,
    )
    columns = [
        "sample_id",
        "symbol",
        "stock_cn_name",
        "signal_date",
        "cost_price",
        *[f"A{window}" for window in args.windows],
        "score",
        "forward_days_available",
        "allow_partial_window",
        "label_status",
    ]
    write_csv(args.output_csv, labels, columns)

    status_counts: Dict[str, int] = {}
    for label in labels:
        status = str(label.get("label_status") or "")
        status_counts[status] = status_counts.get(status, 0) + 1
    print(
        json.dumps(
            {
                "signals": len(signals),
                "labels": len(labels),
                "output_csv": str(args.output_csv),
                "allow_partial_window": args.allow_partial_window,
                "status_counts": status_counts,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
