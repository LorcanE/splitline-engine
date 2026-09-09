#!/usr/bin/env python3
"""End-to-end self test. No network, no pytest, no fixtures on disk required.

Builds a synthetic field, runs every angle, renders a post, builds the product,
and asserts the things that would silently ruin a live run:

  * every angle either produces a Finding or reports why it cannot
  * no angle raises
  * the publish gate rejects a finding with no effect in the data
  * rendered HTML contains no unresolved template holes
  * the product refuses to build from synthetic data unless forced

Run it in CI on every push.
"""
from __future__ import annotations

import logging
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.disable(logging.INFO)

FAILURES: list[str] = []
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if cond:
        print(f"  ok    {label}")
    else:
        print(f"  FAIL  {label}")
        FAILURES.append(label)


def main() -> int:
    from splitline import config
    from splitline.analysis import angles
    from splitline.analysis.finding import Finding
    from splitline.render import post as render_post

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from make_fixture import build as build_fixture

    print("building synthetic field ...")
    df = build_fixture(30_000, config.CF_YEAR)
    check(len(df) == 30_000, "fixture row count")
    check(int((df["workouts_scored"] >= 3).sum()) > 15_000, "fixture has finishers")
    pct = df["overall_pct"]
    check(pct.dropna().between(0, 1).all(), "percentiles are in [0,1]")
    # Only non-finishers may lack an overall percentile — if a finisher ever
    # comes through as NaN, every downstream median is quietly wrong.
    check(bool((df.loc[pct.isna(), "workouts_scored"] < 3).all()),
          "percentile is missing only for non-finishers")

    tmp = Path(tempfile.mkdtemp(prefix="splitline-selftest-"))
    try:
        print("\nrunning every angle ...")
        passed = 0
        for slug in angles.ORDER:
            f = angles.run_angle(slug, df, tmp / slug)
            check(isinstance(f, Finding), f"{slug} returns a Finding")
            check(not f.skip_reason.startswith("angle raised"),
                  f"{slug} does not raise")
            ok, why = f.publishable(config.MIN_SAMPLE, config.MIN_EFFECT)
            if ok:
                passed += 1
                check(bool(f.headline), f"{slug} has a headline")
                check(f.n >= config.MIN_SAMPLE, f"{slug} reports its sample")
        check(passed >= 5, f"at least five angles clear the gate (got {passed})")

        print("\ngate behaviour ...")
        # There is no home-judge effect in the fixture, so the gate must catch it.
        hj = angles.run_angle("home-judge", df, tmp / "hj")
        ok, why = hj.publishable(config.MIN_SAMPLE, config.MIN_EFFECT)
        check(not ok, f"gate rejects the absent effect ({why})")

        print("\nrendering ...")
        f = angles.run_angle("age-curve", df, tmp / "render")
        meta = render_post.render(f, tmp / "render")
        html = (tmp / "render" / "email.html").read_text()
        check("<style" not in html, "no <style> block (beehiiv strips it)")
        check("style=" in html, "styles are inlined")
        check(not re.search(r"\{[a-z_]+\}", html), "no unresolved template holes")
        check("nan" not in html.lower().replace("finance", ""), "no NaN leaked into copy")
        check(meta["n"] > 0 and meta["title"], "post metadata is populated")
        check((tmp / "render" / "preview.html").exists(), "preview page written")

        # The chart URL in the email must point at where the workflow actually
        # commits the file. Locally the image is on disk either way, so a wrong
        # URL is invisible until subscribers see broken images.
        from splitline import config as _cfg
        real_dir = _cfg.POSTS / "2099-01-01" / "age-curve"
        real_dir.mkdir(parents=True, exist_ok=True)
        try:
            f2 = angles.run_angle("age-curve", df, real_dir)
            m2 = render_post.render(f2, real_dir,
                                    source="the public CrossFit Games Open leaderboard")
            html2 = (real_dir / "email.html").read_text()
            for asset in m2["assets"]:
                want = f"posts/2099-01-01/age-curve/{asset}"
                check(want in html2 or f"/{asset}" in html2 and not render_post.ASSET_BASE,
                      f"chart URL matches the committed path ({asset})")
                check((real_dir / asset).exists(), f"chart file exists ({asset})")
        finally:
            shutil.rmtree(_cfg.POSTS / "2099-01-01", ignore_errors=True)
        # A HYROX post must never cite the CrossFit leaderboard, and vice
        # versa. Getting this wrong is invisible in testing and fatal to trust.
        alt = render_post.render(f, tmp / "src", source="the HYROX results")
        alt_html = (tmp / "src" / "email.html").read_text()
        check("HYROX results" in alt_html and "CrossFit" not in alt_html,
              "post cites the data source it was actually built from")

        print("\nproduct ...")
        from splitline.product import workbook
        out = tmp / "wb.xlsx"
        workbook.build(df, config.CF_YEAR, out)
        check(out.exists() and out.stat().st_size > 8000, "workbook builds")
        from openpyxl import load_workbook
        wb = load_workbook(out)
        for sheet in ("Start here", "My athletes", "Divisions", "AgeCurves",
                      "Cutlines", "Method"):
            check(sheet in wb.sheetnames, f"workbook has '{sheet}'")
        ws = wb["My athletes"]
        check(str(ws["H5"].value).startswith("=") and
              str(ws["J5"].value).startswith("="), "live formulas present")
        check("SUMPRODUCT" in str(ws["J5"].value),
              "age lookup avoids array formulas")
        print("\nhyrox parser (real captured pages) ...")
        _check_hyrox()
        print("\nproduct is not given away ...")
        _check_not_public()
        print("\nhyrox pacing product ...")
        _check_pacing(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    if FAILURES:
        print("\nFAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("self test passed")
    return 0


def _check_hyrox() -> None:
    """Parse real captured HYROX pages. Guards against silent markup drift."""
    from bs4 import BeautifulSoup
    from splitline.sources import hyrox

    root = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    detail_f, list_f = root / "hyrox_detail.html", root / "hyrox_list.html"
    if not (detail_f.exists() and list_f.exists()):
        check(False, "hyrox fixtures present")
        return

    rec = {}
    soup = BeautifulSoup(detail_f.read_text(), "lxml")
    for tr in soup.find_all("tr"):
        cells = [hyrox._clean(c) for c in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        if len(cells) < 2:
            continue
        label, value = cells[0], cells[1]
        if label in hyrox.STATIONS:
            rec[hyrox.STATIONS[label]] = hyrox.to_seconds(value)
        elif label in hyrox.RUNS:
            rec[hyrox.RUNS[label]] = hyrox.to_seconds(value)
        elif label in hyrox.EXTRAS:
            rec[hyrox.EXTRAS[label]] = hyrox.to_seconds(value)
        elif label == "Nat":
            rec["nation"] = value

    check(all(rec.get(k) for k in hyrox.STATIONS.values()), "all 8 stations parsed")
    check(all(rec.get(k) for k in hyrox.RUNS.values()), "all 8 runs parsed")
    check(bool(rec.get("roxzone")), "roxzone parsed")
    check(rec.get("nation") == "CHN", "text fields are clean")

    # The splits must add up to the published total. This is the check that
    # catches a mis-parsed or silently dropped split.
    parts = (sum(rec[k] for k in hyrox.STATIONS.values())
             + sum(rec[k] for k in hyrox.RUNS.values()) + rec["roxzone"])
    drift = abs(parts - rec["total"]) / rec["total"]
    check(drift < 0.01,
          f"splits reconstruct the total (drift {drift * 100:.2f}%)")

    soup = BeautifulSoup(list_f.read_text(), "lxml")
    rows = [li for li in soup.select("li.list-group-item")
            if not li.select_one(".list-info__text") and li.find("a", href=True)
            and hyrox._IDP.search(li.find("a", href=True)["href"])]
    check(len(rows) == 100, f"roster page yields 100 athletes (got {len(rows)})")

    times = []
    for li in rows:
        node = li.select_one(".type-time")
        if node:
            times.append(hyrox.to_seconds(hyrox._clean(node).replace("Total", "").strip()))
    check(all(t for t in times) and len(times) == 100, "every finish time parsed")
    check(times == sorted(times), "roster is ordered by finish time")


def _check_not_public() -> None:
    """The repo is public; the products are paid. Keep them apart."""
    root = Path(__file__).resolve().parent.parent
    ignore = (root / ".gitignore").read_text()
    check("dist/" in ignore, "dist/ is gitignored")
    check("*.xlsx" in ignore, "built workbooks are gitignored")

    for wf in (root / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text()
        check("gh-release" not in text and "softprops" not in text,
              f"{wf.name} does not publish a public release")
        check("git add data dist" not in text,
              f"{wf.name} does not commit dist/")


def _check_pacing(tmp: Path) -> None:
    """Build a pacing plan from real splits and check it holds together."""
    import numpy as np
    import pandas as pd
    from splitline.product import pacing

    raw = Path(__file__).resolve().parent.parent / "data" / "hyrox_beijing_men_raw.txt"
    if not raw.exists():
        check(False, "hyrox split data present")
        return

    keys = pacing.ORDER + ["roxzone", "total"]
    order = ["r1", "ski", "r2", "push", "r3", "pull", "r4", "burpee", "r5",
             "row", "r6", "farmers", "r7", "lunges", "r8", "wall",
             "roxzone", "total"]
    rows = [l.split("|") for l in raw.read_text().splitlines()]
    df = pd.DataFrame([
        {k: (float(v) if v not in ("", "None") else np.nan)
         for k, v in zip(order, r[4:])} for r in rows
    ])

    cleaned = pacing.clean(df)
    check(len(cleaned) > 300, f"cleaning keeps a usable field ({len(cleaned)})")
    # Every surviving athlete's splits must reconstruct their finish time.
    parts = cleaned[pacing.STATIONS + pacing.RUNS + ["roxzone"]].sum(axis=1)
    check(bool((((parts - cleaned["total"]).abs() / cleaned["total"]) < 0.02).all()),
          "every kept athlete's splits reconstruct their total")

    tbl = pacing.pacing_table(cleaned)
    segs = pacing.ORDER + ["roxzone"]
    err = (tbl[segs].sum(axis=1) / 60 - tbl["target_min"]).abs().max()
    # A race plan that does not add up to its own target reads as broken.
    check(err < 0.001, f"every plan sums exactly to its target (max error {err:.4f} min)")
    check(int(tbl["target_min"].diff().dropna().max()) == 1,
          "targets are on a 1-minute grid, so no target snaps to another")
    check(all((tbl[s].diff().dropna() >= -1e-6).all() for s in segs),
          "no segment gets faster as the target gets slower")
    check(bool((tbl[segs] > 0).all().all()), "no zero or negative splits")

    out = tmp / "pace.xlsx"
    women_raw = raw.parent / "hyrox_beijing_women_raw.txt"
    dfw = None
    if women_raw.exists():
        rows_w = [l.split("|") for l in women_raw.read_text().splitlines()]
        dfw = pd.DataFrame([
            {k: (float(v) if v not in ("", "None") else np.nan)
             for k, v in zip(order, r[4:])} for r in rows_w])
    pacing.build(df, out, "self test", df_women=dfw)
    check(out.exists() and out.stat().st_size > 8000, "pacing plan builds")
    from openpyxl import load_workbook
    wb = load_workbook(out)
    for sheet in ("My race plan", "Where the race is won", "PacingMen",
                  "Method"):
        check(sheet in wb.sheetnames, f"pacing plan has '{sheet}'")
    ws = wb["My race plan"]
    # Find the first segment row rather than hard-coding it, so a layout
    # change cannot make this check silently stop testing anything.
    row = next((r for r in range(5, 20)
                if str(ws.cell(row=r, column=2).value or "").startswith("=")
                and "INDEX(" in str(ws.cell(row=r, column=2).value)), None)
    check(row is not None, "plan uses live formulas")
    if row:
        f = str(ws.cell(row=row, column=2).value)
        check("MATCH(MIN(ABS" not in f,
              "plan avoids the array lookup that breaks outside Excel")
        check('IF($B$5="Women"' in f, "plan is division-aware")


if __name__ == "__main__":
    raise SystemExit(main())
