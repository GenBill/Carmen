# Clean Overfit Data

Generated from the full `origin/gh-pages` HTML history, not from the runtime queue.

Files:

- `clean_signals.csv`: one deduplicated A-share buy signal per `symbol + signal_date + buy_score`.
- `clean_samples.jsonl`: one JSON object per signal, with `kline_250d` and `volume_250d` arrays.
- `market_cache/yfinance/`: cached per-symbol yfinance history payloads used to slice 250-day windows.
- `clean_directional_amp_labels.csv`: post-signal signed directional amplitude labels.
- `clean_summary.json`: row counts and fetch failures.

Sample JSONL shape:

```json
{
  "symbol": "688010.SS",
  "stock_cn_name": "福光股份",
  "signal_date": "2026-06-12",
  "trigger_signal": "Buy 2.4 (...) vs Sell 0.0",
  "kline_250d": [{"date": "2025-06-10", "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0}],
  "volume_250d": [{"date": "2025-06-10", "volume": 100000, "amount": null, "turnover_rate": null}]
}
```

Labels are intentionally omitted from `clean_samples.jsonl`.

## Directional amplitude labels

Build labels with:

```bash
python scripts/label_directional_amp.py
```

The label script reads `clean_signals.csv` and full per-symbol `market_cache/yfinance/*.json` histories. It does not use `kline_250d`, because `clean_samples.jsonl` intentionally contains only pre-signal bars.

For each signal:

- `cost_price = high[signal_date]`
- `signed_amp_t = (close_t - cost_price) / cost_price`, starting from the first trading day after `signal_date`
- `A7`, `A14`, and `A28` are the mean signed amplitudes for the first 7, 14, and 28 post-signal trading days
- `score = (A7 + A14 + A28) / 3`

By default, insufficient future bars make that window and `score` blank. Use `--allow-partial-window` to average the available post-signal bars instead.
