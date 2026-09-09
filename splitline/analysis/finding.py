"""The unit of editorial output.

An angle produces a Finding. The runner decides whether a Finding is worth
publishing by looking at `n` and `effect` — not at how confident the prose
sounds. That separation is the whole reason this pipeline can run unattended
without shipping filler.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

BlockKind = Literal["lede", "p", "h2", "h3", "chart", "table", "callout", "rule"]


@dataclass
class Block:
    kind: BlockKind
    text: str = ""
    # chart
    src: str = ""
    alt: str = ""
    caption: str = ""
    # table
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    numeric_from: int = 1  # first column index rendered right-aligned


@dataclass
class Finding:
    slug: str
    headline: str
    subtitle: str
    blocks: list[Block] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    n: int = 0
    effect: float = 0.0
    # Some designs are sound at far smaller n than a raw field comparison.
    # A matched-pairs test on 160 athletes is stronger evidence than a
    # single-group median on 600, so an angle may declare its own floor
    # rather than inherit one calibrated for a different question.
    min_n: int | None = None
    # Set when the angle itself decides the data cannot support a story.
    skip_reason: str = ""

    # ------------------------------------------------------------ builders --
    def lede(self, text: str) -> "Finding":
        self.blocks.append(Block("lede", text=text))
        return self

    def p(self, text: str) -> "Finding":
        self.blocks.append(Block("p", text=text))
        return self

    def h2(self, text: str) -> "Finding":
        self.blocks.append(Block("h2", text=text))
        return self

    def h3(self, text: str) -> "Finding":
        self.blocks.append(Block("h3", text=text))
        return self

    def chart(self, src: str, alt: str, caption: str = "") -> "Finding":
        self.blocks.append(Block("chart", src=src, alt=alt, caption=caption))
        return self

    def table(self, columns: list[str], rows: list[list[Any]],
              numeric_from: int = 1) -> "Finding":
        self.blocks.append(
            Block("table", columns=columns, rows=rows, numeric_from=numeric_from)
        )
        return self

    def callout(self, text: str) -> "Finding":
        self.blocks.append(Block("callout", text=text))
        return self

    def rule(self) -> "Finding":
        self.blocks.append(Block("rule"))
        return self

    # ------------------------------------------------------------- verdict --
    def publishable(self, min_sample: int, min_effect: float) -> tuple[bool, str]:
        if self.skip_reason:
            return False, self.skip_reason
        floor = self.min_n if self.min_n is not None else min_sample
        if self.n < floor:
            return False, f"sample too small (n={self.n:,} < {floor:,})"
        if abs(self.effect) < min_effect:
            return False, f"effect too small ({abs(self.effect):.3f} < {min_effect:.3f})"
        if not any(b.kind in ("p", "lede") for b in self.blocks):
            return False, "no prose produced"
        return True, "ok"
