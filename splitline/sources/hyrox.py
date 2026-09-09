"""HYROX results ingester.

Verified against the live site on 2026-09-09. Unlike the CrossFit Open, HYROX
publishes no JSON API — results are server-rendered HTML from a Mika Timing
installation — so this module parses the two page types that matter.

**Roster (one request per 100 athletes)**

    GET /season-{s}/?page={n}&event={eventId}&num_results=100&pid=list
        &search[sex]={M|W}&ranking=time_finish_netto

  Each `li.list-group-item` carries place, name, nation, age group and total
  time, and its anchor holds `idp=` — the stable athlete id used to join
  everything else. Note that a given event id is usually single-sex: at most
  venues the men race Saturday and the women Sunday, under different event
  ids, and asking for the other sex returns zero results rather than an error.

**Detail (one request per athlete)**

    GET /season-{s}/?content=detail&pid=list&idp={idp}&event={eventId}

  A two-column split table holding all eight runs, all eight stations, and —
  the reason this dataset is worth having — **roxzone time**, the total spent
  in transition. Everyone in the sport argues about the roxzone; almost nobody
  measures it, because it is only visible one athlete at a time.

Sorting the roster by a station (`ranking=time_11`) reorders the list but
still prints total time, so splits genuinely require the detail page. Budget
one request per athlete and crawl politely.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Iterable, Iterator

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import MAX_RETRIES, REQUEST_TIMEOUT_S, USER_AGENT

log = logging.getLogger(__name__)

BASE = "https://results.hyrox.com"

# Station labels as the site prints them, mapped to stable column names.
STATIONS = {
    "1000m SkiErg": "ski",
    "50m Sled Push": "sled_push",
    "50m Sled Pull": "sled_pull",
    "80m Burpee Broad Jump": "burpees",
    "1000m Row": "row",
    "200m Farmers Carry": "farmers",
    "100m Sandbag Lunges": "lunges",
    "Wall Balls": "wall_balls",
}
RUNS = {f"Running {i}": f"run{i}" for i in range(1, 9)}
EXTRAS = {
    "Roxzone Time": "roxzone",
    "Run Total": "run_total",
    "Best Run Lap": "best_run",
    "Overall Time": "total",
}

_IDP = re.compile(r"idp=([A-Za-z0-9]+)")
_HMS = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})$")
_MS = re.compile(r"^(\d{1,3}):(\d{2})$")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT,
                      "Accept": "text/html,application/xhtml+xml"})
    return s


def _get(sess: requests.Session, path: str, params: dict) -> str | None:
    delay = 1.0
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = sess.get(f"{BASE}{path}", params=params, timeout=REQUEST_TIMEOUT_S)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.text
        except Exception as exc:  # noqa: BLE001
            if attempt == MAX_RETRIES:
                log.warning("giving up on %s %s: %s", path, params, exc)
                return None
            time.sleep(delay)
            delay = min(delay * 2, 30)
    return None


def to_seconds(text: str) -> float | None:
    """'00:58:35' or '4:07' to seconds. Returns None for '–' and blanks."""
    t = (text or "").strip()
    if not t or t in {"-", "–", "—"}:
        return None
    if m := _HMS.match(t):
        h, mi, s = (int(x) for x in m.groups())
        return h * 3600 + mi * 60 + s
    if m := _MS.match(t):
        mi, s = (int(x) for x in m.groups())
        return mi * 60 + s
    return None


def _clean(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


# ------------------------------------------------------------- roster ----
def roster(season: int, event: str, sex: str, delay: float = 0.3,
           max_pages: int = 60) -> list[dict]:
    """Every athlete in one event/sex, with the id needed to fetch splits."""
    sess = _session()
    out: list[dict] = []
    seen: set[str] = set()

    for page in range(1, max_pages + 1):
        html = _get(sess, f"/season-{season}/", {
            "page": page, "event": event, "num_results": 100,
            "pid": "list", "search[sex]": sex, "ranking": "time_finish_netto",
        })
        if not html:
            break
        soup = BeautifulSoup(html, "lxml")
        added = 0
        for li in soup.select("li.list-group-item"):
            if li.select_one(".list-info__text"):
                continue  # the header row that reports the result count
            a = li.find("a", href=True)
            if not a:
                continue
            m = _IDP.search(a["href"])
            if not m or m.group(1) in seen:
                continue
            idp = m.group(1)
            seen.add(idp)

            def field(sel: str, strip: str = "") -> str:
                node = li.select_one(sel)
                if not node:
                    return ""
                txt = _clean(node)
                return txt.replace(strip, "").strip() if strip else txt

            out.append({
                "idp": idp,
                "event": event,
                "season": season,
                "sex": sex,
                "age_group": field(".type-age_class", "Age Group"),
                "nation": field(".type-nation_flag", "Nat"),
                "total_display": field(".type-time", "Total"),
                "place": _int(field(".type-place.place-primary")),
            })
            added += 1
        if added == 0:
            break
        log.info("event %s %s: page %s, %s athletes so far", event, sex, page, len(out))
        time.sleep(delay)
    return out


def _int(s: str) -> int | None:
    try:
        return int(re.sub(r"[^\d]", "", s))
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------- detail ----
def splits(season: int, event: str, idp: str,
           sess: requests.Session | None = None) -> dict | None:
    """Every run, station and transition for one athlete."""
    sess = sess or _session()
    html = _get(sess, f"/season-{season}/", {
        "content": "detail", "pid": "list", "idp": idp, "event": event,
    })
    if not html:
        return None

    soup = BeautifulSoup(html, "lxml")
    rec: dict = {"idp": idp, "event": event, "season": season}

    for tr in soup.find_all("tr"):
        cells = [_clean(c) for c in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        if len(cells) < 2:
            continue
        label, value = cells[0], cells[1]
        place = cells[2] if len(cells) > 2 else ""

        if label in STATIONS:
            key = STATIONS[label]
            rec[key] = to_seconds(value)
            rec[f"{key}_place"] = _int(place)
        elif label in RUNS:
            rec[RUNS[label]] = to_seconds(value)
        elif label in EXTRAS:
            key = EXTRAS[label]
            rec[key] = to_seconds(value)
            if place:
                rec[f"{key}_place"] = _int(place)
        elif label == "Age Group":
            rec["age_group"] = value
        elif label == "Nat":
            rec["nation"] = value
        elif label == "Division":
            rec["division"] = value
        elif label.startswith("Rank (M/W)"):
            rec["place"] = _int(value)

    return rec if rec.get("total") else None


def fetch_event(season: int, event: str, sexes: Iterable[str] = ("M", "W"),
                sample: int = 0, delay: float = 0.25) -> pd.DataFrame:
    """Crawl one event into a tidy frame of athletes and their splits.

    `sample` takes a systematic sample of that many athletes per sex, drawn at
    even intervals down the finishing order, instead of the whole field. Even
    spacing over finishing place is what keeps split percentiles unbiased.
    """
    sess = _session()
    records: list[dict] = []

    for sex in sexes:
        people = roster(season, event, sex, delay=delay)
        if not people:
            log.info("event %s has no %s field — most venues run the sexes on "
                     "separate days under different event ids", event, sex)
            continue
        if sample and sample < len(people):
            step = len(people) / sample
            people = [people[int(i * step)] for i in range(sample)]
            log.info("event %s %s: sampling %s of the field", event, sex, len(people))

        for i, person in enumerate(people, 1):
            detail = splits(season, event, person["idp"], sess=sess)
            if detail:
                records.append({**person, **detail})
            if i % 100 == 0:
                log.info("event %s %s: %s/%s splits", event, sex, i, len(people))
            time.sleep(delay)

    if not records:
        raise RuntimeError(f"no results collected for event {event}")
    return _postprocess(pd.DataFrame(records))


def _postprocess(df: pd.DataFrame) -> pd.DataFrame:
    """Derived columns the pacing analysis depends on."""
    station_cols = [c for c in STATIONS.values() if c in df.columns]
    run_cols = [c for c in RUNS.values() if c in df.columns]

    if station_cols:
        df["station_total"] = df[station_cols].sum(axis=1, min_count=1)
    if run_cols:
        df["run_total_calc"] = df[run_cols].sum(axis=1, min_count=1)
        df["run_spread"] = df[run_cols].max(axis=1) - df[run_cols].min(axis=1)
        # Positive means the athlete slowed down over the race.
        if "run1" in df.columns and "run8" in df.columns:
            df["fade"] = df["run8"] - df["run1"]

    if "total" in df.columns:
        for col in station_cols + run_cols + ["roxzone"]:
            if col in df.columns:
                df[f"{col}_share"] = df[col] / df["total"]
        # Finish-time bands are how a pacing table is read: an athlete picks
        # their target time and reads the row.
        df["target_band"] = pd.cut(
            df["total"] / 60,
            bins=[0, 60, 70, 80, 90, 100, 110, 120, 140, 1000],
            labels=["<60", "60-70", "70-80", "80-90", "90-100",
                    "100-110", "110-120", "120-140", "140+"],
        )
    return df
