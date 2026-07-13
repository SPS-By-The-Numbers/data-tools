"""Parse the page-1 expenditures partition of the Federal Indirect Cost
Rate Schedule sub-reports on OSPI F-196 All Pages PDFs.

Two schedules per file: Restricted (pp 72-73 typical) and Unrestricted
(pp 74-75 typical). Each schedule's page 1 has the same 7-column shape:

    TOTAL PROGRAM EXPENDITURES | CAPITAL OUTLAY | DEBT SERVICE
    | DISTORTING ITEMS | (ADDED TO BASE) UNALLOWABLE
    | (POOL) INDIRECT EXPENDITURES | (BASE) DIRECT EXPENDITURES

Rows on page 1:

  - `TOTAL PROGRAMS 01-89, 98, 99` -- 1 row (row_kind='programs_total').
  - `PROGRAM 97 ACTIVITIES` -- section header, skipped.
  - `<NN> <activity label> <values...>` -- ~20 activity_detail rows.
  - `Total Program 97` -- 1 row (row_kind='program_97_total').

Parsing approach:

  1. Locate each schedule's page 1 by banner regex.
  2. Extract words with use_text_flow=True.
  3. Group by y-tolerance into rows.
  4. Bin numeric values by right-edge x1 into 7 column windows.
     Windows are set from vintage-safe ranges; the same anchors hold
     across 2013-14 / 2020-21 / 2024-25.
  5. Multi-line activity labels: rows with only label tokens (no
     leading code, no values) are joined into the previous row's label
     buffer (e.g. row 67 "Building and Property" + wrap "Security").
"""

import logging
import re
from collections import defaultdict
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_BANNER_RESTRICTED = re.compile(
    r"Schedule\s+for\s+Determining\s+School\s+District\s+Federal\s+Restricted\s+Indirect\s+Cost\s+Rate",
    re.IGNORECASE)
_BANNER_UNRESTRICTED = re.compile(
    r"Schedule\s+for\s+Determining\s+School\s+District\s+Federal\s+Unrestricted\s+Indirect\s+Cost\s+Rate",
    re.IGNORECASE)

_PROGRAMS_TOTAL_RE = re.compile(r"^TOTAL\s+PROGRAMS\s+01-89", re.IGNORECASE)
_PROGRAM_97_TOTAL_RE = re.compile(r"^Total\s+Program\s+97\b", re.IGNORECASE)
_PROGRAM_97_HEADER_RE = re.compile(r"^PROGRAM\s+97\s+ACTIVITIES\b", re.IGNORECASE)

_ACTIVITY_CODE_RE = re.compile(r"^(\d{2})$")
_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d{2}$")

_Y_TOLERANCE = 2.0

# Column-anchor windows keyed by column name. Each maps to (x1_lo, x1_hi).
# Values right-align to these x1 positions across 2013-14, 2020-21, and
# 2024-25 vintages.
_COL_WINDOWS = [
    ("total_expenditures", (250.0, 290.0)),
    ("capital_outlay",     (335.0, 380.0)),
    ("debt_service",       (415.0, 460.0)),
    ("distorting_items",   (495.0, 525.0)),
    ("unallowable",        (570.0, 605.0)),
    ("indirect_pool",      (655.0, 700.0)),
    ("direct_base",        (735.0, 790.0)),
]

_VALUE_COLUMNS = [name for name, _ in _COL_WINDOWS]

_REPORT_TYPES = {
    "apportionment", "fiscal", "state_institutions", "esd_allocations",
    "county_treasurer", "state_agencies_schools_colleges", "technical_colleges",
}


def parse_f196_indirect_rate_detail_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_indirect_rate_detail",
    }

    with pdfplumber.open(info.path) as pdf:
        restricted_p1: Optional[int] = None
        unrestricted_p1: Optional[int] = None
        for i, page in enumerate(pdf.pages):
            t = page.extract_text() or ""
            first_lines = " ".join(t.split("\n", 3)[:3])
            if restricted_p1 is None and _BANNER_RESTRICTED.search(first_lines):
                restricted_p1 = i
            elif unrestricted_p1 is None and _BANNER_UNRESTRICTED.search(first_lines):
                unrestricted_p1 = i

        if restricted_p1 is None and unrestricted_p1 is None:
            return

        # District from first found page. Use extract_text() (spatially
        # ordered top-to-bottom) rather than extract_words (text-flow
        # ordered) so the REPORT F196 line is available in the top rows.
        anchor_pg = restricted_p1 if restricted_p1 is not None else unrestricted_p1
        first_text = pdf.pages[anchor_pg].extract_text() or ""
        d = _district_from_text(first_text)
        if d:
            base["district"] = d

        if restricted_p1 is not None:
            yield from _parse_schedule_page(
                pdf.pages[restricted_p1], "restricted", base)
        if unrestricted_p1 is not None:
            yield from _parse_schedule_page(
                pdf.pages[unrestricted_p1], "unrestricted", base)


def _district_from_text(text: str) -> Optional[str]:
    for line in text.split("\n")[:10]:
        m = re.search(r"REPORT\s+F196\s+(.+?)\s+No\.\s*\d+", line, re.IGNORECASE)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _parse_schedule_page(page, rate_kind: str, base) -> Iterator[dict]:
    words = page.extract_words(use_text_flow=True)
    rows = _group_rows(words)

    # Find the start of the data section: everything after the header row
    # "PROGRAM AND ACTIVITY TITLES" (or the first row matching
    # TOTAL PROGRAMS 01-89 if that header is absent).
    data_started = False
    pending_row: Optional[dict] = None

    for row_words in rows:
        text = " ".join(w["text"] for w in row_words).strip()
        text_l = text.lower()

        if not data_started:
            if _PROGRAMS_TOTAL_RE.match(text) or "program and activity titles" in text_l:
                data_started = True
                # Fall through -- if this is the PROGRAMS TOTAL row itself, we
                # want to process it as data.
                if not _PROGRAMS_TOTAL_RE.match(text):
                    continue
            else:
                continue

        # Skip section headers, page footers, banner echoes.
        if _PROGRAM_97_HEADER_RE.match(text):
            if pending_row is not None:
                yield pending_row
                pending_row = None
            continue
        if re.match(r"^Page\s+\d+\s+of\s+\d+", text):
            continue

        # Programs Total row.
        if _PROGRAMS_TOTAL_RE.match(text):
            if pending_row is not None:
                yield pending_row
            pending_row = _build_row(
                base, rate_kind, "programs_total", "00",
                "TOTAL PROGRAMS 01-89, 98, 99", row_words)
            continue

        # Program 97 Total row.
        if _PROGRAM_97_TOTAL_RE.match(text):
            if pending_row is not None:
                yield pending_row
            pending_row = _build_row(
                base, rate_kind, "program_97_total", "00",
                "Total Program 97", row_words)
            continue

        # Activity detail rows: leading token is a 2-digit code.
        first_token = row_words[0]["text"]
        if _ACTIVITY_CODE_RE.match(first_token):
            if pending_row is not None:
                yield pending_row
            code = first_token
            label_words = [
                w for w in row_words[1:]
                if not _VALUE_RE.match(w["text"])
            ]
            label = re.sub(
                r"\s+", " ",
                " ".join(w["text"] for w in label_words).strip())
            pending_row = _build_row(
                base, rate_kind, "activity_detail", code, label, row_words)
            continue

        # Otherwise: label continuation for pending_row.
        if pending_row is not None:
            label_words = [
                w for w in row_words if not _VALUE_RE.match(w["text"])
            ]
            suffix = re.sub(
                r"\s+", " ",
                " ".join(w["text"] for w in label_words).strip())
            if suffix:
                joined = pending_row["activity_label"] + " " + suffix
                pending_row["activity_label"] = re.sub(r"\s+", " ", joined).strip()

    if pending_row is not None:
        yield pending_row


def _build_row(base, rate_kind: str, row_kind: str, activity_code: str,
               activity_label: str, row_words) -> dict:
    row = {
        **base,
        "rate_kind": rate_kind,
        "row_kind": row_kind,
        "activity_code": activity_code,
        "activity_label": activity_label,
    }
    for col in _VALUE_COLUMNS:
        row[col] = None

    for w in row_words:
        if not _VALUE_RE.match(w["text"]):
            continue
        x1 = w["x1"]
        for name, (lo, hi) in _COL_WINDOWS:
            if lo <= x1 <= hi:
                row[name] = parse_decimal(w["text"])
                break
    return row


def _group_rows(words, y_tol=_Y_TOLERANCE) -> List[List[dict]]:
    rows: List[List[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        placed = False
        for row in rows:
            if abs(row[0]["top"] - w["top"]) <= y_tol:
                row.append(w)
                placed = True
                break
        if not placed:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
    rows.sort(key=lambda row: min(w["top"] for w in row))
    return rows


def _source_path(p) -> str:
    parts = list(p.parts)
    idx = -1
    for i, seg in enumerate(parts[:-1]):
        if seg == "fiscal" and i + 1 < len(parts) and parts[i + 1] in _REPORT_TYPES:
            idx = i
    if idx < 0:
        return str(p)
    return "/".join(parts[idx + 1:])
