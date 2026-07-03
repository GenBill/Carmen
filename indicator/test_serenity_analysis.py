import json
from datetime import datetime, timedelta

import async_ai
import serenity_analysis


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send_buy_signal(self, **kwargs):
        self.sent.append({"kind": "buy", **kwargs})
        return True

    def send_serenity_analysis(self, **kwargs):
        self.sent.append({"kind": "serenity", **kwargs})
        return True


def test_serenity_cache_reuses_recent_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(serenity_analysis, "CACHE_FILE", tmp_path / "serenity_cache.json")
    serenity_analysis.save_serenity_cache_entry(
        "abc",
        "cached-message",
        model="cached-model",
        market="US",
        stock_cn_name="",
    )

    hit = serenity_analysis.read_serenity_cache_entry("ABC", max_age_days=3)

    assert hit is not None
    assert hit["message"] == "cached-message"
    assert hit["model"] == "cached-model"


def test_serenity_cache_ignores_stale_entry(tmp_path, monkeypatch):
    cache_file = tmp_path / "serenity_cache.json"
    monkeypatch.setattr(serenity_analysis, "CACHE_FILE", cache_file)
    stale_dt = datetime.now(serenity_analysis.HK_TZ) - timedelta(days=4)
    cache_file.write_text(json.dumps({
        "entries": {
            "ABC": {
                "symbol": "ABC",
                "message": "stale-message",
                "created_at": stale_dt.isoformat(timespec="seconds"),
            }
        }
    }), encoding="utf-8")

    assert serenity_analysis.read_serenity_cache_entry("ABC", max_age_days=3) is None


def test_generate_serenity_analysis_saves_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(serenity_analysis, "CACHE_FILE", tmp_path / "serenity_cache.json")
    monkeypatch.setattr(
        serenity_analysis,
        "_call_openclaw_serenity_skill",
        lambda prompt, timeout_seconds: (
            "BEGIN_TELEGRAM_MESSAGE\n"
            "产业链/chokepoint cached body\n"
            "END_TELEGRAM_MESSAGE"
        ),
    )

    msg = serenity_analysis.generate_serenity_analysis(
        symbol="ABC",
        market="US",
        price=10.0,
        score=1.0,
        backtest_str=None,
        rsi=None,
        volume_ratio=None,
        turnover_rate=None,
        volume_ma_info=None,
        refined_info=None,
        refine_analysis="",
        summary_analysis="",
        full_analysis="",
    )

    hit = serenity_analysis.read_serenity_cache_entry("ABC", max_age_days=3)
    assert "产业链/chokepoint cached body" in msg
    assert hit is not None
    assert hit["message"] == msg


def test_openclaw_skips_model_by_default(monkeypatch):
    captured = {}

    class Result:
        returncode = 0
        stdout = '{"reply":"ok"}'
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Result()

    monkeypatch.delenv("CARMEN_SERENITY_OPENCLAW_MODEL", raising=False)
    monkeypatch.setattr(serenity_analysis.subprocess, "run", fake_run)

    assert serenity_analysis._call_openclaw_serenity_skill("prompt", 1) == "ok"
    assert captured["cmd"][captured["cmd"].index("--agent") + 1] == "main"
    assert "--model" not in captured["cmd"]


def test_async_ai_sends_cached_serenity_without_claim_or_generation(monkeypatch):
    import analysis
    import telegram_notifier

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
    audits = []
    monkeypatch.setattr(telegram_notifier, "append_signal_audit", lambda event: audits.append(event))
    monkeypatch.setattr(serenity_analysis, "read_serenity_cache_entry", lambda symbol: {
        "message": "cached-serenity",
        "age_seconds": 60,
    })
    monkeypatch.setattr(serenity_analysis, "claim_serenity_daily_slot", lambda symbol: (_ for _ in ()).throw(AssertionError("should not claim")))
    monkeypatch.setattr(serenity_analysis, "generate_serenity_analysis", lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not generate")))
    notifier = FakeNotifier()

    result = async_ai.process_ai_task(
        symbol="ABC",
        market="US",
        bot_notifier=notifier,
        price=10.0,
        score=1.0,
        backtest_str="(1/1)",
        rsi=50.0,
        volume_ratio=1.0,
    )

    assert result["status"] == "completed"
    serenity_msgs = [item for item in notifier.sent if item["kind"] == "serenity"]
    assert serenity_msgs == [{
        "kind": "serenity",
        "symbol": "ABC",
        "msg": "cached-serenity",
        "signal_id": None,
    }]
    assert any(event.get("event") == "serenity_cache_hit" for event in audits)
