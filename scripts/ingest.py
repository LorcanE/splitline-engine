#!/usr/bin/env python3
"""Crawl the Open leaderboard into the parquet store.

    python scripts/ingest.py --probe              # field sizes, one request
    python scripts/ingest.py --max-pages 5        # cheap smoke test
    python scripts/ingest.py                      # full ingest
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splitline import config, store  # noqa: E402
from splitline.sources import crossfit  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=config.CF_YEAR)
    ap.add_argument("--divisions", default=None,
                    help="comma separated division ids (default from config)")
    ap.add_argument("--max-pages", type=int, default=config.MAX_PAGES)
    ap.add_argument("--probe", action="store_true",
                    help="report field sizes without crawling")
    args = ap.parse_args()

    divisions = ([int(x) for x in args.divisions.split(",")]
                 if args.divisions else config.CF_DEFAULT_DIVISIONS)

    if args.probe:
        out = [crossfit.probe(args.year, d) for d in divisions]
        print(json.dumps(out, indent=2))
        total = sum(p["total_competitors"] for p in out)
        pages = sum(p["total_pages"] for p in out)
        est = pages * (config.REQUEST_DELAY_S + 0.35) / 60
        log.info("%s athletes over %s pages — roughly %.0f min to crawl",
                 f"{total:,}", f"{pages:,}", est)
        return 0

    df = crossfit.fetch(args.year, divisions, max_pages=args.max_pages)
    path = store.save(df, args.year)
    log.info("%s rows -> %s", f"{len(df):,}", path)
    log.info("finishers: %s", f"{int((df['workouts_scored'] >= 3).sum()):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
