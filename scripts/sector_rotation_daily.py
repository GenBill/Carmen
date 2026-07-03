#!/usr/bin/env python3
"""Daily sector rotation OpenClaw report (A / HK / US).

Crontab examples (Asia/Shanghai)::

    0 10 * * 1-5 /home/serv/Carmen/scripts/cron_us_sector_rotation.sh
    0 16 * * 1-5 /home/serv/Carmen/scripts/cron_a_share_sector_rotation.sh
    0 17 * * 1-5 /home/serv/Carmen/scripts/cron_hk_sector_rotation.sh
"""
from __future__ import annotations

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDICATOR_DIR = os.path.join(BASE_DIR, "indicator")
if INDICATOR_DIR not in sys.path:
    sys.path.insert(0, INDICATOR_DIR)

from sector_rotation import run_daily_sector_rotation_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run daily sector rotation OpenClaw report.")
    parser.add_argument(
        "--market",
        choices=["A", "HK", "US"],
        default="A",
        help="Market to report (default: A)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print OpenClaw prompt only.")
    parser.add_argument("--force", action="store_true", help="Ignore daily dedup state.")
    args = parser.parse_args()

    ok = run_daily_sector_rotation_report(
        args.market,
        force=args.force,
        dry_run=args.dry_run,
    )
    return 0 if ok or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
