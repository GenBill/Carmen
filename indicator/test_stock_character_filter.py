import pandas as pd

from stock_character_filter import evaluate_stock_character


def _hist_from_closes(closes, volume=10_000_000):
    rows = []
    prev = closes[0]
    for close in closes:
        open_ = prev
        high = max(open_, close) * 1.01
        low = min(open_, close) * 0.99
        rows.append({
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": volume,
        })
        prev = close
    return pd.DataFrame(rows)


def test_liquidity_reason_alone_does_not_block_when_score_is_not_low():
    hist = _hist_from_closes([10.0] * 90, volume=1_000_000)

    result = evaluate_stock_character({
        "symbol": "000001.SZ",
        "hist": hist,
        "close": 10.0,
        "estimated_volume": 50_000_000,
    })

    assert result["passed"] is True
    assert result["auxiliary_blocked"] is False
    assert result["metrics"]["avg_amount_20"] == result["metrics"]["avg_amount_20_hist"]
    assert any("流动性弱" in reason for reason in result["reasons"])


def test_mild_orderly_pullback_after_spike_is_not_pump_fade_veto():
    closes = [100.0] * 80 + [106.0, 104.94, 103.89, 102.85, 104.0, 105.0]
    hist = _hist_from_closes(closes, volume=20_000_000)

    result = evaluate_stock_character({"symbol": "000001.SZ", "hist": hist})

    assert result["passed"] is True
    assert result["metrics"]["pump_fade_next_day_20"] == 0


def test_low_score_with_auxiliary_veto_reason_blocks():
    rows = []
    close = 10.0
    for i in range(100):
        open_ = close
        if i >= 30 and i % 5 == 0:
            high = open_ * 1.08
            close = open_ * 0.96
        else:
            high = open_ * 1.01
            close = open_ * 0.995
        low = min(open_, close) * 0.99
        rows.append({
            "Open": open_,
            "High": high,
            "Low": low,
            "Close": close,
            "Volume": 1_000_000,
        })
    hist = pd.DataFrame(rows)

    result = evaluate_stock_character({"symbol": "000001.SZ", "hist": hist})

    assert result["score"] < 55
    assert result["passed"] is False
    assert result["auxiliary_blocked"] is True
    assert any("流动性弱" in reason for reason in result["reasons"])
