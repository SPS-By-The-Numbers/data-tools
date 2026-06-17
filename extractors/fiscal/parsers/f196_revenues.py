"""Parse the 'Report of Revenues and Other Financing Sources' sub-report
of OSPI F-196 All Pages PDFs.

This sub-report appears as a contiguous block of 7-9 pages within each
F-196 All Pages PDF (pp 23-29 in Seattle 2018-19, pp 23-31 in Issaquah
2024-25). It captures revenue actuals per OSPI 4-digit account code per
fund -- the per-line-item counterpart to F-196 SUMMARY's per-fund
totals, and the actuals counterpart to F-195's per-account budgeted
revenue items.

Layout per page:
  Page header (3 lines): REPORT F196 / E.S.D. NN Report of Revenues ... / COUNTY: ...
  Column header (3 lines): 'Debt Capital Transportation' / 'General Service Projects Vehicle' / 'Fund Fund Fund Fund'
  Section header repeated from prior page (e.g. 'FEDERAL, SPECIAL PURPOSE')
  Item rows: '<4-digit code> <label> <value>...'
  Section subtotal: '<section-anchor-code> TOTAL <SECTION> <value>...'
  Final page only: 'TOTAL REVENUES AND OTHER FINANCING SOURCES <value>...'
  Footer: 'Page N of M'

Funds: only 4 (General, Debt Service, Capital Projects, Transportation
Vehicle). ASB and Permanent are omitted; no cross-fund Total column.

Parser uses the same positional column-anchor extraction patterns as
`f196_all_pages.py` to handle:
  - Sparse rows. Most accounts are fund-restricted; rows print 1-4
    values rather than always 4. Binning by x1 against column anchors
    handles this directly; missing cells emit NULL.
  - Trailing-digit and sign-placeholder wraps. Same shapes as the
    SUMMARY page parser; uses the same wrap-merge logic.
  - Multi-line labels. E.g. '2298 School Food Services--Sales of Goods,
    Supplies, and / Services' wraps 'Services' to the next visual line.
    Pure-label rows accumulate as suffix on the most recent emitted item.
  - Section headers (UPPER-CASE, no values). Used to track the current
    section slug for emitted rows; the header itself is not emitted.

Column anchors are established from the first row that prints all 4
fund values (typically '1000 TOTAL LOCAL TAXES' on page 1). The anchor
geometry holds across all sub-report pages.
"""

import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_FUND_ORDER = [
    "general", "debt_service", "capital_projects", "transportation_vehicle",
]

# Title row regex -- distinguishes the Report of Revenues sub-report from
# the (similarly named) Statement of Revenues, Expenditures, and Changes
# in Fund Balance sub-report which has its own different layout.
# The ESD anchor is normally a 3-digit number (E.S.D. 121) but tribal
# compact schools sit under direct OSPI oversight and print 'E.S.D. SPI'
# instead -- \w+ captures both.
_SUBREPORT_TITLE_RE = re.compile(
    r"E\.S\.D\.\s*\w+\s+Report\s+of\s+Revenues\s+and\s+Other\s+Financing\s+Sources",
    re.IGNORECASE,
)

# Section headers as printed in the form. Map to canonical slugs.
# OSPI has a recurring typo: 'ENTITITES' (extra TI) in 'OTHER ENTITIES'.
_SECTION_HEADERS = {
    "LOCAL TAXES":                            "local_taxes",
    "LOCAL SUPPORT NONTAX":                   "local_support_nontax",
    "STATE, GENERAL PURPOSE":                 "state_general_purpose",
    "STATE, SPECIAL PURPOSE":                 "state_special_purpose",
    "FEDERAL, GENERAL PURPOSE":               "federal_general_purpose",
    "FEDERAL, SPECIAL PURPOSE":               "federal_special_purpose",
    "REVENUES FROM OTHER SCHOOL DISTRICTS":   "revenues_from_other_school_districts",
    "REVENUES FROM OTHER ENTITIES":           "revenues_from_other_entities",
    "REVENUES FROM OTHER ENTITITES":          "revenues_from_other_entities",  # OSPI typo
    "OTHER FINANCING SOURCES":                "other_financing_sources",
}

# Section anchor codes: '1000' is the subtotal for the 1xxx Local Taxes
# section, '2000' for 2xxx, etc.
_SECTION_ANCHOR_CODES = {
    "local_taxes":                          "1000",
    "local_support_nontax":                 "2000",
    "state_general_purpose":                "3000",
    "state_special_purpose":                "4000",
    "federal_general_purpose":              "5000",
    "federal_special_purpose":              "6000",
    "revenues_from_other_school_districts": "7000",
    "revenues_from_other_entities":         "8000",
    "other_financing_sources":              "9000",
}

# Grand total row text -- comes at the very end of the sub-report.
_GRAND_TOTAL_RE = re.compile(
    r"^TOTAL\s+REVENUES\s+AND\s+OTHER\s+FINANCING\s+SOURCES\b", re.IGNORECASE
)

# Item row: starts with a 4-digit account code, then a label, then values.
_ACCOUNT_CODE_RE = re.compile(r"^\d{4}$")

# A fully-formed F-196 value: must contain a decimal point. Bare integers
# (1-3 digit fragments) are wrap-fragments handled separately.
_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")
_SIGN_PLACEHOLDER_RE = re.compile(r"^-$")

_COL_TOLERANCE = 6.0
_Y_TOLERANCE = 2.0
_WRAP_FRAGMENT_MAX_Y_GAP = 14.0


def parse_f196_revenues_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_revenues",
    }

    with pdfplumber.open(info.path) as pdf:
        # First pass: find which pages belong to the Report of Revenues
        # sub-report. The title line on every page of this sub-report
        # matches `_SUBREPORT_TITLE_RE`.
        sub_pages: List[int] = []
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if _SUBREPORT_TITLE_RE.search(text):
                sub_pages.append(i)
            elif sub_pages:
                # Left the sub-report.
                break

        if not sub_pages:
            return

        # District name (from any sub-report page banner).
        first_words = pdf.pages[sub_pages[0]].extract_words()
        district = _district_from_words(first_words)
        if district:
            base["district"] = district

        # Two-pass over the sub-report pages:
        #   Pass 1: find column anchors from the first all-4-values row anywhere.
        column_anchors = _find_column_anchors(pdf, sub_pages)
        if column_anchors is None:
            logger.warning(
                "no 4-value anchor row found in Report of Revenues for %s; "
                "skipping",
                base["_source"],
            )
            return

        #   Pass 2: emit rows page by page, carrying state across pages.
        state = _ParserState()
        for pg_idx in sub_pages:
            words = pdf.pages[pg_idx].extract_words()
            yield from _parse_page(words, base, state, column_anchors)
        # Flush any final pending rows / label buffer.
        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r


# ---- internal helpers ------------------------------------------------------


class _ParserState:
    """Holds parser state carried across pages of the sub-report."""

    def __init__(self):
        self.current_section: Optional[str] = None
        self.label_buf: List[str] = []
        self.pending_rows: Optional[List[dict]] = None
        self.pending_wrap_meta: Optional[List[Optional[dict]]] = None
        self.pending_row_top: Optional[float] = None

    def flush_suffix_into_pending(self) -> None:
        if self.pending_rows and self.label_buf:
            suffix = " ".join(self.label_buf).strip()
            if suffix:
                for r in self.pending_rows:
                    joined = (r["item_label"] + " " + suffix).strip()
                    r["item_label"] = re.sub(r"\s+", " ", joined)
        self.label_buf.clear()

    def emit_pending(self):
        rows_out = self.pending_rows or []
        self.pending_rows = None
        self.pending_wrap_meta = None
        self.pending_row_top = None
        return rows_out


def _district_from_words(words) -> Optional[str]:
    text = " ".join(w["text"] for w in words[:30])
    m = re.search(r"REPORT\s+F196\s+(.+?)\s+No\.\s*\d+", text, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _group_rows(words, y_tol=_Y_TOLERANCE) -> List[List[dict]]:
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    rows: List[List[dict]] = []
    for w in sorted_words:
        placed = False
        for row in rows:
            if abs(row[0]["top"] - w["top"]) <= y_tol:
                row.append(w)
                placed = True
                break
        if not placed:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w["x0"])
    rows.sort(key=lambda row: min(w["top"] for w in row))
    return rows


def _find_column_anchors(pdf, sub_pages) -> Optional[List[float]]:
    """Scan sub-report pages until we find a row with exactly 4 full-value
    tokens; return their x1 positions as column anchors. Section subtotal
    rows ('1000 TOTAL LOCAL TAXES ...') are typically all-funds and
    provide a stable anchor on page 1.
    """
    for pg_idx in sub_pages:
        words = pdf.pages[pg_idx].extract_words()
        for row in _group_rows(words):
            full_values = [w for w in row if _FULL_VALUE_RE.match(w["text"])]
            if len(full_values) == len(_FUND_ORDER):
                return [w["x1"] for w in full_values]
    return None


def _is_page_header_row(text: str) -> bool:
    """Page-header noise rows that aren't data."""
    return bool(
        text.startswith("REPORT F196")
        or _SUBREPORT_TITLE_RE.search(text)
        or text.startswith("COUNTY:")
        or text.startswith("E.S.D.")
        # Column header lines (any combination of the 3 column-header lines):
        or re.match(r"^(Debt\s+Capital\s+Transportation|"
                    r"General\s+Service\s+Projects\s+Vehicle|"
                    r"Fund(\s+Fund){2,3})\s*$", text)
        or re.match(r"^Page\s+\d+\s+of\s+\d+\s*$", text)
        or text.startswith("For the Year Ended")
    )


def _parse_page(words, base, state: _ParserState,
                column_anchors: List[float]) -> Iterator[dict]:
    rows = _group_rows(words)

    for row in rows:
        row_top = min(w["top"] for w in row)
        text = " ".join(w["text"] for w in row).strip()

        if not text or _is_page_header_row(text):
            continue

        full_value_words = [w for w in row if _FULL_VALUE_RE.match(w["text"])]
        fragment_words = [w for w in row
                          if _WRAP_FRAGMENT_RE.match(w["text"])
                          and not _FULL_VALUE_RE.match(w["text"])]
        sign_words = [w for w in row if _SIGN_PLACEHOLDER_RE.match(w["text"])]
        label_words = [w for w in row
                       if not _FULL_VALUE_RE.match(w["text"])
                       and not _WRAP_FRAGMENT_RE.match(w["text"])
                       and not _SIGN_PLACEHOLDER_RE.match(w["text"])]
        label_text = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_words).strip())

        # ---- Section header (label-only, exact match against known set) ----
        if not full_value_words and not fragment_words and not sign_words:
            section_slug = _SECTION_HEADERS.get(label_text)
            if section_slug is not None:
                # Flush any prior pending rows + suffix; switch section.
                state.flush_suffix_into_pending()
                for r in state.emit_pending():
                    yield r
                state.current_section = section_slug
                continue
            # Pure-label row: either a wrapped-label continuation or noise.
            if label_text:
                state.label_buf.append(label_text)
            continue

        # ---- Wrap-continuation absorption (same as f196_all_pages.py) -----
        if (
            state.pending_rows is not None
            and state.pending_wrap_meta is not None
            and state.pending_row_top is not None
            and (row_top - state.pending_row_top) <= _WRAP_FRAGMENT_MAX_Y_GAP
        ):
            anchor_for_col = [
                (column_anchors[i]
                 if state.pending_wrap_meta[i] is not None
                    or _is_truncated_value(state.pending_rows[i]["value_text"])
                 else None)
                for i in range(len(_FUND_ORDER))
            ]
            absorbed_any = False
            for vw in full_value_words:
                idx = _closest_column_index(vw["x1"], anchor_for_col)
                if idx is None:
                    continue
                meta = state.pending_wrap_meta[idx]
                if meta is None or "sign" not in meta:
                    continue
                merged = meta["sign"] + vw["text"]
                state.pending_rows[idx]["value_text"] = merged
                state.pending_rows[idx]["value"] = parse_decimal(merged)
                state.pending_wrap_meta[idx] = None
                anchor_for_col[idx] = None
                absorbed_any = True
            for frag in fragment_words:
                idx = _closest_column_index(frag["x1"], anchor_for_col)
                if idx is None:
                    continue
                existing = state.pending_rows[idx]["value_text"]
                if not existing:
                    continue
                merged = existing + frag["text"]
                state.pending_rows[idx]["value_text"] = merged
                state.pending_rows[idx]["value"] = parse_decimal(merged)
                state.pending_wrap_meta[idx] = None
                anchor_for_col[idx] = None
                absorbed_any = True
            if absorbed_any:
                if label_text:
                    state.label_buf.append(label_text)
                continue

        # ---- Grand-total row ------------------------------------------------
        if _GRAND_TOTAL_RE.match(label_text):
            state.flush_suffix_into_pending()
            for r in state.emit_pending():
                yield r
            new_rows, wrap_meta = _build_value_rows(
                base,
                section="grand_total",
                revenue_account="GRAND_TOTAL",
                is_section_total=False,
                is_grand_total=True,
                item_label=label_text,
                full_value_words=full_value_words,
                sign_words=sign_words,
                column_anchors=column_anchors,
            )
            state.pending_rows = new_rows
            state.pending_wrap_meta = wrap_meta
            state.pending_row_top = row_top
            continue

        # ---- Regular item or section subtotal row ---------------------------
        # Item rows lead with a 4-digit account code. The first label word
        # should be a 4-digit code; otherwise treat as noise/suffix.
        if not label_words or not _ACCOUNT_CODE_RE.match(label_words[0]["text"]):
            if label_text:
                state.label_buf.append(label_text)
            continue

        account_code = label_words[0]["text"]
        item_label = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_words[1:]).strip())
        is_section_total = item_label.upper().startswith("TOTAL ")
        section_slug = state.current_section
        if section_slug is None:
            # Item appeared before any section header -- the form should
            # always print sections, so log and skip.
            logger.warning("item %s with no current section in %s",
                           account_code, base["_source"])
            continue

        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r

        new_rows, wrap_meta = _build_value_rows(
            base,
            section=section_slug,
            revenue_account=account_code,
            is_section_total=is_section_total,
            is_grand_total=False,
            item_label=item_label,
            full_value_words=full_value_words,
            sign_words=sign_words,
            column_anchors=column_anchors,
        )
        state.pending_rows = new_rows
        state.pending_wrap_meta = wrap_meta
        state.pending_row_top = row_top


def _build_value_rows(base, section, revenue_account, is_section_total,
                      is_grand_total, item_label, full_value_words,
                      sign_words, column_anchors):
    """Emit per-fund value rows for one item, plus wrap-meta tracking sign
    placeholders for wrap-continuation absorption on the next row.
    """
    rows: List[dict] = []
    wrap_meta: List[Optional[dict]] = [None] * len(_FUND_ORDER)
    for col_idx, anchor in enumerate(column_anchors):
        fund = _FUND_ORDER[col_idx]
        matched = _closest_value(full_value_words, anchor)
        if matched is None:
            sign = _closest_sign(sign_words, anchor)
            if sign is not None:
                wrap_meta[col_idx] = {"sign": "-"}
            rows.append({
                **base,
                "section": section,
                "revenue_account": revenue_account,
                "fund": fund,
                "is_section_total": is_section_total,
                "is_grand_total": is_grand_total,
                "item_label": item_label,
                "value": None,
                "value_text": "",
            })
        else:
            rows.append({
                **base,
                "section": section,
                "revenue_account": revenue_account,
                "fund": fund,
                "is_section_total": is_section_total,
                "is_grand_total": is_grand_total,
                "item_label": item_label,
                "value": parse_decimal(matched["text"]),
                "value_text": matched["text"],
            })
    return rows, wrap_meta


def _closest_value(value_words, anchor) -> Optional[dict]:
    best = None
    best_d = _COL_TOLERANCE
    for w in value_words:
        d = abs(w["x1"] - anchor)
        if d <= best_d:
            best = w
            best_d = d
    return best


def _closest_sign(sign_words, anchor) -> Optional[dict]:
    best = None
    best_d = _COL_TOLERANCE
    for w in sign_words:
        d = abs(w["x1"] - anchor)
        if d <= best_d:
            best = w
            best_d = d
    return best


def _closest_column_index(x1: float, anchor_x1s: List[Optional[float]]) -> Optional[int]:
    best_idx = None
    best_d = _COL_TOLERANCE
    for i, a in enumerate(anchor_x1s):
        if a is None:
            continue
        d = abs(x1 - a)
        if d <= best_d:
            best_idx = i
            best_d = d
    return best_idx


def _is_truncated_value(value_text: str) -> bool:
    if not value_text:
        return False
    dot = value_text.rfind(".")
    if dot < 0:
        return False
    return len(value_text) - dot - 1 != 2


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
