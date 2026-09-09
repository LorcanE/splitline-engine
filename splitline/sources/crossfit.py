"""CrossFit Open leaderboard ingester.

The public leaderboard endpoint returns 50 athletes per page with full entrant
demographics and per-workout scores. A full division is a few thousand pages,
which is why the result is cached to parquet and only refreshed on demand.

Endpoint contract (verified 2026-09-09 against the live API):

    GET {CF_API}/open/{year}/leaderboards?division={d}&sort=0&page={n}

    {
      "pagination": {"totalPages": 2543, "totalCompetitors": 127113, "currentPage": 1},
      "competition": {"year": 2026, "competitionId": 259, "division": "1", ...},
      "leaderboardRows": [
        {
          "overallRank": "1", "overallScore": "...",
          "entrant": {"competitorId","competitorName","gender","age","height",
                      "weight","countryOfOriginName","regionName","affiliateId",
                      "affiliateName","divisionId","status", ...},
          "scores": [{"ordinal","rank","score","scoreDisplay","breakdown",
                      "time","scaled","valid","judge","affiliate", ...}, ...]
        }, ...
      ]
    }
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Iterator

import pandas as pd
import requests

from ..config import (
    CF_API,
    CF_DIVISIONS,
    MAX_RETRIES,
    REQUEST_DELAY_S,
    REQUEST_TIMEOUT_S,
    USER_AGENT,
)

log = logging.getLogger(__name__)

_HEIGHT_IN = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*in\s*$", re.I)
_HEIGHT_CM = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*cm\s*$", re.I)
_WEIGHT_LB = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*lb\s*$", re.I)
_WEIGHT_KG = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*kg\s*$", re.I)
_REPS = re.compile(r"(\d+)\s*reps", re.I)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def _get(sess: requests.Session, url: str, params: dict[str, Any]) -> dict:
    """GET with exponential backoff. Raises on final failure."""
    delay = 1.0
    last: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = sess.get(url, params=params, timeout=REQUEST_TIMEOUT_S)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001 - deliberate: retry everything
            last = exc
            if attempt == MAX_RETRIES:
                break
            log.warning("request failed (%s/%s): %s — retrying in %.1fs",
                        attempt, MAX_RETRIES, exc, delay)
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise RuntimeError(f"giving up on {url} {params}: {last}")


# ------------------------------------------------------------- parsing ----
def _to_cm(raw: str | None) -> float | None:
    if not raw:
        return None
    if m := _HEIGHT_IN.match(raw):
        return round(float(m.group(1)) * 2.54, 1)
    if m := _HEIGHT_CM.match(raw):
        return float(m.group(1))
    return None


def _to_kg(raw: str | None) -> float | None:
    if not raw:
        return None
    if m := _WEIGHT_LB.match(raw):
        return round(float(m.group(1)) * 0.453592, 1)
    if m := _WEIGHT_KG.match(raw):
        return float(m.group(1))
    return None


def _int(raw: Any) -> int | None:
    try:
        v = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return v


def _reps(breakdown: str | None) -> int | None:
    if not breakdown:
        return None
    if m := _REPS.search(breakdown):
        return int(m.group(1))
    return None


def _flatten(row: dict, year: int, division: int) -> dict | None:
    ent = row.get("entrant") or {}
    cid = ent.get("competitorId")
    if not cid:
        return None

    rec: dict[str, Any] = {
        "year": year,
        "division_id": division,
        "division": CF_DIVISIONS.get(division, str(division)),
        "competitor_id": str(cid),
        "name": ent.get("competitorName") or "",
        "gender": ent.get("gender") or "",
        "age": _int(ent.get("age")),
        "height_cm": _to_cm(ent.get("height")),
        "weight_kg": _to_kg(ent.get("weight")),
        "country": ent.get("countryOfOriginName") or "",
        "region": ent.get("regionName") or "",
        "affiliate_id": str(ent.get("affiliateId") or ""),
        "affiliate": ent.get("affiliateName") or "",
        "status": ent.get("status") or "",
        "overall_rank": _int(row.get("overallRank")),
        "overall_score": _int(row.get("overallScore")),
    }

    scored = 0
    for s in row.get("scores") or []:
        o = _int(s.get("ordinal"))
        if not o:
            continue
        valid = str(s.get("valid") or "") == "1"
        rank = _int(s.get("rank"))
        rec[f"wk{o}_rank"] = rank
        rec[f"wk{o}_display"] = s.get("scoreDisplay") or ""
        rec[f"wk{o}_reps"] = _reps(s.get("breakdown"))
        rec[f"wk{o}_time"] = _int(s.get("time")) or None
        rec[f"wk{o}_scaled"] = str(s.get("scaled") or "") == "1"
        rec[f"wk{o}_valid"] = valid
        rec[f"wk{o}_judge"] = (s.get("judge") or "").strip()
        rec[f"wk{o}_judge_aff"] = (s.get("affiliate") or "").strip()
        if valid and rank:
            scored += 1

    rec["workouts_scored"] = scored
    return rec


# ------------------------------------------------------------- crawling ----
def probe(year: int, division: int) -> dict:
    """One cheap request that reports field size without crawling it."""
    sess = _session()
    payload = _get(sess, f"{CF_API}/open/{year}/leaderboards",
                   {"division": division, "sort": 0, "page": 1})
    pg = payload.get("pagination") or {}
    return {
        "year": year,
        "division": division,
        "division_name": CF_DIVISIONS.get(division, str(division)),
        "total_pages": _int(pg.get("totalPages")) or 0,
        "total_competitors": _int(pg.get("totalCompetitors")) or 0,
        "rows_on_page": len(payload.get("leaderboardRows") or []),
    }


def iter_division(year: int, division: int, max_pages: int = 0,
                  progress_every: int = 100) -> Iterator[dict]:
    """Yield flattened athlete records for one division."""
    sess = _session()
    url = f"{CF_API}/open/{year}/leaderboards"

    first = _get(sess, url, {"division": division, "sort": 0, "page": 1})
    pg = first.get("pagination") or {}
    total_pages = _int(pg.get("totalPages")) or 1
    total_comp = _int(pg.get("totalCompetitors")) or 0
    if max_pages:
        total_pages = min(total_pages, max_pages)

    log.info("division %s (%s): %s athletes over %s pages",
             division, CF_DIVISIONS.get(division, division), total_comp, total_pages)

    for row in first.get("leaderboardRows") or []:
        if rec := _flatten(row, year, division):
            yield rec

    for page in range(2, total_pages + 1):
        time.sleep(REQUEST_DELAY_S)
        payload = _get(sess, url, {"division": division, "sort": 0, "page": page})
        rows = payload.get("leaderboardRows") or []
        if not rows:
            log.info("division %s: empty page %s, stopping early", division, page)
            break
        for row in rows:
            if rec := _flatten(row, year, division):
                yield rec
        if page % progress_every == 0:
            log.info("division %s: page %s/%s", division, page, total_pages)


def fetch(year: int, divisions: list[int], max_pages: int = 0) -> pd.DataFrame:
    """Crawl the given divisions into a single tidy frame."""
    frames: list[pd.DataFrame] = []
    for d in divisions:
        rows = list(iter_division(year, d, max_pages=max_pages))
        if not rows:
            log.warning("division %s returned nothing", d)
            continue
        frames.append(pd.DataFrame(rows))
        log.info("division %s: %s rows collected", d, len(rows))
    if not frames:
        raise RuntimeError("no data collected from any division")
    df = pd.concat(frames, ignore_index=True)
    return _postprocess(df)


def _postprocess(df: pd.DataFrame) -> pd.DataFrame:
    """Derived columns every angle can rely on existing.

    Percentiles are computed over the population the stated method claims:
    a workout's percentile ranks only athletes who posted a valid score on
    that workout, and the overall percentile ranks only finishers. Ranking
    over everyone instead would quietly fold the people who quit into the
    denominator and flatter the whole field.

    Ranking within the frame (rather than dividing by the published field
    size) also means these percentiles stay correct for a systematic sample
    of the leaderboard, not just a complete crawl.
    """
    wk_cols = sorted({c.split("_")[0] for c in df.columns
                      if c.startswith("wk") and f"{c.split('_')[0]}_rank" in df.columns})

    n_wk = len(wk_cols)
    if "workouts_scored" not in df.columns:
        df["workouts_scored"] = sum(
            df[f"{wk}_rank"].notna().astype(int) for wk in wk_cols
        ) if wk_cols else 0

    for wk in wk_cols:
        rank_col, pct_col = f"{wk}_rank", f"{wk}_pct"
        scored = df[rank_col].notna()
        df[pct_col] = pd.Series(pd.NA, index=df.index, dtype="Float64")
        if scored.any():
            df.loc[scored, pct_col] = (
                df.loc[scored].groupby("division_id")[rank_col].rank(pct=True)
            )

    if "overall_rank" in df.columns:
        finisher = (df["workouts_scored"] >= n_wk) & df["overall_rank"].notna()
        df["overall_pct"] = pd.Series(pd.NA, index=df.index, dtype="Float64")
        if finisher.any():
            df.loc[finisher, "overall_pct"] = (
                df.loc[finisher].groupby("division_id")["overall_rank"].rank(pct=True)
            )

    # Body composition, guarded against the many blank profiles.
    h = df.get("height_cm")
    w = df.get("weight_kg")
    if h is not None and w is not None:
        valid = h.notna() & w.notna() & h.between(120, 230) & w.between(35, 200)
        df["bmi"] = pd.Series(pd.NA, index=df.index, dtype="Float64")
        df.loc[valid, "bmi"] = (w[valid] / (h[valid] / 100) ** 2).round(1)

    df["age_band"] = pd.cut(
        df["age"],
        bins=[0, 17, 24, 29, 34, 39, 44, 49, 54, 59, 200],
        labels=["<18", "18-24", "25-29", "30-34", "35-39",
                "40-44", "45-49", "50-54", "55-59", "60+"],
        right=True,
    )
    return df
