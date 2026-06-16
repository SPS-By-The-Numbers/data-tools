"""Parse one OSPI Report 1735T Special Education Enrollment PDF.

The form is a single small monthly enrollment table (3-5 grade rows x
10 months + AVERAGE). Walks lines, picks up the month-column header,
then emits one row per (grade, month, value) cell until the TOTAL row.
"""

import logging
import re
from typing import Iterator, List, Optional

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, is_na, merge_split_leading_digit,
    parse_decimal, read_pdf_lines,
)


logger = logging.getLogger(__name__)


_MONTH_HEADER_RE = re.compile(
    r"^SEPTEMBER\s+OCTOBER\s+NOVEMBER\s+DECEMBER\s+JANUARY\s+FEBRUARY\s+MARCH\s+APRIL\s+MAY\s+JUNE\b",
    re.IGNORECASE,
)
_VALUE_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
_END_LINE_RE = re.compile(r"^(I\s+hereby|Superintendent\s+or\s+Authorized)\b", re.IGNORECASE)


def parse_1735t_pdf(info: FiscalFilename) -> Iterator[dict]:
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
        "_source_table": "fiscal_1735t_sped_enrollment",
    }

    # District + county from header.
    for ln in lines[:8]:
        m = re.match(r"^(.+?)\s+(?:No\.\s*\d+|#\d+)\s+-\s+\(\d{5}\)\s+(.+?)\s+County\b", ln)
        if m:
            base["district"] = m.group(1).strip()
            base["county"] = m.group(2).strip()
            break

    months: List[str] = []
    pending_label = ""  # accumulator for cross-line label tails (e.g. 'Other Tier K-' + '21')
    last_row_grade: Optional[str] = None  # to attach trailing label tail back

    for ln in lines:
        if _END_LINE_RE.match(ln):
            break
        if ln.startswith(("STATE OF WASHINGTON", "Report 1735T", "SUPERINTENDENT",
                          "SPECIAL EDUCATION ENROLLMENT", "* 9 month")):
            continue

        if _MONTH_HEADER_RE.match(ln):
            months = ln.split()
            continue
        if not months:
            continue

        tokens = ln.split()
        # Anchor on the TRAILING N tokens being numeric -- the label can
        # itself start with digits (e.g. the 2024-25 row '14 18 Tier TK 0 0
        # 0 0 0 0 0 0 0 0 0.00') so leading-numeric scanning would
        # mis-classify the label as the value-start position.
        n_months = len(months)
        if len(tokens) < n_months + 1:
            continue
        candidate_values = tokens[-n_months:]
        if not all(_VALUE_RE.match(t) for t in candidate_values):
            continue
        grade_tokens = tokens[:-n_months]
        if not grade_tokens:
            continue
        grade = _slug(" ".join(grade_tokens))
        if not grade:
            continue
        for month, vtext in zip(months, candidate_values):
            yield {
                **base,
                "grade": grade,
                "month": month.upper(),
                "value": parse_decimal(vtext),
                "value_text": vtext,
            }
        last_row_grade = grade


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("_", s.lower()).strip("_")


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
