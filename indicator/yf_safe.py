"""Thread-safe yfinance access for Carmen.

`yfinance.download()` uses module-level shared state in `yfinance.shared` while
assembling multi-ticker results. Calling it concurrently from the scan thread and
AI/backtest worker threads can cross-contaminate ticker data (observed: VELO data
persisted under VERA cache). Route every in-process download through one lock.
"""
from __future__ import annotations

from threading import RLock
from typing import Any

import yfinance as yf

_YF_DOWNLOAD_LOCK = RLock()


def yf_download(*args: Any, **kwargs: Any):
    """Serialize all yfinance downloads in this process."""
    with _YF_DOWNLOAD_LOCK:
        return yf.download(*args, **kwargs)
