import analysis
import async_ai
import serenity_analysis
import telegram_notifier


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send_buy_signal(self, **kwargs):
        self.sent.append(kwargs)
        return True


def _patch_completed_ai(monkeypatch):
    monkeypatch.setattr(
        analysis,
        "build_or_load_ai_result",
        lambda symbol, market=None: {
            "symbol": symbol,
            "status": "completed",
            "refined_info": {},
            "refine_analysis": "",
            "summary_analysis": "",
            "full_analysis": "",
        },
    )
    monkeypatch.setattr(analysis, "empty_refined_info", lambda: {})
    monkeypatch.setattr(telegram_notifier, "append_signal_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(serenity_analysis, "claim_serenity_daily_slot", lambda symbol: False)


def _run_task(backtest_str):
    return async_ai.process_ai_task(
        symbol="300213.SZ",
        market="HKA",
        bot_notifier=FakeNotifier(),
        price=6.05,
        score=0.0,
        backtest_str=backtest_str,
        rsi=17.0,
        volume_ratio=100.0,
        volume_ma_info={"position_build_score": 9.0, "has_recent_golden_cross": True},
        alert_date="2026-06-29",
        stock_cn_name="佳讯飞鸿",
    )


def test_rsi_signal_does_not_record_high_build_queue(monkeypatch):
    _patch_completed_ai(monkeypatch)
    recorded = []
    monkeypatch.setattr(async_ai, "maybe_record_high_build_alert", lambda **kwargs: recorded.append(kwargs))

    result = _run_task("(RSI18)")

    assert result["status"] == "completed"
    assert recorded == []


def test_non_rsi_signal_records_high_build_queue(monkeypatch):
    _patch_completed_ai(monkeypatch)
    recorded = []
    monkeypatch.setattr(async_ai, "maybe_record_high_build_alert", lambda **kwargs: recorded.append(kwargs))

    result = _run_task("(3/5)")

    assert result["status"] == "completed"
    assert recorded == [{
        "symbol": "300213.SZ",
        "alert_date": "2026-06-29",
        "position_build_score": 9.0,
        "stock_cn_name": "佳讯飞鸿",
    }]
