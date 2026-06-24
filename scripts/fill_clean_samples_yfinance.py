#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / 'overfit_data'
SIGNALS_CSV = OUT_DIR / 'clean_signals.csv'
SAMPLES_JSONL = OUT_DIR / 'clean_samples.jsonl'
SUMMARY_JSON = OUT_DIR / 'clean_summary.json'
CACHE_DIR = OUT_DIR / 'market_cache' / 'yfinance'


def parse_float(value: Any) -> Optional[float]:
    if value in (None, ''):
        return None
    try:
        return float(value)
    except Exception:
        return None


def load_signals() -> List[Dict[str, Any]]:
    with SIGNALS_CSV.open('r', encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in [
            'buy_score', 'scan_price', 'scan_change_pct', 'scan_volume_ratio_pct',
            'scan_rsi_prev', 'scan_rsi_current', 'scan_dif', 'scan_dea', 'scan_macd_slope'
        ]:
            row[key] = parse_float(row.get(key))
    return rows


def normalize_yfinance(raw: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if raw is None or getattr(raw, 'empty', True):
        return rows
    df = raw.copy()
    if hasattr(df.columns, 'nlevels') and df.columns.nlevels > 1:
        df.columns = [col[0] for col in df.columns]
    for idx, item in df.iterrows():
        rows.append({
            'date': str(idx)[:10],
            'open': parse_float(item.get('Open')),
            'high': parse_float(item.get('High')),
            'low': parse_float(item.get('Low')),
            'close': parse_float(item.get('Close')),
            'volume': parse_float(item.get('Volume')),
            'amount': None,
            'turnover_rate': None,
        })
    return rows


def fetch_symbol(symbol: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    cache_file = CACHE_DIR / f'{symbol}.json'
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding='utf-8')).get('raw_daily', [])

    import yfinance as yf

    raw = yf.download(
        symbol,
        start=start_date,
        end=(datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d'),
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    rows = normalize_yfinance(raw)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({
        'symbol': symbol,
        'provider': 'yfinance.download',
        'start_date': start_date,
        'end_date': end_date,
        'bar_count': len(rows),
        'raw_daily': rows,
    }, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    time.sleep(0.05)
    return rows


def slice_250(rows: List[Dict[str, Any]], signal_date: str) -> Dict[str, Any]:
    sliced = [row for row in rows if row['date'] <= signal_date][-250:]
    return {
        'bar_count': len(sliced),
        'kline_250d': [
            {'date': r['date'], 'open': r['open'], 'high': r['high'], 'low': r['low'], 'close': r['close']}
            for r in sliced
        ],
        'volume_250d': [
            {'date': r['date'], 'volume': r['volume'], 'amount': r['amount'], 'turnover_rate': r['turnover_rate']}
            for r in sliced
        ],
    }


def main() -> None:
    signals = load_signals()
    min_date = min(row['signal_date'] for row in signals)
    max_date = max(row['signal_date'] for row in signals)
    start_date = (datetime.strptime(min_date, '%Y-%m-%d') - timedelta(days=540)).strftime('%Y-%m-%d')
    symbols = sorted({row['symbol'] for row in signals})

    histories: Dict[str, List[Dict[str, Any]]] = {}
    failures: List[Dict[str, Any]] = []
    for idx, symbol in enumerate(symbols, 1):
        try:
            histories[symbol] = fetch_symbol(symbol, start_date, max_date)
        except Exception as exc:
            failures.append({'symbol': symbol, 'error': str(exc)})
            histories[symbol] = []
        if idx % 50 == 0:
            print(f'fetched yfinance symbols {idx}/{len(symbols)}')

    empty_samples = 0
    with SAMPLES_JSONL.open('w', encoding='utf-8') as f:
        for idx, signal in enumerate(signals, 1):
            hist = slice_250(histories.get(signal['symbol'], []), signal['signal_date'])
            sample = dict(signal)
            sample.update({
                'market_data_provider': 'yfinance.download',
                'market_data_adjust': 'auto_adjust=False',
                'bar_count': hist['bar_count'],
                'kline_250d': hist['kline_250d'],
                'volume_250d': hist['volume_250d'],
            })
            if hist['bar_count'] == 0:
                empty_samples += 1
            f.write(json.dumps(sample, ensure_ascii=False, separators=(',', ':')) + '\n')
            if idx % 500 == 0:
                print(f'built samples {idx}/{len(signals)}')

    summary = {
        'generated_at': datetime.now().isoformat(),
        'source_ref': 'origin/gh-pages',
        'html_paths': ['docs/index_a.html', 'docs/index_hka.html'],
        'signal_count': len(signals),
        'sample_count': len(signals),
        'unique_symbols': len(symbols),
        'date_min': min_date,
        'date_max': max_date,
        'market_data_fetched': True,
        'market_source': 'yfinance',
        'symbol_fetch_failure_count': len(failures),
        'symbol_fetch_failures': failures,
        'empty_sample_count': empty_samples,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
