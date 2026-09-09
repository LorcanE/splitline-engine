#!/usr/bin/env python3
"""Build the paid product from the cached dataset.

Refuses to build from a preview/synthetic dataset unless --allow-preview is
passed, and stamps any preview build so it can never be mistaken for the real
thing or sold by accident.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splitline import config, store  # noqa: E402
from splitline.product import workbook  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("product")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=config.CF_YEAR)
    ap.add_argument("--allow-preview", action="store_true",
                    help="permit building from synthetic data (watermarked)")
    args = ap.parse_args()

    df = store.load(args.year)
    synthetic = bool(getattr(df, "attrs", {}).get("synthetic")) or \
        (config.DATA / f"open_{args.year}.SYNTHETIC").exists()

    if synthetic and not args.allow_preview:
        log.error(
            "dataset for %s is synthetic preview data. Run a real ingest "
            "(`python scripts/ingest.py --year %s`) before building a product "
            "for sale, or pass --allow-preview to build a watermarked sample.",
            args.year, args.year,
        )
        return 1

    suffix = "-PREVIEW-SYNTHETIC" if synthetic else ""
    sample = store.sample_meta(args.year)
    out = config.DIST / f"splitline-open-benchmark-workbook-{args.year}{suffix}.xlsx"
    workbook.build(df, args.year, out, sample=store.sample_meta(args.year))

    manifest = {
        "product": "Splitline Open Benchmark Workbook",
        "year": args.year,
        "built": date.today().isoformat(),
        "rows": int(len(df)),
        "synthetic_preview": synthetic,
        "sampled": bool(sample),
        "file": out.name,
        "bytes": out.stat().st_size,
    }
    (config.DIST / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    log.info("built %s (%.0f KB)%s", out.name, out.stat().st_size / 1024,
             "  ** SYNTHETIC PREVIEW **" if synthetic else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
