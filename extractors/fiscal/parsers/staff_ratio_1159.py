"""Parse one OSPI Report 1159 K-12 Certificated Instructional Staff Ratio PDF.

The form is short (one page, ~25 lines of body text) and stable across
the three years it ran (2013-14 through 2015-16). Each item is a
labeled line that ends with at most one printed value -- a decimal, a
percentage, the month-name text for A.1, the Yes/No answer for D, or
the `---` placeholder used for D.2 when no penalty applies.

Implementation: walk lines, recognize section letters (A/B/C/D),
match each item line by the leading numeric prefix (`1.`-`8.`) plus
its anchoring label phrase, and strip the label to recover the value.
Per-item label phrases are stable across all three vintages so a
single set of patterns covers the whole corpus.
"""

import logging
import re
from typing import Iterator, List, Optional

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, merge_split_leading_digit,
    parse_decimal, read_pdf_lines,
)


logger = logging.getLogger(__name__)


_LEAF_RE = re.compile(r"^1159\s*-\s*K12\s+Staff\s+Ratios$", re.IGNORECASE)

# Title / header detection.
_REPORT_HEADER_RE = re.compile(
    r"^Report\s+1159\s*\(([FR])\)\s+(\S+-\S+-\S+)\s*$", re.IGNORECASE,
)
_TITLE_RE = re.compile(
    r"^Calculation\s+of\s+\d{4}-\d{2,4}\s+Certificated\s+Instructional\s+Staff\s+Ratio\s*$",
    re.IGNORECASE,
)
_RECIPIENT_RE = re.compile(r"^(\d{5})\s+(.+?)\s*$")

# Section anchors on the body lines that start each lettered group.
_SEC_A_RE = re.compile(r"^A\.\s+Full-Time\s+Equivalent\b", re.IGNORECASE)
_SEC_B_RE = re.compile(r"^B\.\s+FTE\s+Certificated\s+Instructional\s+Staff\b", re.IGNORECASE)
_SEC_C_RE = re.compile(
    r"^C\.\s+Calculated\s+Basic\s+Education\s+CIS\s+Ratio\b.*?\s+(\S+?)\s*$",
    re.IGNORECASE,
)
# D's question wraps onto a second line that ends with the Yes/No answer.
_SEC_D_RE = re.compile(r"^D\.\s+Did\s+the\s+district\s+maintain\b", re.IGNORECASE)
_D_ANSWER_RE = re.compile(
    r"^Basic\s+Education\s+CIS\s+per\s+1000\s+Students\s+in\s+K-12\?\s+(\S+)\s*$",
    re.IGNORECASE,
)

# Per-item label patterns. Each one anchors on the printed leading
# `N.` and the stable label phrase; the trailing value (or blank) is
# captured into group 1.
_A1_RE = re.compile(
    r"^1\.\s+October\s+\d{4}\s+or\s+month\s+selected\s+on\s+Form\s+SPI\s+1160(?:\s+(.+?))?\s*$",
    re.IGNORECASE,
)
_A2_RE = re.compile(
    r"^2\.\s+K-12\s+FTE\s+students\s+\(less\s+Running\s+Start\)\s+from\s+Report\s+P-223(?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)
_A3_RE = re.compile(
    r"^3\.\s+K-12\s+FTE\s+students\s+in\s+Alternative\s+Learning\s+Experience\s+\(ALE\)(?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)
_A4_RE = re.compile(
    r"^4\.\s+K-12\s+FTE\s+students\s+less\s+ALE\s+\[A\.2\s*-\s*A\.3\](?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)
_B1_RE = re.compile(
    r"^1\.\s+K-12\s+FTE\s+CIS\s+in\s+basic\s+education\s+from\s+Report\s+S-275(?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)
_B2_RE = re.compile(
    r"^2\.\s+K-12\s+FTE\s+CIS\s+in\s+ALE\s+\(program\s+02\)\s+from\s+Report\s+S-275(?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)
_B3_RE = re.compile(
    r"^3\.\s+K-12\s+FTE\s+CIS\s+in\s+basic\s+education\s+less\s+ALE\s+\[B\.1\s*-\s*B\.2\](?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)
_B4_RE = re.compile(
    r"^4\.\s+K-12\s+FTE\s+CIS\s+in\s+basic\s+education\s+from\s+Form\s+SPI\s+1158(?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)
_B5_RE = re.compile(
    r"^5\.\s+K-12\s+FTE\s+CIS\s+in\s+special\s+education\s+from\s+Report\s+S-275(?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)
_B6_RE = re.compile(
    r"^6\.\s+K-12\s+FTE\s+CIS\s+in\s+special\s+education\s+from\s+Form\s+SPI\s+1158(?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)
_B7_RE = re.compile(
    r"^7\.\s+K-12\s+FTE\s+CIS\s+in\s+special\s+education\s+%\s+to\s+basic\s+education(?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)
_B8_RE = re.compile(
    r"^8\.\s+Total\s+K-12\s+FTE\s+CIS\s+\[B\.3\s*\+\s*B\.4\s*\+\s*\(\(B\.5\s*\+\s*B\.6\)\s*\*\s*B\.7\)\](?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)
_D1_RE = re.compile(
    r'^1\.\s+If\s+"No,?"\s+K-12\s+ratio\s+shortfall\s+\[46\.00\s*-\s*C\](?:\s+(\S+))?\s*$',
    re.IGNORECASE,
)
_D2_RE = re.compile(
    r"^2\.\s+Penalty\s+Basic\s+Education\s+CIS\s+FTE\s+\[D\.1\s*\*\s*A\.2\s*/\s*1000\](?:\s+(\S+))?\s*$",
    re.IGNORECASE,
)


# Per-item dispatch tables. Order matters only in that within each
# section the (item_num -> regex / item_code / label) mapping is
# applied to each line in order, so duplicates can't happen.
_SECTION_A_ITEMS = [
    ("A.1", _A1_RE, "Selected month (per Form SPI 1160)", "text"),
    ("A.2", _A2_RE, "K-12 FTE students (less Running Start) from Report P-223", "decimal"),
    ("A.3", _A3_RE, "K-12 FTE students in Alternative Learning Experience (ALE)", "decimal"),
    ("A.4", _A4_RE, "K-12 FTE students less ALE [A.2 - A.3]", "decimal"),
]
_SECTION_B_ITEMS = [
    ("B.1", _B1_RE, "K-12 FTE CIS in basic education from Report S-275", "decimal"),
    ("B.2", _B2_RE, "K-12 FTE CIS in ALE (program 02) from Report S-275", "decimal"),
    ("B.3", _B3_RE, "K-12 FTE CIS in basic education less ALE [B.1 - B.2]", "decimal"),
    ("B.4", _B4_RE, "K-12 FTE CIS in basic education from Form SPI 1158", "decimal"),
    ("B.5", _B5_RE, "K-12 FTE CIS in special education from Report S-275", "decimal"),
    ("B.6", _B6_RE, "K-12 FTE CIS in special education from Form SPI 1158", "decimal"),
    ("B.7", _B7_RE, "K-12 FTE CIS in special education % to basic education", "decimal"),
    ("B.8", _B8_RE, "Total K-12 FTE CIS [B.3 + B.4 + ((B.5 + B.6) * B.7)]", "decimal"),
]
_SECTION_D_ITEMS = [
    ("D.1", _D1_RE, 'If "No," K-12 ratio shortfall [46.00 - C]', "decimal"),
    ("D.2", _D2_RE, "Penalty Basic Education CIS FTE [D.1 * A.2 / 1000]", "decimal"),
]


def parse_staff_ratio_1159_pdf(info: FiscalFilename) -> Iterator[dict]:
    if not _LEAF_RE.match(info.leaf):
        return
    raw_lines = read_pdf_lines(info.path, max_pages=1)
    lines = [collapse_numeric_paren_spaces(merge_split_leading_digit(ln))
             for ln in raw_lines]

    # Header scan (first ~8 lines).
    status = ""
    report_date_text = ""
    focal_ccddd = info.ccddd if info.ccddd is not None else 0
    district = ""

    for ln in lines[:8]:
        if not status:
            m = _REPORT_HEADER_RE.match(ln)
            if m:
                status = "Final" if m.group(1).upper() == "F" else "Revised"
                report_date_text = m.group(2).strip()
                continue
        if not district:
            m = _RECIPIENT_RE.match(ln)
            if m and not _TITLE_RE.match(ln):
                code_str = m.group(1)
                # Avoid matching the title's year-prefix or unrelated 5-digit
                # leads. The recipient line is the first 5-digit-prefixed line
                # after the title.
                if code_str.isdigit():
                    code = int(code_str)
                    if focal_ccddd == 0 or code == focal_ccddd:
                        focal_ccddd = code
                        district = m.group(2).strip()

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": focal_ccddd,
        "county": "",
        "district": district,
        "status": status or "Final",
        "report_date_text": report_date_text,
        "_source": _source_path(info.path),
        "_source_table": "fiscal_1159_staff_ratio",
    }

    section: Optional[str] = None
    pending_d_question = False  # waiting for the "...K-12? Yes/No" continuation

    for ln in lines:
        # Section transitions.
        if _SEC_A_RE.match(ln):
            section = "enrollment"
            continue
        if _SEC_B_RE.match(ln):
            section = "cis"
            continue
        if _SEC_C_RE.match(ln):
            # C is a single-line item; its value is the trailing token.
            m = _SEC_C_RE.match(ln)
            value_text = (m.group(1) or "").strip()
            yield _emit(
                base,
                section="ratio",
                item_code="C",
                item_label="Calculated Basic Education CIS Ratio [B.8 / A.4 * 1000]",
                value_text=value_text,
                kind="decimal",
            )
            section = "compliance"
            continue
        if _SEC_D_RE.match(ln):
            # D's question wraps to a second line; emit a placeholder row
            # carrying the answer once the continuation arrives.
            section = "compliance"
            pending_d_question = True
            continue
        if pending_d_question:
            m = _D_ANSWER_RE.match(ln)
            if m:
                answer = m.group(1).strip().rstrip("?.")
                yield _emit(
                    base,
                    section="compliance",
                    item_code="D",
                    item_label=(
                        "Did the district maintain the statutory ratio of "
                        "46 Basic Education CIS per 1000 Students in K-12?"
                    ),
                    value_text=answer,
                    kind="text",
                )
                pending_d_question = False
                continue
            # If the next line isn't the continuation, drop the pending
            # state -- the parser will resync at the next `1.` item.
            pending_d_question = False

        # Per-section item lines.
        if section == "enrollment":
            for code, pat, label, kind in _SECTION_A_ITEMS:
                m = pat.match(ln)
                if m:
                    value_text = (m.group(1) or "").strip()
                    # A.1's value text can be a two-token month (e.g.
                    # "October 2015"); the trailing-token regex captures
                    # only "2015". Pull the full month-name suffix off
                    # the printed line instead.
                    if code == "A.1":
                        value_text = _extract_a1_month(ln)
                    yield _emit(base, "enrollment", code, label, value_text, kind)
                    break
            continue

        if section == "cis":
            for code, pat, label, kind in _SECTION_B_ITEMS:
                m = pat.match(ln)
                if m:
                    value_text = (m.group(1) or "").strip()
                    yield _emit(base, "cis", code, label, value_text, kind)
                    break
            continue

        if section == "compliance":
            for code, pat, label, kind in _SECTION_D_ITEMS:
                m = pat.match(ln)
                if m:
                    value_text = (m.group(1) or "").strip()
                    yield _emit(base, "compliance", code, label, value_text, kind)
                    break
            continue


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


_A1_MONTH_TAIL_RE = re.compile(
    r"Form\s+SPI\s+1160\s+(.+?)\s*$", re.IGNORECASE,
)


def _extract_a1_month(line: str) -> str:
    """Pull the trailing month-name from an A.1 line.

    `'1. October 2013 or month selected on Form SPI 1160 October 2013'`
    -> `'October 2013'`. Returns empty string when the printed value
    cell is blank.
    """
    m = _A1_MONTH_TAIL_RE.search(line)
    if not m:
        return ""
    tail = m.group(1).strip()
    # Guard against the form printing nothing after "Form SPI 1160" --
    # the regex would then capture leftover content from a continuation
    # line. Realistically the corpus always prints the month here.
    return tail


def _emit(base: dict, section: str, item_code: str, item_label: str,
          value_text: str, kind: str) -> dict:
    """Build one fact row.

    `kind == 'text'` items (A.1's month, D's Yes/No) keep their raw
    text in `value_text` and store NULL in `value`. `kind == 'decimal'`
    items parse the value text into a Decimal (NULL on blank or the
    `---` placeholder).
    """
    if kind == "decimal":
        value = _parse_value(value_text)
    else:
        value = None
    return {
        **base,
        "section": section,
        "item_code": item_code,
        "item_label": item_label,
        "value": value,
        "value_text": value_text,
    }


def _parse_value(value_text: str):
    """Parse a numeric value cell to Decimal, NULL for blank / `---`."""
    if not value_text:
        return None
    s = value_text.strip()
    if s in ("---", "--", "-", "$-"):
        return None
    has_percent = s.endswith("%")
    if has_percent:
        s = s[:-1]
    s = s.lstrip("$")
    s = collapse_numeric_paren_spaces(merge_split_leading_digit(s))
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return parse_decimal(s)


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
