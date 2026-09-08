from __future__ import annotations

import scan_ai_common


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_snapshot(self, symbols):
        self.calls.append(list(symbols))
        return [{"thscode": "600519.SH", "open_price": 1324.0}]


def test_a_share_open_filter_uses_hithink_candidate_snapshot(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(scan_ai_common, "get_hithink_client", lambda: client)
    monkeypatch.setattr(scan_ai_common, "_A_SHARE_TODAY_OPEN_CACHE", None)
    monkeypatch.setattr(scan_ai_common, "_A_SHARE_TODAY_OPEN_CACHE_DATE", None)

    context = scan_ai_common.resolve_opening_price_context_for_filter(
        "600519.SS", {"open": 1300.0}
    )

    assert context.open_for_filter == 1324.0
    assert context.opening_uncertain is False
    assert context.open_drop_filter_enabled is True
    assert client.calls == [["600519.SS"]]


def test_a_share_open_filter_reuses_same_day_hithink_cache(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(scan_ai_common, "get_hithink_client", lambda: client)
    monkeypatch.setattr(scan_ai_common, "_A_SHARE_TODAY_OPEN_CACHE", None)
    monkeypatch.setattr(scan_ai_common, "_A_SHARE_TODAY_OPEN_CACHE_DATE", None)

    for _ in range(2):
        scan_ai_common.resolve_opening_price_context_for_filter(
            "600519.SS", {"open": 1300.0}
        )

    assert client.calls == [["600519.SS"]]