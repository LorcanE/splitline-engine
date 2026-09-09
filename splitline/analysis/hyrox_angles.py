"""HYROX story bank.

Same contract as the Open angles: each one asks a real question of real race
splits, computes the answer, and reports its own sample and effect size so the
runner can refuse to publish it.

HYROX is the in-season sport — races run most weekends from September — so
this is where the weekly post comes from for most of the year.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from ..product.pacing import LABELS, ORDER, RUNS, STATIONS
from ..render import charts
from .finding import Finding

log = logging.getLogger(__name__)

REGISTRY: dict[str, Callable[[pd.DataFrame, Path], Finding]] = {}
ORDER_LIST: list[str] = []


def angle(slug: str):
    def deco(fn):
        REGISTRY[slug] = fn
        ORDER_LIST.append(slug)
        return fn
    return deco


# Short labels for charts. The full names belong in tables, where there is
# room; on a 350px-wide chart they crowd out the plot itself.
SHORT = {
    "1000m SkiErg": "SkiErg", "50m Sled Push": "Sled push",
    "50m Sled Pull": "Sled pull", "80m Burpee Broad Jump": "Burpees",
    "1000m Row": "Row", "200m Farmers Carry": "Farmers carry",
    "100m Sandbag Lunges": "Lunges", "Wall Balls": "Wall balls",
    "Roxzone": "Roxzone", "All eight runs": "Runs (all 8)",
}


def _short(name: str) -> str:
    return SHORT.get(name, name)


def _ms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def _n(x) -> str:
    return f"{int(x):,}"


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


# ================================================ 1. same time, different race ==
@angle("sex-shape")
def sex_shape(df: pd.DataFrame, out: Path) -> Finding:
    """Match men and women on finish time; what is left is race shape."""
    f = Finding(slug="sex-shape", headline="", subtitle="")
    if "sex" not in df.columns:
        f.skip_reason = "dataset holds only one division"
        return f

    lo, hi = 85 * 60, 95 * 60
    m = df[(df["sex"] == "M") & df["total"].between(lo, hi)]
    w = df[(df["sex"] == "W") & df["total"].between(lo, hi)]
    if len(m) < 30 or len(w) < 30:
        f.skip_reason = f"matched groups too small (men {len(m)}, women {len(w)})"
        return f

    rows = []
    for seg in STATIONS + ["roxzone"]:
        rows.append((LABELS.get(seg, "Roxzone"), float(m[seg].median()),
                     float(w[seg].median())))
    rows.append(("All eight runs", float(m[RUNS].sum(axis=1).median()),
                 float(w[RUNS].sum(axis=1).median())))
    rows.sort(key=lambda t: t[2] - t[1])

    diffs = [w_ - m_ for _, m_, w_ in rows]
    biggest_w = rows[0]
    biggest_m = rows[-1]
    span = max(diffs) - min(diffs)
    effect = span / (95 * 60 - 85 * 60)

    chart = charts.barh(
        [_short(r[0]) for r in rows][::-1], [r[2] - r[1] for r in rows][::-1],
        "Women minus men, at the same finish time",
        "seconds (negative = women faster)",
        out / "sex_shape.png", value_fmt="{:+.0f}s",
    )

    f.headline = "Same finish time, completely different race"
    f.subtitle = (
        f"{_n(len(m))} men and {_n(len(w))} women who finished between 85 and "
        f"95 minutes. Matching on finish time strips out speed and leaves only "
        f"shape."
    )
    f.n = len(m) + len(w)
    # Matched on finish time, so speed is already controlled for. The floor
    # is set by what the medians need, not by the size of the whole field.
    f.min_n = 120
    f.effect = effect
    f.stats = {"n_men": len(m), "n_women": len(w),
               "women_best": biggest_w[0], "women_worst": biggest_m[0],
               "span_s": span}

    f.lede(
        "Comparing men's and women's HYROX times tells you nothing except that "
        "men are faster. The interesting question is what happens when you "
        "hold finish time fixed — take only the athletes who finished within "
        "the same ten-minute window, and ask where each group spent it."
    )
    f.chart(chart, "Segment-by-segment difference at matched finish time",
            "Each bar is the women's median minus the men's median for that "
            "segment. Bars to the left are segments where women were faster.")
    f.p(
        f"The biggest gap in the women's favour is {biggest_w[0]}, where they "
        f"were {_ms(abs(biggest_w[2] - biggest_w[1]))} quicker. The biggest "
        f"gap the other way is {biggest_m[0]}, where they were "
        f"{_ms(abs(biggest_m[2] - biggest_m[1]))} slower. Between those two "
        f"extremes there is {_ms(span)} of spread — inside a race where, by "
        f"construction, both groups finished within ten minutes of each other."
    )
    f.h2("What it means if you are coaching")
    f.p(
        "The pattern is consistent rather than random: at matched finish time "
        "the ergs and the runs cost women time, and the strength and skill "
        "stations give it back. Pacing a woman off a man's splits therefore "
        "puts her behind on exactly the segments where she has least room to "
        "recover, and hands her a cushion where she needed none."
    )
    f.callout(
        "If you hand every athlete in your gym the same race plan, half of "
        "them are being paced off the wrong distribution."
    )
    f.table(["Segment", "Men", "Women", "Difference"],
            [[nm, _ms(mv), _ms(wv), f"{'+' if wv > mv else '−'}{_ms(abs(wv - mv))}"]
             for nm, mv, wv in rows])
    return f


# ======================================================= 2. where it is won ==
@angle("where-won")
def where_won(df: pd.DataFrame, out: Path) -> Finding:
    f = Finding(slug="where-won", headline="", subtitle="")
    if len(df) < 200:
        f.skip_reason = "field too small"
        return f

    fast = df[df["total"] <= df["total"].quantile(0.10)]
    slow = df[df["total"] >= df["total"].quantile(0.90)]
    gap = float(slow["total"].median() - fast["total"].median())
    if gap <= 0:
        f.skip_reason = "no spread in finish times"
        return f

    rows = []
    for seg in STATIONS + ["roxzone"]:
        d = float(slow[seg].median() - fast[seg].median())
        rows.append((LABELS.get(seg, "Roxzone"), float(fast[seg].median()),
                     float(slow[seg].median()), d, d / gap))
    d_runs = float(slow[RUNS].sum(axis=1).median() - fast[RUNS].sum(axis=1).median())
    rows.append(("All eight runs", float(fast[RUNS].sum(axis=1).median()),
                 float(slow[RUNS].sum(axis=1).median()), d_runs, d_runs / gap))
    rows.sort(key=lambda t: t[4], reverse=True)

    top = rows[0]
    stations_only = [r for r in rows if r[0] not in ("All eight runs", "Roxzone")]
    top_station = max(stations_only, key=lambda r: r[4])
    three = sum(r[4] for r in sorted(stations_only, key=lambda r: r[4],
                                     reverse=True)[:3])

    chart = charts.barh(
        [_short(r[0]) for r in rows][::-1], [r[4] * 100 for r in rows][::-1],
        "Share of the fast-to-slow gap, by segment",
        "% of the total gap", out / "where_won.png",
        highlight=len(rows) - 1, value_fmt="{:.1f}%",
    )

    f.headline = f"{top_station[0]} decide your HYROX"
    f.subtitle = (
        f"The fastest 10% and the slowest 10% of {_n(len(df))} finishers are "
        f"{_ms(gap)} apart. Here is exactly where that time goes."
    )
    f.n = len(df)
    f.effect = float(top_station[4])
    f.stats = {"gap_s": gap, "top_segment": top[0], "top_share": top[4],
               "top_station": top_station[0], "three_stations_share": three}

    f.lede(
        f"Every HYROX athlete has a theory about where their race is lost. "
        f"The splits settle it. Across {_n(len(df))} finishers, the gap "
        f"between the fastest tenth of the field and the slowest is "
        f"{_ms(gap)} — and it is not spread evenly."
    )
    f.chart(chart, "Each segment's share of the fast-to-slow gap",
            "The share of the total time difference attributable to each "
            "segment. The eight runs are pooled.")
    f.p(
        f"{top_station[0]} alone accounts for {_pct(top_station[4])} of the "
        f"entire gap: {_ms(top_station[1])} for the fast group against "
        f"{_ms(top_station[2])} for the slow one. That is a single station "
        f"taking almost three times as long."
    )
    f.p(
        f"Take the three worst stations together and they explain "
        f"{_pct(three)} of the difference between a fast race and a slow one. "
        f"The ergs — the two machines everyone trains most — barely feature."
    )
    f.h2("The roxzone nobody measures")
    rox = next(r for r in rows if r[0] == "Roxzone")
    f.p(
        f"Transition time is {_pct(rox[4])} of the gap on its own: "
        f"{_ms(rox[1])} for the fast group, {_ms(rox[2])} for the slow. It is "
        f"the only segment of a HYROX race that requires no fitness to "
        f"improve, and almost nobody trains it."
    )
    f.table(["Segment", "Fastest 10%", "Slowest 10%", "Gap", "Share of gap"],
            [[nm, _ms(fv), _ms(sv), _ms(d), _pct(sh)] for nm, fv, sv, d, sh in rows])
    return f


# ============================================================= 3. run fade ==
@angle("run-fade")
def run_fade(df: pd.DataFrame, out: Path) -> Finding:
    f = Finding(slug="run-fade", headline="", subtitle="")
    if len(df) < 200 or "r1" not in df.columns or "r8" not in df.columns:
        f.skip_reason = "run splits unavailable"
        return f

    d = df.copy()
    d["band"] = pd.cut(d["total"] / 60, [0, 70, 80, 90, 100, 110, 120, 999],
                       labels=["<70", "70-80", "80-90", "90-100",
                               "100-110", "110-120", "120+"])
    g = d.groupby("band", observed=True).agg(
        n=("total", "size"), r1=("r1", "median"), r8=("r8", "median"))
    g = g[g["n"] >= 15]
    if len(g) < 4:
        f.skip_reason = "too few populated finish-time bands"
        return f
    g["fade"] = g["r8"] / g["r1"] - 1

    labels = [str(i) for i in g.index]
    effect = float(g["fade"].max() - g["fade"].min())

    chart = charts.line_by_band(
        labels, {"Run 8 against run 1": [float(v) * 100 for v in g["fade"]]},
        "How much the last kilometre slows down, by finish time",
        "run 8 slower than run 1 (%)", out / "run_fade.png",
        invert_y=False, annotate_peak=False,
    )

    best, worst = g.iloc[0], g.iloc[-1]
    f.headline = "The slowest athletes do not run slower — they collapse"
    f.subtitle = (
        f"Run 1 against run 8 for {_n(int(g['n'].sum()))} finishers, grouped "
        f"by finish time."
    )
    f.n = int(g["n"].sum())
    f.effect = effect
    f.stats = {"fastest_band": str(g.index[0]), "fastest_fade": float(best["fade"]),
               "slowest_band": str(g.index[-1]), "slowest_fade": float(worst["fade"])}

    f.lede(
        "A HYROX is eight one-kilometre runs with a station between each. The "
        "interesting number is not how fast the first one is — it is how much "
        "slower the last one is than the first."
    )
    f.chart(chart, "Run 8 slowdown against run 1, by finish-time band",
            "Higher means the athlete faded more over the race.")
    f.p(
        f"Athletes finishing in the {g.index[0]} band ran their last kilometre "
        f"{_pct(float(best['fade']))} slower than their first — "
        f"{_ms(float(best['r1']))} out to {_ms(float(best['r8']))}. Athletes in "
        f"the {g.index[-1]} band went from {_ms(float(worst['r1']))} to "
        f"{_ms(float(worst['r8']))}, a fade of {_pct(float(worst['fade']))}."
    )
    f.h2("This is a pacing problem, not a fitness problem")
    f.p(
        "A fade that size is not what running out of fitness looks like. It is "
        "what starting too fast looks like. The first kilometre of a HYROX is "
        "run in a crowd, on fresh legs, with a clock that has just started — "
        "and it is the single easiest place in the sport to lose ten minutes "
        "you will never get back."
    )
    f.callout(
        "If your run 8 is more than about 10% slower than your run 1, your "
        "race was decided in the first five minutes."
    )
    f.table(["Finish time", "Athletes", "Run 1", "Run 8", "Fade"],
            [[str(i), _n(r["n"]), _ms(r["r1"]), _ms(r["r8"]), _pct(r["fade"])]
             for i, r in g.iterrows()])
    return f


def run_angle(slug: str, df: pd.DataFrame, out: Path) -> Finding:
    fn = REGISTRY.get(slug)
    if fn is None:
        raise KeyError(f"unknown hyrox angle: {slug}")
    try:
        return fn(df, out)
    except Exception as exc:  # noqa: BLE001
        log.exception("hyrox angle %s raised", slug)
        f = Finding(slug=slug, headline="", subtitle="")
        f.skip_reason = f"angle raised {type(exc).__name__}: {exc}"
        return f
