#!/usr/bin/env python3
"""Ingest SPS Annual Enrollment Report PDFs into tidy data files.

Standalone extractor for the Seattle Public Schools "Annual Enrollment Report"
series (one PDF per school year). It reads every
``*-Annual-Enrollment-Report.pdf`` in an input directory and emits CSVs that
combine all years, tagged with a ``year`` column (the school-year label, e.g.
``2024-25``).

Two datasets are produced, both of which appear across the whole 2010-11 .. 2024-25
range despite substantial format drift:

  Section 4 -- "Comparison of Enrollment and Attendance Areas"
    The observed origin-destination (OD) data. For every attendance area it
    reports where its resident students actually enrolled, and for every school
    where its attendees live. Three files:
      * section4_od.csv        year, level, grade_band, residence_area, school, n
                               (area residents -> schools; the OD matrix rows)
      * section4_attendees.csv year, level, grade_band, school, residence_area, n
                               (school attendees by residence; the OD columns)
      * section4_option_draw.csv
                               year, level, school, grade_band, residence_area, n
                               (option / K-8 draw-only blocks)

  Table 1-D -- "Comparison of Enrollment and Projections by School"
    Per-school headcount + projection. One file:
      * enrollment_by_school.csv
                               year, service_area, school_name,
                               prior_enrollment, projected_enrollment,
                               enrollment, change
    (Absent from the 2016-17 report, which rendered Section 1 as charts only;
    that year is skipped for this dataset and noted in the run report.)

School / area names are kept RAW (e.g. "Martin Luther King Jr.", "MLK Jr",
"West Seattle Elem") -- names drift across years and normalization is left to
downstream consumers.

Format drift handled here:
  * Unicode hyphen (U+2010) vs ASCII '-' in markers, bands, and names.
  * Band labels "(PreK-5)" / "(K-5)" / "(6-8)".
  * HS table is 4-D in 2010-11 (no 4-E) but 4-E from 2011-12 on.
  * Section 4 block titles that wrap across multiple text lines and sit at
    different vertical positions in the left vs right column (older reports).
  * Table 1-D trailing "2015 Functional Capacity" column in 2010-11.

Usage (run from repo root):
    venv/bin/python3 extractors/enrollment_reports.py                      # all PDFs in data/sps/enrollment
    venv/bin/python3 extractors/enrollment_reports.py --indir DIR --outdir DIR
    venv/bin/python3 extractors/enrollment_reports.py --year 2024-25 --year 2010-11

Requires ``pdftotext`` (poppler) on PATH and pandas.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_INDIR = _REPO_ROOT / "data" / "sps" / "enrollment"
DEFAULT_OUTDIR = _REPO_ROOT / "out_enrollment"

_YEAR_RE = re.compile(r"(\d{4}-\d{2})-Annual-Enrollment-Report\.pdf$")

# --- text normalization ------------------------------------------------------

# Map the various unicode dashes poppler emits to a plain ASCII hyphen so the
# rest of the parser only has to reason about one character.
_DASHES = {
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "−": "-",
}
_NBSP = " "


def _normalize(text: str) -> str:
    for bad, good in _DASHES.items():
        text = text.replace(bad, good)
    return text.replace(_NBSP, " ")


def _pdf_lines(pdf: Path) -> list[str]:
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        check=True, capture_output=True, text=True,
    )
    return _normalize(out.stdout).splitlines()


# =============================================================================
# Section 4 -- origin/destination blocks
# =============================================================================

import bisect

_S4_MARKER_RE = re.compile(r"Table:?\s*4-([A-E])\b")
_BAND_RE = re.compile(r"\((?:Pre)?K-5\)|\(6-8\)")
# "Grand Total" terminates a sub-table; one 2021-22 page misspells it
# "Grandt Total", so match loosely.
_GRAND_TOTAL_RE = re.compile(r"^Grand.{0,2}\s+Total$")
# A fragment is a run of tokens separated by single spaces (2+ spaces split it).
_FRAGMENT_RE = re.compile(r"\S+(?: \S+)*")
_ATTEND_TITLE_RE = re.compile(r"Where Students Attending\s+(.*?)\s+Live", re.DOTALL)
_RESIDENT_TITLE_RE = re.compile(r"Living in the\s+(.*?)\s+Attendance Area", re.DOTALL)
# A column-header line: one or more "<label> ... Total" sub-columns. Older
# reports place TWO paired blocks side by side -> four sub-columns
# (Attendance Area | School | Attendance Area | School); newer reports use one
# block (two sub-columns). We treat every sub-column independently.
_LABEL_RE = re.compile(r"\b(Attendance Area|School)\b")


def _band_of(text: str) -> str | None:
    m = _BAND_RE.search(text)
    if not m:
        return None
    return "6-8" if "6-8" in m.group(0) else "K-5"


def _clean_name(name: str) -> str:
    name = _BAND_RE.sub("", name)
    return re.sub(r"\s+", " ", name).strip()


def _level_map(letters: set[str]) -> dict[str, str]:
    """Map Section 4 sub-table letters to ES/MS/HS for this report.

    A is always ES, C always MS. HS is 4-E when present (2011-12+), otherwise
    4-D (2010-11). Summary tables (B, and D when E exists) map to nothing.
    """
    m = {"A": "ES", "C": "MS"}
    if "E" in letters:
        m["E"] = "HS"
    elif "D" in letters:
        m["D"] = "HS"
    return m


def _colheader_starts(line: str) -> list[int] | None:
    """If `line` is a column-header, return the start column of each sub-column.

    Each sub-column is a "<label> ... Total" pair; the returned starts are the
    label positions, which also align with where each sub-column's data names
    begin. Returns None if the line is not a column header.
    """
    if "Total" not in line:
        return None
    if not line.lstrip().startswith(("Attendance Area", "School")):
        return None
    labels = [m.start() for m in _LABEL_RE.finditer(line)]
    if not labels or line.count("Total") < len(labels):
        return None
    return labels


# A parsed sub-column: an attendee table (where school X's attendees live) or a
# resident table (where area X's residents attend), keyed (level, kind, name,
# band). Rows accumulate across continuation pages that repeat the header.
def _subcol_meta(title: str, level: str):
    """Classify a sub-column from its title text -> (kind, name, band) or None."""
    band = _band_of(title)
    rm = _RESIDENT_TITLE_RE.search(title)
    if rm:
        return ("residents", _clean_name(rm.group(1)), band)
    am = _ATTEND_TITLE_RE.search(title)
    if am:
        return ("attendees", _clean_name(am.group(1)), band)
    return None


def _titles_above(lines: list[str], hdr_idx: int, starts: list[int]) -> list[str]:
    """For each sub-column, gather + join the title text sitting above it."""
    window: list[str] = []
    n_blank = 0
    for j in range(hdr_idx - 1, max(-1, hdr_idx - 10), -1):
        line = lines[j]
        if not line.strip():
            n_blank += 1
            if n_blank >= 3:
                break
            continue
        n_blank = 0
        if (_S4_MARKER_RE.search(line) or _colheader_starts(line) is not None
                or "Grand Total" in line):
            break
        window.append(line)
    window.reverse()  # top-to-bottom

    buckets: list[list[str]] = [[] for _ in starts]
    for line in window:
        for frag in _FRAGMENT_RE.finditer(line):
            mid = (frag.start() + frag.end()) // 2
            i = max(0, bisect.bisect_right(starts, mid) - 1)
            buckets[i].append(frag.group())
    return [" ".join(b) for b in buckets]


# A column value: a space-delimited integer (the right-aligned count in a
# cell). Requiring whitespace on both sides means digits embedded in a name --
# "Orca K-8", "South Shore PK-8", "AS #1" -- are NOT mistaken for a value.
_VALUE_RE = re.compile(r"(?<=\s)-?\d[\d,]*(?=\s|$)")


def _feed_rows(lines: list[str], start: int, starts: list[int],
               cols: list[dict | None]) -> None:
    """Read data rows downward.

    Each row is a sequence of "<name> <value>" cells laid out in columns. We
    anchor on the values (space-delimited integers) rather than fixed character
    boundaries: a cell's name is the text preceding its value, and the cell is
    assigned to a sub-column by the value's position. This is robust to the
    cramped older HS tables where only a single space separates one column's
    number from the next column's name (e.g. "1090 Ballard").
    """
    n = len(cols)
    for k in range(start, min(len(lines), start + 250)):
        line = lines[k]
        # Stop at the next sub-table (its own column header) or a new section,
        # but NOT at a bare Section-4 page header: long sub-tables span a page
        # break, with the per-page "... Table: 4-A" banner sitting mid-table and
        # the remaining rows + Grand Total continuing below it. Page banners and
        # service-area sub-headers carry no space-delimited values, so reading
        # through them is safe.
        if _colheader_starts(line) is not None or _OTHER_MARKER_RE.search(line):
            break
        seg_start = 0
        for m in _VALUE_RE.finditer(line):
            seg = line[seg_start:m.start()]
            # A value belongs to the cell to its left. Real names use only
            # single spaces, so any 2+-space gap means an adjacent valueless
            # cell (a wrapped long name, or leftover header furniture) bled in;
            # the value's true name is the fragment after the last such gap.
            stripped = seg.rstrip()
            gaps = list(re.finditer(r"\s{2,}", stripped))
            name_off = gaps[-1].end() if gaps else len(stripped) - len(stripped.lstrip())
            name = stripped[name_off:].strip()
            name_left = seg_start + name_off
            seg_start = m.end()
            if not name:
                continue
            # Assign by the CELL's midpoint, which sits well inside its column.
            # Value right-edges and name left-edges both drift onto a neighbor's
            # boundary in the cramped older 4-column layouts; the midpoint does
            # not.
            mid = (name_left + m.end()) // 2
            i = max(0, min(n - 1, bisect.bisect_right(starts, mid) - 1))
            c = cols[i]
            if c is None or c["done"]:
                continue
            c["rows"].append((name, int(m.group().replace(",", ""))))
            if _GRAND_TOTAL_RE.match(name):
                c["done"] = True
        if all(c is None or c["done"] for c in cols):
            break


# Any other-section marker that should reset the active Section-4 level. We scan
# the whole document (the table-of-contents lists "Table 4-A" too, so a simple
# first-4-marker .. first-5-marker slice would collapse onto the TOC); instead
# we carry the active level forward from 4-x markers and clear it whenever we
# enter a different section. The TOC and other sections contain no Section-4
# column-header lines, so they yield no blocks even while scanned.
_OTHER_MARKER_RE = re.compile(r"Table:?\s*([0-35-9]|1[0-9])-[A-Z]\b|Section\s*([0-35-9]|1[0-9])\b")


def _parse_section4(lines: list[str]) -> dict[tuple, list]:
    """Return {(level, kind, name, band): [(row_name, n), ...]} for all sub-tables."""
    letters = {m.group(1) for ln in lines for m in [_S4_MARKER_RE.search(ln)] if m}
    if not letters:
        return {}
    lvlmap = _level_map(letters)

    # Active level per line: set by 4-x markers, cleared by any other-section
    # marker. A summary sub-table (4-B, or 4-D when 4-E exists) maps to None.
    active: list[str | None] = []
    cur: str | None = None
    for ln in lines:
        m4 = _S4_MARKER_RE.search(ln)
        if m4:
            cur = lvlmap.get(m4.group(1))
        elif _OTHER_MARKER_RE.search(ln):
            cur = None
        active.append(cur)

    tables: dict[tuple, list] = {}
    for i, line in enumerate(lines):
        starts = _colheader_starts(line)
        if starts is None:
            continue
        level = active[i]
        if level is None:
            continue
        titles = _titles_above(lines, i, starts)
        cols: list[dict | None] = [None] * len(starts)
        for j, title in enumerate(titles):
            meta = _subcol_meta(title, level)
            if meta is None:
                continue
            key = (level, *meta)
            cols[j] = {"rows": tables.setdefault(key, []), "done": False}
        if any(c is not None for c in cols):
            _feed_rows(lines, i + 1, starts, cols)
    return tables


def _section4_frames(year: str, tables: dict[tuple, list]):
    od, attendees, option = [], [], []
    names = {(lvl, name, band) for (lvl, _kind, name, band) in tables}
    for lvl, name, band in names:
        res = tables.get((lvl, "residents", name, band))
        att = tables.get((lvl, "attendees", name, band))
        if res is not None:  # attendance area: residents -> OD, attendees -> att
            for school, n in res:
                if not _GRAND_TOTAL_RE.match(school) and not _is_bad_name(school):
                    od.append((year, lvl, band, name, school, n))
            if att is not None:
                for area, n in att:
                    if not _GRAND_TOTAL_RE.match(area) and not _is_bad_name(area):
                        attendees.append((year, lvl, band, name, area, n))
        elif att is not None:  # option / draw-only school
            for area, n in att:
                if not _GRAND_TOTAL_RE.match(area) and not _is_bad_name(area):
                    option.append((year, lvl, name, band, area, n))
    return od, attendees, option


# A row name is suspect if it starts with a lowercase letter or digit, is a
# single character, or still contains a 2+-space gap -- all signs of a
# pdftotext column artifact rather than a real school/area name.
_BAD_NAME_RE = re.compile(r"^[a-z0-9]|^.$|\s{2,}")


def _is_bad_name(name: str) -> bool:
    return not _GRAND_TOTAL_RE.match(name) and bool(_BAD_NAME_RE.search(name))


def _section4_health(tables: dict[tuple, list]) -> tuple[int, int, int]:
    """(data rows, malformed-name rows, tables missing a Grand Total)."""
    nrows = bad = no_gt = 0
    for rows in tables.values():
        if rows and not _GRAND_TOTAL_RE.match(rows[-1][0]):
            no_gt += 1
        for nm, _ in rows:
            if _GRAND_TOTAL_RE.match(nm):
                continue
            nrows += 1
            if _is_bad_name(nm):
                bad += 1
    return nrows, bad, no_gt


# =============================================================================
# Table 1-D -- per-school enrollment + projections
# =============================================================================

_T1D_TITLE = "Comparison of Enrollment and Projections by School"
_T1D_END_RE = re.compile(r"(?:Section\s*2\b|Table:?\s*2-[A-Z]\b|Open Enrollment and School Choice)")
_T1D_NUM_RE = re.compile(r"-?[\d,]+")


def _parse_table1d(lines: list[str]) -> list[tuple]:
    """Return rows of (service_area, school_name, nums, has_capacity).

    Service-area labels sit in the left column and apply to every school row
    until the next label. Some areas wrap across two physical lines ("Robert
    Eagle" / "Staff", "Option Schools" / "with"): the wrap shows up as a second
    consecutive non-empty service cell (a real new area is always preceded by
    blank service cells, since each area spans several school rows). We treat a
    non-empty service cell that immediately follows another as a continuation
    of the same area, and a lone service-only line as a pending prefix.
    """
    rows: list[tuple] = []
    name_col: int | None = None
    has_capacity = False
    in_region = False
    service_area = ""
    prev_row_had_svc = False
    pending_prefix = ""

    for line in lines:
        if _T1D_TITLE in line:
            in_region = True
            name_col = None  # re-armed; wait for the "School Name" header
            continue
        if not in_region:
            continue
        if _T1D_END_RE.search(line) and name_col is not None:
            in_region = False
            name_col = None
            continue
        # 2010-11 carries a trailing "2015 Functional Capacity" column; its
        # header words land on separate physical lines, so match either word.
        if "Functional" in line or "Capacity" in line:
            has_capacity = True
        if "School Name" in line:
            name_col = line.index("School Name")
            continue
        if name_col is None:
            continue

        svc = line[:name_col].strip()
        rest = line[name_col:].rstrip()
        m = re.match(r"^(.+?)\s{2,}(-?[\d,].*)$", rest)
        if not m:
            # A line carrying only a service-area label, no school yet: hold it
            # to prepend to whichever area starts next.
            if svc and not rest.strip():
                pending_prefix = (pending_prefix + " " + svc).strip()
            continue

        if svc:
            if prev_row_had_svc:
                service_area = (service_area + " " + svc).strip()  # wrap
            else:
                service_area = (pending_prefix + " " + svc).strip()
                pending_prefix = ""
        prev_row_had_svc = bool(svc)

        school = m.group(1).strip()
        nums = [int(x.replace(",", "")) for x in _T1D_NUM_RE.findall(m.group(2))]
        if not school or not nums or school == "Grand Total":
            continue
        rows.append((service_area, school, nums, has_capacity))
    return rows


def _table1d_frame(year: str, rows: list[tuple]) -> list[tuple]:
    out = []
    for service_area, school, nums, has_capacity in rows:
        prior = projected = enrollment = change = None
        if has_capacity:
            # [..., final_projected, enrollment, change, capacity]
            if len(nums) >= 4:
                enrollment = nums[-3]
                change = nums[-2]
                projected = nums[-4]
                prior = nums[0] if len(nums) >= 5 else None
        else:
            # [prior, projected, enrollment, change]
            if len(nums) >= 3:
                enrollment = nums[-2]
                change = nums[-1]
                projected = nums[-3]
                prior = nums[0] if len(nums) >= 4 else None
        if enrollment is None:
            continue
        out.append((year, service_area, school, prior, projected, enrollment, change))
    return out


def _table1d_check(year: str, frame: list[tuple]) -> str:
    # change should equal enrollment - prior when prior is present.
    checked = ok = 0
    for _, _, _, prior, _, enrollment, change in frame:
        if prior is not None and change is not None:
            checked += 1
            if enrollment - prior == change:
                ok += 1
    if not checked:
        return f"{len(frame)} schools (no prior-year column to cross-check)"
    return f"{len(frame)} schools, {ok}/{checked} change==enrollment-prior"


# =============================================================================
# Driver
# =============================================================================

def _discover(indir: Path, only: list[str] | None) -> list[tuple[str, Path]]:
    found = []
    for pdf in sorted(indir.glob("*-Annual-Enrollment-Report.pdf")):
        m = _YEAR_RE.search(pdf.name)
        if not m:
            continue
        year = m.group(1)
        if only and year not in only:
            continue
        found.append((year, pdf))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--indir", type=Path, default=DEFAULT_INDIR)
    ap.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    ap.add_argument("--year", action="append", dest="years",
                    help="restrict to this school-year label (repeatable)")
    args = ap.parse_args(argv)

    pdfs = _discover(args.indir, args.years)
    if not pdfs:
        print(f"No enrollment-report PDFs found in {args.indir}", file=sys.stderr)
        return 1

    args.outdir.mkdir(parents=True, exist_ok=True)
    all_od, all_at, all_op, all_1d = [], [], [], []

    print(f"Ingesting {len(pdfs)} report(s) from {args.indir}\n")
    for year, pdf in pdfs:
        lines = _pdf_lines(pdf)

        tables = _parse_section4(lines)
        od, at, op = _section4_frames(year, tables)
        all_od += od
        all_at += at
        all_op += op

        rows = _parse_table1d(lines)
        frame = _table1d_frame(year, rows)
        all_1d += frame

        nrows, bad, no_gt = _section4_health(tables)
        flags = []
        if bad:
            flags.append(f"{bad} malformed dropped")
        if no_gt:
            flags.append(f"{no_gt} tables w/o Grand Total")
        note = f"  [{'; '.join(flags)}]" if flags else ""
        s4 = (f"S4: {len(tables):>3} tbls -> {len(od):>4} od / {len(at):>4} att "
              f"/ {len(op):>3} opt{note}")
        t1 = (f"1-D: {_table1d_check(year, frame)}" if frame
              else "1-D: (none -- charts only)")
        print(f"  {year}  {s4}")
        print(f"         {t1}")

    od_df = pd.DataFrame(all_od, columns=["year", "level", "grade_band",
                                          "residence_area", "school", "n"])
    at_df = pd.DataFrame(all_at, columns=["year", "level", "grade_band",
                                          "school", "residence_area", "n"])
    op_df = pd.DataFrame(all_op, columns=["year", "level", "school",
                                          "grade_band", "residence_area", "n"])
    d1_df = pd.DataFrame(all_1d, columns=["year", "service_area", "school_name",
                                          "prior_enrollment", "projected_enrollment",
                                          "enrollment", "change"])

    # Each (area, school) cell should appear once per table; a school listed
    # twice (rare source re-listing or a leftover layout artifact in the cramped
    # older tables) is collapsed by summing the student counts -- the right
    # normalization since `n` is a headcount. NaN grade_band is preserved.
    def _dedup(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
        before = len(df)
        df = (df.groupby(keys, dropna=False, as_index=False, sort=False)["n"].sum())
        collapsed = before - len(df)
        if collapsed:
            print(f"  (collapsed {collapsed} duplicate cell(s) by summing n)")
        return df

    od_df = _dedup(od_df, ["year", "level", "grade_band", "residence_area", "school"])
    at_df = _dedup(at_df, ["year", "level", "grade_band", "school", "residence_area"])
    op_df = _dedup(op_df, ["year", "level", "school", "grade_band", "residence_area"])

    od_df.to_csv(args.outdir / "section4_od.csv", index=False)
    at_df.to_csv(args.outdir / "section4_attendees.csv", index=False)
    op_df.to_csv(args.outdir / "section4_option_draw.csv", index=False)
    d1_df.to_csv(args.outdir / "enrollment_by_school.csv", index=False)

    print(f"\nWrote to {args.outdir}:")
    print(f"  section4_od.csv           {len(od_df):>6} rows")
    print(f"  section4_attendees.csv    {len(at_df):>6} rows")
    print(f"  section4_option_draw.csv  {len(op_df):>6} rows")
    print(f"  enrollment_by_school.csv  {len(d1_df):>6} rows  "
          f"({d1_df.year.nunique()} years)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
