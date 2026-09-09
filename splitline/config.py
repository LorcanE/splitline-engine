"""Central configuration. Everything tunable lives here or in env vars."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
POSTS = ROOT / "posts"
DIST = ROOT / "dist"
STATE = ROOT / "state"

for _p in (DATA, POSTS, DIST, STATE):
    _p.mkdir(parents=True, exist_ok=True)


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def env_bool(key: str, default: bool = False) -> bool:
    v = env(key).lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- brand ----
BRAND = "Splitline"
TAGLINE = "Hybrid fitness, measured honestly."
SITE = env("SPLITLINE_SITE", "https://splitline.beehiiv.com")
PRODUCT_URL = env("SPLITLINE_PRODUCT_URL", "")

# ------------------------------------------------------------ data source ----
CF_API = "https://c3po.crossfit.com/api/competitions/v2/competitions"
CF_YEAR = int(env("CF_YEAR", "2026"))

# CrossFit division ids. Verified against the public leaderboard.
CF_DIVISIONS = {
    1: "Men",
    2: "Women",
    3: "Men 35-39",
    4: "Women 35-39",
    5: "Men 40-44",
    6: "Women 40-44",
    7: "Men 45-49",
    8: "Women 45-49",
    9: "Men 50-54",
    10: "Women 50-54",
    11: "Men 55-59",
    12: "Women 55-59",
    13: "Men 60+",
    14: "Women 60+",
    15: "Boys 14-15",
    16: "Girls 14-15",
    17: "Boys 16-17",
    18: "Girls 16-17",
}

# Divisions pulled by default. Open Men/Women are the bulk of the field and
# carry every age group inside the `age` field anyway, so they are enough for
# most angles. Masters divisions add resolution for age-specific work.
CF_DEFAULT_DIVISIONS = [int(x) for x in env("CF_DIVISIONS", "1,2").split(",") if x.strip()]

# Politeness. The public leaderboard is not rate-limit documented; this is a
# deliberately conservative crawl that still finishes a full ingest inside a
# single GitHub Actions job.
REQUEST_DELAY_S = float(env("CF_REQUEST_DELAY", "0.25"))
REQUEST_TIMEOUT_S = float(env("CF_TIMEOUT", "30"))
MAX_RETRIES = int(env("CF_MAX_RETRIES", "5"))
USER_AGENT = env(
    "CF_USER_AGENT",
    "SplitlineResearchBot/1.0 (+https://splitline.beehiiv.com; contact splitlinehq@gmail.com)",
)

# Cap for cheap/dry runs. 0 = no cap.
MAX_PAGES = int(env("CF_MAX_PAGES", "0"))

# ------------------------------------------------------------- editorial ----
# A finding must clear these bars or the runner refuses to publish it and
# falls through to the next angle. This is what stops the newsletter shipping
# noise on a slow week.
MIN_SAMPLE = int(env("MIN_SAMPLE", "500"))
MIN_EFFECT = float(env("MIN_EFFECT", "0.08"))  # normalised effect size floor

# ------------------------------------------------------------- delivery ----
BEEHIIV_API_KEY = env("BEEHIIV_API_KEY")
BEEHIIV_PUB_ID = env("BEEHIIV_PUB_ID", "pub_385f736e-c99e-4e63-80ad-46fa8a31d552")
# The create-post endpoint is Max/Enterprise only. Leave off until the plan
# supports it; the pipeline delivers a paste-ready post either way.
BEEHIIV_AUTOPOST = env_bool("BEEHIIV_AUTOPOST", False)
BEEHIIV_STATUS = env("BEEHIIV_STATUS", "draft")  # draft | confirmed | scheduled

SMTP_HOST = env("SMTP_HOST")
SMTP_PORT = int(env("SMTP_PORT", "587"))
SMTP_USER = env("SMTP_USER")
SMTP_PASS = env("SMTP_PASS")
NOTIFY_EMAIL = env("NOTIFY_EMAIL")


@dataclass
class RunConfig:
    """Per-run knobs, set by the CLI."""

    year: int = CF_YEAR
    divisions: list[int] = field(default_factory=lambda: list(CF_DEFAULT_DIVISIONS))
    max_pages: int = MAX_PAGES
    dry_run: bool = False
    force_angle: str | None = None
    refresh_data: bool = False
