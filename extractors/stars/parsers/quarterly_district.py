"""Parser for STARS Quarterly District Detail (PDF + DOCX).

Each file covers one quarter (FALL/WINTER/SPRING) for one district. The
PDF lays each of the three summary sections (STUDENT DETAIL, ROUTE
SUMMARY, BUS SUMMARY) out as a header block plus a one-line data row
("Almira (22017) 107 0 0 107 0 0 1 0 0 1"). The DOCX renders the same
table with each cell on its own paragraph, so a "row" is the district
name line followed by N numeric-only lines.

For both layouts we:
  1. Find each section's header line.
  2. Bound it by the next section's header (or "ROUTE DETAIL" / EOF).
  3. Collect numeric tokens inside the bounds, in document order.
  4. Take the first N tokens (10 / 10 / 8) as the metric values.

The per-route ROUTE DETAIL section that follows BUS SUMMARY is not
extracted by this parser.
"""

import logging
import re
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from .common import parse_decimal, read_lines, tokenize_value_line
from ..filename import StarsFilename


logger = logging.getLogger(__name__)


# Ordered list of summary sections. Each tuple is:
#   (section_header_prefix, expected_metric_count, metric_codes_in_order)
_SECTIONS: List[Tuple[str, int, Tuple[str, ...]]] = [
    (
        "STUDENT DETAIL", 10,
        (
            "basic_students_on_buses",
            "basic_students_in_walk_areas",
            "basic_students_transit_buses",
            "basic_students_total",
            "special_students_special_ed",
            "special_students_bilingual",
            "special_students_gifted",
            "special_students_homeless",
            "special_students_early_ed",
            "special_students_total",
        ),
    ),
    (
        "ROUTE SUMMARY", 10,
        (
            "routes_basic",
            "routes_special",
            "routes_bilingual",
            "routes_gifted",
            "routes_homeless",
            "routes_early_ed",
            "routes_total",
            "route_summary_destinations",
            "route_summary_total_buses",
            "route_summary_average_distance",
        ),
    ),
    (
        "BUS SUMMARY", 8,
        (
            "buses_basic",
            "buses_special",
            "buses_bilingual",
            "buses_gifted",
            "buses_homeless",
            "buses_early_ed",
            "bus_summary_destinations",
            "bus_summary_total_buses",
        ),
    ),
]


# Section-boundary markers that should never be crossed when collecting
# values for a section. Includes the next-section headers (we look those
# up at runtime) plus the ROUTE DETAIL terminator and a few page-chrome
# patterns that contain stray digits (e.g. "Run: Feb 04, 2025 9:35 AM").
_ROUTE_DETAIL_RE = re.compile(r"^ROUTE DETAIL\b")
_PAGE_CHROME_RES = [
    re.compile(r"^Page\s+\d+\s+of\s+\d+"),       # "Page 1 of 2 ..."
    re.compile(r"^State of Washington"),
    re.compile(r"^Superintendent of Public Instruction"),
    re.compile(r"^School Year\s"),                # data row for next quarter
    re.compile(r"^(Fall|Winter|Spring)\s+District Detail Report", re.I),
    re.compile(r"^STF-\d+$"),
]


def _is_chrome(line: str) -> bool:
    return any(p.search(line) for p in _PAGE_CHROME_RES)


_QUARTER_RE = re.compile(r"\b(FALL|WINTER|SPRING)\b", re.IGNORECASE)


def _quarter_from_original_name(original_name: str) -> Optional[str]:
    """Pull FALL/WINTER/SPRING out of the scraper's original-name segment.

    Filename examples: "Almira FALL", "Almira WINTER", "Seattle Public
    Schools SPRING", "AlmiraWINTER" (no space, rare).
    """
    m = _QUARTER_RE.search(original_name.upper())
    return m.group(1) if m else None


def _find_section_starts(lines: List[str]) -> dict:
    """Map section header prefix -> first line index where it occurs."""
    out = {}
    for idx, ln in enumerate(lines):
        for header, _, _ in _SECTIONS:
            if header not in out and ln.startswith(header):
                out[header] = idx
    return out


def _gather_numerics(lines: List[str], start: int, end: int) -> List:
    """Collect parse_decimal-able tokens from lines[start:end] in order.

    Skips page chrome lines so stray dates / page numbers don't bleed
    into the value stream.
    """
    out = []
    for i in range(start, end):
        ln = lines[i]
        if _is_chrome(ln):
            continue
        for tok in tokenize_value_line(ln):
            v = parse_decimal(tok)
            if v is not None:
                out.append(v)
    return out


def parse_quarterly_district(info: StarsFilename) -> Iterator[dict]:
    """Yield stars_quarterly_district rows for one PDF or DOCX."""

    quarter = _quarter_from_original_name(info.original_name)
    if quarter is None:
        logger.warning(
            "%s: cannot infer quarter from original_name %r; skipping",
            info.path.name, info.original_name,
        )
        return

    lines = read_lines(info.path)
    section_starts = _find_section_starts(lines)

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd,
        "county": None,
        "district": info.district_name,
        "_source": info.path.name,
        "_source_table": "stars_quarterly_district",
        "quarter": quarter,
    }

    # Order matters: build the end-cap for each section by looking up the
    # next section's start (or ROUTE DETAIL, or EOF).
    next_headers = [hdr for hdr, _, _ in _SECTIONS]

    for idx, (header, expected_n, metric_codes) in enumerate(_SECTIONS):
        start = section_starts.get(header)
        if start is None:
            logger.warning("%s: section %r not found", info.path.name, header)
            continue

        end = len(lines)
        for later_header in next_headers[idx + 1:]:
            later_start = section_starts.get(later_header)
            if later_start is not None and later_start > start:
                end = min(end, later_start)
                break
        for j in range(start + 1, end):
            if _ROUTE_DETAIL_RE.match(lines[j]):
                end = j
                break

        values = _gather_numerics(lines, start + 1, end)
        if len(values) < expected_n:
            # Two known patterns produce a short value stream:
            # 1. The district reported zero activity for the quarter
            #    (small districts / ESDs / charters). Section header + column
            #    labels are rendered but no data row appears.
            # 2. Partial-data charter schools where the rightmost columns
            #    aren't populated (e.g. ROUTE SUMMARY missing the
            #    average_distance column when there are no routes).
            # In both cases keep the section's row coverage but mark missing
            # metrics as NULL so downstream consumers can distinguish from
            # genuine zeros.
            logger.info(
                "%s: section %r expected %d numerics, got %d -- padding with NULL",
                info.path.name, header, expected_n, len(values),
            )
            values = list(values) + [None] * (expected_n - len(values))

        for metric_code, val in zip(metric_codes, values[:expected_n]):
            yield {**base, "metric_code": metric_code, "value": val}
