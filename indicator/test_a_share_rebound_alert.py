from datetime import date

import pandas as pd

from a_share_rebound_alert import check_rebound_conditions


def _hist(rows):
    df = pd.DataFrame(
        rows,
        columns=["Date", "Open", "High", "Low", "Close", "Volume"],
    )
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date")


def test_rebound_alert_blocks_break_below_first_alert_low():
    hist = _hist(
        [
            ("2026-06-22", 6.76, 6.81, 6.60, 6.79, 11630525),
            ("2026-06-23", 6.75, 7.38, 6.75, 7.19, 25642167),
            ("2026-06-24", 7.18, 7.19, 6.73, 6.77, 17484451),
            ("2026-06-25", 6.71, 6.94, 6.67, 6.83, 13613104),
            ("2026-06-26", 6.82, 6.86, 6.64, 6.73, 9707428),
            ("2026-06-29", 6.73, 6.73, 6.73, 6.73, 0),
            ("2026-06-30", 5.45, 5.69, 5.38, 5.38, 39501210),
            ("2026-07-01", 5.17, 5.35, 5.09, 5.25, 36115235),
            ("2026-07-02", 5.22, 5.44, 5.20, 5.21, 20324495),
            ("2026-07-03", 5.21, 5.27, 5.15, 5.19, 11845274),
            ("2026-07-06", 5.13, 5.24, 5.12, 5.18, 13030058),
            ("2026-07-07", 5.21, 5.21, 5.08, 5.10, 3727710),
        ]
    )
    entry = {"symbol": "300087.SZ", "first_alert_date": "2026-07-02", "position_build_score": 8.0}

    ok, ma_trigger, peak_high, peak_low = check_rebound_conditions(
        entry, hist, current_price=5.10, today=date(2026, 7, 7)
    )

    assert ok is False
    assert ma_trigger is None
    assert peak_high is None
    assert peak_low is None


def test_rebound_alert_allows_pullback_above_first_alert_low_with_imminent_volume_cross():
    hist = _hist(
        [
            ("2026-06-22", 6.76, 6.81, 6.60, 6.79, 11630525),
            ("2026-06-23", 6.75, 7.38, 6.75, 7.19, 25642167),
            ("2026-06-24", 7.18, 7.19, 6.73, 6.77, 17484451),
            ("2026-06-25", 6.71, 6.94, 6.67, 6.83, 13613104),
            ("2026-06-26", 6.82, 6.86, 6.64, 6.73, 9707428),
            ("2026-06-29", 6.73, 6.73, 6.73, 6.73, 0),
            ("2026-06-30", 5.45, 5.69, 5.38, 5.38, 39501210),
            ("2026-07-01", 5.17, 5.35, 5.09, 5.25, 36115235),
            ("2026-07-02", 5.22, 5.44, 5.20, 5.21, 20324495),
            ("2026-07-03", 5.21, 5.32, 5.21, 5.28, 11845274),
            ("2026-07-06", 5.25, 5.36, 5.23, 5.31, 13030058),
            ("2026-07-07", 5.26, 5.31, 5.22, 5.23, 3727710),
        ]
    )
    entry = {"symbol": "300087.SZ", "first_alert_date": "2026-07-02", "position_build_score": 8.0}

    ok, ma_trigger, peak_high, peak_low = check_rebound_conditions(
        entry, hist, current_price=5.23, today=date(2026, 7, 7)
    )

    assert ok is True
    assert ma_trigger == "量能5/10即将死叉"
    assert round(peak_high, 2) == 5.36
    assert round(peak_low, 2) == 5.21
