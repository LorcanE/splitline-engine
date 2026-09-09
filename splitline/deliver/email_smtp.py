"""Ready-to-publish email.

On any beehiiv plan below Max, this is the delivery that matters: the finished
post arrives in Lorcan's inbox, rendered, with the HTML attached. Publishing is
then select-all, copy, paste, send — about sixty seconds of work a week, with
no analysis, writing or chart-making in it.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from ..config import (
    BRAND,
    NOTIFY_EMAIL,
    SMTP_HOST,
    SMTP_PASS,
    SMTP_PORT,
    SMTP_USER,
)

log = logging.getLogger(__name__)


def send_ready_to_publish(meta: dict, post_dir: Path) -> dict:
    html_body = (post_dir / "email.html").read_text(encoding="utf-8")

    msg = EmailMessage()
    msg["Subject"] = f"[{BRAND}] Ready to publish — {meta['title']}"
    msg["From"] = SMTP_USER
    msg["To"] = NOTIFY_EMAIL

    plain = (
        f"{meta['title']}\n{meta['subtitle']}\n\n"
        f"Sample: {meta['n']:,} athletes   Effect: {meta['effect']}\n\n"
        f"The rendered post is in the HTML part of this email and attached as "
        f"email.html. Paste it into a new beehiiv post, set the title and "
        f"subtitle above, and send.\n"
    )
    msg.set_content(plain)

    banner = (
        '<div style="background:#12161C;color:#fff;padding:16px 20px;'
        'font-family:-apple-system,Helvetica,Arial,sans-serif;">'
        f'<div style="font-size:13px;opacity:.7;letter-spacing:.06em;'
        f'text-transform:uppercase;">{BRAND} · ready to publish</div>'
        f'<div style="font-size:19px;font-weight:700;margin-top:6px;">'
        f'{meta["title"]}</div>'
        f'<div style="font-size:14px;opacity:.75;margin-top:4px;">'
        f'{meta["subtitle"]}</div>'
        f'<div style="font-size:13px;opacity:.6;margin-top:10px;">'
        f'n = {meta["n"]:,} · effect = {meta["effect"]}</div></div>'
    )
    msg.add_alternative(
        f'<div style="max-width:680px;margin:0 auto;">{banner}'
        f'<div style="padding:0 20px;">{html_body}</div></div>',
        subtype="html",
    )
    msg.add_attachment(
        html_body.encode("utf-8"),
        maintype="text", subtype="html", filename="email.html",
    )
    for name in meta.get("assets", []):
        p = post_dir / name
        if p.exists():
            msg.add_attachment(p.read_bytes(), maintype="image",
                               subtype="png", filename=name)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=45) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        log.warning("smtp send failed: %s", exc)
        return {"channel": "email", "ok": False, "detail": f"send failed: {exc}"}

    return {"channel": "email", "ok": True,
            "detail": f"ready-to-publish email sent to {NOTIFY_EMAIL}"}
