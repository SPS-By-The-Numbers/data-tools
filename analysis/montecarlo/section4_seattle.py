"""Extract the SPS Annual Enrollment Report "Section 4" origin-destination data.

Source: ``data/2024-25-section4.pdf`` — "Comparison of Enrollment and
Attendance Areas" from the SPS 2024-25 Annual Enrollment Report. For every
attendance area it reports where the resident students actually enrolled, and
for every school where its attendees live. That is an **observed
origin-destination (OD) matrix** of residence attendance-area -> school for
the 2024-25 baseline year — the empirical ground truth for the assignment
stage's draw kernels (option-school pull, HCC pathways, neighborhood
retention/opt-out).

The PDF has five tables:

  * 4-A  ES/K-8: one block per attendance area (paired tables); K-8
         attendance schools get TWO paired blocks (K-5 and 6-8); option
         schools get draw-only blocks (double K-5/6-8, or a single table for
         district-draw schools like Cascadia).
  * 4-B  MS summary matrix     (redundant with 4-C; not parsed)
  * 4-C  MS, paired tables per attendance area
  * 4-D  HS summary matrix     (redundant with 4-E; not parsed)
  * 4-E  HS, paired tables per attendance area

Each *paired* block looks like:

      Where Students Attending          Where the Students Living in the
              <X>                              <X> Attendance Area
                Live                                Attend School
  Attendance Area      Total       School                         Total
  ...                              ...

The RIGHT table is a row of the OD matrix (residents of X -> schools); the
LEFT table is the column for X's school (attendees of school X by residence,
including "Out of District/Unknown"). Header names may wrap across lines and
blocks may continue onto a second page with a repeated header.

Outputs (tracked CSVs under ``analysis/montecarlo/section4/``):

  * od.csv           -- level, grade_band, residence_area, school, n
                        (right tables; grade_band only for K-8 blocks)
  * attendees.csv    -- level, grade_band, school, residence_area, n
                        (left tables; for K-8 "6-8" blocks the residence
                        areas are MIDDLE-school areas)
  * option_draw.csv  -- level, school, grade_band, residence_area, n
                        (draw-only blocks; band "all" for single tables)

School/area names are RAW (e.g. "Martin Luther King", "West Seattle ES",
"Daniel Bagley"); normalization to ``school_id`` happens in the
school_directory stage.

Build (requires the PDF + ``pdftotext``):

    $ python3 -m analysis.montecarlo.section4_seattle --build

Then in code:

    from analysis.montecarlo import section4_seattle as s4
    od = s4.load_od()
    draw = s4.load_option_draw()
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PDF = _REPO_ROOT / "data" / "2024-25-section4.pdf"
OUT_DIR = Path(__file__).resolve().parent / "section4"

# Table marker -> grade level of the blocks that follow it.
_TABLE_LEVEL = {"4-A": "ES", "4-C": "MS", "4-E": "HS"}

_ROW_RE = re.compile(r"^(.+?)\s{2,}([\d,]+)$")
_TABLE_MARKER_RE = re.compile(r"Table:\s*(4-[A-E])")
_BAND_RE = re.compile(r"\((K-5|6-8)\)")
# Trailing header-furniture tokens to strip off a wrapped right-side name.
_FURNITURE = {"Attendance", "Area", "Attend", "School"}


def _pdf_text() -> list[str]:
    if not SOURCE_PDF.exists():
        raise FileNotFoundError(
            f"{SOURCE_PDF} not found. The section4/ intermediates are tracked "
            "and may already be sufficient; only --build needs the PDF."
        )
    out = subprocess.run(
        ["pdftotext", "-layout", str(SOURCE_PDF), "-"],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.splitlines()


def _parse_side(text: str) -> tuple[str, int] | None:
    m = _ROW_RE.match(text.strip())
    if not m:
        return None
    return m.group(1).strip(), int(m.group(2).replace(",", ""))


def _strip_furniture(name: str) -> str:
    """Drop trailing 'Attendance Area Attend School' fragments from a name."""
    tokens = name.split()
    while tokens and tokens[-1] in _FURNITURE:
        tokens.pop()
    return " ".join(tokens)


class _Block:
    """One parsed table block.

    kind:
      * "paired" -- attendance-area block; left = attendees of the area
        school by residence, right = area residents by school attended.
      * "double" -- option/K-8 draw page: two attendee-style tables (K-5/6-8).
      * "single" -- option draw page with one table (district-wide draw).
    """

    def __init__(self, level: str, kind: str, name: str, right_name: str | None,
                 left_band: str | None, right_band: str | None, split: int | None):
        self.level = level
        self.kind = kind
        self.name = name
        self.right_name = right_name
        self.left_band = left_band
        self.right_band = right_band
        self.split = split
        self.left_rows: list[tuple[str, int]] = []
        self.right_rows: list[tuple[str, int]] = []
        self._left_done = False
        self._right_done = kind == "single"

    def key(self):
        return (self.level, self.kind, self.name, self.left_band, self.right_band)

    def feed(self, line: str) -> None:
        if self.split is None:
            left, right = line.strip(), ""
        else:
            left, right = line[: self.split].strip(), line[self.split:].strip()
        if left and not self._left_done:
            parsed = _parse_side(left)
            if parsed:
                self.left_rows.append(parsed)
                if parsed[0] == "Grand Total":
                    self._left_done = True
        if right and not self._right_done:
            parsed = _parse_side(right)
            if parsed:
                self.right_rows.append(parsed)
                if parsed[0] == "Grand Total":
                    self._right_done = True

    @property
    def done(self) -> bool:
        return self._left_done and self._right_done


def _find_header(lines: list[str], i: int, level: str) -> tuple[_Block, int] | None:
    """If lines[i] starts a block header, return (_Block, next_line_index).

    A header is: a "Where Students Attending" line, then 1-3 name/Live lines
    (possibly wrapped, possibly with blank lines), then the column-header
    line ("Attendance Area ... Total [School|Attendance Area ... Total]").
    """
    line = lines[i]
    if "Where Students Attending" not in line:
        return None
    paired = "Students Living in the" in line
    double = not paired and line.count("Where Students Attending") == 2

    # Collect the header group: non-blank lines up to the column-header line.
    group: list[str] = []
    j = i + 1
    while j < len(lines) and len(group) < 5:
        nxt = lines[j]
        if nxt.strip():
            # One source page (Rainier View) mislabels the left column
            # header as "School", so accept either label.
            if nxt.lstrip().startswith(("Attendance Area", "School")) and "Total" in nxt:
                break
            if "Where Students Attending" in nxt or _TABLE_MARKER_RE.search(nxt):
                return None  # ran into the next block: malformed, skip
            group.append(nxt)
        j += 1
    else:
        return None
    colheader = lines[j]

    needed_totals = 1 if not (paired or double) else 2
    if colheader.count("Total") < needed_totals:
        return None

    # Split column = where the right-hand table's label column begins.
    if paired:
        split = colheader.index("School", colheader.index("Total")) - 2
    elif double:
        first = colheader.index("Attendance Area")
        split = colheader.index("Attendance Area", first + 1) - 2
    else:
        split = None

    # The "Live" line ends the name lines (it may carry right-name fragments).
    name_lines = [g for g in group if not g[: split].strip().startswith(("Live", "Attend"))] \
        if split is not None else [g for g in group if not g.strip().startswith("Live")]
    live_lines = [g for g in group if g not in name_lines]

    def left_of(s: str) -> str:
        return s[:split].strip() if split is not None else s.strip()

    def right_of(s: str) -> str:
        return s[split:].strip() if split is not None else ""

    # Long names wrap onto the "Where Students Attending" line itself
    # (e.g. "Where Students Attending Fairmount" / "Park" / "Live").
    name_prefix = re.sub(
        r".*?Where Students Attending", "", left_of(line)
    ).strip()
    name = _BAND_RE.sub(
        "", " ".join([name_prefix] + [left_of(g) for g in name_lines])
    ).strip()
    name = re.sub(r"(\s+Live)+$", "", name)  # "Live" sometimes shares the name line
    left_band_m = _BAND_RE.search(" ".join(left_of(g) for g in live_lines + name_lines))

    if paired:
        # Right-side area name: tail of the Where-line + wrapped fragments.
        tail = re.search(r"Students Living in the(.*)$", line).group(1)
        fragments = [tail] + [right_of(g) for g in group]
        right_name = _strip_furniture(
            _BAND_RE.sub("", " ".join(" ".join(fragments).split())).strip()
        )
        band = left_band_m.group(1) if left_band_m else None
        return _Block(level, "paired", name, right_name, band, band, split), j + 1
    if double:
        right_band_m = _BAND_RE.search(" ".join(right_of(g) for g in group))
        return _Block(
            level, "double", name, name,
            left_band_m.group(1) if left_band_m else "K-5",
            right_band_m.group(1) if right_band_m else "6-8",
            split,
        ), j + 1
    return _Block(level, "single", name, None,
                  left_band_m.group(1) if left_band_m else "all",
                  None, None), j + 1


def _parse_blocks(lines: list[str]) -> list[_Block]:
    blocks: list[_Block] = []
    current: _Block | None = None
    level: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _TABLE_MARKER_RE.search(line)
        if m:
            level = _TABLE_LEVEL.get(m.group(1))  # None for 4-B / 4-D
            i += 1
            continue
        if level is not None:
            found = _find_header(lines, i, level)
            if found is not None:
                block, i = found
                if current is not None and not current.done and current.key() == block.key():
                    pass  # continuation page: keep feeding the same block
                else:
                    if current is not None and not current.done:
                        # Known defect: a few source pages visually cut off the
                        # right table at the page border (no Grand Total).
                        print(f"  NOTE: block {current.name!r} "
                              f"(band={current.left_band}) truncated in source PDF "
                              "(tail rows + Grand Total cut at page border)")
                    current = block
                    blocks.append(block)
                continue
            if current is not None and not current.done:
                current.feed(line)
        i += 1
    return blocks


def _frames(blocks: list[_Block]):
    od, attendees, option = [], [], []
    for b in blocks:
        if b.kind == "paired":
            for school, n in b.right_rows:
                if school != "Grand Total":
                    od.append((b.level, b.left_band, b.right_name, school, n))
            for area, n in b.left_rows:
                if area != "Grand Total":
                    attendees.append((b.level, b.left_band, b.name, area, n))
        else:
            sides = [(b.left_band, b.left_rows)]
            if b.kind == "double":
                sides.append((b.right_band, b.right_rows))
            for band, rows in sides:
                for area, n in rows:
                    if area != "Grand Total":
                        option.append((b.level, b.name, band, area, n))
    od_df = pd.DataFrame(od, columns=["level", "grade_band", "residence_area", "school", "n"])
    at_df = pd.DataFrame(attendees, columns=["level", "grade_band", "school", "residence_area", "n"])
    op_df = pd.DataFrame(option, columns=["level", "school", "grade_band", "residence_area", "n"])
    return od_df, at_df, op_df


def _validate(blocks: list[_Block], od: pd.DataFrame, at: pd.DataFrame) -> None:
    """Internal consistency checks; prints a short report."""
    # 1. Paired blocks: the first row of each side is the area school's own
    #    residents-attending count and must agree. (Compared positionally —
    #    headers use familiar names, rows official ones, e.g. "Hamilton" vs
    #    "Hamilton Intl".)
    paired = [b for b in blocks if b.kind == "paired" and b.left_band != "6-8"]
    bad = []
    for b in paired:
        if not b.left_rows or not b.right_rows or b.left_rows[0] != b.right_rows[0]:
            bad.append((b.name, b.left_rows[:1], b.right_rows[:1]))
    print(f"  diagonal check: {len(paired) - len(bad)}/{len(paired)} blocks consistent")
    for name, l, r in bad:
        print(f"    MISMATCH {name!r}: left={l} right={r}")

    # 2. Transpose: od[area i -> school j] == attendees[school j <- area i]
    #    wherever both were reported (same level, non-K-8 bands).
    m = od[od.grade_band.isna()].merge(
        at[at.grade_band.isna()],
        on=["level", "school", "residence_area"], how="inner",
        suffixes=("_od", "_at"),
    )
    n_bad = (m.n_od != m.n_at).sum()
    print(f"  transpose check: {len(m) - n_bad}/{len(m)} overlapping cells agree")
    if n_bad:
        print(m[m.n_od != m.n_at].to_string(index=False))


def build(verbose: bool = True) -> None:
    lines = _pdf_text()
    blocks = _parse_blocks(lines)
    od, at, op = _frames(blocks)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    od.to_csv(OUT_DIR / "od.csv", index=False)
    at.to_csv(OUT_DIR / "attendees.csv", index=False)
    op.to_csv(OUT_DIR / "option_draw.csv", index=False)

    if verbose:
        kinds = pd.Series([b.kind for b in blocks]).value_counts().to_dict()
        per_level = pd.Series(
            [b.level for b in blocks if b.kind == "paired" and b.left_band != "6-8"]
        ).value_counts().to_dict()
        print(f"  parsed {len(blocks)} blocks {kinds}; attendance areas {per_level}")
        print(f"  od               {len(od):>5} rows -> od.csv")
        print(f"  attendees        {len(at):>5} rows -> attendees.csv")
        print(f"  option_draw      {len(op):>5} rows -> option_draw.csv")
        _validate(blocks, od, at)
        print(f"\nWrote Section 4 intermediates to {OUT_DIR}")


# --- loaders: read the tracked intermediates ---------------------------------

def _load(name: str) -> pd.DataFrame:
    path = OUT_DIR / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python3 -m analysis.montecarlo."
            "section4_seattle --build` (requires data/2024-25-section4.pdf)."
        )
    return pd.read_csv(path)


def load_od() -> pd.DataFrame:
    """Observed 2024-25 OD: level, grade_band, residence_area, school, n."""
    return _load("od")


def load_attendees() -> pd.DataFrame:
    """Where each attendance-area school's attendees live (incl. Out of District)."""
    return _load("attendees")


def load_option_draw() -> pd.DataFrame:
    """Option-school draw by residence area (level, school, grade_band)."""
    return _load("option_draw")


def _summary() -> None:
    print(f"Section 4 OD intermediates in {OUT_DIR}\n")
    if not (OUT_DIR / "od.csv").exists():
        print("  (not built yet — run with --build)")
        return
    od = load_od()
    base = od[od.grade_band.isna()]
    for level in ["ES", "MS", "HS"]:
        sub = base[base.level == level]
        total = sub.n.sum()
        stay = sub[sub.residence_area == sub.school].n.sum()
        print(f"  {level}: {sub.residence_area.nunique()} areas, "
              f"{sub.school.nunique()} destination schools, "
              f"{total} students, {stay / total:.1%} attend their area school")
    op = load_option_draw()
    print(f"\n  option/K-8 draw blocks: {op.school.nunique()} schools")
    for level in ["ES", "MS", "HS"]:
        schools = sorted(op[op.level == level].school.unique())
        if schools:
            print(f"    {level}: {', '.join(schools)}")


if __name__ == "__main__":
    import sys
    if "--build" in sys.argv:
        build()
    else:
        _summary()
