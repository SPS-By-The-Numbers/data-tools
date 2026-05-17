"""Parser for the COMPACT / CHARTER variant of Operations Allocation Detail.

Tribal compact schools and charter school districts use a different
1026A form (`Report 1026A (COMPACT)` or `(CHARTER)`). The parser
matches text patterns rather than a fixed-column table because
formatting varies across years (some years run numbers right up
against the label with no space; older years use plain hyphens
versus newer em-dashes; charter A.3 is split into a/b/c sub-items
while tribal compact A.3 is a single line).

Each successfully-detected COMPACT/CHARTER file yields exactly one
stars_operations_allocation_compact row.
"""

import logging
import re
from pathlib import Path
from typing import Iterator, Optional

from .common import parse_decimal, read_lines
from ..filename import StarsFilename


logger = logging.getLogger(__name__)


# Match a number with optional thousands commas and decimal portion.
_NUM = r"[\d,]+(?:\.\d+)?"


# Explicit type tags seen in cover-page text. Three observed forms:
#   "Report 1026A (COMPACT)"
#   "Report 1026A (CHARTER)"
#   "Report 1026A Charter Schools (9/2020)"
# Tribal-compact files revised after the initial publish drop the
# "(COMPACT)" suffix and use "Report 1026A Revised" instead, so the
# explicit tag may be missing. We classify by Section A presence
# (which is unique to compact/charter format) and then infer the
# tribal-vs-charter distinction from filename / body keywords.
_EXPLICIT_TYPE_RE = re.compile(
    r"Report\s+1026A\s+(?:\((COMPACT|CHARTER)\)|(Charter)\s+Schools)",
    re.IGNORECASE,
)

# "SECTION A - Calculation of 2016-17 per Student Allocation for North Kitsap"
# "SECTION A-Calculation of 2025-26 per Student Allocation for North Kitsap"
# "SECTION A - Calculation of 2016-17 per Student Allocation for SPOKANE Public Schools"
# "SECTION A—Calculation of 2017-18 per Student Allocation for Tacoma"
_SECTION_A_HEADER_RE = re.compile(
    r"SECTION\s+A\s*[-–—]?\s*Calculation of\s+"
    r"(?P<year>\d{4}[-]\d{2,4})\s+per Student Allocation for\s+"
    r"(?P<host>.+?)\s+A\.\s*1",
    re.IGNORECASE | re.DOTALL,
)


def _classify_type(raw_flat: str, filename: str) -> Optional[str]:
    """Determine 'COMPACT' or 'CHARTER' for a compact/charter file.

    Try the explicit cover-page tag first; fall back to keyword matching
    in the filename and body for revisions/older formats that don't tag.
    """
    m = _EXPLICIT_TYPE_RE.search(raw_flat)
    if m:
        if m.group(1):
            return m.group(1).upper()
        if m.group(2):
            return "CHARTER"
    fn = filename.lower()
    if "tribal" in fn or "compact" in fn:
        return "COMPACT"
    if "charter" in fn:
        return "CHARTER"
    # Body fallback: 'Compact School' / 'Charter' anywhere.
    body = raw_flat.lower()
    if "compact school" in body or "tribal" in body:
        return "COMPACT"
    if "charter" in body:
        return "CHARTER"
    return None


# Per-field patterns.
#
# For $-amount fields, anchor the captured number on a literal `$`
# (with `.*?` between label and `$`). The host-district reference
# years embedded in lines like "From Ferndale 2016-17 1191TRNF" sit
# between the label and the actual value and would otherwise be
# captured as the number.
#
# For non-$ count fields (A.1, B.1-B.4), strip parenthesized formula
# text from the input first (`_PARENS_RE` below) so expressions like
# "((B.1 * 3/8) + ...)" don't pollute the numeric scan.

_A1_RE = re.compile(
    r"A\.\s*1\.?[^\n]*?Total\s+Eligible\s+Riders\s*[: ]*\s*(" + _NUM + r")",
    re.IGNORECASE,
)
_A2_RE = re.compile(
    r"A\.\s*2\.?.*?Operations?\s+Allocation.*?\$\s*(" + _NUM + r")",
    re.IGNORECASE,
)
# For A.3, prefer the "Total ... Depreciation" form (charters split A.3
# into a/b/c sub-items where c is the total). Fall back to plain
# "Depreciation" (tribal compacts have a single A.3 line).
_A3_TOTAL_RE = re.compile(
    r"[abc]\.\s*Total\s+\w+(?:\s+\d{4}[-]\d{2,4})?\s+Depreciation"
    r".*?\$\s*(" + _NUM + r")",
    re.IGNORECASE,
)
_A3_PLAIN_RE = re.compile(
    r"A\.\s*3\.?.*?Depreciation.*?\$\s*(" + _NUM + r")",
    re.IGNORECASE,
)
_A4_RE = re.compile(
    r"A\.\s*4\.?.*?Total\s+Transportation\s+Funding.*?\$\s*(" + _NUM + r")",
    re.IGNORECASE,
)
_A5_RE = re.compile(
    r"A\.\s*5\.?.*?per\s+(?:Rider|Eligible\s+Rider)\s+Allocation"
    r"[^\n$]*?\$?\s*(" + _NUM + r")",
    re.IGNORECASE,
)
# Fallback A.5 pattern that omits the trailing word "Allocation" (some
# 2025-26 reports drop it).
_A5_FALLBACK_RE = re.compile(
    r"A\.\s*5\.?.*?per\s+(?:Rider|Eligible\s+Rider)"
    r"[^\n$]*?\$?\s*(" + _NUM + r")",
    re.IGNORECASE,
)

_B1_RE = re.compile(
    r"B\.\s*1\.?\s+Spring\s+\d{4}[^\d]*?(" + _NUM + r")",
    re.IGNORECASE,
)
_B2_RE = re.compile(
    r"B\.\s*2\.?\s+Fall\s+\d{4}[^\d]*?(" + _NUM + r")",
    re.IGNORECASE,
)
_B3_RE = re.compile(
    r"B\.\s*3\.?\s+Winter\s+\d{4}[^\d]*?(" + _NUM + r")",
    re.IGNORECASE,
)
_B4_RE = re.compile(
    r"B\.\s*4\.?[^\n]*?Prorated\s+Riders[^\d]*(" + _NUM + r")",
    re.IGNORECASE,
)

# Section C final allocation: "SECTION C ... $XXX,XXX.XX". Both formats
# emit the dollar amount somewhere in the C block.
_SECTION_C_RE = re.compile(
    r"SECTION\s+C[^$]*\$\s*(" + _NUM + r")",
    re.IGNORECASE,
)

# Matches `(...)` (no nested parens). Apply twice to handle one level of nesting.
_PARENS_RE = re.compile(r"\([^()]*\)")


def _flatten(lines):
    """Join all lines into a single space-separated string for cross-line regex."""
    return re.sub(r"\s+", " ", " ".join(lines))


def _strip_parens(text: str) -> str:
    """Remove parenthesized expressions, including one level of nesting.

    Formula annotations like "((B.1 * 3/8) + (B.2 * 2/8) + (B.3 * 3/8))"
    and parenthetical descriptions like "(A.4 divided by A.1)" leak
    digits into the numeric search. Stripping them up front simplifies
    the patterns above.
    """
    prev = None
    while prev != text:
        prev = text
        text = _PARENS_RE.sub(" ", text)
    return text


def _cover_name(lines) -> Optional[str]:
    """Pull the school/compact name from the cover page.

    The cover always has the all-caps or title-case name on its own line
    a few lines down, just before the "SECTION A" header. Heuristic: the
    last non-chrome line before the first SECTION A line.
    """
    for i, ln in enumerate(lines):
        if ln.startswith("SECTION A") or ln.startswith("SECTION A "):
            for j in range(i - 1, -1, -1):
                cand = lines[j].strip()
                if not cand:
                    continue
                if cand.startswith("Report ") or cand.startswith("School Year"):
                    continue
                if cand.startswith("State of Washington"):
                    continue
                if cand.startswith("Superintendent of Public Instruction"):
                    continue
                if "Transportation Operations Allocation" in cand:
                    continue
                return cand
            return None
    return None


def _to_int_or_none(s):
    d = parse_decimal(s)
    return int(d) if d is not None else None


def parse_operations_allocation_compact(info: StarsFilename) -> Iterator[dict]:
    """Yield one row for a COMPACT / CHARTER 1026A file."""
    lines = read_lines(info.path)
    raw_flat = _flatten(lines)

    # Classify based on whether this looks like a compact/charter file at
    # all. The Section A header pattern is unique to the compact/charter
    # 1026A variants -- the standard form doesn't use it. We then read
    # COMPACT vs CHARTER from the explicit tag or fall back to filename
    # and body keywords (older revisions don't always carry the tag).
    if not _SECTION_A_HEADER_RE.search(raw_flat):
        return
    report_type = _classify_type(raw_flat, info.path.name)
    if report_type is None:
        logger.warning(
            "%s: compact/charter Section A detected but type indeterminate",
            info.path.name,
        )
        report_type = "COMPACT"

    flat = _strip_parens(raw_flat)

    sec_a = _SECTION_A_HEADER_RE.search(flat)
    host_district = sec_a.group("host").strip() if sec_a else None
    host_data_year = sec_a.group("year") if sec_a else None

    def _first(pat):
        m = pat.search(flat)
        return parse_decimal(m.group(1)) if m else None

    host_total_eligible = _first(_A1_RE)
    host_ops_alloc = _first(_A2_RE)
    # Prefer "Total ... Depreciation" (charters); else plain (tribal).
    a3_total = _A3_TOTAL_RE.search(flat)
    if a3_total:
        host_depreciation = parse_decimal(a3_total.group(1))
    else:
        host_depreciation = _first(_A3_PLAIN_RE)
    host_total_funding = _first(_A4_RE)
    host_per_rider = _first(_A5_RE) or _first(_A5_FALLBACK_RE)

    spring = _first(_B1_RE)
    fall = _first(_B2_RE)
    winter = _first(_B3_RE)
    prorated = _first(_B4_RE)

    final_alloc_m = _SECTION_C_RE.search(flat)
    final_alloc = parse_decimal(final_alloc_m.group(1)) if final_alloc_m else None

    yield {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd,
        "county": None,
        "district": info.district_name,
        "report_type": report_type,
        "school_name": _cover_name(lines),
        "host_district": host_district,
        "host_data_year": host_data_year,
        "host_total_eligible_riders": host_total_eligible,
        "host_operations_allocation": host_ops_alloc,
        "host_depreciation": host_depreciation,
        "host_total_transportation_funding": host_total_funding,
        "host_per_rider_allocation": host_per_rider,
        "spring_riders": _to_int_or_none(spring) if spring is not None else None,
        "fall_riders": _to_int_or_none(fall) if fall is not None else None,
        "winter_riders": _to_int_or_none(winter) if winter is not None else None,
        "prorated_riders": prorated,
        "final_allocation": final_alloc,
        "_source": info.path.name,
        "_source_table": "stars_operations_allocation_compact",
    }
