"""Parse page 1 of an OSPI Form F-195 Budget Overview PDF.

Page 1 is a 5-fund summary:
  - SECTION A: BUDGET SUMMARY (~7 line items)
  - SECTION B: EXCESS LEVIES FOR <year> COLLECTION (~3 line items)

Each line item has 5 trailing numeric tokens, one per fund:
  General | ASB | Debt Service | Capital Projects | Transportation Vehicle

Labels frequently wrap across 2-3 source lines. The parser buffers
non-value lines and joins them with the value-bearing line's prefix to
reconstruct the full label. The remaining ~40 pages of the report (per-
fund detail) duplicate the F-195 Budget full document and are not parsed
here.
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


# Fund column order on the form. Stable across all years (verified
# 2013-14 through 2024-25 by hand).
_FUND_ORDER = ["general", "asb", "debt_service", "capital_projects", "transportation_vehicle"]

# Positional item codes per section. The form's item order is stable, so we
# use position-derived codes rather than slugifying labels -- label text
# wraps unpredictably across line breaks, which would otherwise produce
# inconsistent codes across years.
_SECTION_A_CODES = [
    "total_revenues_and_other_financing_sources",
    "total_appropriation_expenditures",
    "transfers_out_g_l_536",
    "other_financing_uses_g_l_535",
    "excess_of_revenues_over_expenditures",
    "beginning_total_fund_balance",
    "ending_total_fund_balance",
]
_SECTION_B_CODES = [
    "excess_levies_approved_by_voters",
    "rollback_mandated_by_board",
    "net_excess_levy_after_rollback",
]
_SECTION_CODES = {
    "a_budget_summary": _SECTION_A_CODES,
    "b_excess_levies":  _SECTION_B_CODES,
}

_SECTION_A_RE = re.compile(r"^SECTION\s+A:\s+BUDGET\s+SUMMARY\s*$", re.IGNORECASE)
_SECTION_B_RE = re.compile(r"^SECTION\s+B:\s+EXCESS\s+LEVIES", re.IGNORECASE)
_PAGE_END_RE = re.compile(r"^Form\s+F-195\s+Page\s+1\b", re.IGNORECASE)

# A 5-fund value token: a signed/unsigned numeric, or 'XXXX'/'XXXXX' for n/a.
_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$|^XXX+$")


def _trailing_five_values(tokens: List[str]):
    """Return (label_tokens, value_tokens) if the line ends with 5 fund values."""
    if len(tokens) < 6:
        return None
    last5 = tokens[-5:]
    if all(_VALUE_TOKEN_RE.match(t) for t in last5):
        return tokens[:-5], last5
    return None


# Strip the four-digit collection-year reference so the resulting slug is
# stable across school years: 'for 2025 collection' -> 'for collection'.
_COLLECTION_YEAR_RE = re.compile(r"\bfor\s+\d{4}\s+collection\b", re.IGNORECASE)


def _slugify(label: str) -> str:
    s = _COLLECTION_YEAR_RE.sub("for collection", label.lower())
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")
    return s


def parse_f195_overview_pdf(info: FiscalFilename) -> Iterator[dict]:
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
        "_source_table": "fiscal_f195_overview",
    }

    section: Optional[str] = None
    label_buf: List[str] = []
    position_in_section = 0
    last_emitted_rows: Optional[List[dict]] = None  # for appending post-value continuations

    def _flush_buf_to(rows):
        """Append any post-value label continuation onto the last emitted item.

        Mutates label_buf in place (clears it).
        """
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
        # District name from second line.
        if not base["district"] and "District" in ln and ln.endswith(
                "District No.001") or "District No." in ln:
            base["district"] = re.sub(r"\s+District No\.\d+.*$", "", ln).strip()

        if _PAGE_END_RE.match(ln):
            _flush_buf_to(last_emitted_rows)
            for r in (last_emitted_rows or []):
                yield r
            last_emitted_rows = None
            label_buf = []
            break

        if _SECTION_A_RE.match(ln):
            _flush_buf_to(last_emitted_rows)
            for r in (last_emitted_rows or []):
                yield r
            last_emitted_rows = None
            section = "a_budget_summary"
            label_buf = []
            position_in_section = 0
            continue
        if _SECTION_B_RE.match(ln):
            _flush_buf_to(last_emitted_rows)
            for r in (last_emitted_rows or []):
                yield r
            last_emitted_rows = None
            section = "b_excess_levies"
            label_buf = []
            position_in_section = 0
            continue
        if section is None:
            continue

        tokens = ln.split()
        match = _trailing_five_values(tokens)
        if match is None:
            # Non-value line: either pre-value label fragment or post-value
            # continuation. Skip banner / page-header / footnote lines.
            if not ln or ln.startswith("Form ") or ln.startswith("FY "):
                continue
            # Footnote markers like '1/ Rollback of levies...' aren't part
            # of any item label.
            if re.match(r"^\d/\s", ln):
                continue
            label_buf.append(ln.strip())
            continue

        # Value line -- flush any buffered post-continuation onto the previous
        # item, then emit the previous item's rows, then start this one.
        _flush_buf_to(last_emitted_rows)
        for r in (last_emitted_rows or []):
            yield r
        last_emitted_rows = None

        label_tokens, value_tokens = match
        label_prefix = " ".join(label_tokens).strip()
        # `label_buf` here is the PRE-value continuation (rare on F-195: just
        # the older 2013-14 case where the value line's leading label was
        # broken by a column wrap).
        full_label = (" ".join(label_buf + ([label_prefix] if label_prefix else []))).strip()
        full_label = re.sub(r"\s+", " ", full_label)
        full_label = re.sub(r"^\d/\s*", "", full_label)         # leading '1/' footnote
        full_label = re.sub(r"\s*\d/\s*$", "", full_label)      # trailing '1/' footnote
        label_buf = []

        codes = _SECTION_CODES.get(section, [])
        if position_in_section >= len(codes):
            logger.warning("%s: section %s overflowed at position %d (label=%r)",
                           info.path.name, section, position_in_section, full_label)
            continue
        item_code = codes[position_in_section]
        position_in_section += 1

        rows = []
        for fund, vtext in zip(_FUND_ORDER, value_tokens):
            value = None if vtext.startswith("XXX") else parse_decimal(vtext)
            rows.append({
                **base,
                "section": section,
                "item_code": item_code,
                "fund": fund,
                "item_label": full_label,
                "value": value,
                "value_text": vtext,
            })
        last_emitted_rows = rows

    # End-of-document flush.
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
