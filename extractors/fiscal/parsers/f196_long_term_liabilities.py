"""Parse the Schedule of Long-Term Liabilities sub-report of OSPI F-196
All Pages PDFs.

Two form vintages, both captured:

  - **Per-fund layout** (2013-14 through 2018-19, 4 pages): separate
    schedule per fund (General / Debt Service / Capital Projects /
    Transportation Vehicle). 2013-14 forms carry ': GENERAL FUND'
    etc. in the banner; 2015-16 through 2018-19 forms drop the fund
    label -- fund is attributed by page order (1st=general, 2nd=
    debt_service, 3rd=capital_projects, 4th=transportation_vehicle).
  - **Combined layout** (2019-20+, 1 page): all liabilities in a
    single schedule; rows carry `fund='combined'`.

Layout is a 5-value-column table:

    Beginning Outstanding | Amount Increased | Amount Decreased
        | Ending Outstanding | Amount Due Within One Year

grouped into sections:

  1. Voted Debt (Voted Bonds + LOCAL Program Proceeds Issued in Lieu
     of Bonds; only populated on Debt Service Fund page in per-fund
     vintages, or on combined page)
  2. Non-Voted Debt and Liabilities (Non-Voted Bonds, Capital Leases /
     Leases post-GASB-87, Contracts Payable, Compensated Absences,
     Long-Term Notes, ...)
  3. Other Liabilities (Non-Voted Notes Not Recorded as Debt)
  4. Net Pension Liabilities (added 2015-16 with GASB 68; TRS 1, TRS
     2/3, SERS 2/3, PERS 1). Rows have 4 values only -- 'Amount Due
     Within One Year' is blank on pension rows.
  5. TOTAL row ('Total Long-Term Liabilities'; per-fund page in old
     vintages, whole-file in combined vintages).

Parsing approach:

  - Locate pages via banner 'Schedule of Long-Term Liabilities'.
  - Determine variant + fund per page:
      * If banner has ': GENERAL FUND' etc: use that.
      * Otherwise: infer from position -- if 1 page total, fund=combined;
        if 4 pages, page order maps to (general, debt_service,
        capital_projects, transportation_vehicle).
  - Extract words via `extract_words(use_text_flow=True)`.
  - Group into rows by y-tolerance.
  - Filter page-frame rows.
  - Section state machine on section-header rows.
  - Column anchors: right-edge x1 of the first row with 5 full values
    (typically 'Voted Bonds' or 'Capital Leases').
  - Value rows: bin values by right-edge x1 to column anchors. Missing
    values (e.g. 4-value pension rows) emit NULL for the corresponding
    field.
  - Multi-line labels: 2015-16+ forms have single-line labels for most
    items. If a wrap occurs (rare), absorb into a pending row's label.
  - Skip OPEB footnote at the bottom of newer vintages.
"""

import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


# Value column semantic names (5 columns).
_COLUMN_NAMES = [
    "beginning_outstanding",
    "amount_increased",
    "amount_decreased",
    "ending_outstanding",
    "amount_due_within_one_year",
]

_PER_FUND_ORDER = [
    "general", "debt_service", "capital_projects", "transportation_vehicle",
]

# Banner detection.
_BANNER_RE = re.compile(r"Schedule\s+of\s+Long-Term\s+Liabilities", re.IGNORECASE)
_BANNER_FUND_LABEL_RE = re.compile(
    r"Schedule\s+of\s+Long-Term\s+Liabilities:\s*"
    r"(GENERAL|DEBT\s+SERVICE|CAPITAL\s+PROJECTS|TRANSPORTATION\s+VEHICLE)\s+FUND",
    re.IGNORECASE,
)
_BANNER_FUND_MAP = {
    "GENERAL": "general",
    "DEBT SERVICE": "debt_service",
    "CAPITAL PROJECTS": "capital_projects",
    "TRANSPORTATION VEHICLE": "transportation_vehicle",
}

# Section-header rows. Order in _SECTION_HEADERS is not important -- the
# match is by regex.
_SECTION_HEADERS = [
    ("voted_debt",                     re.compile(r"^Voted\s+Debt$", re.IGNORECASE)),
    ("non_voted_debt_and_liabilities", re.compile(r"^Non-Voted\s+Debt(\s+and\s+Liabilities)?$", re.IGNORECASE)),
    ("other_liabilities",              re.compile(r"^Other\s+Liabilities$", re.IGNORECASE)),
    ("net_pension_liabilities",        re.compile(r"^Net\s+Pension\s+Liabilities:$", re.IGNORECASE)),
]

# TOTAL row. Emits `is_total=True` and item_code='total_long_term_liabilities'.
_TOTAL_RE = re.compile(r"^Total\s+Long[- ]Term\s+Liabilities$", re.IGNORECASE)

# Page-frame rows to skip.
_PAGE_FRAME_PATTERNS = [
    re.compile(r"^REPORT\s+F196\b", re.IGNORECASE),
    re.compile(r"^E\.S\.D\.\s+\w+\s+Schedule\s+of\s+Long-Term", re.IGNORECASE),
    re.compile(r"^COUNTY:\s+\d+\s+\w+", re.IGNORECASE),
    re.compile(r"^For\s+the\s+Year\s+Ended", re.IGNORECASE),
    re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE),
    # OPEB footnote (present in newer vintages).
    re.compile(r"^Other\s+postemployment\s+benefits", re.IGNORECASE),
    # Column-header rows (4 physical lines).
    re.compile(r"^Beginning$", re.IGNORECASE),
    re.compile(r"^Outstanding\s+Debt\s+Amount\s+Ending$", re.IGNORECASE),
    re.compile(r"^September\s+\d+,?\s+Amount", re.IGNORECASE),
    re.compile(r"^Description\s+\d{4}\s+Increased\s+Decreased", re.IGNORECASE),
]

_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")

_COL_TOLERANCE = 8.0
_Y_TOLERANCE = 2.0
_WRAP_FRAGMENT_MAX_Y_GAP = 14.0

# Cap on how many contiguous pages of the schedule to scan (defensive
# against unexpected form growth).
_MAX_PAGES = 6


def parse_f196_long_term_liabilities_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_long_term_liabilities",
    }

    with pdfplumber.open(info.path) as pdf:
        lt_pages, page_texts = _find_lt_pages(pdf)
        if not lt_pages:
            return

        # Determine variant + fund per page.
        page_funds = _attribute_funds(page_texts)

        # District name from first page banner.
        first_words = pdf.pages[lt_pages[0]].extract_words(use_text_flow=True)
        d = _district_from_words(first_words)
        if d:
            base["district"] = d

        for pg_idx, fund in zip(lt_pages, page_funds):
            words = pdf.pages[pg_idx].extract_words(use_text_flow=True)
            yield from _parse_page(words, base, fund)


# ---- page discovery + fund attribution -------------------------------------


def _find_lt_pages(pdf):
    """Return (list of 0-indexed page numbers, list of raw text) for the
    contiguous run of Schedule of Long-Term Liabilities pages.
    """
    idxs: List[int] = []
    texts: List[str] = []
    for i, page in enumerate(pdf.pages):
        if i > 30:  # front-of-doc sub-report; hard cap
            break
        t = page.extract_text() or ""
        if _BANNER_RE.search(t):
            # The first line of the banner is unambiguous. Guard against
            # matches like "Long-Term Financing" appearing in unrelated
            # sub-reports.
            first_lines = t.split("\n", 4)[:4]
            joined = " ".join(first_lines)
            if _BANNER_RE.search(joined):
                idxs.append(i)
                texts.append(t)
                if len(idxs) >= _MAX_PAGES:
                    break
        elif idxs:
            # Sub-report ended.
            break
    return idxs, texts


def _attribute_funds(page_texts: List[str]) -> List[str]:
    """Determine fund per page.

    Priority 1: explicit fund label in banner (2013-14 vintages).
    Priority 2: 1 page -> 'combined'; 4 pages -> per-fund by order.
    Fallback: 'combined' for any page whose fund can't be determined.
    """
    labels: List[Optional[str]] = []
    for t in page_texts:
        m = _BANNER_FUND_LABEL_RE.search(t)
        if m:
            key = re.sub(r"\s+", " ", m.group(1).upper()).strip()
            labels.append(_BANNER_FUND_MAP.get(key))
        else:
            labels.append(None)

    if all(lbl is not None for lbl in labels):
        return labels  # type: ignore[return-value]

    # No explicit labels: infer from page count.
    if len(page_texts) == 1:
        return ["combined"]
    if len(page_texts) == 4:
        return list(_PER_FUND_ORDER)
    # Unexpected count -- attribute what we can from labels, fallback to
    # 'combined' for the rest.
    return [lbl if lbl else "combined" for lbl in labels]


# ---- parsing internals -----------------------------------------------------


def _district_from_words(words) -> Optional[str]:
    text = " ".join(w["text"] for w in words[:30])
    m = re.search(r"REPORT\s+F196\s+(.+?)\s+No\.\s*\d+", text, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


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


def _is_page_frame(text: str) -> bool:
    return any(pat.search(text) for pat in _PAGE_FRAME_PATTERNS)


def _match_section_header(text: str) -> Optional[str]:
    for name, pat in _SECTION_HEADERS:
        if pat.match(text):
            return name
    return None


def _slugify(label: str) -> str:
    s = label.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _parse_page(words, base, fund: str) -> Iterator[dict]:
    rows = _group_rows(words)

    section: Optional[str] = None
    column_anchors: Optional[List[float]] = None
    pending_row: Optional[dict] = None
    pending_row_top: Optional[float] = None
    label_buf: List[str] = []

    def _flush_suffix():
        nonlocal pending_row
        if pending_row and label_buf:
            suffix = " ".join(label_buf).strip()
            if suffix:
                joined = (pending_row["item_label"] + " " + suffix).strip()
                pending_row["item_label"] = re.sub(r"\s+", " ", joined)
                if not pending_row["is_total"]:
                    pending_row["item_code"] = _slugify(pending_row["item_label"]) or "unknown"
        label_buf.clear()

    def _emit():
        nonlocal pending_row, pending_row_top
        r = pending_row
        pending_row = None
        pending_row_top = None
        return r

    for row in rows:
        row_top = min(w["top"] for w in row)
        text = " ".join(w["text"] for w in row).strip()
        if not text or _is_page_frame(text):
            continue

        # Section-header rows.
        new_section = _match_section_header(text)
        if new_section is not None:
            _flush_suffix()
            r = _emit()
            if r:
                yield r
            section = new_section
            continue

        # Classify tokens.
        full_value_words = [w for w in row if _FULL_VALUE_RE.match(w["text"])]
        label_words = [w for w in row
                       if not _FULL_VALUE_RE.match(w["text"])
                       and not _WRAP_FRAGMENT_RE.match(w["text"])]
        label_text = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_words).strip())

        # Pure label continuation (no numeric values). Absorbed into the
        # pending row's label suffix.
        if not full_value_words:
            if label_text:
                label_buf.append(label_text)
            continue

        # Establish column anchors from the first row with 5 full values.
        if column_anchors is None:
            if len(full_value_words) != len(_COLUMN_NAMES):
                # Pension rows and blank-cell rows have < 5 values. Defer
                # anchor detection until a fully-populated row appears
                # (typically 'Voted Bonds' or 'Capital Leases' with 5x
                # '0.00').
                if label_text:
                    label_buf.append(label_text)
                continue
            column_anchors = [w["x1"] for w in full_value_words]

        # Flush the previous pending row before starting a new item.
        _flush_suffix()
        r = _emit()
        if r:
            yield r

        # TOTAL row?
        is_total = bool(_TOTAL_RE.match(label_text))
        if is_total:
            section_out = "summary"
            item_code = "total_long_term_liabilities"
        else:
            section_out = section or "unknown"
            item_code = _slugify(label_text) or "unknown"

        row_data = {
            **base,
            "fund": fund,
            "section": section_out,
            "item_code": item_code,
            "is_total": is_total,
            "item_label": label_text,
        }
        for col_idx, name in enumerate(_COLUMN_NAMES):
            matched = _closest_value(full_value_words, column_anchors[col_idx])
            row_data[name] = parse_decimal(matched["text"]) if matched else None
        pending_row = row_data
        pending_row_top = row_top

    _flush_suffix()
    r = _emit()
    if r:
        yield r


def _closest_value(value_words, anchor):
    best = None
    best_d = _COL_TOLERANCE
    for w in value_words:
        d = abs(w["x1"] - anchor)
        if d <= best_d:
            best = w
            best_d = d
    return best


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
