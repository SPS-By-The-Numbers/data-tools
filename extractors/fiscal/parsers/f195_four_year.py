"""Parse one OSPI Form F-195F Four-year Budget Summary Plan PDF.

The form is a per-district multi-page report (~14 pages) with a uniform
4-year-column shape:
  - Page 1: ENROLLMENT AND STAFF COUNTS (Section A: 18 enrollment items,
    Section B: 2 staff-count items).
  - Subsequent pages: SUMMARY OF X FUND BUDGET for each of 5 funds
    (General, ASB, Debt Service, Capital Projects, Transportation Vehicle).
    Each fund repeats: REVENUES, totals, EXPENDITURES, totals,
    BEGINNING FUND BALANCE, ENDING FUND BALANCE.

Every value-bearing line carries 4 trailing numeric tokens (Current +
Forecast Year +1 / +2 / +3). The parser emits 4 long-form rows per item.
"""

import logging
import re
from typing import Iterator, Optional

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, is_na, merge_split_leading_digit,
    parse_decimal, read_pdf_lines,
)


logger = logging.getLogger(__name__)


_FUND_HEADERS = [
    ("SUMMARY OF GENERAL FUND BUDGET",                 "general"),
    ("SUMMARY OF ASSOCIATED STUDENT BODY FUND BUDGET", "asb"),
    ("SUMMARY OF DEBT SERVICE FUND BUDGET",            "debt_service"),
    ("SUMMARY OF CAPITAL PROJECTS FUND BUDGET",        "capital_projects"),
    ("SUMMARY OF TRANSPORTATION VEHICLE FUND BUDGET",  "transportation_vehicle"),
]

# Section markers within a fund, in checked order (longer first).
_SECTION_MARKERS = [
    ("REVENUES AND OTHER FINANCING SOURCES", "revenues"),
    ("REVENUES",            "revenues"),
    ("EXPENDITURES",        "expenditures"),
    ("BEGINNING FUND BALANCE", "beginning_balance"),
    ("ENDING FUND BALANCE", "ending_balance"),
]

# Page 1 enrollment+staff sub-sections (driven by Section letter).
_ENROLLMENT_STAFF_LETTERS = {
    "A": "enrollment",
    "B": "staff",
}

# Year column header line ('2021-2022 2022-2023 2023-2024 2024-2025').
_YEAR_COLS_RE = re.compile(
    r"^\s*(\d{4}-\d{4})\s+(\d{4}-\d{4})\s+(\d{4}-\d{4})\s+(\d{4}-\d{4})\s*$"
)

# Line prefix patterns.
_OSPI_CODE_RE = re.compile(r"^(\d{2,4})(?:\s+\|)?\s+(.+)$")
_GL_CODE_RE = re.compile(r"^(G\.L\.\d+)\s+(.+)$")
_SECTION_LETTER_RE = re.compile(r"^([A-Z])\.\s+(.+)$")
_ITEM_NUMBER_RE = re.compile(r"^(\d+)\.\s+(.+)$")

# A single value token: optional minus, digits, possibly comma-separated, optional decimal.
_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$")


def _has_trailing_4_values(tokens):
    """Return the last 4 tokens if they all look numeric, else None."""
    if len(tokens) < 4:
        return None
    last4 = tokens[-4:]
    if all(_VALUE_TOKEN_RE.match(t) for t in last4):
        return last4
    return None


def _parse_year_cols(lines, start_idx):
    """Look for a year-column header within the next few lines after start_idx.

    Returns (year_list, found_idx) or (None, start_idx).
    """
    for j in range(start_idx, min(start_idx + 6, len(lines))):
        m = _YEAR_COLS_RE.match(lines[j])
        if m:
            return [m.group(1), m.group(2), m.group(3), m.group(4)], j
    return None, start_idx


def _strip_footnote_suffix(label: str) -> str:
    """Drop trailing '1/', '2/', etc. footnote markers and surrounding noise."""
    return re.sub(r"\s*\d/\s*$", "", label).strip()


def parse_f195_four_year_pdf(info: FiscalFilename) -> Iterator[dict]:
    raw_lines = read_pdf_lines(info.path)
    lines = [collapse_numeric_paren_spaces(merge_split_leading_digit(ln))
             for ln in raw_lines]

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f195_four_year",
    }

    fund: Optional[str] = None
    section: Optional[str] = None
    year_cols: Optional[list] = None  # 4 data_school_year labels

    i = 0
    while i < len(lines):
        ln = lines[i]

        # District name from second line (e.g. 'Seattle Public Schools District No.001').
        if not base["district"] and i < 5 and "District" in ln:
            base["district"] = re.sub(r"\s+District No\.\d+.*$", "", ln).strip()

        # Year-column header -- usually right after a fund or enrollment header.
        m = _YEAR_COLS_RE.match(ln)
        if m:
            year_cols = [m.group(1), m.group(2), m.group(3), m.group(4)]
            i += 1
            continue

        # Fund header.
        matched_fund = None
        for needle, name in _FUND_HEADERS:
            if needle in ln:
                matched_fund = name
                break
        if matched_fund:
            # Page boundaries re-print the fund header at the top of each page.
            # Only reset the active section when we genuinely enter a NEW fund.
            if matched_fund != fund:
                fund = matched_fund
                section = None
            # Year cols may follow in the next few lines.
            new_cols, jdx = _parse_year_cols(lines, i + 1)
            if new_cols is not None:
                year_cols = new_cols
                i = jdx + 1
                continue
            i += 1
            continue

        # Page 1's enrollment table.
        if ln.startswith("ENROLLMENT AND STAFF COUNTS"):
            fund = "enrollment_staff"
            section = None
            new_cols, jdx = _parse_year_cols(lines, i + 1)
            if new_cols is not None:
                year_cols = new_cols
                i = jdx + 1
                continue
            i += 1
            continue

        # Section letter -- in enrollment_staff drives Section A=enrollment / B=staff.
        if fund == "enrollment_staff":
            m = _SECTION_LETTER_RE.match(ln)
            if m and m.group(1) in _ENROLLMENT_STAFF_LETTERS:
                section = _ENROLLMENT_STAFF_LETTERS[m.group(1)]
                i += 1
                continue

        # Section marker within a fund.
        matched_section = None
        for needle, name in _SECTION_MARKERS:
            if ln == needle:
                matched_section = name
                break
        if matched_section is not None:
            section = matched_section
            i += 1
            continue

        # Skip page header / footer noise.
        if (ln.startswith("Form F-195F")
                or ln.endswith(" PM") or ln.endswith(" AM")
                or ln.startswith(f"{info.school_year}")
                or ln.endswith(" F-195F")
                or ln == "F-195F"
                or ln.startswith(("1/", "2/", "3/", "4/"))):
            i += 1
            continue

        # Value-bearing line: must have 4 trailing numeric tokens.
        if year_cols is None or fund is None:
            i += 1
            continue
        tokens = ln.split()
        last4 = _has_trailing_4_values(tokens)
        if last4 is None:
            i += 1
            continue

        # Extract label (everything before the 4 trailing values) and identify the
        # item_code prefix.
        label_part = " ".join(tokens[:-4]).strip()
        if not label_part:
            i += 1
            continue
        item_code, item_label, derived_section = _classify_line(label_part)
        # In enrollment_staff fund, section comes from numbered items'
        # already-tracked context (A or B). Otherwise stash totals/section-letter
        # rows as 'summary'.
        if section is None and fund == "enrollment_staff":
            section = "enrollment"  # default before we hit Section A label
        if derived_section and section is None:
            section = derived_section
        # For section-letter rows (totals), override to 'summary' so they don't
        # collide with sibling code-prefixed items in the same logical bucket.
        if derived_section == "summary":
            row_section = "summary"
        else:
            row_section = section or ""

        for offset, (year, vtext) in enumerate(zip(year_cols, last4)):
            val = parse_decimal(vtext)
            yield {
                **base,
                "fund": fund,
                "section": row_section,
                "item_code": item_code,
                "data_year_offset": offset,
                "data_school_year": year,
                "data_class_of": int(year.split("-")[1]),
                "item_label": item_label,
                "value": val,
                "value_text": vtext,
            }
        i += 1


def _slugify_label(label: str) -> str:
    """Produce a stable snake_case identifier from a free-text label.

    Used as the `item_code` fallback for lines that carry no OSPI / G.L. /
    section-letter prefix (e.g. Debt Service Fund's 'Matured Bond
    Expenditures', 'Interest on Bonds', etc.).
    """
    s = re.sub(r"[^A-Za-z0-9]+", "_", label.lower()).strip("_")
    return s


def _classify_line(label_part: str):
    """Identify (item_code, normalized_label, derived_section) from a label prefix.

    Strips OSPI code / G.L. code / section letter / item number prefixes.
    For lines with no recognizable prefix, derives item_code from a slug of
    the label so siblings within a section don't collide on '' codes.
    derived_section is 'summary' for section-letter (totals) rows, None otherwise.
    """
    s = label_part.strip()
    m = _GL_CODE_RE.match(s)
    if m:
        return m.group(1), _strip_footnote_suffix(m.group(2)), None
    m = _OSPI_CODE_RE.match(s)
    if m and m.group(1).isdigit() and 2 <= len(m.group(1)) <= 4:
        return m.group(1), _strip_footnote_suffix(m.group(2)), None
    m = _SECTION_LETTER_RE.match(s)
    if m:
        return m.group(1), _strip_footnote_suffix(m.group(2)), "summary"
    m = _ITEM_NUMBER_RE.match(s)
    if m:
        return m.group(1), _strip_footnote_suffix(m.group(2)), None
    label = _strip_footnote_suffix(s)
    return _slugify_label(label), label, None


def _source_path(p) -> str:
    parts = list(p.parts)
    REPORT_TYPES = {
        "apportionment", "fiscal", "state_institutions", "esd_allocations",
        "county_treasurer", "state_agencies_schools_colleges", "technical_colleges",
    }
    idx = -1
    for i, seg in enumerate(parts[:-1]):
        if seg == "fiscal" and i + 1 < len(parts) and parts[i + 1] in REPORT_TYPES:
            idx = i
    if idx < 0:
        return str(p)
    return "/".join(parts[idx + 1:])
