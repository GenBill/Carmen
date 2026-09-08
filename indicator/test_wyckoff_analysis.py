import pandas as pd

from wyckoff_analysis import analyze_wyckoff, format_wyckoff_report


def _frame(closes, volumes=None):
    volumes = volumes or [1_000_000] * len(closes)
    rows = []
    for close, volume in zip(closes, volumes):
        rows.append(
            {
                "Open": close,
                "High": close * 1.02,
                "Low": close * 0.98,
                "Close": close,
                "Volume": volume,
            }
        )
    return pd.DataFrame(rows)


def test_wyckoff_unknown_when_history_too_short():
    result = analyze_wyckoff({"hist": _frame([100] * 30)})

    assert result["phase"] == "Unknown"
    assert result["confidence"] == 0.0


def test_wyckoff_marks_accumulation_after_downtrend_range():
    downtrend = [160 - i for i in range(70)]
    range_prices = [92 + (i % 5) * 0.8 for i in range(70)]
    result = analyze_wyckoff({"hist": _frame(downtrend + range_prices)})

    assert result["phase"] == "B"
    assert result["bias"] == "Accumulation"
    assert "前置下跌" in result["signals"]


def test_wyckoff_marks_sos_breakout():
    downtrend = [150 - i * 0.7 for i in range(80)]
    base = [94 + (i % 4) * 0.7 for i in range(55)]
    breakout = [99, 101, 104, 107, 110]
    volumes = [1_000_000] * (len(downtrend) + len(base)) + [1_400_000, 1_500_000, 1_700_000, 1_800_000, 2_200_000]
    result = analyze_wyckoff({"hist": _frame(downtrend + base + breakout, volumes)})

    assert result["phase"] in {"D", "E"}
    assert result["bias"] in {"Bullish confirmation", "Markup"}


def test_wyckoff_report_is_telegram_html_safe():
    hist = _frame([100] * 100)
    report = format_wyckoff_report("TEST", {"hist": hist, "date": "2026-07-31"}, telegram_html=True)

    assert "Wyckoff 阶段参考" in report
    assert "<code>TEST</code>" in report
