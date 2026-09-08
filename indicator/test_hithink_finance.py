from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from hithink_finance import (
    HithinkFinanceClient,
    HithinkFinanceError,
    _date_ms,
    normalize_thscode,
)


@dataclass
class FakeResponse:
    payload: dict
    status_code: int = 200
    headers: dict | None = None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("600519.SS", "600519.SH"),
        ("688981.SH", "688981.SH"),
        ("000001.SZ", "000001.SZ"),
        ("920799.BJ", "920799.BJ"),
        ("300750", "300750.SZ"),
        ("600519", "600519.SH"),
    ],
)
def test_normalize_thscode(symbol, expected):
    assert normalize_thscode(symbol) == expected


def test_date_ms_uses_shanghai_midnight():
    expected = int(
        datetime(2026, 9, 4, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1000
    )
    assert _date_ms(date(2026, 9, 4)) == expected


def test_turnover_uses_hithink_snapshot_and_float_market_cap():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "code": 0,
                    "message": "success",
                    "request_id": "snapshot-id",
                    "data": {
                        "item": [
                            {
                                "thscode": "600519.SH",
                                "volume": 2_524_962,
                                "last_price": 1316.01,
                            }
                        ]
                    },
                }
            ),
            FakeResponse(
                {
                    "code": 0,
                    "message": "success",
                    "request_id": "auction-id",
                    "data": {
                        "item": [
                            {
                                "thscode": "600519.SH",
                                "float_market_cap": 1_645_119_887_732.01,
                            }
                        ]
                    },
                }
            ),
        ]
    )
    client = HithinkFinanceClient(api_key="test-key", session=session)

    assert client.get_turnover_pct("600519.SS") == pytest.approx(0.201999, rel=1e-4)
    assert session.calls[0][1]["params"] == {"thscodes": "600519.SH"}
    assert session.calls[1][1]["params"] == {
        "thscodes": "600519.SH",
        "stage": "final",
    }


def test_request_retries_http_429_then_returns_success():
    session = FakeSession(
        [
            FakeResponse(
                {"code": 429, "message": "request limit exceeded"},
                status_code=429,
            ),
            FakeResponse(
                {
                    "code": 0,
                    "message": "success",
                    "request_id": "ok-id",
                    "data": {"item": []},
                }
            ),
        ]
    )
    sleeps = []
    client = HithinkFinanceClient(
        api_key="test-key",
        session=session,
        sleep=sleeps.append,
        min_interval=0,
        max_attempts=2,
    )

    assert client.get_snapshot(["600519.SS"]) == []
    assert len(session.calls) == 2
    assert sleeps == [1.0]


def test_request_raises_business_error_with_request_id():
    session = FakeSession(
        [
            FakeResponse(
                {
                    "code": 2003,
                    "message": "permission denied",
                    "request_id": "denied-id",
                    "data": None,
                }
            )
        ]
    )
    client = HithinkFinanceClient(api_key="test-key", session=session)

    with pytest.raises(HithinkFinanceError, match="denied-id"):
        client.get_snapshot(["600519.SS"])