"""The Splitline Open Benchmark Workbook — the paid product.

A coach pastes their gym's athletes and their Open finishing ranks into one
sheet. Live formulas, running against percentile tables computed from the
public field, return for each athlete:

  * exact percentile in their division
  * age-adjusted percentile — how they did against people their own age
  * their weakest workout, named
  * how many places closing that weakness is worth

This is the product because it is the thing a coach cannot make themselves.
The tables behind it require crawling ~250k athlete records; the formulas turn
that into a five-minute job on a Monday morning.

Everything is real openpyxl formulas, not baked values, so the workbook keeps
working when the coach edits it.
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

INK = "FF12161C"
ACCENT = "FFE4572E"
BLUE = "FF1B4965"
WASH = "FFF5F6F8"
RULE = "FFDDE1E6"

H1 = Font(name="Calibri", size=18, bold=True, color=INK)
H2 = Font(name="Calibri", size=13, bold=True, color=INK)
TH = Font(name="Calibri", size=10, bold=True, color="FFFFFFFF")
BODY = Font(name="Calibri", size=11, color=INK)
MUTED = Font(name="Calibri", size=10, color="FF6B7480")
INPUT_FONT = Font(name="Calibri", size=11, color="FF0A3D62", bold=True)

FILL_HEAD = PatternFill("solid", fgColor=BLUE)
FILL_INPUT = PatternFill("solid", fgColor="FFEAF2F8")
FILL_WASH = PatternFill("solid", fgColor=WASH)
THIN = Side(style="thin", color=RULE)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

MAX_ATHLETES = 60


def _title_block(ws, title: str, subtitle: str) -> int:
    ws["A1"] = f"{BRAND} — {title}"
    ws["A1"].font = H1
    ws["A2"] = subtitle
    ws["A2"].font = MUTED
    return 4


def _header_row(ws, row: int, headers: list[str], widths: list[int]) -> None:
    for i, (h, w) in enumerate(zip(headers, widths), start=1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = TH
        c.fill = FILL_HEAD
        c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        c.border = BOX
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[row].height = 30


# ---------------------------------------------------------- lookup tables ----
DIVISION_IDS = {"Men": 1, "Women": 2}


def _division_table(df: pd.DataFrame, sample: dict | None = None) -> pd.DataFrame:
    """Finishers per division — as a count of the real field, always.

    The percentile formula in the workbook divides a coach's real finishing
    place by this number. If it held a sample tally instead of the field size,
    every percentile in the product would be wrong by the sampling factor, so
    a sampled dataset is scaled back up here using each division's published
    entrant count.
    """
    n_wk = _n_workouts(df)
    rows = []
    for div, sub in df.groupby("division", observed=True):
        finishers = int((sub["workouts_scored"] >= n_wk).sum())
        entrants = None
        if sample:
            by_div = {int(k): v for k, v in
                      (sample.get("entrants_by_division") or {}).items()}
            entrants = by_div.get(DIVISION_IDS.get(str(div), -1))
        if entrants:
            finishers = int(round(finishers / len(sub) * entrants))
        rows.append({"division": str(div), "finishers": finishers})
    return (pd.DataFrame(rows)
              .sort_values("finishers", ascending=False)
              .reset_index(drop=True))


def _n_workouts(df: pd.DataFrame) -> int:
    return len({c.split("_")[0] for c in df.columns
                if c.startswith("wk") and c.endswith("_pct")})


def _age_table(df: pd.DataFrame) -> pd.DataFrame:
    """Median percentile per division × age band — the age adjustment."""
    d = df[df["workouts_scored"] >= _n_workouts(df)]
    d = d[d["age"].between(14, 80)]
    g = (d.groupby(["division", "age_band"], observed=True)
           .agg(median_pct=("overall_pct", "median"),
                athletes=("competitor_id", "size"))
           .reset_index())
    g = g[g["athletes"] >= 30].copy()
    order = ["<18", "18-24", "25-29", "30-34", "35-39", "40-44",
             "45-49", "50-54", "55-59", "60+"]
    g["_o"] = g["age_band"].astype(str).map({b: i for i, b in enumerate(order)})
    return (g.sort_values(["division", "_o"])
             .drop(columns="_o").reset_index(drop=True))


def _workout_table(df: pd.DataFrame, div_tbl: pd.DataFrame) -> pd.DataFrame:
    """Percentile checkpoints per workout — what each score band was worth."""
    d = df[df["workouts_scored"] >= _n_workouts(df)]
    wks = sorted({c.split("_")[0] for c in d.columns
                  if c.startswith("wk") and c.endswith("_pct")})
    rows = []
    for div, sub in d.groupby("division", observed=True):
        if len(sub) < 300:
            continue
        for wk in wks:
            q = sub[f"{wk}_pct"].astype(float)
            disp = sub[f"{wk}_display"].astype(str)
            for t in (0.01, 0.05, 0.10, 0.25, 0.50, 0.75):
                idx = (q - t).abs().nsmallest(25).index
                mode = disp.loc[idx].mode()
                rows.append({
                    "division": div,
                    "workout": f"Workout {wk[2:]}",
                    "percentile": t,
                    "score": str(mode.iloc[0]) if len(mode) else "",
                    # Places are positions in the real field, not the sample.
                    "place": int(round(t * float(
                        div_tbl.loc[div_tbl["division"] == str(div),
                                    "finishers"].iloc[0]))),
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------- sheets ----
def _sheet_start(wb: Workbook, year: int, meta: dict) -> None:
    ws = wb.create_sheet("Start here", 0)
    r = _title_block(
        ws, f"Open Benchmark Workbook {year}",
        "Paste your athletes in. The workbook does the rest.",
    )
    ws.column_dimensions["A"].width = 108

    lines = [
        ("H2", "What this is"),
        ("P", f"Percentile tables computed from the public {year} CrossFit "
              f"Open field, wired into live formulas."),
        ("P", meta["field_line"]),
        ("P", "It answers the question a leaderboard cannot: not where an "
              "athlete placed, but whether that placing was good for who they are."),
        ("H2", "How to use it, in three steps"),
        ("P", "1.  Open the 'My athletes' sheet. Type each athlete's name, pick "
              "their division from the dropdown, enter their age, and enter "
              "their overall finishing place from the Open leaderboard."),
        ("P", "2.  Enter each athlete's per-workout finishing place in the three "
              "workout columns. Leave any you do not have blank."),
        ("P", "3.  Everything from column H rightwards fills itself in: "
              "percentile, age-adjusted percentile, weakest workout, and what "
              "closing that weakness is worth in places."),
        ("H2", "Reading the age-adjusted column"),
        ("P", "A positive age-adjusted figure means the athlete beat the median "
              "athlete of their own age band. That is the number worth showing "
              "a 47-year-old, because their raw percentile is competing against "
              "23-year-olds and will always look worse than their fitness is."),
        ("H2", "Where the numbers come from"),
        ("P", "The public CrossFit Games Open leaderboard, recomputed each "
              "season. Percentiles are over athletes who scored "
              "every workout, not everyone who registered — including the "
              "non-finishers would flatter everybody by about fifteen points."),
        ("P", "The 'Method' sheet states every definition precisely. If you find "
              "a number you think is wrong, reply to any Splitline email and it "
              "will be checked and corrected publicly."),
        ("H2", "Licence"),
        ("P", "One gym, one coaching staff. Share the outputs with your athletes "
              "freely; please do not redistribute the workbook itself."),
        ("P", f"{BRAND} · {SITE}" + (f" · {PRODUCT_URL}" if PRODUCT_URL else "")),
    ]
    for kind, text in lines:
        r += 1 if kind == "P" else 2
        c = ws.cell(row=r, column=1, value=text)
        c.font = H2 if kind == "H2" else BODY
        c.alignment = Alignment(wrap_text=True, vertical="top")
        if kind == "P":
            ws.row_dimensions[r].height = 15 * (1 + len(text) // 100)
        r += 1


def _sheet_athletes(wb: Workbook, divisions: list[str], n_wk: int,
                    n_age_rows: int) -> None:
    ws = wb.create_sheet("My athletes", 1)
    r = _title_block(ws, "My athletes",
                     "Blue cells are yours to fill. Everything else computes.")

    wk_headers = [f"WK{i} place" for i in range(1, n_wk + 1)]
    headers = (["Athlete", "Division", "Age", "Overall place"] + wk_headers +
               ["Field size", "Percentile", "Age-adjusted", "Weakest",
                "Places to gain"])
    widths = ([22, 16, 7, 13] + [11] * n_wk + [11, 11, 13, 11, 14])
    head_row = r
    _header_row(ws, head_row, headers, widths)

    first = head_row + 1
    last = head_row + MAX_ATHLETES

    dv = DataValidation(
        type="list",
        formula1=f"'Divisions'!$A$2:$A${len(divisions) + 1}",
        allow_blank=True,
        showDropDown=False,
    )
    ws.add_data_validation(dv)
    dv.add(f"B{first}:B{last}")

    n_input = 4 + n_wk
    col_field = get_column_letter(n_input + 1)
    col_pct = get_column_letter(n_input + 2)
    col_adj = get_column_letter(n_input + 3)
    col_weak = get_column_letter(n_input + 4)
    col_gain = get_column_letter(n_input + 5)

    wk_cols = [get_column_letter(5 + i) for i in range(n_wk)]

    for row in range(first, last + 1):
        for col in range(1, n_input + 1):
            c = ws.cell(row=row, column=col)
            c.fill = FILL_INPUT
            c.font = INPUT_FONT
            c.border = BOX

        # Field size for the athlete's division.
        ws[f"{col_field}{row}"] = (
            f'=IFERROR(VLOOKUP($B{row},Divisions!$A:$B,2,FALSE),"")'
        )
        # Overall percentile.
        ws[f"{col_pct}{row}"] = (
            f'=IFERROR(IF(OR($D{row}="",{col_field}{row}=""),"",'
            f'$D{row}/{col_field}{row}),"")'
        )
        # Age-adjusted: how far ahead of their own age band's median they are.
        # Positive = better than the median athlete their age.
        #
        # SUMPRODUCT rather than an INDEX/MATCH array formula: exactly one
        # AgeCurves row can match a (division, age) pair, so the product sums
        # to that row's median — and unlike an array formula it needs no
        # Ctrl+Shift+Enter and behaves identically in Excel, Numbers and
        # LibreOffice.
        last_age = n_age_rows + 1
        band = (
            f'SUMPRODUCT((AgeCurves!$A$2:$A${last_age}=$B{row})'
            f'*($C{row}>=AgeCurves!$D$2:$D${last_age})'
            f'*($C{row}<=AgeCurves!$E$2:$E${last_age})'
            f'*AgeCurves!$C$2:$C${last_age})'
        )
        ws[f"{col_adj}{row}"] = (
            f'=IFERROR(IF(OR({col_pct}{row}="",$C{row}=""),"",'
            f'IF({band}=0,"",{band}-{col_pct}{row})),"")'
        )
        # Weakest workout = the one with the worst (highest) finishing place.
        # MATCH over the contiguous workout range keeps this portable between
        # Excel, Numbers and LibreOffice; array forms do not travel well.
        ws[f"{col_weak}{row}"] = (
            f'=IFERROR(IF(COUNT({wk_cols[0]}{row}:{wk_cols[-1]}{row})=0,"",'
            f'"WK"&MATCH(MAX({wk_cols[0]}{row}:{wk_cols[-1]}{row}),'
            f'{wk_cols[0]}{row}:{wk_cols[-1]}{row},0)),"")'
        )
        # Places gained if the weakest workout were merely average for them.
        ws[f"{col_gain}{row}"] = (
            f'=IFERROR(IF(COUNT({wk_cols[0]}{row}:{wk_cols[-1]}{row})<2,"",'
            f'ROUND(MAX({wk_cols[0]}{row}:{wk_cols[-1]}{row})'
            f'-MEDIAN({wk_cols[0]}{row}:{wk_cols[-1]}{row}),0)),"")'
        )

        for col in (col_field, col_pct, col_adj, col_weak, col_gain):
            c = ws[f"{col}{row}"]
            c.font = BODY
            c.border = BOX
            c.fill = FILL_WASH
        ws[f"{col_pct}{row}"].number_format = "0.0%"
        ws[f"{col_adj}{row}"].number_format = "+0.0%;-0.0%;0.0%"
        ws[f"{col_field}{row}"].number_format = "#,##0"
        ws[f"{col_gain}{row}"].number_format = "#,##0"

    ws.freeze_panes = f"A{first}"

    note = last + 2
    ws.cell(row=note, column=1,
            value=("Places to gain = how many places the athlete's worst workout "
                   "sits behind their own median workout. It is the cheapest "
                   "improvement available to them.")).font = MUTED
    ws.merge_cells(start_row=note, start_column=1, end_row=note, end_column=6)


def _sheet_divisions(wb: Workbook, div_tbl: pd.DataFrame) -> None:
    ws = wb.create_sheet("Divisions")
    _header_row(ws, 1, ["Division", "Finishers"], [24, 12])
    for i, row in enumerate(div_tbl.itertuples(index=False), start=2):
        ws.cell(row=i, column=1, value=str(row.division)).font = BODY
        c = ws.cell(row=i, column=2, value=int(row.finishers))
        c.font = BODY
        c.number_format = "#,##0"


def _sheet_age_curves(wb: Workbook, age_tbl: pd.DataFrame) -> None:
    ws = wb.create_sheet("AgeCurves")
    _header_row(ws, 1, ["Division", "Age band", "Median percentile",
                        "Age from", "Age to", "Athletes"],
                [22, 12, 17, 10, 10, 11])
    bounds = {
        "<18": (0, 17), "18-24": (18, 24), "25-29": (25, 29), "30-34": (30, 34),
        "35-39": (35, 39), "40-44": (40, 44), "45-49": (45, 49),
        "50-54": (50, 54), "55-59": (55, 59), "60+": (60, 120),
    }
    r = 2
    for row in age_tbl.itertuples(index=False):
        lo, hi = bounds.get(str(row.age_band), (0, 120))
        ws.cell(row=r, column=1, value=str(row.division)).font = BODY
        ws.cell(row=r, column=2, value=str(row.age_band)).font = BODY
        c = ws.cell(row=r, column=3, value=float(row.median_pct))
        c.number_format = "0.0%"
        c.font = BODY
        ws.cell(row=r, column=4, value=lo).font = BODY
        ws.cell(row=r, column=5, value=hi).font = BODY
        ws.cell(row=r, column=6, value=int(row.athletes)).font = BODY
        r += 1


def _sheet_workouts(wb: Workbook, wk_tbl: pd.DataFrame) -> None:
    ws = wb.create_sheet("Cutlines")
    _header_row(ws, 1, ["Division", "Workout", "Percentile", "Score at the line",
                        "Place"], [22, 13, 12, 20, 11])
    for i, row in enumerate(wk_tbl.itertuples(index=False), start=2):
        ws.cell(row=i, column=1, value=str(row.division)).font = BODY
        ws.cell(row=i, column=2, value=str(row.workout)).font = BODY
        c = ws.cell(row=i, column=3, value=float(row.percentile))
        c.number_format = "0%"
        c.font = BODY
        ws.cell(row=i, column=4, value=str(row.score)).font = BODY
        c = ws.cell(row=i, column=5, value=int(row.place))
        c.number_format = "#,##0"
        c.font = BODY


def _sheet_method(wb: Workbook, meta: dict) -> None:
    ws = wb.create_sheet("Method")
    r = _title_block(ws, "Method", "Every definition, stated plainly.")
    ws.column_dimensions["A"].width = 108
    items = [
        ("Source", "The public CrossFit Games Open leaderboard "
                   "(c3po.crossfit.com competitions API)."),
        ("Ingested", meta["ingested"]),
        ("Field", meta["field_line"]),
        ("Finisher", "An athlete with a valid score on every workout. All "
                     "percentiles are over finishers only."),
        ("Percentile", "Finishing place divided by the number of finishers in "
                       "that division. 0% is the winner; 100% is last. Lower "
                       "is better throughout."),
        ("Age band", "Five-year bands from 18, plus <18 and 60+. A band needs "
                     "at least 30 finishers to appear in the age table."),
        ("Age-adjusted", "The athlete's own age band's median percentile minus "
                         "the athlete's percentile. Positive means they beat "
                         "the median athlete their age."),
        ("Score at the line", "The most common observed score among the 25 "
                              "athletes nearest that percentile. Read it as the "
                              "neighbourhood of the line, not an exact boundary."),
        ("Known limits", "Height and weight are self-reported and often blank, "
                         "so body-composition figures cover a subset of the "
                         "field. Affiliate names are free text and are matched "
                         "on the leaderboard's own affiliate id where possible."),
        ("Corrections", "Reply to any Splitline email. Corrections are "
                        "published, not quietly patched."),
    ]
    for label, text in items:
        ws.cell(row=r, column=1, value=label).font = H2
        r += 1
        c = ws.cell(row=r, column=1, value=text)
        c.font = BODY
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 15 * (1 + len(text) // 95)
        r += 2


def build(df: pd.DataFrame, year: int, out: Path,
          sample: dict | None = None) -> Path:
    """Build the workbook. Returns the written path."""
    n_wk = _n_workouts(df)
    if n_wk == 0:
        raise ValueError("dataset has no workout percentile columns")

    div_tbl = _division_table(df, sample)
    age_tbl = _age_table(df)
    wk_tbl = _workout_table(df, div_tbl)

    meta = {
        "athletes": int(len(df)),
        "divisions": int(df["division"].nunique()),
        "ingested": date.today().isoformat(),
    }
    if sample:
        meta["field_line"] = (
            f"A systematic sample of {sample['sampled_athletes']:,} athletes, "
            f"drawn at even intervals across the full ranked field of "
            f"{sample['total_entrants']:,} entrants in "
            f"{meta['divisions']} divisions. Sampling evenly over rank is "
            f"unbiased for medians, percentile positions and rates — which is "
            f"everything in this workbook. It is not a complete census, so "
            f"treat each median as carrying a margin of roughly one "
            f"percentage point."
        )
    else:
        meta["field_line"] = (
            f"{meta['athletes']:,} athlete records across "
            f"{meta['divisions']} divisions, from a complete crawl."
        )

    wb = Workbook()
    wb.remove(wb.active)
    _sheet_start(wb, year, meta)
    _sheet_athletes(wb, [str(d) for d in div_tbl["division"]], n_wk, len(age_tbl))
    _sheet_divisions(wb, div_tbl)
    _sheet_age_curves(wb, age_tbl)
    _sheet_workouts(wb, wk_tbl)
    _sheet_method(wb, meta)

    wb.properties.title = f"{BRAND} Open Benchmark Workbook {year}"
    wb.properties.creator = BRAND
    wb.properties.description = (
        f"Percentile benchmarks from the {year} CrossFit Open field."
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    log.info("workbook written: %s (%.0f KB)", out.name, out.stat().st_size / 1024)
    return out
