"""Parse the Balance Sheet - Governmental Funds sub-report of OSPI F-196
All Pages PDFs.

The sub-report spans 2 pages (small districts) or 3 pages (medium+
districts) starting at PDF page 3. Layout is a 7-column table:

    General | ASB | Debt Service | Capital Projects | Transportation Vehicle
        | Permanent | Total

decomposed into five (six in older vintages: no DEFERRED OUTFLOWS)
sections:

  1. ASSETS (multiple detail items + TOTAL ASSETS)
  2. DEFERRED OUTFLOWS OF RESOURCES (multiple + TOTAL; absent 2013-14)
  3. TOTAL ASSETS AND DEFERRED OUTFLOWS OF RESOURCES  (combined total)
  4. LIABILITIES (multiple + TOTAL LIABILITIES; heading may repeat on
     page continuation)
  5. DEFERRED INFLOWS OF RESOURCES (multiple + TOTAL)
  6. FUND BALANCE (multiple + TOTAL FUND BALANCE)
  7. TOTAL LIABILITIES, DEFERRED INFLOW OF RESOURCES, AND FUND BALANCE
     (combined total)

Parsing approach:

  - Locate Balance Sheet pages via a banner regex ("Balance Sheet ...
    Governmental Funds"). Both forms exist ("Balance Sheet - Governmental
    Funds" one-line, and "Balance Sheet" + "Governmental Funds" two-line).
  - Extract words with `use_text_flow=True` (mirrors Phase 2b/2c-i to
    avoid pdfplumber column-overlay artifacts).
  - Group into rows by y-tolerance.
  - Filter out page-framing rows (banner, county, date, column headers,
    'Page N of M' footer).
  - Column anchors: right-edge x1 of the first row that carries 7
    non-blank values (typically 'Cash and Cash Equivalents'). Anchors
    persist across all pages of this sub-report.
  - Section state machine: label-only rows matching section-name
    patterns transition the current section without emitting rows.
  - TOTAL rows: matched by leading 'TOTAL' + section keyword. The two
    combined-total rows ('TOTAL ASSETS AND DEFERRED OUTFLOWS...' and
    'TOTAL LIABILITIES, DEFERRED INFLOW...') are routed to
    section='summary'.
  - Detail rows: label + values. Each printed value binds to the column
    anchor whose x1 is closest (within tolerance). Missing values in
    a row leave that column NULL (older-vintage cell-blanking).
  - Multi-line item labels ('Investments/Cash With' + 'Trustee') are
    absorbed via a label-buffer suffix attached to the most-recently-
    emitted row's items.

Quirks handled:

  - 2013-14 has no DEFERRED OUTFLOWS section -- no rows emitted for it
    on those files.
  - Section headers wrap ('DEFERRED OUTFLOWS OF' + 'RESOURCES:'). The
    second-line 'RESOURCES:?' is consumed as a header continuation and
    doesn't leak into the next item's label.
  - TOTAL row labels wrap ('TOTAL DEFERRED OUTFLOWS OF' + 'RESOURCES').
    The trailing 'RESOURCES' label-only row is absorbed by the pending
    TOTAL row's label_buf.
  - Combined-total labels wrap across 3 lines ('TOTAL LIABILITIES,
    DEFERRED' + 'INFLOW OF RESOURCES, AND FUND' + 'BALANCE'). Absorbed
    the same way.
  - Section headers may re-print on continuation pages ('LIABILITIES:'
    at the bottom of page 3 AND at the top of page 4). Repeated headers
    that don't change the section state are no-ops.
  - Tribal compact schools print 'E.S.D. SPI' -- title regex uses \\w+.
"""

import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_FUND_ORDER = [
    "general", "asb", "debt_service", "capital_projects",
    "transportation_vehicle", "permanent", "total",
]

_BANNER_RE = re.compile(r"Balance\s+Sheet", re.IGNORECASE)
_GOVFUNDS_RE = re.compile(r"Governmental\s+Funds", re.IGNORECASE)

# Section-transition regexes. Case-insensitive; the form prints uppercase
# but 2023-24 uses mixed-case 'Assets' as a section label.
_SECTION_HEADERS = [
    ("assets",             re.compile(r"^ASSETS:?$", re.IGNORECASE)),
    ("deferred_outflows",  re.compile(r"^DEFERRED\s+OUTFLOWS\s+OF(?:\s+RESOURCES:?)?$", re.IGNORECASE)),
    ("liabilities",        re.compile(r"^LIABILITIES:?$", re.IGNORECASE)),
    ("deferred_inflows",   re.compile(r"^DEFERRED\s+INFLOWS\s+OF(?:\s+RESOURCES:?)?$", re.IGNORECASE)),
    ("fund_balance",       re.compile(r"^FUND\s+BALANCE:?$", re.IGNORECASE)),
]

# Second-line wrap of a DEFERRED ... OF section header. On its own row,
# 'RESOURCES' or 'RESOURCES:' is a section-header continuation.
_SECTION_HEADER_WRAP_RE = re.compile(r"^RESOURCES:?$", re.IGNORECASE)

# TOTAL rows. Ordering matters: more-specific patterns first so that the
# combined-total rows don't get caught by their per-section prefix.
_TOTAL_PATTERNS = [
    # Combined totals (routed to section='summary'). The trailing-comma
    # form ('TOTAL LIABILITIES,') matches early so that the values row --
    # which prints only the comma-clause label and pushes 'DEFERRED
    # INFLOW OF RESOURCES, AND FUND BALANCE' to the next 2-3 label-only
    # continuation rows -- is classified as 'summary' not 'liabilities'.
    (re.compile(r"^TOTAL\s+ASSETS\s+AND\s+DEFERRED\b", re.IGNORECASE),
     "summary", "total_assets_and_deferred_outflows_of_resources"),
    (re.compile(r"^TOTAL\s+LIABILITIES,", re.IGNORECASE),
     "summary", "total_liabilities_deferred_inflows_and_fund_balance"),
    # Per-section totals:
    (re.compile(r"^TOTAL\s+ASSETS\b", re.IGNORECASE),
     "assets", "total_assets"),
    (re.compile(r"^TOTAL\s+DEFERRED\s+OUTFLOWS\b", re.IGNORECASE),
     "deferred_outflows", "total_deferred_outflows_of_resources"),
    (re.compile(r"^TOTAL\s+LIABILITIES\b", re.IGNORECASE),
     "liabilities", "total_liabilities"),
    (re.compile(r"^TOTAL\s+DEFERRED\s+INFLOWS\b", re.IGNORECASE),
     "deferred_inflows", "total_deferred_inflows_of_resources"),
    (re.compile(r"^TOTAL\s+FUND\s+BALANCE\b", re.IGNORECASE),
     "fund_balance", "total_fund_balance"),
]

# Page-framing rows to skip (banner, county, form date, column headers,
# per-page footer).
_PAGE_FRAME_PATTERNS = [
    re.compile(r"^REPORT\s+F196\b", re.IGNORECASE),
    re.compile(r"^E\.S\.D\.\s+\w+\s+Balance\s+Sheet", re.IGNORECASE),
    re.compile(r"^COUNTY:\s+\d+\s+\w+", re.IGNORECASE),
    re.compile(r"^August\s+\d+,\s*\d{4}$"),
    re.compile(r"^Debt\s+Capital\s+Transportation$"),
    re.compile(r"^General\s+ASB\s+Service\s+Projects", re.IGNORECASE),
    re.compile(r"^Fund(\s+Fund)+(\s+Total)?$"),
    re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE),
]

# Numeric value patterns.
_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")
_SIGN_PLACEHOLDER_RE = re.compile(r"^-$")

# Tolerances (see f196_all_pages.py for the rationale).
_COL_TOLERANCE = 6.0
_Y_TOLERANCE = 2.0
_WRAP_FRAGMENT_MAX_Y_GAP = 14.0

# Maximum pages after the first Balance Sheet page to keep scanning.
_MAX_BS_PAGES = 4


# ---- public entrypoint -----------------------------------------------------


def parse_f196_balance_sheet_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_balance_sheet",
    }

    with pdfplumber.open(info.path) as pdf:
        bs_pages = _find_balance_sheet_pages(pdf)
        if not bs_pages:
            return

        # District name from first BS-page banner.
        first_words = pdf.pages[bs_pages[0]].extract_words(use_text_flow=True)
        d = _district_from_words(first_words)
        if d:
            base["district"] = d

        state = _ParseState()
        for pg_idx in bs_pages:
            words = pdf.pages[pg_idx].extract_words(use_text_flow=True)
            yield from _parse_page(words, base, state)

        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r


# ---- internal helpers ------------------------------------------------------


class _ParseState:
    """Cross-page parser state (persists across the 2-3 pages of the
    sub-report).

    column_anchors: right-edge x1 per fund column, set from the first
      row that carries 7 non-blank values.
    section: current section state ('assets' initially, transitions per
      SECTION_HEADERS matches).
    pending_rows: the 7 rows (one per fund) most-recently emitted, held
      so that a following label-only row can attach a label suffix.
    label_buf: label continuation tokens waiting to be attached.
    """
    def __init__(self):
        self.column_anchors: Optional[List[float]] = None
        self.section: str = "assets"
        self.pending_rows: Optional[List[dict]] = None
        self.pending_row_top: Optional[float] = None
        self.pending_wrap_meta: Optional[List[Optional[dict]]] = None
        self.label_buf: List[str] = []

    def flush_suffix_into_pending(self) -> None:
        if self.pending_rows and self.label_buf:
            suffix = " ".join(self.label_buf).strip()
            if suffix:
                for r in self.pending_rows:
                    joined = (r["item_label"] + " " + suffix).strip()
                    r["item_label"] = re.sub(r"\s+", " ", joined)
                    # Re-slug non-TOTAL rows so multi-line item labels
                    # ('Due From Other' + 'Governmental Units') get the
                    # full slug ('due_from_other_governmental_units').
                    # TOTAL rows keep their hardcoded item_code.
                    if not r["is_total"]:
                        r["item_code"] = _slugify(r["item_label"]) or "unknown"
        self.label_buf.clear()

    def emit_pending(self):
        rows = self.pending_rows or []
        self.pending_rows = None
        self.pending_row_top = None
        self.pending_wrap_meta = None
        return rows


def _find_balance_sheet_pages(pdf) -> List[int]:
    """Return the 0-indexed page numbers of the Balance Sheet sub-report."""
    out: List[int] = []
    for i, page in enumerate(pdf.pages):
        if i > 10:  # Balance Sheet is always at the front of the PDF.
            break
        text = page.extract_text() or ""
        if _BANNER_RE.search(text) and _GOVFUNDS_RE.search(text):
            out.append(i)
            if len(out) >= _MAX_BS_PAGES:
                break
        elif out:
            # Sub-report ended.
            break
    return out


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


def _is_page_frame(text: str) -> bool:
    return any(pat.search(text) for pat in _PAGE_FRAME_PATTERNS)


def _slugify(label: str) -> str:
    s = label.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _parse_page(words, base, state: _ParseState) -> Iterator[dict]:
    rows = _group_rows(words)

    for row in rows:
        row_top = min(w["top"] for w in row)
        text = " ".join(w["text"] for w in row).strip()
        if not text or _is_page_frame(text):
            continue

        # Section-header continuation ('RESOURCES:' or 'RESOURCES') --
        # discard as a no-op (already consumed by the previous section-
        # header match).
        if _SECTION_HEADER_WRAP_RE.match(text):
            continue

        # Section-header row.
        new_section = _match_section_header(text)
        if new_section is not None:
            # Flush any pending suffix onto the last emitted item.
            state.flush_suffix_into_pending()
            for r in state.emit_pending():
                yield r
            state.section = new_section
            continue

        # Classify tokens.
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

        # ---- Wrap-continuation absorption (value overflow) -----------------
        if _try_absorb_wrap(row, row_top, full_value_words, fragment_words,
                            label_text, state):
            continue

        # Pure label continuation. A row with NO full-value tokens is a
        # wrap of the previous item's label -- even if it contains a bare
        # '-' (which is a hyphen inside a label like 'Resources - Other',
        # not a sign-placeholder). Sign-placeholder wraps only occur on
        # rows that also carry other funds' values.
        if not full_value_words:
            if label_text:
                state.label_buf.append(label_text)
            continue

        # Establish column anchors from the first row with 7 full values.
        if state.column_anchors is None:
            if len(full_value_words) != len(_FUND_ORDER):
                # Defer -- typical first row is 'Cash and Cash Equivalents'
                # with 7 values. If we see fewer, buffer the label and skip.
                if label_text:
                    state.label_buf.append(label_text)
                continue
            state.column_anchors = [w["x1"] for w in full_value_words]

        # New item row: flush the previous pending row's suffix, then emit.
        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r

        # TOTAL row check -- routes item_code + section.
        total_match = _match_total_row(label_text)
        if total_match is not None:
            section_out, item_code = total_match
            is_total = True
        else:
            section_out = state.section
            item_code = _slugify(label_text) or "unknown"
            is_total = False

        new_rows: List[dict] = []
        wrap_meta: List[Optional[dict]] = [None] * len(_FUND_ORDER)
        for col_idx, anchor in enumerate(state.column_anchors):
            fund = _FUND_ORDER[col_idx]
            matched = _closest_value(full_value_words, anchor)
            if matched is None:
                sign = _closest_sign(sign_words, anchor)
                if sign is not None:
                    wrap_meta[col_idx] = {"sign": "-"}
                new_rows.append({
                    **base,
                    "section": section_out,
                    "item_code": item_code,
                    "fund": fund,
                    "is_total": is_total,
                    "item_label": label_text,
                    "value": None,
                    "value_text": "",
                })
            else:
                new_rows.append({
                    **base,
                    "section": section_out,
                    "item_code": item_code,
                    "fund": fund,
                    "is_total": is_total,
                    "item_label": label_text,
                    "value": parse_decimal(matched["text"]),
                    "value_text": matched["text"],
                })
        state.pending_rows = new_rows
        state.pending_row_top = row_top
        state.pending_wrap_meta = wrap_meta


def _match_section_header(text: str) -> Optional[str]:
    for name, pat in _SECTION_HEADERS:
        if pat.match(text):
            return name
    return None


def _match_total_row(label_text: str):
    for pat, section, code in _TOTAL_PATTERNS:
        if pat.match(label_text):
            return (section, code)
    return None


def _try_absorb_wrap(row, row_top, full_value_words, fragment_words,
                     label_text, state: _ParseState) -> bool:
    """Attempt to absorb this row as a value-wrap continuation of the
    pending row. Return True if absorbed (caller should skip further
    handling of the row).
    """
    if (
        state.pending_rows is None
        or state.pending_wrap_meta is None
        or state.column_anchors is None
        or state.pending_row_top is None
    ):
        return False
    if (row_top - state.pending_row_top) > _WRAP_FRAGMENT_MAX_Y_GAP:
        return False

    # Column anchors that still have wrap obligations.
    anchor_for_col = [
        state.column_anchors[i]
        if (state.pending_wrap_meta[i] is not None
            or _is_truncated_value(state.pending_rows[i]["value_text"]))
        else None
        for i in range(len(_FUND_ORDER))
    ]

    absorbed = False

    # sign-placeholder + full-body wrap: value on next line = sign + body.
    for vw in full_value_words:
        col = _closest_column_index(vw["x1"], anchor_for_col)
        if col is None:
            continue
        meta = state.pending_wrap_meta[col]
        if meta is None or "sign" not in meta:
            continue
        merged = meta["sign"] + vw["text"]
        state.pending_rows[col]["value_text"] = merged
        state.pending_rows[col]["value"] = parse_decimal(merged)
        state.pending_wrap_meta[col] = None
        anchor_for_col[col] = None
        absorbed = True

    # trailing-digit-fragment wrap: append fragment to parent value.
    for frag in fragment_words:
        col = _closest_column_index(frag["x1"], anchor_for_col)
        if col is None:
            continue
        existing = state.pending_rows[col]["value_text"]
        if not existing:
            continue
        merged = existing + frag["text"]
        state.pending_rows[col]["value_text"] = merged
        state.pending_rows[col]["value"] = parse_decimal(merged)
        state.pending_wrap_meta[col] = None
        anchor_for_col[col] = None
        absorbed = True

    if absorbed:
        # A wrap row often also carries label continuation ('Trustee',
        # 'RESOURCES', 'BALANCE', ...).
        if label_text:
            state.label_buf.append(label_text)
        return True
    return False


def _is_truncated_value(value_text: str) -> bool:
    if not value_text:
        return False
    dot = value_text.rfind(".")
    if dot < 0:
        return False
    return len(value_text) - dot - 1 != 2


def _closest_value(value_words, anchor):
    best = None
    best_d = _COL_TOLERANCE
    for w in value_words:
        d = abs(w["x1"] - anchor)
        if d <= best_d:
            best = w
            best_d = d
    return best


def _closest_sign(sign_words, anchor):
    best = None
    best_d = _COL_TOLERANCE
    for w in sign_words:
        d = abs(w["x1"] - anchor)
        if d <= best_d:
            best = w
            best_d = d
    return best


def _closest_column_index(x1: float, anchors) -> Optional[int]:
    best_idx = None
    best_d = _COL_TOLERANCE
    for i, a in enumerate(anchors):
        if a is None:
            continue
        d = abs(x1 - a)
        if d <= best_d:
            best_idx = i
            best_d = d
    return best_idx


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
