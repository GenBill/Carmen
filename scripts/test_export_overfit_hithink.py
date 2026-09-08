from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.export_overfit_data_v2 import _historical_row


def test_historical_row_uses_shanghai_date_and_price_fields():
    date_ms = int(
        datetime(2026, 9, 4, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000
    )
    row = _historical_row(
        {
            "date_ms": date_ms,
            "open_price": 10.1,
            "high_price": 10.8,
            "low_price": 9.9,
            "close_price": 10.5,
            "volume": 1234,
            "amount": 5678,
        }
    )

    assert row["date"] == "2026-09-04"
    assert (row["open"], row["high"], row["low"], row["close"]) == (
        10.1,
        10.8,
        9.9,
        10.5,
    )