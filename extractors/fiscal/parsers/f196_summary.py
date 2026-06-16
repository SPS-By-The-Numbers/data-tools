"""Parse the REPORT F-196 SUMMARY table (page 2) from an F-196 Summary PDF.

Page 2 is a 7-column matrix:
  General | ASB | Debt Service | Capital Projects | Transportation Vehicle | Permanent | Total

With 7 line items (in fixed order):
  1. Total Revenues and Other Financing Sources
  2. Total Expenditures
  3. Other Financing Uses
  4. Excess of Revenues/Other Financing Sources Over/(Under) Expenditures
     and Other Financing Uses
  5. Beginning Total Fund Balance
  6. Prior Year(s) Corrections or Restatements / Accounting Changes and
     Error Corrections (label varies across years)
  7. Ending Total Fund Balance

Labels wrap across 2-3 source lines. Parser uses same pre/post buffer
pattern as F-195 Overview, with positional item codes for stable
cross-year joins.
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


_FUND_ORDER = [
    "general", "asb", "debt_service", "capital_projects",
    "transportation_vehicle", "permanent", "total",
]

_ITEM_CODES = [
    "total_revenues_and_other_financing_sources",
    "total_expenditures",
    "other_financing_uses",
    "excess_of_revenues_over_expenditures",
    "beginning_total_fund_balance",
    "corrections_or_restatements",
    "ending_total_fund_balance",
]

_HEADER_RE = re.compile(r"^REPORT\s+F-196\s+SUMMARY\b", re.IGNORECASE)
_END_RE = re.compile(r"^(Not\s+Locked|Page\s+\d+\s+of\s+\d+)\s*$", re.IGNORECASE)

_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$")


def _trailing_seven_values(tokens: List[str]):
    if len(tokens) < 8:
        return None
    last7 = tokens[-7:]
    if all(_VALUE_TOKEN_RE.match(t) for t in last7):
        return tokens[:-7], last7
    return None


def parse_f196_summary_pdf(info: FiscalFilename) -> Iterator[dict]:
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
        "_source_table": "fiscal_f196_summary",
    }

    in_summary = False
    label_buf: List[str] = []
    position = 0
    last_emitted_rows: Optional[List[dict]] = None

    def _flush_buf_to(rows):
        if not rows or not label_buf:
            label_buf.clear()
            return
        suffix = " ".join(label_buf).strip()
        label_buf.clear()
        if not suffix:
            return
        for r in rows:
            r["item_label"] = re.sub(r"\s+", " ", (r["item_label"] + " " + suffix).strip())

    for ln in lines:
        # District name from the first 'REPORT F196 <district name> No.<NNN>' line.
        if not base["district"]:
            m = re.match(r"^REPORT\s+F196\s+(.+?)\s+No\.\s*\d+\b", ln)
            if m:
                base["district"] = m.group(1).strip()

        if not in_summary:
            if _HEADER_RE.match(ln):
                in_summary = True
                position = 0
                label_buf.clear()
                last_emitted_rows = None
                # The header line itself might also carry the column names;
                # any value tokens that follow on its own line would be a parse
                # bug -- skip directly to the next line.
                continue
            continue

        # In the summary section.
        if _END_RE.match(ln) or position >= len(_ITEM_CODES):
            _flush_buf_to(last_emitted_rows)
            for r in (last_emitted_rows or []):
                yield r
            last_emitted_rows = None
            in_summary = False
            continue

        tokens = ln.split()
        match = _trailing_seven_values(tokens)
        if match is None:
            # Skip page-header noise (E.S.D., COUNTY:, etc.) and footnote
            # markers (none present in F-196 Summary, but guard regardless).
            if not ln or ln.startswith(("E.S.D.", "COUNTY:", "REPORT F196",
                                       "Transportation", "Debt Service Capital",
                                       "General Fund ASB", "RUN DATE", "RUN TIME")):
                continue
            if re.match(r"^\d/\s", ln):
                continue
            label_buf.append(ln.strip())
            continue

        _flush_buf_to(last_emitted_rows)
        for r in (last_emitted_rows or []):
            yield r
        last_emitted_rows = None

        label_tokens, value_tokens = match
        label_prefix = " ".join(label_tokens).strip()
        full_label = (" ".join(label_buf + ([label_prefix] if label_prefix else []))).strip()
        full_label = re.sub(r"\s+", " ", full_label)
        label_buf.clear()

        item_code = _ITEM_CODES[position]
        position += 1

        rows = []
        for fund, vtext in zip(_FUND_ORDER, value_tokens):
            value = parse_decimal(vtext)
            rows.append({
                **base,
                "item_code": item_code,
                "fund": fund,
                "item_label": full_label,
                "value": value,
                "value_text": vtext,
            })
        last_emitted_rows = rows

    _flush_buf_to(last_emitted_rows)
    for r in (last_emitted_rows or []):
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
