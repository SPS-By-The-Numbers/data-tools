"""Parse one OSPI Form F-780 Levy Authority PDF.

The form is a 2-page report: page 1 is the data (SUMMARY + SCHEDULE
I/II/III), page 2 is boilerplate explanatory text. Each top-level line
item is letter-prefixed (A./B./C./...) and ends with a trailing numeric
value, sometimes parenthesized for negatives.

Schedule I additionally has 2 sub-items under section A (an enrollment
breakdown) -- these don't carry a letter prefix and get slug-derived
item_codes.
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


_LEAF_RE = re.compile(
    r"^F-780\s+(Initial|Final)\s+(\d{4})\s+Levy\s+Authority$",
    re.IGNORECASE,
)

_SECTION_HEADERS = [
    (re.compile(r"^SUMMARY\s*$", re.IGNORECASE), "summary"),
    (re.compile(r"^SCHEDULE\s+I\b", re.IGNORECASE), "schedule_i"),
    (re.compile(r"^SCHEDULE\s+II\b", re.IGNORECASE), "schedule_ii"),
    (re.compile(r"^SCHEDULE\s+III\b", re.IGNORECASE), "schedule_iii"),
]

_LETTER_ITEM_RE = re.compile(r"^([A-Z])\.\s+(.+)$")
_DISTRICT_RE = re.compile(r"^(\d{5})\s+(.+)\s*$")


def parse_f780_levy_pdf(info: FiscalFilename) -> Iterator[dict]:
    m = _LEAF_RE.match(info.leaf)
    if not m:
        return
    status = m.group(1).capitalize()
    levy_year = int(m.group(2))

    raw_lines = read_pdf_lines(info.path, max_pages=1)
    lines = [collapse_numeric_paren_spaces(merge_split_leading_digit(ln))
             for ln in raw_lines]

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "levy_year": levy_year,
        "status": status,
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f780_levy",
    }

    # District name from the line right after the report title:
    # '17001 Seattle School District'.
    for ln in lines[:6]:
        m = _DISTRICT_RE.match(ln)
        if m and "Levy Authority" not in ln:
            base["district"] = m.group(2).strip()
            break

    section: Optional[str] = None
    for ln in lines:
        # Page footer 'N of M' marks the end of page 1 data; stop processing.
        if re.match(r"^\d+\s+of\s+\d+\s*$", ln):
            break
        # Section header?
        for pat, name in _SECTION_HEADERS:
            if pat.match(ln):
                section = name
                break
        else:
            if section is None:
                continue
            m = _LETTER_ITEM_RE.match(ln)
            if m:
                letter = m.group(1)
                rest = m.group(2).strip()
                label, vtext, value = _split_label_value(rest)
                yield {
                    **base, "section": section,
                    "item_code": letter, "item_label": label,
                    "value": value, "value_text": vtext,
                }
                continue
            # Sub-item: has a trailing value but no letter prefix
            stripped = ln.strip()
            label, vtext, value = _split_label_value(stripped)
            if value is None:
                continue
            slug = _slug(label)
            if not slug:
                continue
            yield {
                **base, "section": section,
                "item_code": slug, "item_label": label,
                "value": value, "value_text": vtext,
            }
            continue


def _split_label_value(s: str):
    """Split a line's text into (label, value_text, value)."""
    parts = s.rsplit(None, 1)
    if len(parts) < 2:
        return s, "", None
    label = parts[0].strip()
    raw = parts[1].strip()
    cleaned = raw.replace("$", "").strip()
    # Parenthesized negative: '($687,798)' -> '-687,798'
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    cleaned = cleaned.lstrip("-")  # keep sign for parse_decimal but strip extras
    # Re-add the leading '-' if cleaned was originally negative.
    if (raw.startswith("(") and raw.endswith(")")
            or raw.replace("$", "").lstrip().startswith("-")):
        cleaned = "-" + cleaned if not cleaned.startswith("-") else cleaned
    val = parse_decimal(cleaned)
    return label, raw, val


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("_", s.lower()).strip("_")[:60]


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
