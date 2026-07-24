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
            "basic_ride_equivalents_on_bus",
            "basic_rides_in_walk_zone",
            "basic_transit_passes_issued",
            "basic_program_total",
            "special_rides_special_ed",
            "special_rides_bilingual",
            "special_rides_gifted",
            "special_rides_homeless",
            "special_rides_early_ed",
            "special_program_total",
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
            "route_summary_avg_stop_to_dest_distance",
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


# ---------- per-route detail parsing -----------------------------------

# PDF ROUTE DETAIL lines look like:
#   "Basic Program (A) 0079-I 9018 214367 Kimball Elementary 8 8 1.19"
#   "0157-I 9039 214365 Sandpoint Elementary 11 11 1.90"
# DOCX puts each of the seven cells on its own paragraph, preceded by the
# program label as its own paragraph:
#   "Basic Program (A)"
#   "1"
#   "1"
#   "203249"
#   "Coulee City Elementary"
#   "1"
#   "1"
#   "19.15"
_PROGRAM_LABEL_RE = re.compile(
    r"^(Basic|Special Ed|Bilingual|Gifted|Homeless|Early Ed)"
    r"\s+Program\s*\(([ASBGHE])\)"
)

# Map program label -> canonical snake_case code (matches the summary
# metric_codes' program suffix, e.g. routes_basic / routes_special).
_PROGRAM_CANONICAL = {
    "Basic": "basic",
    "Special Ed": "special_ed",
    "Bilingual": "bilingual",
    "Gifted": "gifted",
    "Homeless": "homeless",
    "Early Ed": "early_ed",
}


def _parse_pdf_route_line(line: str) -> Tuple[Optional[str], Optional[dict]]:
    """Parse a single PDF ROUTE DETAIL line.

    Returns (program_or_None, route_dict_or_None). When the line begins
    with a program label, also returns the canonical program name (the
    program continues until another label is seen).
    """
    program = None
    m = _PROGRAM_LABEL_RE.match(line)
    if m:
        program = _PROGRAM_CANONICAL[m.group(1)]
        line = line[m.end():].lstrip()
    tokens = line.split()
    if len(tokens) < 7:
        return program, None
    avg = parse_decimal(tokens[-1])
    if avg is None:
        return program, None
    total = parse_decimal(tokens[-2])
    stop = parse_decimal(tokens[-3])
    dist_bus = parse_decimal(tokens[1])
    state_bus = parse_decimal(tokens[2])
    if any(v is None for v in (total, stop, dist_bus, state_bus)):
        return program, None
    return program, {
        "route_number": tokens[0],
        "district_bus_number": int(dist_bus),
        "state_bus_number": int(state_bus),
        "destination_name": " ".join(tokens[3:-3]),
        "stop_count": int(stop),
        "total_stops": int(total),
        "average_distance": avg,
    }


def _looks_like_pdf_route_chrome(line: str) -> bool:
    """Lines that show up between routes on a PDF page break or section header."""
    if _is_chrome(line):
        return True
    if line.startswith("ROUTE DETAIL"):
        return True
    if _ROUTE_DETAIL_RE.match(line):
        return True
    # Re-printed column headers (the header lines we saw in the PDF dump).
    if line.startswith("District District State"):
        return True
    if line.startswith("Destination Name"):
        return True
    if line.startswith("Route Number Bus Number"):
        return True
    # District banner ("ALMIRA", "SEATTLE"). Pure-uppercase short string.
    if line.isupper() and 2 <= len(line.split()) <= 5 and not any(c.isdigit() for c in line):
        return True
    # Single ALL-UPPER token like "ALMIRA"
    if line.isupper() and len(line.split()) == 1 and line.isalpha():
        return True
    return False


def _parse_routes_pdf(lines: List[str]) -> Iterator[dict]:
    """Yield route dicts (without base fields) from PDF lines.

    Walks every line, ignores chrome / column header / district banner
    reprints, picks up program labels, and emits a route dict per route
    line. The function operates on the *full* line list; it locates the
    first ROUTE DETAIL header itself.
    """
    started = False
    current_program: Optional[str] = None
    for line in lines:
        if not started:
            if line.startswith("ROUTE DETAIL"):
                started = True
            continue
        if _looks_like_pdf_route_chrome(line):
            continue
        program, route = _parse_pdf_route_line(line)
        if program is not None:
            current_program = program
        if route is not None:
            if current_program is None:
                logger.warning("route before program: %r", line)
                continue
            yield {**route, "program": current_program}


def _parse_routes_docx(path: Path) -> Iterator[dict]:
    """Yield route dicts from a DOCX, walking the underlying table rows.

    The OSPI Quarterly District Detail DOCX renders ROUTE DETAIL as an
    8-column table: col 0 holds the program label on the first row of
    each program group (empty on continuation rows), and cols 1-7 are
    route_number / district_bus_number / state_bus_number /
    destination_name / stop_count / total_stops / average_distance.

    Iterating `<w:tr>` directly instead of walking paragraphs is
    necessary because per-paragraph extraction filters out empty cells
    and breaks the 7-cell grouping for routes where some columns are
    blank (e.g. continuation rows in older Seattle reports).
    """
    import docx
    from docx.oxml.ns import qn
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    d = docx.Document(path)

    current_program: Optional[str] = None
    for tr in d.element.body.iter(f"{w}tr"):
        cells = list(tr.iter(f"{w}tc"))
        if len(cells) != 8:
            continue
        texts = []
        for tc in cells:
            text = "".join((t.text or "") for t in tc.iter(f"{w}t")).strip()
            texts.append(text)
        # Cell 0: program label (or empty continuation). If it matches a
        # known program, update current_program.
        m = _PROGRAM_LABEL_RE.match(texts[0]) if texts[0] else None
        if m:
            current_program = _PROGRAM_CANONICAL[m.group(1)]
        # Cells 1-7 are the route fields.
        route_number = texts[1]
        if not route_number:
            # Header or padding row.
            continue
        if current_program is None:
            logger.warning("docx route row before any program label: %r", texts)
            continue
        dist_bus = parse_decimal(texts[2])
        state_bus = parse_decimal(texts[3])
        stop = parse_decimal(texts[5])
        total = parse_decimal(texts[6])
        avg = parse_decimal(texts[7])
        if any(v is None for v in (dist_bus, state_bus, stop, total, avg)):
            logger.info("docx route row has unparsable numerics: %r", texts)
            continue
        yield {
            "route_number": route_number,
            "district_bus_number": int(dist_bus),
            "state_bus_number": int(state_bus),
            "destination_name": texts[4],
            "stop_count": int(stop),
            "total_stops": int(total),
            "average_distance": avg,
            "program": current_program,
        }


def parse_quarterly_district_routes(info: StarsFilename) -> Iterator[dict]:
    """Yield stars_quarterly_district_route rows for one PDF or DOCX."""

    quarter = _quarter_from_original_name(info.original_name)
    if quarter is None:
        logger.warning(
            "%s: cannot infer quarter from original_name %r; skipping",
            info.path.name, info.original_name,
        )
        return

    lines = read_lines(info.path)
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd,
        "county": None,
        "district": info.district_name,
        "quarter": quarter,
        "_source": info.path.name,
        "_source_table": "stars_quarterly_district_route",
    }

    ext = info.path.suffix.lower()
    if ext == ".pdf":
        routes = _parse_routes_pdf(lines)
    elif ext == ".docx":
        # DOCX routes need the underlying table structure (empty cells
        # preserved); the pre-extracted `lines` list dropped them.
        routes = _parse_routes_docx(info.path)
    else:
        raise ValueError(f"Unsupported extension {ext!r}")

    for route in routes:
        yield {**base, **route}
