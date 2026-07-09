"""Parse the Federal Restricted / Unrestricted Indirect Cost Rate
Schedule sub-reports on OSPI F-196 All Pages PDFs.

Two schedules per file (Restricted pp 72-73, Unrestricted pp 74-75),
each 2 pages. This parser captures only the RATE CALCULATION on
page 2 of each schedule -- a 14-line computation whose final line
(14) is the newly-calculated indirect rate.

The page-1 expenditures breakdown is NOT captured (structurally
similar to fiscal_f196_program_activity_object; defer to future
work if needed).

Parsing approach:

  - Locate the two schedules by banner regex.
  - On the second page of each schedule, find the 14 calculation
    lines. Each line starts with '<line-number>.' followed by the
    label text, then a decimal value at the end of the line.
  - Multi-line labels are joined via lookback.
  - value is parsed as decimal; for line-5 and line-14 rate lines,
    the value is 0.xxxx (a rate, not a dollar amount).
"""

import logging
import re
from typing import Iterator, List, Optional, Tuple

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

# Line-number pattern (e.g. '1.', '14.') at the start of a line.
_LINE_NUMBER_RE = re.compile(r"^\s*(\d{1,2})\.\s+(.*)$")

# Trailing value at end of a line.
_TRAILING_VALUE_RE = re.compile(r"(-?\d[\d,]*\.\d+)\s*$")

_PAGE_FRAME_RE = re.compile(
    r"^(REPORT\s+F196\b|E\.S\.D\.\s+\w+\s+Schedule\s+for|COUNTY:\s+\S+|"
    r"Fiscal\s+Year\s+\d|For\s+the\s+Year\s+Ended|Page\s+\d+\s+of\s+\d+\s*$|"
    r"With\s+Carry-Forward\s+Calculation|\*\*\*)",
    re.IGNORECASE
)

_MAX_LINE_NUMBER = 14


def parse_f196_indirect_rate_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_indirect_rate",
    }

    with pdfplumber.open(info.path) as pdf:
        # Locate the two schedules.
        restricted_pages: List[int] = []
        unrestricted_pages: List[int] = []
        for i, page in enumerate(pdf.pages):
            t = page.extract_text() or ""
            first_lines = " ".join(t.split("\n", 3)[:3])
            if _BANNER_RESTRICTED.search(first_lines):
                restricted_pages.append(i)
            elif _BANNER_UNRESTRICTED.search(first_lines):
                unrestricted_pages.append(i)

        if not restricted_pages and not unrestricted_pages:
            return

        # District from first found page.
        anchor_pg = (restricted_pages or unrestricted_pages)[0]
        first_words = pdf.pages[anchor_pg].extract_words(use_text_flow=True)
        d = _district_from_words(first_words)
        if d:
            base["district"] = d

        if restricted_pages:
            yield from _parse_schedule(pdf, restricted_pages, "restricted", base)
        if unrestricted_pages:
            yield from _parse_schedule(pdf, unrestricted_pages, "unrestricted", base)


def _district_from_words(words) -> Optional[str]:
    text = " ".join(w["text"] for w in words[:30])
    m = re.search(r"REPORT\s+F196\s+(.+?)\s+No\.\s*\d+", text, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _parse_schedule(pdf, page_indexes: List[int], rate_kind: str, base
                    ) -> Iterator[dict]:
    """Parse the calculation section of a schedule (page 2 of the 2-page
    sub-report).
    """
    # Collect text lines from all pages of this schedule.
    lines: List[str] = []
    for pg_idx in page_indexes:
        t = pdf.pages[pg_idx].extract_text() or ""
        for L in t.split("\n"):
            stripped = L.strip()
            if not stripped:
                continue
            if _PAGE_FRAME_RE.search(stripped):
                continue
            lines.append(stripped)

    # Find the calculation section start. The calculation is preceded by
    # '*** FIXED WITH CARRY-FORWARD ... RATE CALCULATION ***'. We stripped
    # that via _PAGE_FRAME_RE. Instead: any line matching _LINE_NUMBER_RE
    # with a numeric line number in 1-14 is a calc line.
    #
    # Iterate lines, accumulate label continuations.
    pending_number: Optional[str] = None
    pending_label_parts: List[str] = []
    pending_value_text: Optional[str] = None
    seen_numbers: set = set()

    def emit():
        nonlocal pending_number, pending_label_parts, pending_value_text
        if pending_number is None or pending_number in seen_numbers:
            pending_number = None
            pending_label_parts = []
            pending_value_text = None
            return None
        label = re.sub(r"\s+", " ",
                       " ".join(pending_label_parts).strip())
        row = {
            **base,
            "rate_kind": rate_kind,
            "line_number": pending_number,
            "line_label": label,
            "value": parse_decimal(pending_value_text) if pending_value_text else None,
        }
        seen_numbers.add(pending_number)
        pending_number = None
        pending_label_parts = []
        pending_value_text = None
        return row

    for line in lines:
        # Filter out non-calc lines: e.g. 'FY 21-22', 'FY 23-24' section
        # headers, table header rows.
        if re.match(r"^FY\s+\d{2}-\d{2}\s*$", line):
            continue
        # Skip the column-header lines from page 1 that leaked through
        # (the exp-breakdown table).
        if re.match(r"^(TOTAL|CAPITAL|DEBT|DISTORTING|\(ADDED|\(POOL\)|\(BASE\))",
                    line):
            continue
        if re.match(r"^(Sub-Total|Unallowable|Totals|Sub-Total|PROGRAM AND)",
                    line, re.IGNORECASE):
            continue

        m = _LINE_NUMBER_RE.match(line)
        if m:
            num_str, rest = m.group(1), m.group(2)
            try:
                num_int = int(num_str)
            except ValueError:
                num_int = -1
            if 1 <= num_int <= _MAX_LINE_NUMBER and num_str not in seen_numbers:
                # Emit previous.
                r = emit()
                if r:
                    yield r
                pending_number = num_str
                # Extract trailing value.
                tv_match = _TRAILING_VALUE_RE.search(rest)
                if tv_match:
                    pending_value_text = tv_match.group(1)
                    pending_label_parts = [rest[: tv_match.start()].rstrip()]
                else:
                    pending_label_parts = [rest]
                    pending_value_text = None
                continue

        # Continuation line for the current pending item.
        if pending_number is not None:
            # A line with only a numeric value is a value-line for the
            # pending item.
            if _TRAILING_VALUE_RE.fullmatch(line):
                pending_value_text = line
                continue
            # Otherwise it's a label continuation. Also check for trailing
            # value at end.
            tv_match = _TRAILING_VALUE_RE.search(line)
            if tv_match:
                pending_value_text = tv_match.group(1)
                pending_label_parts.append(line[: tv_match.start()].rstrip())
            else:
                pending_label_parts.append(line)

    r = emit()
    if r:
        yield r


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
