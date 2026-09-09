"""Splitline visual identity — one place, used by charts, posts and product.

Charts are built to survive an email client: no transparency, no web fonts,
readable at 600px wide on a phone, and legible when a reader forwards a
screenshot of it.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

# ---------------------------------------------------------------- palette ----
INK = "#12161C"       # near-black, body text
MUTED = "#6B7480"     # axis labels, secondary text
RULE = "#DDE1E6"      # gridlines, hairlines
PAPER = "#FFFFFF"     # chart background
WASH = "#F5F6F8"      # panel fill

# Categorical series. Chosen for separation in both colour and lightness so
# the charts still read when printed grey or viewed by a colour-blind reader.
SERIES = [
    "#1B4965",  # deep blue
    "#E4572E",  # signal orange
    "#3E8E7E",  # teal
    "#B08968",  # clay
    "#6D6A75",  # slate
]
ACCENT = "#E4572E"
BLUE = "#1B4965"

# Sequential ramp for distributions / heat.
RAMP = ["#EAF0F4", "#C3D4DF", "#8FB0C4", "#5C8AA7", "#33697F", "#1B4965"]

FONT_STACK = ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]


def _available_font() -> str:
    have = {f.name for f in font_manager.fontManager.ttflist}
    for name in FONT_STACK:
        if name in have:
            return name
    return "DejaVu Sans"


def apply_theme() -> None:
    """Install the Splitline matplotlib theme process-wide."""
    plt.rcParams.update(
        {
            "font.family": _available_font(),
            "figure.facecolor": PAPER,
            "axes.facecolor": PAPER,
            "savefig.facecolor": PAPER,
            "savefig.bbox": "tight",
            "savefig.dpi": 200,
            "figure.dpi": 110,
            "axes.edgecolor": RULE,
            "axes.linewidth": 1.0,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": RULE,
            "grid.linewidth": 0.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.labelcolor": MUTED,
            "axes.labelsize": 10,
            "axes.titlesize": 13,
            "axes.titleweight": "bold",
            "axes.titlecolor": INK,
            "axes.titlelocation": "left",
            "axes.titlepad": 12,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "legend.frameon": False,
            "legend.fontsize": 9,
            "lines.linewidth": 2.2,
            "lines.solid_capstyle": "round",
        }
    )


def caption(ax, text: str) -> None:
    """Source line under a chart. Every Splitline chart carries one."""
    ax.annotate(
        text,
        xy=(0, -0.16),
        xycoords="axes fraction",
        fontsize=8,
        color=MUTED,
        va="top",
        ha="left",
        annotate_clip=False,
    )


# ------------------------------------------------------------ email HTML ----
# beehiiv strips <style> and <link>, so every rule below is inlined at render
# time. These are the tokens the renderer inlines.
CSS = {
    "body": f"margin:0;padding:0;color:{INK};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;font-size:17px;line-height:1.62;",
    "h2": f"margin:34px 0 10px;font-size:22px;line-height:1.3;font-weight:700;color:{INK};letter-spacing:-0.01em;",
    "h3": f"margin:26px 0 8px;font-size:17px;font-weight:700;color:{INK};",
    "p": f"margin:0 0 18px;color:{INK};",
    "lede": f"margin:0 0 22px;font-size:19px;line-height:1.55;color:{INK};",
    "img": "display:block;width:100%;max-width:100%;height:auto;margin:26px 0 8px;border-radius:6px;",
    "figcap": f"margin:0 0 26px;font-size:13px;line-height:1.5;color:{MUTED};",
    "callout": f"margin:26px 0;padding:16px 18px;background:{WASH};border-left:3px solid {ACCENT};font-size:16px;line-height:1.55;",
    "table": f"width:100%;border-collapse:collapse;margin:22px 0;font-size:15px;color:{INK};",
    "th": f"text-align:left;padding:9px 10px;border-bottom:2px solid {INK};font-size:12px;letter-spacing:0.06em;text-transform:uppercase;color:{MUTED};font-weight:700;",
    "td": f"padding:9px 10px;border-bottom:1px solid {RULE};",
    "tdnum": f"padding:9px 10px;border-bottom:1px solid {RULE};text-align:right;font-variant-numeric:tabular-nums;",
    "rule": f"border:0;border-top:1px solid {RULE};margin:34px 0;",
    "small": f"font-size:13px;line-height:1.55;color:{MUTED};",
    "cta": f"display:inline-block;padding:13px 22px;background:{ACCENT};color:#fff;text-decoration:none;border-radius:6px;font-weight:700;font-size:16px;",
}
