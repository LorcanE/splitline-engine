"""Delivery back-ends.

The pipeline never depends on any single one of these succeeding. It always
writes the post to disk first; delivery is best-effort on top of that, and
every back-end reports what it did so the run summary is honest about where
the post actually ended up.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .. import config

log = logging.getLogger(__name__)


def deliver_all(meta: dict, post_dir: Path) -> list[dict]:
    """Try every configured back-end. Returns a result per attempt."""
    results: list[dict] = []

    if config.BEEHIIV_AUTOPOST and config.BEEHIIV_API_KEY:
        from .beehiiv import create_post
        results.append(create_post(meta, post_dir))
    else:
        results.append({
            "channel": "beehiiv",
            "ok": False,
            "skipped": True,
            "detail": "BEEHIIV_AUTOPOST is off (the create-post endpoint needs "
                      "a Max or Enterprise plan). Post written to disk for "
                      "paste-in publishing.",
        })

    if config.SMTP_HOST and config.NOTIFY_EMAIL:
        from .email_smtp import send_ready_to_publish
        results.append(send_ready_to_publish(meta, post_dir))
    else:
        results.append({
            "channel": "email",
            "ok": False,
            "skipped": True,
            "detail": "SMTP not configured; skipping the ready-to-publish email.",
        })

    return results
