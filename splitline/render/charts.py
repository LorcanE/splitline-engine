"""Chart builders. Every function saves a PNG and returns its path.

Sized for a phone. An email column is about 350px wide on mobile, so charts
are rendered ~1100px with deliberately large type: the browser downscales by
roughly 3x and the labels stay readable at the size people actually see.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from ..style import ACCENT, BLUE, INK, MUTED, RAMP, RULE, SERIES, WASH, apply_theme

apply_theme()

# Set per run by the runner. A chart citing the wrong sport is worse than a
# chart with no citation at all.
SOURCE_LINE = "Splitline"


def set_source(text: str) -> None:
    global SOURCE_LINE
    SOURCE_LINE = f"Splitline · source: {text}"


def _finish(fig, ax, out: Path, source: str | None = None) -> str:
    # Resolved at call time, not bound as a default — a default argument is
    # evaluated once at import, so set_source() would silently never apply.
    source = source or SOURCE_LINE
    # Offset in points, not axes fractions: a fraction scales with figure
    # height, which puts the source line through the x-axis label on short
    # charts and marooned in white space on tall ones.
    drop = -50 if ax.get_xlabel() else -34
    ax.annotate(
        source,
        xy=(0, 0),
        xycoords="axes fraction",
        xytext=(0, drop),
        textcoords="offset points",
        fontsize=11,
        color=MUTED,
        va="top",
        ha="left",
        annotation_clip=False,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return str(out)


def line_by_band(x_labels, series: dict[str, list[float]], title: str,
                 ylabel: str, out: Path, invert_y: bool = True,
                 annotate_peak: bool = True) -> str:
    """Percentile-by-band lines. Lower percentile = better, so y is inverted."""
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    xs = np.arange(len(x_labels))
    # Peak labels only make sense on a single line; on several they collide
    # whenever two series peak on neighbouring bands, which is most of the time.
    annotate_peak = annotate_peak and len(series) == 1
    for i, (label, ys) in enumerate(series.items()):
        ax.plot(xs, ys, color=SERIES[i % len(SERIES)], marker="o",
                markersize=5, label=label, zorder=3)
        if annotate_peak and len(ys):
            arr = np.asarray(ys, dtype=float)
            best = int(np.nanargmin(arr)) if invert_y else int(np.nanargmax(arr))
            ax.annotate(
                x_labels[best],
                xy=(xs[best], arr[best]),
                xytext=(0, -14 if invert_y else 10),
                textcoords="offset points",
                ha="center", fontsize=9, fontweight="bold",
                color=SERIES[i % len(SERIES)],
            )
    ax.set_xticks(xs)
    ax.set_xticklabels(x_labels)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if invert_y:
        ax.invert_yaxis()
    if len(series) > 1:
        ax.legend(loc="best")
    ax.grid(axis="x", visible=False)
    return _finish(fig, ax, out)


def barh(labels, values, title: str, xlabel: str, out: Path,
         highlight: int | None = None, value_fmt: str = "{:.0f}") -> str:
    fig, ax = plt.subplots(figsize=(6.4, max(3.4, 0.46 * len(labels) + 1.7)))
    ys = np.arange(len(labels))[::-1]
    colors = [BLUE] * len(labels)
    if highlight is not None and 0 <= highlight < len(labels):
        colors[highlight] = ACCENT
    values = [float(v) for v in values]
    has_neg = min(values) < 0
    if has_neg and highlight is None:
        # With both signs, colour by direction rather than by position.
        colors = [ACCENT if v < 0 else BLUE for v in values]
    ax.barh(ys, values, color=colors, height=0.7, zorder=3)
    ax.set_yticks(ys)
    ax.set_yticklabels(labels)
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    ax.grid(axis="y", visible=False)

    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    pad = span * 0.22
    if has_neg:
        ax.axvline(0, color=INK, linewidth=1.2, zorder=4)
        ax.set_xlim(lo - pad, hi + pad)
    else:
        ax.set_xlim(0, hi + pad)

    for y, v in zip(ys, values):
        ax.annotate(value_fmt.format(v), xy=(v, y),
                    xytext=(7 if v >= 0 else -7, 0),
                    textcoords="offset points", va="center",
                    ha="left" if v >= 0 else "right",
                    fontsize=12, color=INK, fontweight="bold")
    return _finish(fig, ax, out)


def dist_pair(a, b, labels: tuple[str, str], title: str, xlabel: str,
              out: Path, bins: int = 40) -> str:
    """Two overlaid distributions — the workhorse for 'group A vs group B'."""
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    lo = float(min(np.nanmin(a), np.nanmin(b)))
    hi = float(max(np.nanmax(a), np.nanmax(b)))
    edges = np.linspace(lo, hi, bins + 1)
    ax.hist(a, bins=edges, density=True, color=BLUE, alpha=0.62,
            label=f"{labels[0]} (n={len(a):,})", zorder=3)
    ax.hist(b, bins=edges, density=True, color=ACCENT, alpha=0.62,
            label=f"{labels[1]} (n={len(b):,})", zorder=3)
    for arr, col in ((a, BLUE), (b, ACCENT)):
        ax.axvline(float(np.nanmedian(arr)), color=col, linestyle="--",
                   linewidth=1.6, zorder=4)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("density")
    ax.set_title(title)
    ax.legend(loc="best")
    ax.set_yticks([])
    ax.grid(axis="y", visible=False)
    return _finish(fig, ax, out)


def scatter_binned(x, y, title: str, xlabel: str, ylabel: str, out: Path,
                   bins: int = 24, invert_y: bool = True) -> str:
    """Binned means with a spread band — honest about a noisy cloud."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    qs = np.quantile(x, np.linspace(0, 1, bins + 1))
    qs = np.unique(qs)
    centres, means, los, his = [], [], [], []
    for i in range(len(qs) - 1):
        m = (x >= qs[i]) & (x < qs[i + 1] if i < len(qs) - 2 else x <= qs[i + 1])
        if m.sum() < 30:
            continue
        centres.append(float(np.median(x[m])))
        means.append(float(np.mean(y[m])))
        los.append(float(np.quantile(y[m], 0.25)))
        his.append(float(np.quantile(y[m], 0.75)))

    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    ax.fill_between(centres, los, his, color=BLUE, alpha=0.16, zorder=2,
                    label="middle 50%")
    ax.plot(centres, means, color=BLUE, marker="o", markersize=4,
            zorder=3, label="mean")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if invert_y:
        ax.invert_yaxis()
    ax.legend(loc="best")
    return _finish(fig, ax, out)


def stacked_share(labels, parts: dict[str, list[float]], title: str,
                  out: Path, ylabel: str = "share of field") -> str:
    fig, ax = plt.subplots(figsize=(6.4, 4.6))
    xs = np.arange(len(labels))
    bottom = np.zeros(len(labels))
    for i, (name, vals) in enumerate(parts.items()):
        vals = np.asarray(vals, dtype=float)
        ax.bar(xs, vals, bottom=bottom, color=RAMP[min(i, len(RAMP) - 1)],
               label=name, width=0.72, zorder=3)
        bottom += vals
    ax.set_xticks(xs)
    ax.set_xticklabels(labels)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(loc="upper right", ncols=len(parts))
    ax.grid(axis="x", visible=False)
    return _finish(fig, ax, out)
