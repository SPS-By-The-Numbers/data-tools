"""Parse the `REVENUE WORK SHEET--<FUND>--LOCAL EXCESS LEVIES AND
TIMBER EXCISE TAX` sub-report (GF13 / DS3 / CP5 / TVF3) of OSPI Form
F-195 Budget.

Layout per fund page (single page):

  PART I: LOCAL PROPERTY TAX COLLECTIONS
    Fall <yy>     <col1> <col2> <col3> <col4> <col5>
    Spring <yy+1> <col1> <col2> <col3> <col4> <col5>
    1100 TOTAL LOCAL TAXES: <total_amount_budgeted>

  PART II: TIMBER EXCISE TAX
    Fall <yy>     <col1> <col2> <col3> <col4> <col5>
    Spring <yy+1> <col1> <col2> <col3> <col4> <col5>
    1500 TIMBER EXCISE TAXES: <total_amount_budgeted>

Each part has 2 detail rows (Fall / Spring) + 1 TOTAL row. Col semantics
differ per part but the row shape is stable. Timber fall row's Amount
Budgeted (col 5) is consistently `XXXXX` (timber distributes in a
single spring payment).

Text-line parsing is sufficient: the Fall/Spring labels are
distinctive prefixes, and the TOTAL rows have a specific `NNNN TOTAL...`
prefix.
"""

import logging
import re
from typing import Iterator, List, Optional

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, parse_decimal, normalize_pdf_text,
)


logger = logging.getLogger(__name__)


_TITLE_TO_FUND = {
    "REVENUE WORK SHEET--GENERAL FUND--LOCAL EXCESS LEVIES AND TIMBER EXCISE TAX":
        "general",
    "REVENUE WORK SHEET--DEBT SERVICE FUND--LOCAL EXCESS LEVIES AND TIMBER EXCISE TAX":
        "debt_service",
    "REVENUE WORK SHEET--CAPITAL PROJECTS FUND--LOCAL EXCESS LEVIES AND TIMBER EXCISE TAX":
        "capital_projects",
    "REVENUE WORK SHEET--TRANSPORTATION VEHICLE FUND--LOCAL EXCESS LEVIES AND TIMBER EXCISE TAX":
        "transportation_vehicle",
}

# Part-transition markers.
_PART_I_RE = re.compile(
    r"^PART\s+I:\s+LOCAL\s+PROPERTY\s+TAX\s+COLLECTIONS", re.IGNORECASE
)
_PART_II_RE = re.compile(
    r"^PART\s+II:\s+TIMBER\s+EXCISE\s+TAX", re.IGNORECASE
)

# Detail row prefix.
_FALL_RE = re.compile(r"^Fall\s+\d{4}\b")
_SPRING_RE = re.compile(r"^Spring\s+\d{4}\b")

# Section-total rows.
_TOTAL_1100_RE = re.compile(r"^1100\s+TOTAL\s+LOCAL\s+TAXES:", re.IGNORECASE)
_TOTAL_1500_RE = re.compile(r"^1500\s+TIMBER\s+EXCISE\s+TAXES:", re.IGNORECASE)

# Value token: signed decimal / integer / XXXXX.
_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$|^XXX+$")

# Rows to skip.
_COLUMN_MARKER_RE = re.compile(r"^\(\d\)(\s+\(\d\))+\s*$")
_FOOTER_RE = re.compile(r"^Form\s+F-195\s+Page\s+\d", re.IGNORECASE)
_FOOTNOTE_RE = re.compile(r"^\d+/\s")


def _parse_value(vtext):
    if not vtext or vtext.startswith("XXX"):
        return None
    return parse_decimal(vtext)


def _last_n_values(tokens: List[str], n: int):
    if len(tokens) < n:
        return None
    last = tokens[-n:]
    if all(_VALUE_TOKEN_RE.match(t) for t in last):
        return last
    return None


def parse_f195_revenue_worksheet_pdf(info: FiscalFilename) -> Iterator[dict]:
    """Yield rows for one F-195 Budget PDF. Each PDF has up to 4 pages
    (GF13/DS3/CP5/TVF3) -- one per fund that has a revenue worksheet."""
    import pdfplumber

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f195_revenue_worksheet",
    }

    rows_out: List[dict] = []
    with pdfplumber.open(info.path) as pdf:
        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            fund = _detect_fund(text)
            if fund is None:
                continue
            rows_out.extend(_parse_page(text, base, fund))

    seen = {}
    for r in rows_out:
        seen[(r["fund"], r["part"], r["period"])] = r
    for r in seen.values():
        yield r


def _detect_fund(text: str) -> Optional[str]:
    for title, fund in _TITLE_TO_FUND.items():
        if title in text:
            return fund
    return None


def _parse_page(text: str, base: dict, fund: str) -> List[dict]:
    raw_lines = [ln for ln in (l.strip() for l in text.split("\n")) if ln]
    lines = [collapse_numeric_paren_spaces(ln) for ln in raw_lines]

    # District name (once).
    if not base["district"]:
        for k, ln in enumerate(lines[:6]):
            m = re.match(r"^(.*?) School District No\.?\s*\d+", ln)
            if m:
                base["district"] = m.group(1).strip()
                break

    out: List[dict] = []
    part: Optional[str] = None
    in_footnote = False

    for ln in lines:
        if _FOOTER_RE.match(ln):
            continue
        if _FOOTNOTE_RE.match(ln):
            in_footnote = True
            continue
        if in_footnote:
            continue
        if _COLUMN_MARKER_RE.match(ln):
            continue

        # Part transitions.
        if _PART_I_RE.match(ln):
            part = "local_property_tax"; continue
        if _PART_II_RE.match(ln):
            part = "timber_excise_tax"; continue

        # Section-total rows.
        if _TOTAL_1100_RE.match(ln):
            _emit_total(out, base, fund, "local_property_tax", ln,
                        "1100 TOTAL LOCAL TAXES")
            continue
        if _TOTAL_1500_RE.match(ln):
            _emit_total(out, base, fund, "timber_excise_tax", ln,
                        "1500 TIMBER EXCISE TAXES")
            continue

        # Detail rows.
        if part is None:
            continue
        if _FALL_RE.match(ln):
            _emit_detail(out, base, fund, part, "fall", ln)
            continue
        if _SPRING_RE.match(ln):
            _emit_detail(out, base, fund, part, "spring", ln)
            continue

    return out


def _emit_detail(out, base, fund, part, period, ln):
    """Emit a Fall / Spring detail row. Extract the trailing 5 value
    tokens; the period label is the leading `Fall YYYY` or `Spring YYYY`.
    """
    tokens = ln.split()
    # Period label is 2 tokens ("Fall YYYY" or "Spring YYYY").
    if len(tokens) < 7:
        return
    period_label = " ".join(tokens[:2])
    tail = _last_n_values(tokens, 5)
    if tail is None:
        return
    out.append({
        **base,
        "fund": fund,
        "part": part,
        "period": period,
        "period_label": period_label,
        "amount_1": _parse_value(tail[0]),
        "amount_2": _parse_value(tail[1]),
        "amount_3": _parse_value(tail[2]),
        "collection_pct": _parse_value(tail[3]),
        "amount_budgeted": _parse_value(tail[4]),
    })


def _emit_total(out, base, fund, part, ln, canonical_label):
    """Section-total row: `NNNN TOTAL ... : <amount>`."""
    tokens = ln.split()
    tail = _last_n_values(tokens, 1)
    if tail is None:
        return
    out.append({
        **base,
        "fund": fund,
        "part": part,
        "period": "total",
        "period_label": canonical_label,
        "amount_1": None,
        "amount_2": None,
        "amount_3": None,
        "collection_pct": None,
        "amount_budgeted": _parse_value(tail[0]),
    })


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
