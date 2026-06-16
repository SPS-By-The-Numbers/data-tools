"""Parse OSPI Report 1251 (FTE) or 1251H (Head-count) enrollment PDFs.

Both reports share a multi-section structure: each section is a
free-form title line, then a header line listing the month columns,
then one row per grade with N+1 trailing values (N months plus the
trailing AVERAGE column). The parser walks lines stateful, identifies
section titles by keyword match, picks up month columns from the
header, then emits one row per (grade, month, value) triple.
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


_HEADER_DISTRICT_RE = re.compile(
    r"^(.+?)\s+No\.\s*\d+\s+-\s+\(\d{5}\)\s+(.+?)\s+County\b",
)

# Month column header: SEPTEMBER OCTOBER ... (10 or 12 months) + AVERAGE.
_MONTH_HEADER_RE = re.compile(
    r"^SEPTEMBER\s+OCTOBER\s+NOVEMBER\s+DECEMBER\s+JANUARY\s+FEBRUARY\s+MARCH\s+APRIL\s+MAY\s+JUNE\b",
    re.IGNORECASE,
)

# Section title keywords. Matched as a substring (case-sensitive).
_SECTION_KEYWORDS = (
    "Total K-12 Basic Education Enrollment",
    "Total ALE Enrollment",
    "Transition To Kindergarten",
    "Running Start",
    "Open Doors",
    "TBIP",
)


_VALUE_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")


def parse_1251_enrollment_pdf(info: FiscalFilename) -> Iterator[dict]:
    if "1251 FTE" in info.leaf:
        report_kind = "fte"
    elif "1251H" in info.leaf:
        report_kind = "headcount"
    else:
        return

    raw_lines = read_pdf_lines(info.path)
    lines = [collapse_numeric_paren_spaces(merge_split_leading_digit(ln))
             for ln in raw_lines]

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "report_kind": report_kind,
        "_source": _source_path(info.path),
        "_source_table": "fiscal_1251_enrollment",
    }

    # District + county from header line:
    # 'Seattle School District No. 1 - (17001) King County No. 17 E.S.D 121'.
    for ln in lines[:8]:
        m = _HEADER_DISTRICT_RE.match(ln)
        if m:
            base["district"] = m.group(1).strip()
            base["county"] = m.group(2).strip()
            break

    section: Optional[str] = None
    months: List[str] = []
    # Some older-form sections print multiple TOTALS rows (a grand total plus
    # sub-group totals). Append _2 / _3 / ... to the grade slug for the
    # second/third occurrence so logical-key uniqueness holds.
    totals_seen_per_section: dict = {}

    for ln in lines:
        # Page boilerplate -- skip.
        if ln.startswith(("STATE OF WASHINGTON", "Report 1251", "SUPERINTENDENT",
                          "SUMMARY OF FULL-TIME", "SUMMARY OF HEAD-COUNT")):
            continue

        # Section title?
        if any(kw in ln for kw in _SECTION_KEYWORDS) and not _MONTH_HEADER_RE.match(ln):
            section = _slug_section(ln)
            months = []
            totals_seen_per_section.setdefault(section, 0)
            continue

        # Month column header?
        if _MONTH_HEADER_RE.match(ln):
            months = ln.split()
            continue

        # Data row?
        if section is None or not months:
            continue
        tokens = ln.split()
        # Skip leading *** markers used for total rows.
        start = 0
        while start < len(tokens) and set(tokens[start]) == {"*"}:
            start += 1
        tokens = tokens[start:]
        if not tokens:
            continue
        # Find the first numeric token -- that's where the values start.
        v_start = None
        for i, t in enumerate(tokens):
            if _VALUE_RE.match(t):
                v_start = i
                break
        if v_start is None or v_start == 0:
            continue
        values = tokens[v_start:]
        if len(values) != len(months):
            # Column count doesn't match -- skip rather than misalign.
            continue
        grade_tokens = tokens[:v_start]
        grade = _slug(" ".join(grade_tokens))
        if not grade:
            continue
        if grade == "totals" and section is not None:
            totals_seen_per_section[section] = totals_seen_per_section.get(section, 0) + 1
            n = totals_seen_per_section[section]
            if n > 1:
                grade = f"totals_{n}"
        for month, vtext in zip(months, values):
            yield {
                **base,
                "section": section,
                "grade": grade,
                "month": month.upper(),
                "value": parse_decimal(vtext),
                "value_text": vtext,
            }


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("_", s.lower()).strip("_")


def _slug_section(title: str) -> str:
    """Canonicalize a section title to a stable identifier.

    Drops the trailing parenthetical month-range note (`-, (Oct - Aug)`),
    so 'Running Start - 9 month average, (Oct - Aug)' and a future
    rephrasing of the same idea both produce `running_start`.
    """
    # Strip month-range / averaging notes.
    cleaned = re.sub(r"\s*-\s*\d+[- ]?month[^,]*,?\s*\(.*?\)\s*$", "", title)
    cleaned = re.sub(r"\s*-\s*\d+[- ]?month[^,]*$", "", cleaned)
    return _slug(cleaned)


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
