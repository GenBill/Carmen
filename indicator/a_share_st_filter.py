"""A-share ST / delisting filters shared by scanners and alert queues."""
from __future__ import annotations

from typing import Any


ST_NAME_PREFIXES = ("ST", "*ST", "S*ST", "退市")


def normalize_a_share_name(name: Any) -> str:
    return (
        str(name or "")
        .strip()
        .replace(" ", "")
        .replace("\u3000", "")
        .upper()
    )


def is_st_or_delisting_name(name: Any) -> bool:
    normalized = normalize_a_share_name(name)
    if not normalized:
        return False
    return normalized.startswith(ST_NAME_PREFIXES)
