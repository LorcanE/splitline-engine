"""Parquet-backed dataset store.

The store is the moat. Every ingest is kept, so after a few seasons Splitline
holds a longitudinal record of the Open that nobody else has assembled — which
is what makes both the newsletter and the paid product hard to copy.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import DATA, STATE

log = logging.getLogger(__name__)

MANIFEST = DATA / "manifest.json"


def _have_parquet() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        try:
            import fastparquet  # noqa: F401
            return True
        except ImportError:
            return False


def _parquet_path(year: int) -> Path:
    return DATA / f"open_{year}.parquet"


def _csv_path(year: int) -> Path:
    return DATA / f"open_{year}.csv.gz"


def _path(year: int) -> Path:
    """The dataset for `year`, whichever format it was written in.

    Parquet is preferred — it is a third of the size and keeps dtypes — but a
    gzipped CSV fallback means the engine runs anywhere Python and pandas run,
    including environments where pyarrow cannot be installed.
    """
    pq, csv = _parquet_path(year), _csv_path(year)
    if pq.exists():
        return pq
    if csv.exists():
        return csv
    return pq if _have_parquet() else csv


def save(df: pd.DataFrame, year: int) -> Path:
    if _have_parquet():
        p = _parquet_path(year)
        df.to_parquet(p, index=False, compression="zstd")
    else:
        p = _csv_path(year)
        df.to_csv(p, index=False, compression="gzip")
        log.info("pyarrow not available — wrote gzipped CSV instead of parquet")
    _touch_manifest(year, len(df))
    log.info("wrote %s rows to %s (%.1f MB)", len(df), p.name,
             p.stat().st_size / 1e6)
    return p


# Columns that must survive a CSV round trip with the right dtype.
_CATEGORICAL = ["age_band"]
_BOOLEAN_SUFFIXES = ("_valid", "_scaled")


def load(year: int) -> pd.DataFrame:
    p = _path(year)
    if not p.exists():
        raise FileNotFoundError(
            f"no cached dataset for {year}. "
            f"Run `python scripts/ingest.py --year {year}` first."
        )
    if p.suffix == ".parquet":
        return pd.read_parquet(p)

    df = pd.read_csv(p, compression="gzip", low_memory=False)
    for col in _CATEGORICAL:
        if col in df.columns:
            df[col] = df[col].astype("category")
    for col in df.columns:
        if col.endswith(_BOOLEAN_SUFFIXES):
            df[col] = df[col].astype("boolean")
    return df


def exists(year: int) -> bool:
    return _parquet_path(year).exists() or _csv_path(year).exists()


def age_days(year: int) -> float:
    p = _path(year)
    if not p.exists():
        return float("inf")
    mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    return (datetime.now(timezone.utc) - mtime).total_seconds() / 86400


def years_available() -> list[int]:
    out = set()
    for pattern in ("open_*.parquet", "open_*.csv.gz"):
        for p in DATA.glob(pattern):
            stem = p.name.split(".")[0]
            try:
                out.add(int(stem.split("_")[1]))
            except (IndexError, ValueError):
                continue
    return sorted(out)


def _touch_manifest(year: int, rows: int) -> None:
    m = {}
    if MANIFEST.exists():
        try:
            m = json.loads(MANIFEST.read_text())
        except json.JSONDecodeError:
            m = {}
    m[str(year)] = {
        "rows": int(rows),
        "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    MANIFEST.write_text(json.dumps(m, indent=2, sort_keys=True))


# ------------------------------------------------------- editorial state ----
USED = STATE / "used_angles.json"


def used_angles() -> list[str]:
    if not USED.exists():
        return []
    try:
        return json.loads(USED.read_text()).get("used", [])
    except json.JSONDecodeError:
        return []


def mark_used(slug: str) -> None:
    used = used_angles()
    used.append(slug)
    USED.write_text(json.dumps(
        {"used": used, "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")},
        indent=2,
    ))


def reset_angles() -> None:
    if USED.exists():
        USED.unlink()


def sample_meta(year: int) -> dict | None:
    """Sampling manifest for `year`, or None when the dataset is a full crawl."""
    p = DATA / f"open_{year}.SAMPLE.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None
