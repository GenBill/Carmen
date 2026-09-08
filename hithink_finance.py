"""同花顺金融数据服务的 Carmen 统一客户端。"""
from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, time as datetime_time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

import requests


BASE_URL = "https://fuyao.aicubes.cn"
LEGACY_TOKEN_FILE = Path(__file__).resolve().parent / "agent" / "hithink_finance.token"


class HithinkFinanceError(RuntimeError):
    """同花顺 API 请求或业务信封错误。"""


def normalize_thscode(symbol: str) -> str:
    """将 Carmen/Yahoo 股票代码转换为同花顺 thscode。"""
    value = str(symbol or "").strip().upper()
    if value.endswith(".SS"):
        value = value[:-3] + ".SH"
    if value.endswith((".SH", ".SZ", ".BJ")):
        code, suffix = value.rsplit(".", 1)
        if len(code) == 6 and code.isdigit():
            return f"{code}.{suffix}"
        raise ValueError(f"无效 A 股代码: {symbol}")
    if len(value) != 6 or not value.isdigit():
        raise ValueError(f"无效 A 股代码: {symbol}")
    if value.startswith(("0", "3")):
        return f"{value}.SZ"
    if value.startswith(("4", "8", "9")):
        return f"{value}.BJ"
    return f"{value}.SH"


def load_api_key() -> str:
    """按官方统一凭据顺序读取 API Key。"""
    for name in ("HITHINK_FINANCE_API_KEY", "FUYAO_TOKEN", "API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value

    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    credentials_file = config_home / "hithink-finance" / "credentials.env"
    try:
        lines = credentials_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "HITHINK_FINANCE_API_KEY":
            value = value.strip().strip("'\"")
            if value:
                return value

    # 仅用于无中断迁移旧部署；新凭据只写用户级 credentials.env。
    try:
        value = LEGACY_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if value:
        return value
    raise HithinkFinanceError(
        "缺少同花顺 API Key：请设置 HITHINK_FINANCE_API_KEY 或用户级 credentials.env"
    )


def _date_ms(value: date | datetime | int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.combine(value, datetime_time.min, tzinfo=ZoneInfo("Asia/Shanghai"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return int(dt.timestamp() * 1000)


class HithinkFinanceClient:
    """小规模候选股查询客户端；全局串行节流并对瞬时故障退避。"""

    _rate_lock = threading.Lock()
    _last_request_at = 0.0

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        session: Optional[requests.Session] = None,
        timeout: float = 15.0,
        min_interval: float = 1.0,
        max_attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key or load_api_key()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.min_interval = max(0.0, float(min_interval))
        self.max_attempts = max(1, int(max_attempts))
        self.sleep = sleep

    def _throttle(self) -> None:
        with self._rate_lock:
            now = time.monotonic()
            wait = self.min_interval - (now - type(self)._last_request_at)
            if wait > 0:
                self.sleep(wait)
            type(self)._last_request_at = time.monotonic()

    def request(self, path: str, *, params: Optional[dict] = None) -> dict:
        last_error: Optional[Exception] = None
        for attempt in range(self.max_attempts):
            self._throttle()
            try:
                response = self.session.get(
                    f"{BASE_URL}{path}",
                    params=params or {},
                    headers={
                        "X-api-key": self.api_key,
                        "User-Agent": "Carmen/HiThink-Finance",
                    },
                    timeout=self.timeout,
                )
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                last_error = exc
                retryable = True
            else:
                code = payload.get("code")
                retryable = response.status_code == 429 or response.status_code >= 500
                retryable = retryable or code in {4001, 5001, 5002, 5003, 429}
                if response.status_code == 200 and code == 0:
                    data = payload.get("data")
                    return data if isinstance(data, dict) else {}
                request_id = payload.get("request_id") or "-"
                last_error = HithinkFinanceError(
                    f"同花顺 API 失败: http={response.status_code}, code={code}, "
                    f"message={payload.get('message')}, request_id={request_id}"
                )
            if not retryable or attempt + 1 >= self.max_attempts:
                break
            self.sleep(float(2**attempt))
        if isinstance(last_error, HithinkFinanceError):
            raise last_error
        raise HithinkFinanceError(f"同花顺 API 网络请求失败: {last_error}") from last_error

    @staticmethod
    def _codes(symbols: Iterable[str]) -> str:
        codes = [normalize_thscode(symbol) for symbol in symbols]
        if not codes:
            raise ValueError("股票代码列表为空")
        return ",".join(dict.fromkeys(codes))

    def get_snapshot(self, symbols: Iterable[str]) -> list[dict]:
        data = self.request(
            "/api/a-share/prices/snapshot",
            params={"thscodes": self._codes(symbols)},
        )
        return list(data.get("item") or [])

    def get_auction_snapshot(
        self, symbols: Iterable[str], *, stage: str = "final"
    ) -> list[dict]:
        data = self.request(
            "/api/a-share/auction/snapshot",
            params={"thscodes": self._codes(symbols), "stage": stage},
        )
        return list(data.get("item") or [])

    def get_turnover_pct(self, symbol: str) -> Optional[float]:
        thscode = normalize_thscode(symbol)
        prices = self.get_snapshot([thscode])
        auctions = self.get_auction_snapshot([thscode])
        if not prices or not auctions:
            return None
        price_item = prices[0]
        auction_item = auctions[0]
        try:
            volume = float(price_item["volume"])
            last_price = float(price_item["last_price"])
            float_market_cap = float(auction_item["float_market_cap"])
        except (KeyError, TypeError, ValueError):
            return None
        if volume < 0 or last_price <= 0 or float_market_cap <= 0:
            return None
        return volume * last_price / float_market_cap * 100.0

    def get_historical(
        self,
        symbol: str,
        *,
        start: date | datetime | int,
        end: date | datetime | int,
        adjust: str = "forward",
    ) -> list[dict]:
        data = self.request(
            "/api/a-share/prices/historical",
            params={
                "thscode": normalize_thscode(symbol),
                "interval": "1d",
                "start": _date_ms(start),
                "end": _date_ms(end),
                "adjust": adjust,
                "offset": 0,
            },
        )
        return list(data.get("item") or [])

    def get_valuations(self, symbols: Iterable[str]) -> list[dict]:
        data = self.request(
            "/api/a-share/valuations/snapshot",
            params={"thscodes": self._codes(symbols)},
        )
        return list(data.get("item") or [])

    def get_income_statements(
        self, symbol: str, *, period: str = "quarterly", limit: int = 1
    ) -> list[dict]:
        data = self.request(
            "/api/a-share/financials/income-statements",
            params={
                "thscode": normalize_thscode(symbol),
                "period": period,
                "limit": limit,
            },
        )
        return list(data.get("item") or [])

    def get_financial_indicators(self, symbol: str, report: str) -> dict:
        return self.request(
            "/api/a-share/financials/indicators",
            params={"thscode": normalize_thscode(symbol), "report": report},
        )


_DEFAULT_CLIENT: Optional[HithinkFinanceClient] = None
_DEFAULT_CLIENT_LOCK = threading.Lock()


def get_hithink_client() -> HithinkFinanceClient:
    global _DEFAULT_CLIENT
    with _DEFAULT_CLIENT_LOCK:
        if _DEFAULT_CLIENT is None:
            _DEFAULT_CLIENT = HithinkFinanceClient()
        return _DEFAULT_CLIENT