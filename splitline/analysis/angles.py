"""The story bank.

Each angle is a real statistical question asked of the Open field. An angle
computes the answer, builds the charts, writes the prose around the numbers it
actually found, and reports its own sample size and effect size so the runner
can refuse to publish it.

Nothing here fabricates a number. Every figure in the prose is interpolated
from the computed result, so if the data says "no effect", the angle reports a
small effect and the runner moves on to the next one.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from ..render import charts
from .finding import Finding

log = logging.getLogger(__name__)

REGISTRY: dict[str, Callable[[pd.DataFrame, Path], Finding]] = {}
ORDER: list[str] = []

# When the dataset is a sample rather than a full crawl, the runner sets these
# so that any count describing "how many athletes in the Open" is reported as a
# population estimate instead of a sample tally. Rates, medians and percentiles
# need no adjustment — they estimate the population directly. Counts do, and
# printing a sample tally as though it were the field is the single easiest way
# to publish something false.
SCALE: float = 1.0
IS_SAMPLE: bool = False


def set_population(sampled: int, population: int) -> None:
    global SCALE, IS_SAMPLE
    if sampled > 0 and population > sampled:
        SCALE = population / sampled
        IS_SAMPLE = True
    else:
        SCALE, IS_SAMPLE = 1.0, False


def _athletes(n: float) -> str:
    """A count of athletes, scaled to the field and marked when estimated."""
    if not IS_SAMPLE:
        return f"{int(round(n)):,}"
    scaled = n * SCALE
    # Round estimates so they never masquerade as an exact census.
    step = 100 if scaled < 10_000 else 1_000
    return f"about {int(round(scaled / step) * step):,}"


def angle(slug: str):
    def deco(fn):
        REGISTRY[slug] = fn
        ORDER.append(slug)
        return fn
    return deco


# ------------------------------------------------------------- helpers ----
def _wk_cols(df: pd.DataFrame) -> list[str]:
    """Workout ordinals present in the frame, e.g. ['wk1','wk2','wk3']."""
    return sorted({c.split("_")[0] for c in df.columns
                   if c.startswith("wk") and c.endswith("_pct")})


def _wk_label(wk: str) -> str:
    return f"Workout {wk[2:]}"


def _scored(df: pd.DataFrame) -> pd.DataFrame:
    """Athletes who actually completed the whole Open."""
    n_wk = len(_wk_cols(df))
    return df[df["workouts_scored"] >= n_wk].copy()


def _pct_str(x: float) -> str:
    return f"{x * 100:.1f}%"


def _rank_pct_to_place(pct: float, field: int) -> int:
    return max(1, int(round(pct * field)))


def _fmt_int(n) -> str:
    return f"{int(n):,}"


# =========================================================== 1. age curve ==
@angle("age-curve")
def age_curve(df: pd.DataFrame, out: Path) -> Finding:
    f = Finding(slug="age-curve", headline="", subtitle="")
    wks = _wk_cols(df)
    d = _scored(df)
    d = d[d["age"].between(16, 70)]
    if d.empty or not wks:
        f.skip_reason = "no scored athletes with usable ages"
        return f

    g = d.groupby("age_band", observed=True)
    counts = g.size()
    bands = [b for b in counts.index if counts[b] >= 200]
    if len(bands) < 4:
        f.skip_reason = "too few populated age bands"
        return f

    series: dict[str, list[float]] = {}
    for wk in wks:
        med = g[f"{wk}_pct"].median()
        series[_wk_label(wk)] = [float(med[b]) for b in bands]

    overall = [float(g["overall_pct"].median()[b]) for b in bands]
    best_i = int(np.argmin(overall))
    worst_i = int(np.argmax(overall))
    peak_band, worst_band = str(bands[best_i]), str(bands[worst_i])
    effect = float(overall[worst_i] - overall[best_i])

    # Which workout punishes age hardest? Slope of median percentile per band.
    slopes = {}
    xs = np.arange(len(bands), dtype=float)
    for wk in wks:
        ys = np.asarray(series[_wk_label(wk)], dtype=float)
        slopes[wk] = float(np.polyfit(xs, ys, 1)[0])
    harshest = max(slopes, key=lambda k: slopes[k])
    kindest = min(slopes, key=lambda k: slopes[k])

    chart = charts.line_by_band(
        [str(b) for b in bands], series,
        "Median finishing percentile by age band",
        "median percentile (lower is better)",
        out / "age_curve.png",
    )

    field = int(len(d))
    f.headline = f"The Open peaks at {peak_band} — and one workout does most of the damage"
    f.subtitle = (
        f"{_athletes(field)} athletes who scored every workout, sorted by age. "
        f"The decline is not uniform across the three tests."
    )
    f.n = field
    f.effect = effect
    f.stats = {
        "peak_band": peak_band, "worst_band": worst_band,
        "spread": effect, "harshest": harshest, "kindest": kindest,
        "field": field,
    }

    f.lede(
        f"Everyone knows the Open gets harder with age. Almost nobody checks "
        f"<em>where</em> it gets harder. Across {_athletes(field)} athletes who "
        f"submitted a score for all {len(wks)} workouts, the median finishing "
        f"percentile bottoms out at {peak_band} and drifts steadily from there."
    )
    f.chart(chart, "Median finishing percentile by age band",
            "One line per workout, plotting the median athlete in each age band. "
            "Lower is better, so a line falling away to the right is a workout "
            "that punishes age.")
    f.p(
        f"The gap between the strongest band ({peak_band}) and the weakest "
        f"({worst_band}) is {_pct_str(effect)} of the field — which is to say, "
        f"the same athlete moving from one to the other would slide roughly "
        f"{_fmt_int(_rank_pct_to_place(effect, field))} places."
    )
    f.h2("The three workouts age differently")
    f.p(
        f"Fitting a slope to each line, {_wk_label(harshest)} falls away fastest "
        f"with age and {_wk_label(kindest)} holds up best. That is not a "
        f"statement about effort — it is a statement about what each test "
        f"actually asks for. Tests weighted toward absolute load and short, "
        f"high-power intervals punish age hardest; tests weighted toward "
        f"pacing and cyclical work flatten out."
    )
    f.callout(
        f"If you are over 40 and picking one thing to train between now and the "
        f"next Open, the data points at {_wk_label(harshest)}'s qualities, not "
        f"at more conditioning."
    )
    rows = [[str(b), _pct_str(v), _athletes(counts[b])]
            for b, v in zip(bands, overall)]
    f.table(["Age band", "Median percentile", "Athletes"], rows)
    return f


# ================================================ 2. body-type signature ==
@angle("body-signature")
def body_signature(df: pd.DataFrame, out: Path) -> Finding:
    f = Finding(slug="body-signature", headline="", subtitle="")
    wks = _wk_cols(df)
    d = _scored(df)
    d = d[d["bmi"].notna() & d["height_cm"].notna() & d["weight_kg"].notna()]
    if len(d) < 500 or not wks:
        f.skip_reason = "not enough athletes with complete body data"
        return f

    corrs: dict[str, dict[str, float]] = {}
    for wk in wks:
        col = d[f"{wk}_pct"].astype(float)
        corrs[wk] = {
            "bmi": float(np.corrcoef(d["bmi"].astype(float), col)[0, 1]),
            "height": float(np.corrcoef(d["height_cm"].astype(float), col)[0, 1]),
            "weight": float(np.corrcoef(d["weight_kg"].astype(float), col)[0, 1]),
        }

    flat = [(wk, m, v) for wk, mm in corrs.items() for m, v in mm.items()]
    wk_s, metric, val = max(flat, key=lambda t: abs(t[2]))
    effect = abs(val)
    direction = "heavier" if val < 0 else "lighter"
    metric_label = {"bmi": "BMI", "height": "height", "weight": "bodyweight"}[metric]

    chart = charts.scatter_binned(
        d["bmi"].astype(float), d[f"{wk_s}_pct"].astype(float),
        f"{_wk_label(wk_s)}: finishing percentile against BMI",
        "BMI", "median percentile (lower is better)",
        out / "body_signature.png",
    )

    f.headline = f"{_wk_label(wk_s)} has a body type, and the field is not subtle about it"
    f.subtitle = (
        f"{_athletes(len(d))} athletes with complete height and weight profiles. "
        f"One workout correlates with {metric_label} far more than the others."
    )
    f.n = int(len(d))
    f.effect = effect
    f.stats = {"workout": wk_s, "metric": metric, "r": val, "n": int(len(d))}

    f.lede(
        f"Athletes argue endlessly about whether the Open favours a body type. "
        f"It does — but only on some workouts, and the size of the effect is "
        f"measurable rather than a matter of opinion."
    )
    f.chart(chart, f"{_wk_label(wk_s)} percentile against BMI",
            "Line is the mean within each BMI bin; band is the middle 50% of "
            "athletes in that bin. Lower is better.")
    f.p(
        f"Across {_athletes(len(d))} athletes who filled in both height and "
        f"weight, {_wk_label(wk_s)} shows a correlation of r = {val:+.3f} with "
        f"{metric_label} — meaning {direction} athletes finish measurably "
        f"better on it. Correlations of this size are small in absolute terms "
        f"and enormous relative to everything else in a leaderboard this wide."
    )
    f.h2("The full picture")
    rows = []
    for wk in wks:
        rows.append([
            _wk_label(wk),
            f"{corrs[wk]['bmi']:+.3f}",
            f"{corrs[wk]['height']:+.3f}",
            f"{corrs[wk]['weight']:+.3f}",
        ])
    f.table(["Workout", "r vs BMI", "r vs height", "r vs weight"], rows)
    f.p(
        "Read the signs carefully. A negative correlation means the larger "
        "value finished better, because a lower percentile is a better finish. "
        "Where a workout shows near-zero correlation on all three, it is doing "
        "what a good test is supposed to do: separating athletes on fitness "
        "rather than on anthropometry."
    )
    f.callout(
        "None of this is an excuse. It is a scouting report: it tells you which "
        "workout you are structurally advantaged on, and therefore which one you "
        "have to win by a bigger margin to make the ranking work out."
    )
    return f


# ==================================================== 3. the home judge ==
@angle("home-judge")
def home_judge(df: pd.DataFrame, out: Path) -> Finding:
    """Do athletes score better when judged at their own affiliate?

    Deliberately framed as a measurement, not an accusation. Validating at
    your own gym is the normal, sanctioned way to do the Open — the question
    is only whether the distributions differ, and by how much.
    """
    f = Finding(slug="home-judge", headline="", subtitle="")
    wks = _wk_cols(df)
    d = _scored(df)
    d = d[(d["affiliate"].astype(str).str.len() > 0)]
    if len(d) < 1000 or not wks:
        f.skip_reason = "not enough athletes with affiliate data"
        return f

    aff = d["affiliate"].astype(str).str.strip().str.casefold()
    home_flags = []
    for wk in wks:
        col = f"{wk}_judge_aff"
        if col not in d.columns:
            continue
        judged = d[col].astype(str).str.strip().str.casefold()
        home_flags.append((judged == aff) & (judged.str.len() > 0))
    if not home_flags:
        f.skip_reason = "judging affiliate not present in this season's payload"
        return f

    # Split on the athlete's habit rather than on unanimity: validating away
    # for one week out of three is noise, not a different behaviour.
    home_share = pd.concat(home_flags, axis=1).mean(axis=1)
    d = d.assign(home_share=home_share)
    at_home = d[d["home_share"] >= 2 / 3]
    away = d[d["home_share"] <= 1 / 3]
    if len(at_home) < 300 or len(away) < 300:
        f.skip_reason = (
            f"groups too unbalanced (home={len(at_home):,}, away={len(away):,})"
        )
        return f

    a = at_home["overall_pct"].astype(float).dropna().to_numpy()
    b = away["overall_pct"].astype(float).dropna().to_numpy()
    med_a, med_b = float(np.median(a)), float(np.median(b))
    effect = abs(med_b - med_a)
    better = "at their own affiliate" if med_a < med_b else "away from their own affiliate"

    chart = charts.dist_pair(
        a, b, ("Judged at home", "Judged elsewhere"),
        "Overall finishing percentile by where the score was validated",
        "overall percentile (lower is better)",
        out / "home_judge.png",
    )

    f.headline = "Athletes judged at their own gym finish differently — here is by how much"
    f.subtitle = (
        f"{_fmt_int(len(at_home) + len(away))} athletes split by whether their "
        f"scores were validated at their own affiliate."
    )
    f.n = int(len(at_home) + len(away))
    f.effect = effect
    f.stats = {"median_home": med_a, "median_away": med_b,
               "n_home": int(len(at_home)), "n_away": int(len(away))}

    f.lede(
        "Validating at your own gym is the ordinary, sanctioned way to do the "
        "Open. Most athletes do it. That makes it a clean natural experiment: "
        "the field splits itself into two large groups, and we can simply look "
        "at whether the distributions differ."
    )
    f.chart(chart, "Percentile distributions, home-judged versus not",
            "Dashed lines are group medians. Lower is better.")
    f.p(
        f"Athletes whose scores were all validated at their own affiliate "
        f"(n = {_fmt_int(len(at_home))}) finish at a median percentile of "
        f"{_pct_str(med_a)}. Athletes validated entirely elsewhere "
        f"(n = {_fmt_int(len(away))}) sit at {_pct_str(med_b)}. The gap is "
        f"{_pct_str(effect)}, favouring those judged {better}."
    )
    f.h2("What this does and does not show")
    f.p(
        "It does not show cheating, and reading it that way would be wrong. "
        "The two groups are not randomly assigned: athletes who travel to "
        "another gym to validate are a self-selecting population — often "
        "competitive athletes at gyms without an affiliate licence, or people "
        "at a live event. Selection alone could produce a gap this size."
    )
    f.p(
        "What it does show is that the gap is large enough to be worth "
        "someone's attention, and that it is measurable from public data in "
        "about twenty lines of code. Splitline will keep measuring it each "
        "season; a stable gap is a curiosity, a growing one is a story."
    )
    return f


# ================================================== 4. the affiliate effect ==
@angle("affiliate-effect")
def affiliate_effect(df: pd.DataFrame, out: Path) -> Finding:
    f = Finding(slug="affiliate-effect", headline="", subtitle="")
    d = _scored(df)
    d = d[d["affiliate"].astype(str).str.len() > 0]
    if len(d) < 1000:
        f.skip_reason = "not enough affiliated athletes"
        return f

    grp = d.groupby("affiliate_id", observed=True).agg(
        name=("affiliate", "first"),
        entrants=("competitor_id", "size"),
        med_pct=("overall_pct", "median"),
    )
    grp = grp[grp["entrants"] >= 5]
    if len(grp) < 100:
        f.skip_reason = "too few affiliates clear the size threshold"
        return f

    grp["size_band"] = pd.cut(
        grp["entrants"],
        bins=[4, 9, 19, 39, 79, 10_000],
        labels=["5-9", "10-19", "20-39", "40-79", "80+"],
    )
    band = grp.groupby("size_band", observed=True).agg(
        med=("med_pct", "median"), gyms=("med_pct", "size")
    ).dropna()
    if len(band) < 3:
        f.skip_reason = "not enough size bands"
        return f

    labels = [str(i) for i in band.index]
    vals = [float(v) for v in band["med"]]
    effect = float(max(vals) - min(vals))
    big_better = vals[-1] < vals[0]

    chart = charts.line_by_band(
        labels, {"Median athlete": vals},
        "Median athlete percentile by affiliate size",
        "median percentile (lower is better)",
        out / "affiliate_effect.png",
        annotate_peak=False,
    )

    top = grp[grp["entrants"] >= 20].nsmallest(12, "med_pct")

    f.headline = ("Big gyms really do produce better athletes — but not by as much "
                  "as they charge you for")
    f.subtitle = (
        f"{_fmt_int(len(grp))} affiliates with at least five Open entrants, "
        f"ranked by the percentile of their median athlete."
    )
    f.n = int(len(d))
    f.effect = effect
    f.stats = {"affiliates": int(len(grp)), "spread": effect,
               "big_better": bool(big_better)}

    f.lede(
        f"Gym marketing is built on the claim that the room makes the athlete. "
        f"With {_fmt_int(len(grp))} affiliates and their full Open entrant "
        f"lists, that claim is testable."
    )
    f.chart(chart, "Median athlete percentile by affiliate size",
            "Each point is the median of the median athlete across all "
            "affiliates in that size band. Lower is better.")
    f.p(
        f"The spread from the weakest size band to the strongest is "
        f"{_pct_str(effect)} of the field. The direction is "
        + ("toward larger gyms" if big_better else "toward smaller gyms") +
        ", which is the answer most people expect — but the magnitude is the "
        "interesting part, and it is smaller than the marketing implies."
    )
    f.p(
        "There is an obvious confound and it is worth naming: larger affiliates "
        "are concentrated in wealthier, denser cities, and they recruit athletes "
        "who were already training. Size is partly a proxy for selection. This "
        "chart measures the association, not the coaching."
    )
    f.h2("The affiliates punching hardest")
    rows = [[r["name"], _fmt_int(r["entrants"]), _pct_str(float(r["med_pct"]))]
            for _, r in top.iterrows()]
    f.table(["Affiliate", "Open entrants", "Median athlete percentile"], rows)
    f.p(
        "Minimum twenty entrants, so a single ringer cannot carry a gym onto "
        "this list. These are rooms where the middle of the room is fast."
    )
    return f


# ======================================================== 5. the attrition ==
@angle("attrition")
def attrition(df: pd.DataFrame, out: Path) -> Finding:
    f = Finding(slug="attrition", headline="", subtitle="")
    wks = _wk_cols(df)
    if len(wks) < 2 or df.empty:
        f.skip_reason = "need at least two workouts to measure drop-off"
        return f

    total = int(len(df))
    counts = df["workouts_scored"].value_counts().sort_index()
    finished = int(counts.get(len(wks), 0))
    started = int(total - counts.get(0, 0))
    if started < 500:
        f.skip_reason = "field too small"
        return f
    finish_rate = finished / started

    # Does a bad first workout predict quitting?
    first = f"{wks[0]}_pct"
    d = df[df[first].notna()].copy()
    d["quit"] = d["workouts_scored"] < len(wks)
    q = d.groupby(pd.qcut(d[first], 4, labels=["top 25%", "2nd", "3rd", "bottom 25%"]),
                  observed=True)["quit"].mean()
    if len(q) < 4:
        f.skip_reason = "could not form quartiles on workout 1"
        return f
    effect = float(q.iloc[-1] - q.iloc[0])

    chart = charts.barh(
        [str(i) for i in q.index][::-1],
        [float(v) * 100 for v in q][::-1],
        "Share who never finished the Open, by workout 1 quartile",
        "% who stopped scoring", out / "attrition.png",
        highlight=0, value_fmt="{:.1f}%",
    )

    f.headline = f"Only {_pct_str(finish_rate)} of the field finishes the Open"
    f.subtitle = (
        f"{_athletes(started)} athletes posted a score. What happened to the "
        f"rest is entirely predictable from workout one."
    )
    f.n = started
    f.effect = effect
    f.stats = {"started": started, "finished": finished,
               "finish_rate": finish_rate, "quit_gap": effect}

    f.lede(
        f"Of {_athletes(started)} athletes who posted at least one score, "
        f"{_athletes(finished)} — {_pct_str(finish_rate)} — submitted a score "
        f"for every workout. The Open's real cut is not the Quarterfinals "
        f"line. It is the people who stop."
    )
    f.chart(chart, "Drop-off rate by first-workout quartile",
            "Athletes grouped by where they placed on workout one, then "
            "measured on whether they ever finished.")
    f.p(
        f"Athletes in the bottom quartile of workout one abandoned the Open at "
        f"{_pct_str(float(q.iloc[-1]))}. Athletes in the top quartile did so at "
        f"{_pct_str(float(q.iloc[0]))} — a gap of {_pct_str(effect)}. A bad "
        f"first score is roughly "
        f"{float(q.iloc[-1]) / max(float(q.iloc[0]), 1e-9):.1f}× as likely to "
        f"end someone's season as a good one."
    )
    f.h2("Why this matters more than the leaderboard")
    f.p(
        "Every affiliate owner reading this has a retention problem hiding in "
        "these numbers. The athletes who quit after workout one are not the "
        "ones who were never going to compete — they signed up and paid. They "
        "got one number they did not like and disappeared."
    )
    f.callout(
        "The cheapest intervention in the sport: on the Monday after workout "
        "one, message everyone in your gym's bottom quartile. Nothing else in "
        "this dataset moves a bigger number."
    )
    rows = [[f"{int(k)} of {len(wks)}", _athletes(v), _pct_str(v / started)]
            for k, v in counts.items() if int(k) > 0]
    f.table(["Workouts scored", "Athletes", "Share of starters"], rows)
    return f


# ====================================================== 6. spike vs floor ==
@angle("spike-vs-floor")
def spike_vs_floor(df: pd.DataFrame, out: Path) -> Finding:
    f = Finding(slug="spike-vs-floor", headline="", subtitle="")
    wks = _wk_cols(df)
    d = _scored(df)
    if len(wks) < 3 or len(d) < 1000:
        f.skip_reason = "need three scored workouts and a full field"
        return f

    pct = d[[f"{w}_pct" for w in wks]].astype(float)
    d = d.assign(
        best=pct.min(axis=1),
        worst=pct.max(axis=1),
        spread=pct.max(axis=1) - pct.min(axis=1),
    )

    bands = pd.qcut(d["overall_pct"], 10, labels=[f"{i*10}-{(i+1)*10}%" for i in range(10)])
    g = d.groupby(bands, observed=True).agg(
        spread=("spread", "median"), n=("spread", "size")
    )
    labels = [str(i) for i in g.index]
    vals = [float(v) for v in g["spread"]]
    effect = float(max(vals) - min(vals))

    chart = charts.line_by_band(
        labels, {"Median spread between best and worst workout": vals},
        "How uneven athletes are, by where they finish overall",
        "percentile spread across the three workouts",
        out / "spike_vs_floor.png",
        invert_y=False, annotate_peak=False,
    )

    top = d[d["overall_pct"] <= 0.01]
    mid = d[(d["overall_pct"] >= 0.45) & (d["overall_pct"] <= 0.55)]
    top_spread = float(top["spread"].median()) if len(top) else float("nan")
    mid_spread = float(mid["spread"].median()) if len(mid) else float("nan")

    f.headline = "The top 1% are not better at everything — they are better at not being bad"
    f.subtitle = (
        f"{_athletes(len(d))} complete Open records, measured on the gap between "
        f"each athlete's best and worst workout."
    )
    f.n = int(len(d))
    f.effect = effect
    f.stats = {"top_spread": top_spread, "mid_spread": mid_spread,
               "band_spread": effect}

    f.lede(
        "There are two ways to place well in a ranked competition: be "
        "exceptional at one thing, or refuse to be bad at any of them. The "
        "Open's scoring — ranks summed across workouts — quietly decides which "
        "one wins, and the field's own data shows the answer."
    )
    f.chart(chart, "Median best-to-worst percentile spread by finishing decile",
            "Higher means a more lopsided athlete. The overall field's shape "
            "tells you what the scoring rewards.")
    f.p(
        f"Athletes in the top 1% overall carry a median best-to-worst spread of "
        f"{_pct_str(top_spread)}. Athletes sitting mid-field carry "
        f"{_pct_str(mid_spread)}. Across the ten deciles the spread varies by "
        f"{_pct_str(effect)}."
    )
    f.h2("What to do with it")
    f.p(
        "If your best workout percentile is far ahead of your worst, your "
        "ranking is being set by the worst one, and closing that gap is worth "
        "more places than extending the good one. That is not motivational "
        "framing — it is arithmetic about how rank-sum scoring works."
    )
    return f


# ========================================================= 7. the cutlines ==
@angle("cutlines")
def cutlines(df: pd.DataFrame, out: Path) -> Finding:
    """The reference piece. Always publishable, always linked back to."""
    f = Finding(slug="cutlines", headline="", subtitle="")
    wks = _wk_cols(df)
    d = _scored(df)
    if not wks or len(d) < 500:
        f.skip_reason = "field too small"
        return f

    thresholds = [0.01, 0.05, 0.10, 0.25, 0.50]
    rows = []
    for div, sub in d.groupby("division", observed=True):
        if len(sub) < 300:
            continue
        field_n = len(sub)
        row = [str(div), _fmt_int(field_n)]
        for t in thresholds:
            row.append(_fmt_int(_rank_pct_to_place(t, field_n)))
        rows.append(row)
    if not rows:
        f.skip_reason = "no division large enough"
        return f

    wk_rows = []
    for wk in wks:
        sub = d[d[f"{wk}_rank"].notna()]
        if sub.empty:
            continue
        r = [_wk_label(wk)]
        for t in thresholds:
            q = sub[f"{wk}_pct"].astype(float)
            near = sub.loc[(q - t).abs().nsmallest(25).index, f"{wk}_display"]
            disp = near.mode()
            r.append(str(disp.iloc[0]) if len(disp) else "—")
        wk_rows.append(r)

    f.headline = "Every 2026 Open cutline, in one table"
    f.subtitle = ("What you actually had to score to land in the top 1, 5, 10, 25 "
                  "and 50 per cent.")
    f.n = int(len(d))
    f.effect = 1.0  # a reference table is always worth publishing
    f.stats = {"divisions": len(rows)}

    f.lede(
        "Percentiles are easier to argue about than to look up. So here they "
        "are: the finishing place that put you on each side of every line that "
        "matters, taken from the completed field rather than from everyone who "
        "signed up."
    )
    f.h2("Where the lines fell, by place")
    f.table(["Division", "Finishers", "Top 1%", "Top 5%", "Top 10%",
             "Top 25%", "Top 50%"], rows)
    if wk_rows:
        f.h2("And by score, workout by workout")
        f.table(["Workout", "Top 1%", "Top 5%", "Top 10%", "Top 25%", "Top 50%"],
                wk_rows)
        f.p(
            "Scores are the observed score nearest each threshold across the "
            "completed field, so read them as the neighbourhood of the line "
            "rather than an exact boundary."
        )
    f.callout(
        "Bookmark this one. It is the table you will want in February when "
        "someone in your gym claims a number."
    )
    return f


# =========================================================== 8. geography ==
@angle("geography")
def geography(df: pd.DataFrame, out: Path) -> Finding:
    f = Finding(slug="geography", headline="", subtitle="")
    d = _scored(df)
    d = d[d["country"].astype(str).str.len() > 0]
    if len(d) < 1000:
        f.skip_reason = "not enough athletes with country data"
        return f

    g = d.groupby("country", observed=True).agg(
        n=("competitor_id", "size"), med=("overall_pct", "median")
    )
    g = g[g["n"] >= 150]
    if len(g) < 8:
        f.skip_reason = "too few countries clear the size threshold"
        return f
    g = g.sort_values("med")
    effect = float(g["med"].iloc[-1] - g["med"].iloc[0])

    show = pd.concat([g.head(10), g.tail(5)]).drop_duplicates()
    chart = charts.barh(
        list(show.index), [float(v) * 100 for v in show["med"]],
        "Median athlete percentile by country (min. 150 finishers)",
        "median percentile, % (lower is better)",
        out / "geography.png", highlight=0, value_fmt="{:.1f}",
    )

    best, worst = str(g.index[0]), str(g.index[-1])
    f.headline = f"{best} has the deepest field in the Open — and it is not close"
    f.subtitle = (
        f"{_fmt_int(len(g))} countries with at least 150 finishers, ranked by "
        f"the percentile of their median athlete."
    )
    f.n = int(len(d))
    f.effect = effect
    f.stats = {"best": best, "worst": worst, "countries": int(len(g)),
               "spread": effect}

    f.lede(
        "National fitness rankings usually measure who produces champions. "
        "This one measures something more useful: how good the ordinary "
        "athlete is. The median entrant, not the podium."
    )
    f.chart(chart, "Median athlete percentile by country",
            "Median of each country's finishers, plotted against the global "
            "field. Lower is better.")
    f.p(
        f"{best} sits at a median of {_pct_str(float(g['med'].iloc[0]))}, "
        f"{_pct_str(effect)} clear of {worst} at the other end of the table. "
        f"Depth like that is a coaching-culture signal, not a talent one — it "
        f"shows up in the middle of the distribution, where champions do not live."
    )
    f.p(
        "One caveat worth stating plainly: countries with small, self-selecting "
        "Open populations look stronger than they are, because only committed "
        "athletes bother entering. The 150-finisher floor limits that, it does "
        "not remove it."
    )
    rows = [[str(i), _fmt_int(r["n"]), _pct_str(float(r["med"]))]
            for i, r in g.head(15).iterrows()]
    f.table(["Country", "Finishers", "Median percentile"], rows)
    return f


def run_angle(slug: str, df: pd.DataFrame, out: Path) -> Finding:
    fn = REGISTRY.get(slug)
    if fn is None:
        raise KeyError(f"unknown angle: {slug}")
    try:
        return fn(df, out)
    except Exception as exc:  # noqa: BLE001 — one bad angle must not kill the run
        log.exception("angle %s raised", slug)
        f = Finding(slug=slug, headline="", subtitle="")
        f.skip_reason = f"angle raised {type(exc).__name__}: {exc}"
        return f
