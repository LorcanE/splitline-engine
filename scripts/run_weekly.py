#!/usr/bin/env python3
"""The weekly run. This is what the cron calls.

  1. make sure a dataset exists (ingest if missing or stale)
  2. walk the story bank until an angle clears the publish gate
  3. render the post and its charts
  4. deliver it (beehiiv if the plan allows, email always)
  5. write a run summary so a failed week is visible, not silent

Exit code is 0 for "a post was produced", 2 for "nothing cleared the gate",
1 for a hard failure. GitHub Actions surfaces all three differently.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splitline import config, store  # noqa: E402
from splitline.analysis import angles  # noqa: E402
from splitline.deliver import deliver_all  # noqa: E402
from splitline.render import post as render_post  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("weekly")


def ensure_data(year: int, refresh: bool, max_pages: int, max_age_days: float):
    if refresh or not store.exists(year) or store.age_days(year) > max_age_days:
        from splitline.sources import crossfit
        log.info("ingesting %s (refresh=%s, cached age=%.1f days)",
                 year, refresh, store.age_days(year))
        df = crossfit.fetch(year, config.CF_DEFAULT_DIVISIONS, max_pages=max_pages)
        store.save(df, year)
        return df
    log.info("using cached dataset for %s (%.1f days old)", year, store.age_days(year))
    return store.load(year)


def choose_angle(df, work_dir: Path, forced: str | None):
    """Walk the bank in order, skipping used angles, until one clears."""
    used = set(store.used_angles())
    order = [forced] if forced else [a for a in angles.ORDER if a not in used]
    if not order:
        log.info("every angle has been used — cycling the bank")
        store.reset_angles()
        order = list(angles.ORDER)

    attempts = []
    for slug in order:
        log.info("evaluating angle: %s", slug)
        out = work_dir / slug
        out.mkdir(parents=True, exist_ok=True)
        finding = angles.run_angle(slug, df, out)
        ok, why = finding.publishable(config.MIN_SAMPLE, config.MIN_EFFECT)
        attempts.append({"angle": slug, "ok": ok, "reason": why,
                         "n": finding.n, "effect": round(finding.effect, 4)})
        if ok:
            log.info("angle %s cleared the gate (n=%s, effect=%.3f)",
                     slug, finding.n, finding.effect)
            return finding, attempts
        log.info("angle %s rejected: %s", slug, why)
        shutil.rmtree(out, ignore_errors=True)
    return None, attempts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=config.CF_YEAR)
    ap.add_argument("--angle", default=None, help="force a specific angle slug")
    ap.add_argument("--refresh-data", action="store_true")
    ap.add_argument("--max-pages", type=int, default=config.MAX_PAGES)
    ap.add_argument("--max-age-days", type=float, default=30.0,
                    help="re-ingest if the cached dataset is older than this")
    ap.add_argument("--dry-run", action="store_true",
                    help="render but do not deliver or mark the angle used")
    args = ap.parse_args()

    started = datetime.now(timezone.utc)
    summary: dict = {"started": started.isoformat(timespec="seconds"),
                     "year": args.year, "dry_run": args.dry_run}

    try:
        df = ensure_data(args.year, args.refresh_data, args.max_pages,
                         args.max_age_days)
    except Exception as exc:  # noqa: BLE001
        log.exception("ingest failed")
        summary |= {"ok": False, "stage": "ingest", "error": str(exc)}
        _write_summary(summary)
        return 1

    summary["rows"] = int(len(df))

    # A sampled dataset must never report sample tallies as field counts.
    sample = store.sample_meta(args.year)
    dataset_note = ""
    if sample:
        angles.set_population(sample["sampled_athletes"], sample["total_entrants"])
        dataset_note = (
            f"Method: figures are computed from a systematic sample of "
            f"{sample['sampled_athletes']:,} athletes drawn at even intervals "
            f"across the full ranked field of {sample['total_entrants']:,} "
            f"2026 Open entrants. Rates, medians and percentiles estimate the "
            f"whole field directly; athlete counts are scaled estimates and are "
            f"marked as approximate."
        )
        log.info("sampled dataset: scaling counts by %.1fx", angles.SCALE)
    else:
        angles.set_population(0, 0)
    summary["sampled"] = bool(sample)
    work = config.POSTS / f"{date.today():%Y-%m-%d}"
    work.mkdir(parents=True, exist_ok=True)

    finding, attempts = choose_angle(df, work, args.angle)
    summary["attempts"] = attempts

    if finding is None:
        log.warning("no angle cleared the publish gate this week")
        summary |= {"ok": False, "stage": "editorial",
                    "error": "no angle cleared the gate"}
        _write_summary(summary)
        return 2

    post_dir = work / finding.slug
    meta = render_post.render(finding, post_dir, dataset_note)
    summary |= {"slug": finding.slug, "title": meta["title"],
                "n": meta["n"], "effect": meta["effect"],
                "post_dir": str(post_dir.relative_to(config.ROOT))}
    log.info("rendered: %s", meta["title"])

    if args.dry_run:
        log.info("dry run — not delivering, not marking the angle used")
        summary |= {"ok": True, "delivered": [], "stage": "dry-run"}
        _write_summary(summary)
        return 0

    results = deliver_all(meta, post_dir)
    for r in results:
        log.info("delivery [%s] ok=%s %s", r["channel"], r["ok"], r.get("detail", ""))
    store.mark_used(finding.slug)

    summary |= {"ok": True, "delivered": results, "stage": "done",
                "finished": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _write_summary(summary)
    return 0


def _write_summary(summary: dict) -> None:
    p = config.STATE / "last_run.json"
    p.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    # GitHub Actions job summary — makes a failed week visible at a glance.
    import os
    if gh := os.environ.get("GITHUB_STEP_SUMMARY"):
        lines = ["## Splitline weekly run", ""]
        if summary.get("ok"):
            lines += [
                f"**{summary.get('title', '—')}**", "",
                f"- angle: `{summary.get('slug', '—')}`",
                f"- sample: {summary.get('n', 0):,} athletes",
                f"- effect: {summary.get('effect', 0)}",
                f"- rows in dataset: {summary.get('rows', 0):,}",
                "",
            ]
            for d in summary.get("delivered", []):
                mark = "✅" if d.get("ok") else ("⏭️" if d.get("skipped") else "❌")
                lines.append(f"- {mark} **{d['channel']}** — {d.get('detail', '')}")
        else:
            lines += [f"**No post this week** — {summary.get('error', 'unknown')}", ""]
            for a in summary.get("attempts", []):
                lines.append(f"- `{a['angle']}` — {a['reason']}")
        with open(gh, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
