#!/usr/bin/env python3
"""Import a systematic sample of the Open leaderboard.

The full crawl is 4,663 pages. This importer exists for the case where you
have a *sample* instead — pages drawn at even intervals across the whole
ranked field — and want real output from it today.

A systematic sample over rank is unbiased for exactly the quantities Splitline
publishes: medians, percentile positions, and rates. It is checked on import:
the share of the sample holding a valid score on each workout, multiplied by
the division's published entrant count, is compared against the largest rank
actually observed. Those two numbers are derived completely differently, so if
they agree the sample is representative. Disagreement beyond a couple of
per cent fails the import rather than quietly producing a wrong dataset.

Row format (pipe-delimited, tilde-separated), as emitted by the collector:

    age|height_cm|weight_kg|country_code|affiliate_id|overall_rank|
    wk1_rank|wk1_display|wk2_rank|wk2_display|wk3_rank|wk3_display|
    workouts_scored|all_scores_at_home_gym
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splitline import config, store  # noqa: E402
from splitline.sources.crossfit import _postprocess  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("import")

FIELDS = ["age", "height_cm", "weight_kg", "country_code", "affiliate_id",
          "overall_rank", "wk1_rank", "wk1_display", "wk2_rank", "wk2_display",
          "wk3_rank", "wk3_display", "workouts_scored", "all_home"]

DIVISIONS = {1: "Men", 2: "Women"}

# Enough of ISO-3166 to name the countries that actually field an Open
# population; anything else keeps its code rather than being guessed at.
COUNTRIES = {
    "US": "United States", "GB": "United Kingdom", "CA": "Canada",
    "AU": "Australia", "BR": "Brazil", "FR": "France", "DE": "Germany",
    "IT": "Italy", "ES": "Spain", "NL": "Netherlands", "SE": "Sweden",
    "NO": "Norway", "DK": "Denmark", "FI": "Finland", "IS": "Iceland",
    "IE": "Ireland", "NZ": "New Zealand", "JP": "Japan", "MX": "Mexico",
    "AR": "Argentina", "CL": "Chile", "CO": "Colombia", "PT": "Portugal",
    "BE": "Belgium", "CH": "Switzerland", "AT": "Austria", "PL": "Poland",
    "CZ": "Czechia", "RU": "Russia", "UA": "Ukraine", "ZA": "South Africa",
    "KR": "South Korea", "CN": "China", "IN": "India", "SG": "Singapore",
    "AE": "United Arab Emirates", "IL": "Israel", "TR": "Turkey",
    "GR": "Greece", "HU": "Hungary", "RO": "Romania", "PE": "Peru",
    "EC": "Ecuador", "UY": "Uruguay", "CR": "Costa Rica", "PA": "Panama",
    "DO": "Dominican Republic", "PR": "Puerto Rico", "HK": "Hong Kong",
    "MY": "Malaysia", "TH": "Thailand", "PH": "Philippines", "ID": "Indonesia",
    "SA": "Saudi Arabia", "QA": "Qatar", "KW": "Kuwait", "LU": "Luxembourg",
    "SK": "Slovakia", "SI": "Slovenia", "HR": "Croatia", "RS": "Serbia",
    "BG": "Bulgaria", "LT": "Lithuania", "LV": "Latvia", "EE": "Estonia",
}


def _num(s: str):
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_chunk(text: str, division: int) -> pd.DataFrame:
    recs = []
    for i, line in enumerate(text.split("~")):
        line = line.strip().strip('"')
        if not line or line.startswith("CHUNK:"):
            continue
        # Identity is the whole row. Overall rank is NOT unique — athletes who
        # posted no score are all tied at the bottom of the division, so
        # de-duplicating on rank would delete most of the people who quit and
        # silently bias every rate in the dataset upward.
        row_id = hashlib.blake2b(line.encode(), digest_size=8).hexdigest()
        parts = line.split("|")
        if len(parts) < len(FIELDS):
            parts += [""] * (len(FIELDS) - len(parts))
        d = dict(zip(FIELDS, parts))
        cc = d["country_code"].strip().upper()
        recs.append({
            "year": config.CF_YEAR,
            "division_id": division,
            "division": DIVISIONS.get(division, str(division)),
            "competitor_id": f"{division}-{row_id}",
            "gender": "M" if division == 1 else "F",
            "age": _num(d["age"]),
            "height_cm": _num(d["height_cm"]),
            "weight_kg": _num(d["weight_kg"]),
            "country": COUNTRIES.get(cc, cc),
            "region": "",
            "affiliate_id": d["affiliate_id"].strip(),
            # Affiliate names are not carried in the sample, so the
            # affiliate angle self-skips rather than printing meaningless ids.
            "affiliate": "",
            "status": "ACT",
            "overall_rank": _num(d["overall_rank"]),
            "wk1_rank": _num(d["wk1_rank"]),
            "wk2_rank": _num(d["wk2_rank"]),
            "wk3_rank": _num(d["wk3_rank"]),
            "wk1_display": d["wk1_display"].strip(),
            "wk2_display": d["wk2_display"].strip(),
            "wk3_display": d["wk3_display"].strip(),
            "workouts_scored": int(_num(d["workouts_scored"]) or 0),
        })
    return pd.DataFrame(recs)


def validate(df: pd.DataFrame, division: int, entrants: int,
             tolerance: float = 0.04) -> list[str]:
    """Cross-check the sample against a number derived a different way."""
    notes = []
    sub = df[df["division_id"] == division]
    n = len(sub)
    for wk in ("wk1", "wk2", "wk3"):
        scored = sub[f"{wk}_rank"].notna()
        if not scored.any():
            continue
        est = scored.mean() * entrants
        seen = float(sub.loc[scored, f"{wk}_rank"].max())
        rel = abs(est - seen) / max(seen, 1)
        status = "ok" if rel <= tolerance else "FAIL"
        notes.append(
            f"    {wk}: estimated field {est:,.0f} vs largest rank observed "
            f"{seen:,.0f}  ({rel * 100:.2f}% apart) [{status}]"
        )
        if rel > tolerance:
            raise SystemExit(
                f"sample validation failed for division {division} {wk}: "
                f"{rel * 100:.1f}% apart, above the {tolerance * 100:.0f}% tolerance"
            )
    return notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunks", nargs="+", required=True,
                    help="files holding the collector output, in the form "
                         "DIVISION:PATH (e.g. 1:d1a.txt 1:d1b.txt 2:d2a.txt)")
    ap.add_argument("--entrants", nargs="+", required=True,
                    help="DIVISION:COUNT from the leaderboard's own pagination "
                         "(e.g. 1:127113 2:105959)")
    ap.add_argument("--year", type=int, default=config.CF_YEAR)
    args = ap.parse_args()

    entrants = {int(x.split(":")[0]): int(x.split(":")[1]) for x in args.entrants}

    frames = []
    for spec in args.chunks:
        div, path = spec.split(":", 1)
        div = int(div)
        raw = Path(path).read_text()
        if path.endswith(".txt") and raw.lstrip().startswith("["):
            payload = "".join(part.get("text", "") for part in json.loads(raw))
        else:
            payload = raw
        frame = parse_chunk(payload, div)
        log.info("%s -> %s rows (division %s)", os.path.basename(path),
                 f"{len(frame):,}", div)
        frames.append(frame)

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["competitor_id"])
    df = _postprocess(df)

    log.info("sample validation:")
    for div, n in entrants.items():
        for line in validate(df, div, n):
            log.info("%s", line)

    finishers = int((df["workouts_scored"] >= 3).sum())
    log.info("%s sampled athletes, %s finishers", f"{len(df):,}", f"{finishers:,}")

    store.save(df, args.year)
    (config.DATA / f"open_{args.year}.SAMPLE.json").write_text(json.dumps({
        "kind": "systematic sample",
        "sampled_athletes": int(len(df)),
        "sampled_finishers": finishers,
        "entrants_by_division": entrants,
        "total_entrants": int(sum(entrants.values())),
        "note": "Pages drawn at even intervals across the full ranked field. "
                "Unbiased for medians, percentile positions and rates; not a "
                "complete census.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
