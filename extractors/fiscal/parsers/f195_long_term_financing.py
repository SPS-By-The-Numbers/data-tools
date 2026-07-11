"""Parse the `<FUND> - LONG-TERM FINANCING - CONDITIONAL SALES CONTRACTS
AND NOTES` sub-report (GF14 / CP9 / TVF4) of OSPI Form F-195 Budget.

Layout per fund page:

  A. Assets Purchased by CONDITIONAL SALES CONTRACTS (RCW 28A.335.170)
     in prior years
       <label> <length_months> <balance_sept1> <prin_fy> <int_fy> <balance_aug31>
       ...
       A. TOTAL <balance_sept1> <prin_fy> <int_fy> <balance_aug31>

  B. Assets to be purchased by CONDITIONAL SALES CONTRACTS AND NOTES
     in new FY
       <label> <length_months> <contract_amount> <prin_fy> <int_fy> <ltf_9500>
       ...
       B. TOTAL <contract_amount> <prin_fy> <int_fy> <ltf_9500> 4/

  C. TOTAL for Both Sections (A+B) <prin_total> 3/ <int_total> 3/ <balance_total>

Detail rows on funds with no active contracts print `0 0 0 0 0` (5
zeros, no label). Section totals skip the length-months column (4
values instead of 5); Section C has just 3 values interspersed with
footnote markers (`3/`).

Parsing uses positional column-anchor extraction: 5-column layout with
anchors set from the first fund-page's per-instrument row (typically
the placeholder `0 0 0 0 0`, whose anchors match the actual detail-row
column positions).
"""

import logging
import re
from typing import Iterator, List, Optional

from ..filename import FiscalFilename
from .common import parse_decimal, normalize_pdf_text


logger = logging.getLogger(__name__)


_TITLE_TO_FUND = {
    "GENERAL FUND - LONG-TERM FINANCING - CONDITIONAL SALES CONTRACTS AND NOTES 1/":
        "general",
    "CAPITAL PROJECTS FUND - LONG-TERM FINANCING - CONDITIONAL SALES CONTRACTS AND NOTES 1/":
        "capital_projects",
    "TRANSPORTATION VEHICLE FUND - LONG-TERM FINANCING - CONDITIONAL SALES CONTRACTS AND NOTES 1/":
        "transportation_vehicle",
}


# Section-transition markers within a fund page. Section A's label is
# often positionally split -- the leading `A.` prints on the column-
# index row (top of section) while `Assets Purchased by CONDITIONAL...`
# prints on the next row. Both regex variants accept either form.
_SECTION_A_LABEL_RE = re.compile(
    r"^(?:A\.\s+)?Assets\s+Purchased\s+by\s+CONDITIONAL", re.IGNORECASE
)
_SECTION_B_LABEL_RE = re.compile(
    r"^(?:B\.\s+)?Assets\s+to\s+be\s+purchased\s+by", re.IGNORECASE
)
# Section total rows.
_A_TOTAL_RE = re.compile(r"^A\.\s+TOTAL\b", re.IGNORECASE)
_B_TOTAL_RE = re.compile(r"^B\.\s+TOTAL\b", re.IGNORECASE)
_C_TOTAL_RE = re.compile(r"^C\.\s+TOTAL\s+for\s+Both\s+Sections", re.IGNORECASE)

# Value token.
_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$")

# Rows to skip.
_COLUMN_MARKER_RE = re.compile(r"^\(\d\)(\s+\(\d\))+\s*$")
# Column-header banner tokens (roughly).
_HEADER_ROW_TOKENS = {
    "Length", "of", "Contract", "months", "(months)", "Outstanding",
    "Principal", "Interest", "Balance", "at", "Payments", "in",
    "Amount", "Prin.", "Pmts.", "Long-Term", "Financing", "Rev.",
    "Acct", "9500", "Purchase", "less", "Down", "Pmts", "FY",
    "Sept", "1,", "Aug", "31,", "SALES", "CONTRACTS", "AND", "NOTES",
    "in", "new", "prior", "years", "purchased", "Assets", "Purchased",
    "by", "CONDITIONAL", "to", "be",
}
_FOOTER_RE = re.compile(r"^Form\s+F-195\s+Page\s+\d", re.IGNORECASE)
_FOOTNOTE_RE = re.compile(r"^\d+/\s")

# Positional tolerances.
_COL_TOLERANCE = 12.0
_Y_TOLERANCE = 2.5


def _group_rows(words, y_tol=_Y_TOLERANCE):
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


def _closest_column(x1: float, anchors: List[float]) -> Optional[int]:
    best_idx = None
    best_d = _COL_TOLERANCE
    for i, a in enumerate(anchors):
        d = abs(x1 - a)
        if d <= best_d:
            best_idx = i
            best_d = d
    return best_idx


def _parse_value(vtext):
    if not vtext:
        return None
    return parse_decimal(vtext)


def _find_fund(text: str) -> Optional[str]:
    for title, fund in _TITLE_TO_FUND.items():
        if title in text:
            return fund
    return None


def parse_f195_long_term_financing_pdf(info: FiscalFilename) -> Iterator[dict]:
    """Yield LTF rows for one F-195 Budget PDF. Each PDF has up to 3
    LTF pages (one per fund: GF14/CP9/TVF4)."""
    import pdfplumber

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f195_long_term_financing",
    }

    rows_out: List[dict] = []

    with pdfplumber.open(info.path) as pdf:
        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            fund = _find_fund(text)
            if fund is None:
                continue
            rows_out.extend(_parse_page(page, base, fund))

    seen = {}
    for r in rows_out:
        seen[(r["fund"], r["section"], r["item_seq"])] = r
    for r in seen.values():
        yield r


def _parse_page(page, base, fund) -> List[dict]:
    """Parse one LTF page for a specific fund. Returns list of row dicts."""
    words = page.extract_words(use_text_flow=True)
    # Update district on first LTF page.
    if not base["district"]:
        banner = " ".join(w["text"] for w in words[:30])
        m = re.search(
            r"(.+?)\s+School\s+District\s+No\.?\s*\d+", banner
        )
        if m:
            base["district"] = re.sub(r"\s+", " ", m.group(1)).strip()

    grouped = _group_rows(words)
    out: List[dict] = []
    section = None                                     # 'existing_contracts', 'new_contracts', 'summary'
    section_seq = 0                                    # per-section detail counter
    column_anchors: Optional[List[float]] = None       # 5 col anchors (length + 4 values)

    for row in grouped:
        text_row = " ".join(w["text"] for w in row).strip()
        if not text_row or _FOOTER_RE.match(text_row):
            continue
        if _FOOTNOTE_RE.match(text_row):
            continue

        # Section-transition rows.
        if _SECTION_A_LABEL_RE.match(text_row):
            section = "existing_contracts"; section_seq = 0
            continue
        if _SECTION_B_LABEL_RE.match(text_row):
            section = "new_contracts"; section_seq = 0
            continue

        # TOTAL rows. Canonical labels avoid dragging in the value
        # text that appears on the same visual row.
        if _A_TOTAL_RE.match(text_row):
            row_data = _extract_total_row(row, "existing_contracts", base, fund,
                                          "A. TOTAL", column_anchors)
            if row_data:
                out.append(row_data)
            continue
        if _B_TOTAL_RE.match(text_row):
            row_data = _extract_total_row(row, "new_contracts", base, fund,
                                          "B. TOTAL", column_anchors)
            if row_data:
                out.append(row_data)
            continue
        if _C_TOTAL_RE.match(text_row):
            row_data = _extract_c_total_row(row, base, fund,
                                            "C. TOTAL for Both Sections (A+B)",
                                            column_anchors)
            if row_data:
                out.append(row_data)
            continue

        # Detail row within section A or B.
        if section not in ("existing_contracts", "new_contracts"):
            continue

        # Skip Section B header-wrap rows -- these have telltale
        # phrases from the multi-line column-header banner that leak
        # into the row loop (e.g. `AND NOTES in new FY (months) Purchase
        # less FY 2024-2025 Payments in Financing Rev.`, `Down Pmts 2/`,
        # etc.). A per-instrument detail row starts with an actual
        # contract-name label or is the placeholder `0 0 0 0 0`.
        upper_row = text_row.upper()
        if any(needle in upper_row for needle in (
            "AND NOTES", "SALES CONTRACTS", "DOWN PMTS", "COL.3",
            "OF RESOURCES", "COL.3-COL.4",
        )):
            continue

        # Value words = numeric tokens in the value-column region
        # (x0 > some threshold to exclude label prefixes and section-
        # marker letters).
        value_words = [w for w in row
                       if _VALUE_TOKEN_RE.match(w["text"])
                       and w["x0"] >= 250]
        if not value_words:
            continue

        # Establish column anchors from the first 5-value detail row.
        if column_anchors is None and len(value_words) == 5:
            column_anchors = [w["x1"] for w in value_words]
        if column_anchors is None:
            # Buffer -- next placeholder-zero row will set anchors.
            continue

        # Bin each value word into one of the 5 columns.
        binned: List[Optional[dict]] = [None] * 5
        for vw in value_words:
            idx = _closest_column(vw["x1"], column_anchors)
            if idx is not None and binned[idx] is None:
                binned[idx] = vw

        # If nothing binned to a column (row is header-wrap junk that
        # happens to contain digit tokens like `9500` from Rev. Acct
        # 9500), skip.
        if all(b is None for b in binned):
            continue

        # Extract label (everything left of the first value_word).
        first_value_x0 = min(w["x0"] for w in value_words)
        label_words = [w for w in row if w["x0"] < first_value_x0]
        item_label = re.sub(
            r"\s+", " ",
            " ".join(w["text"] for w in label_words).strip()
        )

        section_seq += 1
        out.append({
            **base,
            "fund": fund,
            "section": section,
            "item_seq": section_seq,
            "is_total": False,
            "item_label": item_label,
            "contract_length_months": _parse_value(binned[0]["text"]) if binned[0] else None,
            "amount_beginning":       _parse_value(binned[1]["text"]) if binned[1] else None,
            "principal_fy":           _parse_value(binned[2]["text"]) if binned[2] else None,
            "interest_fy":            _parse_value(binned[3]["text"]) if binned[3] else None,
            "amount_ending":          _parse_value(binned[4]["text"]) if binned[4] else None,
        })
    return out


def _extract_total_row(row, section, base, fund, label_text, column_anchors):
    """Section A/B TOTAL: 4 trailing value tokens (skip length col)."""
    value_words = [w for w in row
                   if _VALUE_TOKEN_RE.match(w["text"])
                   and w["x0"] >= 250]
    if not value_words:
        return None
    if column_anchors is None:
        return None
    # Bin against the 4 rightmost anchors (indices 1..4, skipping length).
    binned: List[Optional[dict]] = [None] * 5
    for vw in value_words:
        idx = _closest_column(vw["x1"], column_anchors)
        if idx is not None and idx >= 1 and binned[idx] is None:
            binned[idx] = vw
    return {
        **base,
        "fund": fund,
        "section": section,
        "item_seq": 0,
        "is_total": True,
        "item_label": label_text,
        "contract_length_months": None,
        "amount_beginning": _parse_value(binned[1]["text"]) if binned[1] else None,
        "principal_fy":     _parse_value(binned[2]["text"]) if binned[2] else None,
        "interest_fy":      _parse_value(binned[3]["text"]) if binned[3] else None,
        "amount_ending":    _parse_value(binned[4]["text"]) if binned[4] else None,
    }


def _extract_c_total_row(row, base, fund, label_text, column_anchors):
    """Section C combined total: 3 value tokens (principal, interest, balance).
    Interspersed with footnote markers `3/`.
    """
    value_words = [w for w in row
                   if _VALUE_TOKEN_RE.match(w["text"])
                   and w["x0"] >= 250]
    if not value_words or column_anchors is None:
        return None
    # Bin against columns 2 (principal), 3 (interest), 4 (balance).
    binned: List[Optional[dict]] = [None] * 5
    for vw in value_words:
        idx = _closest_column(vw["x1"], column_anchors)
        if idx is not None and idx >= 2 and binned[idx] is None:
            binned[idx] = vw
    return {
        **base,
        "fund": fund,
        "section": "summary",
        "item_seq": 0,
        "is_total": True,
        "item_label": label_text,
        "contract_length_months": None,
        "amount_beginning": None,
        "principal_fy":     _parse_value(binned[2]["text"]) if binned[2] else None,
        "interest_fy":      _parse_value(binned[3]["text"]) if binned[3] else None,
        "amount_ending":    _parse_value(binned[4]["text"]) if binned[4] else None,
    }


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
