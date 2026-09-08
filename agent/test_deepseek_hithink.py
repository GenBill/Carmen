from __future__ import annotations

from agent import deepseek


class FakeHithinkClient:
    def __init__(self, turnover):
        self.turnover = turnover
        self.symbols = []

    def get_turnover_pct(self, symbol):
        self.symbols.append(symbol)
        return self.turnover


class FakeComprehensiveClient:
    def get_snapshot(self, symbols):
        return [
            {
                "thscode": "600519.SH",
                "ticker": "600519",
                "last_price": 1316.01,
                "price_change_ratio_pct": -1.05188,
            }
        ]

    def get_turnover_pct(self, symbol):
        return 0.201999

    def get_valuations(self, symbols):
        return [
            {
                "thscode": "600519.SH",
                "name": "贵州茅台",
                "pe_ttm": 20.201884,
                "pb_mrq": 6.547647,
            }
        ]

    def get_income_statements(self, symbol, *, period, limit):
        assert period == "quarterly"
        assert limit == 1
        return [{"fiscal_year": 2026, "fiscal_period": "H1"}]

    def get_financial_indicators(self, symbol, report):
        assert report == "2026-2"
        return {
            "abilities": [
                {
                    "ability": "growth",
                    "indicators": [
                        {
                            "index_id": "calculate_operating_income_yoy_growth_ratio",
                            "value": "8.25",
                        }
                    ],
                },
                {
                    "ability": "profitability",
                    "indicators": [
                        {"index_id": "index_weighted_avg_roe", "value": "31.50"}
                    ],
                },
            ]
        }


def test_fetch_a_share_turnover_rate_uses_hithink(monkeypatch):
    client = FakeHithinkClient(3.456789)
    monkeypatch.setattr(deepseek, "get_hithink_client", lambda: client)

    assert deepseek.fetch_a_share_turnover_rate("600519") == 3.4568
    assert client.symbols == ["600519"]


def test_fetch_a_share_turnover_rate_returns_none_on_hithink_failure(monkeypatch):
    def fail():
        raise RuntimeError("temporary API error")

    monkeypatch.setattr(deepseek, "get_hithink_client", fail)

    assert deepseek.fetch_a_share_turnover_rate("600519") is None


def test_fetch_a_share_data_maps_hithink_market_valuation_and_financials(monkeypatch):
    monkeypatch.setattr(
        deepseek, "get_hithink_client", lambda: FakeComprehensiveClient()
    )

    result = deepseek.fetch_a_share_data("600519")

    assert result == {
        "代码": "600519",
        "名称": "贵州茅台",
        "最新价": 1316.01,
        "涨跌幅": -1.05188,
        "换手率": 0.202,
        "量比": "N/A",
        "ROE": 31.5,
        "PE": 20.201884,
        "PB": 6.547647,
        "营收同比增长": 8.25,
        "行业": "N/A",
        "股东户数": "N/A",
        "概念": [],
        "最新预告": "N/A",
    }