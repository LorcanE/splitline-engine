"""Renders a Finding into the two things a publish needs:

  * `email.html` — beehiiv-safe HTML with every style inlined, because beehiiv
    strips <style> and <link> during sanitisation.
  * `post.json`  — title, subtitle, preview text, asset list, stats.

Chart images must be reachable over https by the time the email sends, so the
renderer rewrites local chart paths to ASSET_BASE. Point ASSET_BASE at the raw
GitHub URL for the repo, or better, at a Netlify path on your own domain.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

from ..analysis.finding import Block, Finding
from ..config import BRAND, POSTS, PRODUCT_URL, SITE, env
from ..style import CSS

ASSET_BASE = env("ASSET_BASE", "").rstrip("/")


def _esc(s: str) -> str:
    """Escape text but keep the small set of inline tags the angles use."""
    out = html.escape(s, quote=False)
    for tag in ("em", "strong", "b", "i", "code"):
        out = out.replace(f"&lt;{tag}&gt;", f"<{tag}>")
        out = out.replace(f"&lt;/{tag}&gt;", f"</{tag}>")
    return out


def _asset_url(local_path: str, rel_dir: str) -> str:
    """Public URL for a chart image.

    `rel_dir` is the post's directory relative to posts/ — e.g.
    "2026-09-09/sex-shape". It must match exactly where the workflow commits
    the file, date folder included: a URL missing that folder returns 404 and
    every chart in the email renders as a broken image, which is invisible
    when testing locally because the file is right there on disk.
    """
    name = Path(local_path).name
    if not ASSET_BASE:
        # No host configured — leave a clearly broken relative path rather than
        # a silently wrong absolute one, so a dry run makes the gap obvious.
        return f"./{name}"
    return f"{ASSET_BASE}/{rel_dir}/{name}"


def _block_html(b: Block, rel_dir: str) -> str:
    if b.kind == "lede":
        return f'<p style="{CSS["lede"]}">{_esc(b.text)}</p>'
    if b.kind == "p":
        return f'<p style="{CSS["p"]}">{_esc(b.text)}</p>'
    if b.kind == "h2":
        return f'<h2 style="{CSS["h2"]}">{_esc(b.text)}</h2>'
    if b.kind == "h3":
        return f'<h3 style="{CSS["h3"]}">{_esc(b.text)}</h3>'
    if b.kind == "rule":
        return f'<hr style="{CSS["rule"]}">'
    if b.kind == "callout":
        return f'<div style="{CSS["callout"]}">{_esc(b.text)}</div>'
    if b.kind == "chart":
        url = _asset_url(b.src, rel_dir)
        cap = (f'<p style="{CSS["figcap"]}">{_esc(b.caption)}</p>'
               if b.caption else "")
        return (f'<img src="{html.escape(url, quote=True)}" '
                f'alt="{html.escape(b.alt, quote=True)}" '
                f'style="{CSS["img"]}">{cap}')
    if b.kind == "table":
        head = "".join(f'<th style="{CSS["th"]}">{_esc(str(c))}</th>'
                       for c in b.columns)
        body = []
        for row in b.rows:
            cells = []
            for i, cell in enumerate(row):
                style = CSS["td"] if i < b.numeric_from else CSS["tdnum"]
                cells.append(f'<td style="{style}">{_esc(str(cell))}</td>')
            body.append(f"<tr>{''.join(cells)}</tr>")
        return (f'<table style="{CSS["table"]}"><thead><tr>{head}</tr></thead>'
                f'<tbody>{"".join(body)}</tbody></table>')
    return ""


def _preview_text(f: Finding) -> str:
    for b in f.blocks:
        if b.kind in ("lede", "p"):
            plain = re.sub(r"<[^>]+>", "", b.text)
            return (plain[:180].rsplit(" ", 1)[0] + "…") if len(plain) > 180 else plain
    return f.subtitle


DEFAULT_SOURCE = "the public CrossFit Games Open leaderboard"


def _footer(slug: str, dataset_note: str = "",
            source: str = DEFAULT_SOURCE) -> str:
    bits = [
        f'<hr style="{CSS["rule"]}">',
        f'<p style="{CSS["small"]}">Every number above is computed from '
        f'{html.escape(source)}. The analysis code and the '
        f'exact field definitions are the same ones {BRAND} uses for every '
        f'piece — if a figure looks wrong, reply and tell us, and we will '
        f'publish the correction.</p>',
    ]
    if dataset_note:
        bits.append(f'<p style="{CSS["small"]}">{html.escape(dataset_note)}</p>')
    if PRODUCT_URL:
        bits.append(
            f'<p style="margin:26px 0;"><a href="{html.escape(PRODUCT_URL, quote=True)}" '
            f'style="{CSS["cta"]}">Get the full dataset &amp; race model →</a></p>'
        )
    bits.append(
        f'<p style="{CSS["small"]}">{BRAND} · '
        f'<a href="{html.escape(SITE, quote=True)}" style="color:inherit;">'
        f'{html.escape(SITE.replace("https://", ""), quote=True)}</a></p>'
    )
    return "".join(bits)


def render(f: Finding, out_dir: Path, dataset_note: str = "",
           source: str = DEFAULT_SOURCE) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    # The URL must mirror the committed path exactly, date folder included.
    try:
        rel_dir = out_dir.resolve().relative_to(POSTS.resolve()).as_posix()
    except ValueError:
        rel_dir = out_dir.name
    body = "".join(_block_html(b, rel_dir) for b in f.blocks)
    body += _footer(f.slug, dataset_note, source)

    email_html = (
        f'<div style="{CSS["body"]}">'
        f'<p style="{CSS["small"]}">{date.today():%d %B %Y} · {BRAND}</p>'
        f"{body}</div>"
    )

    (out_dir / "email.html").write_text(email_html, encoding="utf-8")

    meta = {
        "slug": f.slug,
        "title": f.headline,
        "subtitle": f.subtitle,
        "preview_text": _preview_text(f),
        "date": date.today().isoformat(),
        "n": f.n,
        "effect": round(f.effect, 4),
        "stats": f.stats,
        "assets": [Path(b.src).name for b in f.blocks if b.kind == "chart"],
        "asset_base": ASSET_BASE,
        "asset_dir": rel_dir,
        "dataset_note": dataset_note,
        "source": source,
    }
    (out_dir / "post.json").write_text(json.dumps(meta, indent=2, default=str),
                                       encoding="utf-8")

    # A standalone previewable page — useful for eyeballing before publish and
    # for hosting the piece on Netlify as the canonical web version.
    preview = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(f.headline)}</title></head>"
        "<body style='margin:0;background:#F5F6F8;'>"
        "<div style='max-width:680px;margin:0 auto;padding:40px 22px;background:#fff;'>"
        f"<h1 style='font-size:31px;line-height:1.22;margin:0 0 10px;'>{_esc(f.headline)}</h1>"
        f"<p style='font-size:18px;color:#6B7480;margin:0 0 30px;'>{_esc(f.subtitle)}</p>"
        f"{email_html}</div></body></html>"
    )
    (out_dir / "preview.html").write_text(preview, encoding="utf-8")
    return meta
