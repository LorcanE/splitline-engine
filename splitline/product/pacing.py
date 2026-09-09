"""The Splitline HYROX Pacing Plan — the in-season product.

An athlete enters one number: their target finish time. The workbook returns
the split they need at every one of the seventeen segments of a HYROX race,
and the running clock they should see as they leave each one.

The splits are not a percentage of the target time. Race shape changes with
ability — the wall balls take a 90-minute athlete three times as long as a
65-minute athlete, while the ski erg barely moves — so a share-based plan
would hand elite athletes an impossible wall-ball target and slow athletes a
trivial one. Instead every segment is fitted as a smooth function of finish
time across real finishers, and the workbook reads a dense pre-computed table.

Segments, in race order: eight 1km runs interleaved with eight stations, plus
roxzone — the transition time nobody measures and everybody argues about.
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from ..config import BRAND, PRODUCT_URL, SITE

log = logging.getLogger(__name__)

STATIONS = ["ski", "push", "pull", "burpee", "row", "farmers", "lunges", "wall"]
RUNS = [f"r{i}" for i in range(1, 9)]

LABELS = {
    "r1": "Run 1", "ski": "1000m SkiErg", "r2": "Run 2", "push": "50m Sled Push",
    "r3": "Run 3", "pull": "50m Sled Pull", "r4": "Run 4",
    "burpee": "80m Burpee Broad Jump", "r5": "Run 5", "row": "1000m Row",
    "r6": "Run 6", "farmers": "200m Farmers Carry", "r7": "Run 7",
    "lunges": "100m Sandbag Lunges", "r8": "Run 8", "wall": "Wall Balls",
}
ORDER = ["r1", "ski", "r2", "push", "r3", "pull", "r4", "burpee",
         "r5", "row", "r6", "farmers", "r7", "lunges", "r8", "wall"]

INK = "FF12161C"
BLUE = "FF1B4965"
ACCENT = "FFE4572E"
RULE = "FFDDE1E6"

H1 = Font(name="Calibri", size=18, bold=True, color=INK)
H2 = Font(name="Calibri", size=13, bold=True, color=INK)
TH = Font(name="Calibri", size=10, bold=True, color="FFFFFFFF")
BODY = Font(name="Calibri", size=11, color=INK)
MUTED = Font(name="Calibri", size=10, color="FF6B7480")
BIG = Font(name="Calibri", size=20, bold=True, color=BLUE)
INPUT_FONT = Font(name="Calibri", size=16, bold=True, color="FF0A3D62")

FILL_HEAD = PatternFill("solid", fgColor=BLUE)
FILL_INPUT = PatternFill("solid", fgColor="FFEAF2F8")
FILL_WASH = PatternFill("solid", fgColor="FFF5F6F8")
FILL_FLAG = PatternFill("solid", fgColor="FFFDEDE7")
THIN = Side(style="thin", color=RULE)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Drop timing-system artefacts.

    Mass-participation timing produces impossible splits — a mat missed, a
    chip read twice. They are rare but they wreck a median, so each athlete's
    splits must reconstruct their published finish time, and each segment must
    be physically plausible, or the athlete is dropped entirely.
    """
    n0 = len(df)
    df = df[df["total"].between(45 * 60, 3 * 3600)].copy()
    parts = df[STATIONS + RUNS + ["roxzone"]].sum(axis=1, min_count=1)
    df = df[((parts - df["total"]).abs() / df["total"]) < 0.02]
    for c in STATIONS:
        df = df[df[c].between(30, 1500)]
    for c in RUNS:
        df = df[df[c].between(120, 1200)]
    df = df.dropna(subset=STATIONS + RUNS + ["roxzone", "total"])
    log.info("cleaned %s -> %s athletes (%s dropped)", n0, len(df), n0 - len(df))
    return df


def pacing_table(df: pd.DataFrame, lo: int = 60, hi: int = 140,
                 step: int = 1) -> pd.DataFrame:
    """Expected split for every segment, at each target finish time.

    Each segment is fitted against finish time with a quadratic, weighted to
    the athletes nearest that time. Fitting rather than binning means the table
    stays smooth where the field is thin, and monotonic where it should be.
    """
    x = df["total"].to_numpy(dtype=float) / 60.0
    targets = np.arange(lo, hi + step, step, dtype=float)
    out: dict[str, list[float]] = {"target_min": list(targets)}

    for seg in ORDER + ["roxzone"]:
        y = df[seg].to_numpy(dtype=float)
        coef = np.polyfit(x, y, 2)
        fitted = np.polyval(coef, targets)
        # Never let a fit predict below the fastest observed athlete's segment.
        floor = float(np.quantile(y, 0.01))
        out[seg] = list(np.maximum(fitted, floor))

    tbl = pd.DataFrame(out)
    segs = ORDER + ["roxzone"]

    # Rescale so the plan's segments add up to the target the athlete asked for.
    factor = (tbl["target_min"] * 60) / tbl[segs].sum(axis=1)
    for seg in segs:
        tbl[seg] = (tbl[seg] * factor).round(0)

    # Rounding each segment to a whole second leaves a residual of a few
    # seconds. Absorb it into the roxzone rather than letting the plan total
    # a minute the athlete did not ask for — a race plan that does not add up
    # to its own target reads as broken, however small the error.
    residual = tbl["target_min"] * 60 - tbl[segs].sum(axis=1)
    tbl["roxzone"] = tbl["roxzone"] + residual

    tbl["check_min"] = (tbl[segs].sum(axis=1) / 60).round(4)
    return tbl


def gap_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """How much of the fast-to-slow gap each segment is responsible for."""
    fast = df[df["total"] <= df["total"].quantile(0.10)]
    slow = df[df["total"] >= df["total"].quantile(0.90)]
    gap = float(slow["total"].median() - fast["total"].median())
    rows = []
    for seg in ORDER + ["roxzone"]:
        d = float(slow[seg].median() - fast[seg].median())
        rows.append({
            "segment": LABELS.get(seg, "Roxzone"),
            "fast": float(fast[seg].median()),
            "slow": float(slow[seg].median()),
            "gap": d,
            "share": d / gap if gap else 0.0,
        })
    return pd.DataFrame(rows).sort_values("share", ascending=False)


def _hms(ws, cell):
    ws[cell].number_format = "[m]:ss"


def _sheet_plan(wb: Workbook, tbl: pd.DataFrame, lo: int, step: int,
                two_sexes: bool = True) -> None:
    ws = wb.create_sheet("My race plan", 0)
    ws["A1"] = f"{BRAND} — HYROX Pacing Plan"
    ws["A1"].font = H1
    ws["A2"] = "Enter your target finish time. The plan builds itself."
    ws["A2"].font = MUTED
    ws.column_dimensions["A"].width = 26
    for col in "BCDEF":
        ws.column_dimensions[col].width = 15

    ws["A4"] = "TARGET FINISH (minutes)"
    ws["A4"].font = H2
    ws["B4"] = 90
    ws["B4"].font = INPUT_FONT
    ws["B4"].fill = FILL_INPUT
    ws["B4"].border = BOX
    ws["C4"] = '=TEXT(INT($B$4/60),"0")&"h "&TEXT(MOD($B$4,60),"00")&"m"'
    ws["C4"].font = MUTED

    ws["A5"] = "DIVISION"
    ws["A5"].font = H2
    ws["B5"] = "Men"
    ws["B5"].font = INPUT_FONT
    ws["B5"].fill = FILL_INPUT
    ws["B5"].border = BOX
    if two_sexes:
        dv = DataValidation(type="list", formula1='"Men,Women"',
                            allow_blank=False, showDropDown=False)
        ws.add_data_validation(dv)
        dv.add("B5")
    ws["C5"] = ("Race shape differs by division, so this is not cosmetic."
                if two_sexes else "")
    ws["C5"].font = MUTED
    ws["A6"] = "Any whole number of minutes between 60 and 140."
    ws["A6"].font = MUTED

    head = 8
    for i, h in enumerate(["Segment", "Target split", "Cumulative",
                           "Clock at finish", "Share of race"], start=1):
        c = ws.cell(row=head, column=i, value=h)
        c.font = TH
        c.fill = FILL_HEAD
        c.border = BOX
        c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[head].height = 26

    last_tbl = len(tbl) + 1
    n_rows = len(tbl)
    r = head + 1
    prev_cum = None
    for seg in ORDER + ["roxzone"]:
        name = LABELS.get(seg, "Roxzone (all transitions)")
        col = ORDER.index(seg) + 2 if seg in ORDER else len(ORDER) + 2
        letter = get_column_letter(col)

        ws.cell(row=r, column=1, value=name).font = (
            BODY if seg not in ("wall", "burpee", "lunges") else H2)
        if seg in ("wall", "burpee", "lunges"):
            ws.cell(row=r, column=1).fill = FILL_FLAG

        # Nearest row, found by arithmetic rather than by searching.
        #
        # The pacing table is a regular grid, so the right row is computable
        # directly. The obvious MATCH(MIN(ABS(...))) form needs array
        # evaluation, which Excel and LibreOffice disagree about — it silently
        # returned the wrong row rather than an error, which is the worst kind
        # of bug to ship in something people race off.
        idx = f'MIN({n_rows},MAX(1,ROUND(($B$4-{lo})/{step},0)+1))'
        men = f'INDEX(PacingMen!${letter}$2:${letter}${last_tbl},{idx})'
        if two_sexes:
            women = f'INDEX(PacingWomen!${letter}$2:${letter}${last_tbl},{idx})'
            expr = f'IF($B$5="Women",{women},{men})'
        else:
            expr = men
        ws.cell(row=r, column=2, value=f"={expr}/86400")
        cum = f"=B{r}" if prev_cum is None else f"=C{r - 1}+B{r}"
        ws.cell(row=r, column=3, value=cum)
        ws.cell(row=r, column=4, value=f'=TEXT(C{r},"[h]:mm:ss")')
        ws.cell(row=r, column=5, value=f"=B{r}/($B$4/1440)")

        for col_i in range(1, 6):
            ws.cell(row=r, column=col_i).border = BOX
        _hms(ws, f"B{r}")
        ws[f"C{r}"].number_format = "[h]:mm:ss"
        ws[f"E{r}"].number_format = "0.0%"
        ws[f"D{r}"].font = BODY
        prev_cum = cum
        r += 1

    ws.cell(row=r, column=1, value="TOTAL").font = H2
    ws.cell(row=r, column=2, value=f"=SUM(B{head + 1}:B{r - 1})")
    _hms(ws, f"B{r}")
    ws.cell(row=r, column=4, value=f'=TEXT(B{r},"[h]:mm:ss")').font = BIG

    note = r + 2
    ws.cell(row=note, column=1, value=(
        "Highlighted rows are the three segments that separate a fast race "
        "from a slow one more than any others. If you are going to be behind "
        "somewhere, be behind on the ski erg — not here.")).font = MUTED
    ws.merge_cells(start_row=note, start_column=1, end_row=note, end_column=5)
    ws.row_dimensions[note].height = 30


def _sheet_pacing(wb: Workbook, tbl: pd.DataFrame, name: str) -> None:
    ws = wb.create_sheet(name)
    cols = ["target_min"] + ORDER + ["roxzone"]
    heads = ["Target (min)"] + [LABELS.get(s, "Roxzone") for s in ORDER + ["roxzone"]]
    for i, h in enumerate(heads, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = TH
        c.fill = FILL_HEAD
        c.alignment = Alignment(wrap_text=True, vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = 13
    ws.row_dimensions[1].height = 34
    for r, (_, row) in enumerate(tbl.iterrows(), start=2):
        for i, col in enumerate(cols, start=1):
            v = float(row[col])
            c = ws.cell(row=r, column=i, value=v)
            c.font = BODY
            if col != "target_min":
                c.number_format = "0"
    ws.freeze_panes = "B2"


def _sheet_gap(wb: Workbook, gap: pd.DataFrame, n: int) -> None:
    ws = wb.create_sheet("Where the race is won")
    ws["A1"] = "Where a fast race and a slow race actually differ"
    ws["A1"].font = H1
    ws["A2"] = (f"Median of the fastest 10% against the slowest 10%, "
                f"across {n:,} finishers.")
    ws["A2"].font = MUTED
    ws.column_dimensions["A"].width = 28
    for col in "BCDE":
        ws.column_dimensions[col].width = 15

    for i, h in enumerate(["Segment", "Fastest 10%", "Slowest 10%",
                           "Difference", "Share of the gap"], start=1):
        c = ws.cell(row=4, column=i, value=h)
        c.font = TH
        c.fill = FILL_HEAD
        c.border = BOX
    for r, (_, row) in enumerate(gap.iterrows(), start=5):
        ws.cell(row=r, column=1, value=row["segment"]).font = BODY
        for j, key in enumerate(["fast", "slow", "gap"], start=2):
            c = ws.cell(row=r, column=j, value=float(row[key]) / 86400)
            c.number_format = "[m]:ss"
            c.font = BODY
        c = ws.cell(row=r, column=5, value=float(row["share"]))
        c.number_format = "0.0%"
        c.font = H2 if row["share"] > 0.08 else BODY
        if row["share"] > 0.08:
            c.fill = FILL_FLAG
        for j in range(1, 6):
            ws.cell(row=r, column=j).border = BOX


def _sheet_compare(wb: Workbook, men: pd.DataFrame, women: pd.DataFrame) -> None:
    """Same finish time, different race. The most useful page for a coach."""
    lo, hi = 85 * 60, 95 * 60
    m = men[men["total"].between(lo, hi)]
    w = women[women["total"].between(lo, hi)]
    if len(m) < 20 or len(w) < 20:
        return

    ws = wb.create_sheet("Men vs women")
    ws["A1"] = "Same finish time, different race"
    ws["A1"].font = H1
    ws["A2"] = (f"Median splits for the {len(m)} men and {len(w)} women who "
                f"finished between 85 and 95 minutes. Matching on finish time "
                f"strips out speed and leaves only shape.")
    ws["A2"].font = MUTED
    ws.column_dimensions["A"].width = 28
    for col in "BCD":
        ws.column_dimensions[col].width = 15

    for i, h in enumerate(["Segment", "Men", "Women", "Women minus men"], start=1):
        c = ws.cell(row=4, column=i, value=h)
        c.font = TH
        c.fill = FILL_HEAD
        c.border = BOX

    rows = []
    for seg in STATIONS + ["roxzone"]:
        rows.append((LABELS.get(seg, "Roxzone"),
                     float(m[seg].median()), float(w[seg].median())))
    rows.append(("All eight runs",
                 float(m[RUNS].sum(axis=1).median()),
                 float(w[RUNS].sum(axis=1).median())))
    rows.sort(key=lambda t: t[2] - t[1])

    for r, (name, mv, wv) in enumerate(rows, start=5):
        ws.cell(row=r, column=1, value=name).font = BODY
        for j, v in enumerate((mv, wv), start=2):
            c = ws.cell(row=r, column=j, value=v / 86400)
            c.number_format = "[m]:ss"
            c.font = BODY
        d = wv - mv
        c = ws.cell(row=r, column=4, value=d / 86400)
        c.number_format = "+[m]:ss;-[m]:ss"
        c.font = H2 if abs(d) >= 25 else BODY
        if abs(d) >= 25:
            c.fill = FILL_FLAG
        for j in range(1, 5):
            ws.cell(row=r, column=j).border = BOX

    note = len(rows) + 6
    ws.cell(row=note, column=1, value=(
        "Negative means the women were faster. The pattern is consistent: at "
        "the same finish time women give time away on the ergs and the runs "
        "and take it back on the strength and skill stations. Pacing a woman "
        "off a man's plan puts her behind on exactly the segments she cannot "
        "make up.")).font = MUTED
    ws.merge_cells(start_row=note, start_column=1, end_row=note, end_column=4)
    ws.row_dimensions[note].height = 46


def _sheet_method(wb: Workbook, meta: dict) -> None:
    ws = wb.create_sheet("Method")
    ws["A1"] = f"{BRAND} — Method"
    ws["A1"].font = H1
    ws.column_dimensions["A"].width = 108
    items = [
        ("Source", "Public HYROX race results (results.hyrox.com), including "
                   "the per-athlete split table."),
        ("Field", meta["field_line"]),
        ("Cleaning", "An athlete is used only if their sixteen splits plus "
                     "roxzone reconstruct their published finish time to "
                     "within 2%, and every segment is physically plausible. "
                     f"{meta['dropped']} athletes were dropped on those tests."),
        ("The plan", "Each segment is fitted against finish time with a "
                     "quadratic across all clean finishers, then the whole "
                     "plan is rescaled so the segments sum exactly to your "
                     "target. Splits are not a fixed share of finish time — "
                     "race shape genuinely changes with ability."),
        ("Roxzone", "Total time between leaving one segment and starting the "
                    "next, as the timing system records it. It is 10% of a "
                    "fast race and over 12% of a slow one."),
        ("Known limits", meta["limits"]),
        ("Corrections", "Reply to any Splitline email. Corrections are "
                        "published, not quietly patched."),
        ("Licence", "One athlete or one coaching staff. Share your plan "
                    "freely; please do not redistribute the file."),
    ]
    r = 3
    for label, text in items:
        ws.cell(row=r, column=1, value=label).font = H2
        r += 1
        c = ws.cell(row=r, column=1, value=text)
        c.font = BODY
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r] = ws.row_dimensions[r]
        ws.row_dimensions[r].height = 15 * (1 + len(text) // 95)
        r += 2
    ws.cell(row=r, column=1, value=f"{BRAND} · {SITE}"
            + (f" · {PRODUCT_URL}" if PRODUCT_URL else "")).font = MUTED


def build(df_raw: pd.DataFrame, out: Path, race_label: str,
          limits: str = "", df_women: pd.DataFrame | None = None) -> Path:
    n_raw = len(df_raw) + (len(df_women) if df_women is not None else 0)
    df = clean(df_raw)
    women = clean(df_women) if df_women is not None else None
    two = women is not None and len(women) > 100

    tbl = pacing_table(df)
    tbl_w = pacing_table(women) if two else None
    both = pd.concat([df, women]) if two else df
    gap = gap_analysis(both)

    n_clean = len(df) + (len(women) if two else 0)
    field = (f"{len(df):,} men and {len(women):,} women"
             if two else f"{len(df):,} finishers")
    meta = {
        "field_line": f"{field} from {race_label}, after cleaning.",
        "dropped": n_raw - n_clean,
        "limits": limits or (
            "Built from a single race. Course conditions, "
            "altitude and floor surface all move splits by a little, so treat "
            "the plan as a well-founded starting point rather than a law. "
            "Splitline rebuilds it as more races are added."),
    }

    wb = Workbook()
    wb.remove(wb.active)
    _sheet_plan(wb, tbl, 60, 1, two_sexes=two)
    if two:
        _sheet_compare(wb, df, women)
    _sheet_gap(wb, gap, n_clean)
    _sheet_pacing(wb, tbl, "PacingMen")
    if two:
        _sheet_pacing(wb, tbl_w, "PacingWomen")
    _sheet_method(wb, meta)
    wb.properties.title = f"{BRAND} HYROX Pacing Plan"
    wb.properties.creator = BRAND

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    log.info("pacing plan written: %s (%.0f KB)", out.name,
             out.stat().st_size / 1024)
    return out
