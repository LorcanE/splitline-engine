#!/usr/bin/env python3
"""Build the HYROX Pacing Plan from collected race splits."""
from __future__ import annotations

import argparse, logging, sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from splitline import config  # noqa: E402
from splitline.product import pacing  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")

COLS = pacing.ORDER + ["roxzone", "total"]


def load(path: Path) -> pd.DataFrame:
    rows = [l.split("|") for l in path.read_text().splitlines() if l.strip()]
    return pd.DataFrame([
        {"age_group": r[1], "nation": r[2],
         **{k: (float(v) if v not in ("", "None") else np.nan)
            for k, v in zip(COLS, r[4:])}}
        for r in rows
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--men", required=True)
    ap.add_argument("--women", default="")
    ap.add_argument("--race", required=True, help="race label for the method sheet")
    ap.add_argument("--out", default="dist/splitline-hyrox-pacing-plan.xlsx")
    args = ap.parse_args()

    men = load(Path(args.men))
    women = load(Path(args.women)) if args.women else None
    out = pacing.build(men, Path(args.out), args.race, df_women=women)
    logging.info("built %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
