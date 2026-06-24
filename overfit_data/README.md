# overfit_data

This directory contains normalized local exports for later attribution analysis of A-share monitoring signals.

Generated at UTC: `2026-06-14T13:34:44.184011+00:00`

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
