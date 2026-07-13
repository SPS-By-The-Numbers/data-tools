"""Parse OSPI Report 1220TR ESD SPECIAL EDUCATION TRANSFER OF ALLOCATION.

Only files under `apportionment/YYYY-YYYY/esd/...` with leaf name
`1220 Special Education Allocation.pdf` are 1220TR files -- the ESD-level
form printed alongside the per-district Report 1220 (`fiscal_1220_sped`).
Same-year district-path files carry the district form and are skipped
by this parser (parsed by `sped_1220.py` instead).

The 1220TR is 1 page and has this shape:

    REPORT 1220TR ... 2015-2016 SPECIAL EDUCATION TRANSFER OF ALLOCATION
    ACCOUNTS 3121, 4121 & 4122
    06801 ESD 112
    ACCT 3121  ACCT 4121  ACCT 4122
    SPECIAL ED  SPECIAL    SPECIAL ED
    GENERAL APP EDUCATION  INFANTS
    CCDDD NAME ALLOCATION ALLOCATION ALLOCATION
    06098 HOCKINSON   0.00       0.00       30,099.00
    ...
    TOTAL TRANSFERRED TO ESD 1,940,553.40 9,709,544.03 868,252.15
    SAFETY NET 461,367.00
    GRAND TOTAL 10,170,911.03

The SAFETY NET printed line lives in the Account 4121 column. The
GRAND TOTAL printed line prints one value in 2014-15+ vintages
(combined 4121 + safety net) but three values (one per account) in
2013-14 vintage; the parser captures whatever prints in each column.
"""

import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_LEAF_RE = re.compile(r"^1220\s+Special\s+Education\s+Allocation$", re.IGNORECASE)

# Banner: "06801 ESD 112"
_ESD_BANNER_RE = re.compile(r"^\s*(\d{5})\s+ESD\s+(\d+)\s*$", re.IGNORECASE)
# Detail row leading token: 5-digit CCDDD.
_CCDDD_RE = re.compile(r"^\d{5}$")
_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d{2}$")

_TOTAL_TRANSFERRED_RE = re.compile(r"^TOTAL\s+TRANSFERRED\s+TO\s+ESD\b", re.IGNORECASE)
_SAFETY_NET_RE = re.compile(r"^SAFETY\s+NET\b", re.IGNORECASE)
_GRAND_TOTAL_RE = re.compile(r"^GRAND\s+TOTAL\b", re.IGNORECASE)

# Column x1 anchors -- values in the 3 amount columns right-align to
# these ranges. Windows are set from vintage-safe observations
# (2013-14 through 2016-17).
_COL_WINDOWS = [
    ("acct_3121_special_ed_general_app", (370.0, 440.0)),
    ("acct_4121_special_education",      (440.0, 520.0)),
    ("acct_4122_special_ed_infants",     (520.0, 630.0)),
]

_VALUE_COLUMNS = [name for name, _ in _COL_WINDOWS]

_Y_TOLERANCE = 2.5

_REPORT_TYPES = {
    "apportionment", "fiscal", "state_institutions", "esd_allocations",
    "county_treasurer", "state_agencies_schools_colleges", "technical_colleges",
}


def parse_sped_1220_esd_transfer_pdf(info: FiscalFilename) -> Iterator[dict]:
    if not _LEAF_RE.match(info.leaf):
        return
    # Only ESD-path files carry the 1220TR form.
    if info.org_type != "esd":
        return

    with pdfplumber.open(info.path) as pdf:
        if not pdf.pages:
            return
        page = pdf.pages[0]
        words = page.extract_words(use_text_flow=True)

    rows = _group_rows(words)

    esd_code: Optional[str] = None
    esd_number: Optional[str] = None
    for row in rows:
        text = " ".join(w["text"] for w in row).strip()
        m = _ESD_BANNER_RE.match(text)
        if m:
            esd_code = m.group(1)
            esd_number = m.group(2)
            break

    if esd_code is None:
        return

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "esd_code": esd_code,
        "esd_number": esd_number,
        "_source": _source_path(info.path),
        "_source_table": "fiscal_1220_sped_transfer",
    }

    for row in rows:
        text = " ".join(w["text"] for w in row).strip()
        first_token = row[0]["text"] if row else ""

        # Detail row: leading 5-digit CCDDD.
        if _CCDDD_RE.match(first_token) and not _ESD_BANNER_RE.match(text):
            member_ccddd = first_token
            # Collect label tokens (everything between CCDDD and the
            # trailing value tokens).
            label_words = [
                w for w in row[1:]
                if not _VALUE_RE.match(w["text"])
            ]
            member_name = re.sub(
                r"\s+", " ",
                " ".join(w["text"] for w in label_words).strip())
            yield _build_row(base, "detail", member_ccddd, member_name, row)
            continue

        if _TOTAL_TRANSFERRED_RE.match(text):
            yield _build_row(base, "total_transferred", "00000", "", row)
            continue
        if _SAFETY_NET_RE.match(text):
            yield _build_row(base, "safety_net", "00000", "", row)
            continue
        if _GRAND_TOTAL_RE.match(text):
            yield _build_row(base, "grand_total", "00000", "", row)
            continue


def _build_row(base, row_kind: str, member_ccddd: str, member_name: str,
               row_words) -> dict:
    row = {
        **base,
        "row_kind": row_kind,
        "member_ccddd": member_ccddd,
        "member_name": member_name,
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
