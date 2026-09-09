#!/usr/bin/env python3
"""Weekly HYROX run. Same gate, same renderer, same delivery as the Open run.

    python scripts/run_hyrox.py --men data/..._men_raw.txt \
        --women data/..._women_raw.txt --race "2026 HYROX Beijing" --dry-run
"""
from __future__ import annotations

import argparse, json, logging, shutil, sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from splitline import config, store  # noqa: E402
from splitline.analysis import hyrox_angles as ha  # noqa: E402
from splitline.deliver import deliver_all  # noqa: E402
from splitline.product import pacing  # noqa: E402
from splitline.render import charts  # noqa: E402
from splitline.render import post as render_post  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("hyrox")

COLS = pacing.ORDER + ["roxzone", "total"]


def load(path: Path, sex: str) -> pd.DataFrame:
    rows = [l.split("|") for l in path.read_text().splitlines() if l.strip()]
    df = pd.DataFrame([
        {"age_group": r[1], "nation": r[2],
         **{k: (float(v) if v not in ("", "None") else np.nan)
            for k, v in zip(COLS, r[4:])}}
        for r in rows
    ])
    df["sex"] = sex
    return pacing.clean(df)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--men", required=True)
    ap.add_argument("--women", default="")
    ap.add_argument("--race", required=True)
    ap.add_argument("--angle", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    frames = [load(Path(args.men), "M")]
    if args.women:
        frames.append(load(Path(args.women), "W"))
    df = pd.concat(frames, ignore_index=True)
    log.info("%s clean finishers from %s", f"{len(df):,}", args.race)

    note = (f"Method: computed from the published split tables of {len(df):,} "
            f"finishers at {args.race}. An athlete is included only if their "
            f"sixteen splits plus roxzone reconstruct their published finish "
            f"time to within 2%.")

    charts.set_source(f"HYROX race results, {args.race}")

    work = config.POSTS / f"{date.today():%Y-%m-%d}"
    used = set(store.used_angles())
    order = ([args.angle] if args.angle
             else [a for a in ha.ORDER_LIST if f"hyrox:{a}" not in used]
                  or list(ha.ORDER_LIST))

    attempts, chosen = [], None
    for slug in order:
        out = work / slug
        out.mkdir(parents=True, exist_ok=True)
        finding = ha.run_angle(slug, df, out)
        ok, why = finding.publishable(config.MIN_SAMPLE, config.MIN_EFFECT)
        attempts.append({"angle": slug, "ok": ok, "reason": why,
                         "n": finding.n, "effect": round(finding.effect, 4)})
        log.info("angle %-12s %s (n=%s, effect=%.3f) %s", slug,
                 "PASS" if ok else "gate", f"{finding.n:,}", finding.effect,
                 "" if ok else f"- {why}")
        if ok:
            chosen = finding
            break
        shutil.rmtree(out, ignore_errors=True)

    if chosen is None:
        log.warning("no HYROX angle cleared the gate")
        return 2

    post_dir = work / chosen.slug
    meta = render_post.render(chosen, post_dir, note,
                              source="the public HYROX race results at "
                                     "results.hyrox.com")
    log.info("rendered: %s", meta["title"])

    if args.dry_run:
        log.info("dry run - not delivering")
        return 0

    for r in deliver_all(meta, post_dir):
        log.info("delivery [%s] ok=%s %s", r["channel"], r["ok"], r.get("detail", ""))
    store.mark_used(f"hyrox:{chosen.slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
