#!/usr/bin/env python3
"""Generate a synthetic Open dataset with the same schema and the same kinds
of structure as the real one.

This exists so the pipeline can be tested end to end — angles, gates, charts,
renderer, product — without hitting the leaderboard. It is NOT data. Every
build made from it is stamped SYNTHETIC and the product builder refuses to
package it unless explicitly told to.

    python scripts/make_fixture.py --n 40000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from splitline import config, store  # noqa: E402
from splitline.sources.crossfit import _postprocess  # noqa: E402

RNG = np.random.default_rng(20260909)

COUNTRIES = [
    ("United States", 0.42), ("United Kingdom", 0.09), ("Canada", 0.07),
    ("Australia", 0.06), ("Brazil", 0.05), ("France", 0.05), ("Germany", 0.04),
    ("Iceland", 0.01), ("Norway", 0.02), ("Netherlands", 0.03), ("Spain", 0.03),
    ("Italy", 0.03), ("Ireland", 0.02), ("Japan", 0.02), ("Mexico", 0.03),
    ("New Zealand", 0.02), ("Sweden", 0.01),
]
# A small, real-looking national depth effect.
COUNTRY_BONUS = {"Iceland": 0.42, "Norway": 0.20, "Canada": 0.10,
                 "United States": 0.05, "Australia": 0.06, "Japan": -0.10,
                 "Mexico": -0.14, "Italy": -0.08}


def build(n: int, year: int) -> pd.DataFrame:
    names = COUNTRIES
    probs = np.array([p for _, p in names], dtype=float)
    probs /= probs.sum()
    country = RNG.choice([c for c, _ in names], size=n, p=probs)

    gender = RNG.choice(["M", "F"], size=n, p=[0.58, 0.42])
    division_id = np.where(gender == "M", 1, 2)

    # Age: a right-skewed field centred in the low thirties, like the real one.
    age = np.clip(RNG.gamma(shape=6.0, scale=2.4, size=n) + 18, 16, 68).astype(int)

    # Anthropometry, gendered.
    height = np.where(
        gender == "M", RNG.normal(178, 7.0, n), RNG.normal(165, 6.5, n)
    )
    weight = np.where(
        gender == "M", RNG.normal(85, 10.5, n), RNG.normal(66, 9.0, n)
    )

    # Affiliates: a realistic long tail of gym sizes.
    n_gyms = max(200, n // 14)
    gym_size_w = RNG.pareto(1.4, n_gyms) + 1
    gym_size_w /= gym_size_w.sum()
    gym = RNG.choice(np.arange(n_gyms), size=n, p=gym_size_w)
    counts = np.bincount(gym, minlength=n_gyms).astype(float)
    # Bigger rooms are modestly better, plus gym-level noise.
    gym_quality = 0.16 * np.log1p(counts) / np.log1p(counts).max() * 4 \
        + RNG.normal(0, 0.22, n_gyms)

    # Latent ability.
    z = RNG.normal(0, 1, n)
    z += gym_quality[gym]
    z += np.array([COUNTRY_BONUS.get(c, 0.0) for c in country])
    # Age curve: rises to the late twenties, then falls away.
    z += -0.0022 * (age - 28.0) ** 2 + 0.012 * (age - 28.0)

    bmi = weight / (height / 100) ** 2
    bmi_z = (bmi - np.nanmean(bmi)) / np.nanstd(bmi)

    # Per-workout ability with deliberate, differing body-type loadings.
    #   wk1 = long engine piece      -> favours lighter athletes
    #   wk2 = mixed couplet          -> body neutral
    #   wk3 = heavy barbell + gym    -> favours heavier athletes
    w1 = z - 0.30 * bmi_z + RNG.normal(0, 0.55, n)
    w2 = z + 0.02 * bmi_z + RNG.normal(0, 0.60, n)
    w3 = z + 0.34 * bmi_z + RNG.normal(0, 0.55, n)
    # Age bites hardest on the heavy, powerful test.
    w3 += -0.0016 * (age - 28.0) ** 2

    df = pd.DataFrame({
        "year": year,
        "division_id": division_id,
        "division": np.where(gender == "M", "Men", "Women"),
        "competitor_id": [f"S{i:07d}" for i in range(n)],
        "name": [f"Athlete {i}" for i in range(n)],
        "gender": gender,
        "age": age,
        "height_cm": np.round(height, 1),
        "weight_kg": np.round(weight, 1),
        "country": country,
        "region": "Synthetic Region",
        "affiliate_id": [f"G{g:05d}" for g in gym],
        "affiliate": [f"Synthetic Box {g}" for g in gym],
        "status": "ACT",
    })

    # Some athletes leave height/weight blank, as in the real field.
    blank = RNG.random(n) < 0.28
    df.loc[blank, ["height_cm", "weight_kg"]] = np.nan

    # Attrition: a bad workout one makes quitting much more likely.
    p1 = pd.Series(w1).rank(pct=True, ascending=False)  # 0 best
    quit_p = np.clip(0.06 + 0.42 * p1.to_numpy() ** 1.8, 0, 0.85)
    quit_after_1 = RNG.random(n) < quit_p
    quit_after_2 = (~quit_after_1) & (RNG.random(n) < 0.07)

    scored = np.full(n, 3)
    scored[quit_after_2] = 2
    scored[quit_after_1] = 1
    df["workouts_scored"] = scored

    for i, w in enumerate((w1, w2, w3), start=1):
        valid = scored >= i
        rank = pd.Series(np.where(valid, w, np.nan)).rank(
            ascending=False, method="min")
        df[f"wk{i}_rank"] = rank
        reps = np.where(valid, np.round(120 + 60 * (w - w.mean()) / w.std()), np.nan)
        df[f"wk{i}_reps"] = reps
        df[f"wk{i}_display"] = [
            (f"{int(r)} reps" if np.isfinite(r) else "") for r in reps
        ]
        df[f"wk{i}_time"] = np.where(valid, np.round(900 - 4 * (reps - 120)), np.nan)
        df[f"wk{i}_valid"] = valid
        df[f"wk{i}_scaled"] = (~valid) | (RNG.random(n) < 0.11)
        df[f"wk{i}_judge"] = "Synthetic Judge"
        # 82% validate at their own gym; the rest elsewhere.
        home = RNG.random(n) < 0.82
        other = [f"Synthetic Box {g}" for g in RNG.integers(0, n_gyms, n)]
        df[f"wk{i}_judge_aff"] = np.where(
            valid, np.where(home, df["affiliate"], other), "")

    # Judging venue is an athlete-level habit, not an independent coin flip per
    # workout: people validate where they train. Re-derive it that way so the
    # home/away groups have realistic sizes.
    prefers_home = RNG.random(n) < 0.84
    for i in range(1, 4):
        valid = scored >= i
        stray = RNG.random(n) < 0.06  # occasional week away from the home gym
        at_home = prefers_home & ~stray
        other = [f"Synthetic Box {g}" for g in RNG.integers(0, n_gyms, n)]
        df[f"wk{i}_judge_aff"] = np.where(
            valid, np.where(at_home, df["affiliate"], other), "")

    finished = scored >= 3
    overall = pd.Series(np.where(finished, w1 + w2 + w3, np.nan))
    df["overall_rank"] = overall.rank(ascending=False, method="min")
    df["overall_score"] = np.where(finished, np.round(overall * 1000), np.nan)

    return _postprocess(df)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40000)
    ap.add_argument("--year", type=int, default=config.CF_YEAR)
    args = ap.parse_args()

    df = build(args.n, args.year)
    store.save(df, args.year)
    (config.DATA / f"open_{args.year}.SYNTHETIC").write_text(
        "This dataset is synthetic. It exists to test the pipeline. "
        "Do not publish or sell anything built from it.\n"
    )
    print(f"synthetic dataset: {len(df):,} rows, "
          f"{int((df['workouts_scored'] >= 3).sum()):,} finishers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
