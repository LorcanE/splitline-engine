"""beehiiv Create Post delivery.

POST /v2/publications/{publicationId}/posts
Authorization: Bearer <api key>

Requires a Max or Enterprise publication. On any lower plan the call returns a
403 and the pipeline falls back to paste-in publishing — which is why this
module never raises on failure, it only reports.

Note (beehiiv, effective 2026-08-06): posts created without an explicit
`status` now default to draft rather than publishing. We always send status
explicitly so behaviour does not drift with their defaults.
"""
from __future__ import annotations

import logging
from pathlib import Path

import requests

from ..config import (
    BEEHIIV_API_KEY,
    BEEHIIV_PUB_ID,
    BEEHIIV_STATUS,
    REQUEST_TIMEOUT_S,
)

log = logging.getLogger(__name__)

API = "https://api.beehiiv.com/v2"


def create_post(meta: dict, post_dir: Path) -> dict:
    body = (post_dir / "email.html").read_text(encoding="utf-8")
    payload = {
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "body_content": body,
        "status": BEEHIIV_STATUS,
    }
    if base := meta.get("asset_base"):
        if assets := meta.get("assets"):
            payload["thumbnail_image_url"] = f"{base}/{meta['slug']}/{assets[0]}"

    try:
        r = requests.post(
            f"{API}/publications/{BEEHIIV_PUB_ID}/posts",
            json=payload,
            headers={
                "Authorization": f"Bearer {BEEHIIV_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=REQUEST_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("beehiiv request failed: %s", exc)
        return {"channel": "beehiiv", "ok": False, "detail": f"request failed: {exc}"}

    if r.status_code in (200, 201, 202):
        data = (r.json() or {}).get("data", {})
        return {
            "channel": "beehiiv",
            "ok": True,
            "status": BEEHIIV_STATUS,
            "post_id": data.get("id", ""),
            "preview_url": data.get("preview_url", ""),
            "detail": f"created as {BEEHIIV_STATUS}",
        }

    hint = ""
    if r.status_code == 403:
        hint = (" — the create-post endpoint is Max/Enterprise only; leave "
                "BEEHIIV_AUTOPOST off and paste the post in instead.")
    return {
        "channel": "beehiiv",
        "ok": False,
        "detail": f"HTTP {r.status_code}: {r.text[:400]}{hint}",
    }
