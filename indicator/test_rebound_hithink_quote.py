from __future__ import annotations

from datetime import date

import rebound_hithink_quote


class FakeClient:
    def get_historical(self, symbol, *, start, end, adjust):
        assert symbol == "600519.SS"
        assert start == date(2026, 9, 1)
        assert adjust == "forward"
        return [
            {
                "date_ms": 1788192000000,
                "open_price": 1300.0,
                "high_price": 1340.0,
                "low_price": 1290.0,
                "close_price": 1330.0,
                "volume": 100.0,
            },
            {
                "date_ms": 1788451200000,
                "open_price": 1324.0,
                "high_price": 1333.6,
                "low_price": 1312.66,
                "close_price": 1316.01,
                "volume": 200.0,
            },
        ]

    def get_snapshot(self, symbols):
        assert symbols == ["600519.SS"]
        return [{"last_price": 1316.01}]


def test_fetch_rebound_quote_uses_hithink_history_and_snapshot(monkeypatch):
    monkeypatch.setattr(
        rebound_hithink_quote, "get_hithink_client", lambda: FakeClient()
    )

    result = rebound_hithink_quote.fetch_rebound_quote(
        "600519.SS", date(2026, 9, 1)
    )

    assert result["peak_high"] == 1340.0
    assert result["current_price"] == 1316.01
    assert result["price_source"] == "hithink_snapshot"
    assert list(result["hist"].columns) == [
        "date",
        "Open",
        "Close",
        "High",
        "Low",
        "Volume",
    ]