#!/usr/bin/env python3
"""Crawl HYROX race results into the store.

    python scripts/ingest_hyrox.py --season 8 --event H_LR3MS4JI13EE --sample 400

Splits live on per-athlete detail pages, so budget one request per athlete.
`--sample` takes a systematic sample down the finishing order instead of the
whole field, which is unbiased for split percentiles and far cheaper.
"""
from __future__ import annotations

import argparse, logging, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from splitline import config  # noqa: E402
from splitline.sources import hyrox  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=8)
    ap.add_argument("--event", required=True, help="event id, e.g. H_LR3MS4JI13EE")
    ap.add_argument("--sexes", default="M,W")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--delay", type=float, default=0.25)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    df = hyrox.fetch_event(args.season, args.event,
                           sexes=[s for s in args.sexes.split(",") if s],
                           sample=args.sample, delay=args.delay)
    out = Path(args.out) if args.out else config.DATA / f"hyrox_{args.season}_{args.event}.csv.gz"
    df.to_csv(out, index=False, compression="gzip")
    logging.info("%s athletes -> %s", f"{len(df):,}", out.name)
    if "roxzone_share" in df:
        logging.info("median roxzone share: %.1f%% of race time",
                     100 * df["roxzone_share"].median())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
