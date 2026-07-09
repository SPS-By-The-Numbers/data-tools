"""Parse the NCES Object Expenditure Summary sub-report of OSPI F-196
All Pages PDFs.

The sub-report is 4 pages (pp 34-37 typical). Layout: a single-column
value list per NCES 4-digit object code, grouped into 7 sections:

  1. Certificated Salaries (codes 2110-2170)
  2. Classified Salaries (codes 3110-3160)
  3. Employee Bene & P/R Taxes (codes 4212-4293)
  4. Supplies, Non-Capital (codes 5610-5650)
  5. Purchased Services (codes 7310-7960)
  6. Travel (code 8580 only)
  7. Capital Outlay (codes 9710-9960)

The sub-report closes with a single grand-total row:

    TOTAL ALL NCES OBJECT OF EXPENDITURE <amount>

**The sub-report did not exist before 2019-20** -- the parser produces
no rows for older files, which is expected and not an error.

Parsing approach:

  - Locate NCES pages via a banner regex on the first 3 lines. The
    certification page (page 1) does not list this sub-report, but
    the guard is used defensively.
  - Group words into rows by y-tolerance.
  - Skip page-frame rows (banner, county, date, page footer).
  - Section-header row: text matches a known section pattern (ends
    in ' Amount' and has no leading NCES code). Same header re-prints
    on continuation pages -- a no-op transition.
  - Item row: leading 4-digit NCES code + label + amount.
  - Grand-total row: 'TOTAL ALL NCES OBJECT OF EXPENDITURE' + amount.
  - Multi-line labels absorbed via label_buf suffix.
  - Trailing-digit value-wrap absorption for Seattle-scale 10-figure
    grand-total values.
"""

import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_BANNER_RE = re.compile(r"NCES\s+Object\s+Expenditure\s+Summary", re.IGNORECASE)

# Section headers -- canonical slug + regex on the printed header line.
_SECTION_HEADERS = [
    ("certificated_salaries",
     re.compile(r"^Certificated\s+Salaries\s+Amount$", re.IGNORECASE)),
    ("classified_salaries",
     re.compile(r"^Classified\s+Salaries\s+Amount$", re.IGNORECASE)),
    ("employee_benefits_payroll_taxes",
     re.compile(r"^Employee\s+Bene\s+&\s+P/R\s+Taxes\s+Amount$", re.IGNORECASE)),
    ("supplies_non_capital",
     re.compile(r"^Supplies,\s+Non-Capital\s+Amount$", re.IGNORECASE)),
    ("purchased_services",
     re.compile(r"^Purchased\s+Services\s+Amount$", re.IGNORECASE)),
    ("travel",
     re.compile(r"^Travel\s+Amount$", re.IGNORECASE)),
    ("capital_outlay",
     re.compile(r"^Capital\s+Outlay\s+Amount$", re.IGNORECASE)),
]

# Grand-total row (label is followed by a single amount on the same line).
_GRAND_TOTAL_RE = re.compile(
    r"^TOTAL\s+ALL\s+NCES\s+OBJECT\s+OF\s+EXPENDITURE\b", re.IGNORECASE)

# Page-frame rows to skip.
_PAGE_FRAME_PATTERNS = [
    re.compile(r"^REPORT\s+F196\b", re.IGNORECASE),
    re.compile(r"^E\.S\.D\.\s+\w+\s+NCES\s+Object", re.IGNORECASE),
    re.compile(r"^COUNTY:\s+\S+", re.IGNORECASE),
    re.compile(r"^For\s+the\s+Year\s+Ended", re.IGNORECASE),
    re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE),
]

_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")
# NCES codes are 4 digits.
_CODE_RE = re.compile(r"^\d{4}$")

_COL_TOLERANCE = 8.0
_Y_TOLERANCE = 2.0
_WRAP_FRAGMENT_MAX_Y_GAP = 14.0
_MAX_PAGES = 6  # defensive cap; sub-report is 4 pages


def parse_f196_nces_object_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_nces_object",
    }

    with pdfplumber.open(info.path) as pdf:
        nces_pages = _find_nces_pages(pdf)
        if not nces_pages:
            return

        first_words = pdf.pages[nces_pages[0]].extract_words(use_text_flow=True)
        d = _district_from_words(first_words)
        if d:
            base["district"] = d

        state = _ParseState()
        for pg_idx in nces_pages:
            words = pdf.pages[pg_idx].extract_words(use_text_flow=True)
            yield from _parse_page(words, base, state)

        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r


class _ParseState:
    def __init__(self):
        self.value_anchor: Optional[float] = None
        self.section: Optional[str] = None
        self.pending_row: Optional[dict] = None
        self.pending_row_top: Optional[float] = None
        self.label_buf: List[str] = []

    def flush_suffix_into_pending(self) -> None:
        if self.pending_row and self.label_buf:
            suffix = " ".join(self.label_buf).strip()
            if suffix:
                joined = (self.pending_row["item_label"] + " " + suffix).strip()
                self.pending_row["item_label"] = re.sub(r"\s+", " ", joined)
        self.label_buf.clear()

    def emit_pending(self):
        if self.pending_row is None:
            return []
        # Strip parser-local `_text` field before yielding.
        row = {k: v for k, v in self.pending_row.items() if k != "amount_text"}
        self.pending_row = None
        self.pending_row_top = None
        return [row]

    def try_absorb_wrap(self, row, row_top) -> bool:
        if (
            self.pending_row is None
            or self.pending_row_top is None
            or self.value_anchor is None
            or (row_top - self.pending_row_top) > _WRAP_FRAGMENT_MAX_Y_GAP
        ):
            return False
        existing = self.pending_row.get("amount_text", "")
        if not existing or not _is_truncated_value(existing):
            return False
        fragment_words = [w for w in row
                          if _WRAP_FRAGMENT_RE.match(w["text"])
                          and not _FULL_VALUE_RE.match(w["text"])]
        best = None
        best_d = _COL_TOLERANCE
        for frag in fragment_words:
            d = abs(frag["x1"] - self.value_anchor)
            if d <= best_d:
                best = frag
                best_d = d
        if best is None:
            return False
        merged = existing + best["text"]
        self.pending_row["amount_text"] = merged
        self.pending_row["amount"] = parse_decimal(merged)
        return True


def _find_nces_pages(pdf) -> List[int]:
    out: List[int] = []
    for i, page in enumerate(pdf.pages):
        if i > 100:
            break
        t = page.extract_text() or ""
        first_lines = t.split("\n", 3)[:3]
        header_text = " ".join(first_lines)
        if _BANNER_RE.search(header_text):
            out.append(i)
            if len(out) >= _MAX_PAGES:
                break
        elif out:
            break
    return out


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


def _is_truncated_value(value_text: str) -> bool:
    if not value_text:
        return False
    dot = value_text.rfind(".")
    if dot < 0:
        return False
    return len(value_text) - dot - 1 < 2


def _parse_page(words, base, state: _ParseState) -> Iterator[dict]:
    rows = _group_rows(words)

    for row in rows:
        row_top = min(w["top"] for w in row)
        text = " ".join(w["text"] for w in row).strip()
        if not text or _is_page_frame(text):
            continue

        # Section-header row (may re-print on continuation pages -- no-op
        # if section unchanged).
        new_section = _match_section_header(text)
        if new_section is not None:
            state.flush_suffix_into_pending()
            for r in state.emit_pending():
                yield r
            state.section = new_section
            continue

        # Wrap-fragment absorption.
        if state.try_absorb_wrap(row, row_top):
            continue

        full_value_words = [w for w in row if _FULL_VALUE_RE.match(w["text"])]

        # Grand-total row detection (checked BEFORE code detection, since
        # the grand total has no NCES code).
        is_grand = bool(_GRAND_TOTAL_RE.match(text))

        # NCES code detection (leading 4-digit token near x0 ~ 90).
        code_word = None
        for w in row:
            if _CODE_RE.match(w["text"]) and not _FULL_VALUE_RE.match(w["text"]):
                if w["x0"] < 130:
                    code_word = w
                    break

        label_tokens = [w for w in row
                        if w is not code_word
                        and not _FULL_VALUE_RE.match(w["text"])
                        and not _WRAP_FRAGMENT_RE.match(w["text"])]
        label_text = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_tokens).strip())

        # Pure label continuation (no code, no value).
        if not full_value_words and code_word is None and not is_grand:
            if label_text:
                state.label_buf.append(label_text)
            continue

        if not full_value_words:
            # Item row with a code but no value on this row -- unusual,
            # treat as label continuation.
            if label_text:
                state.label_buf.append(
                    (code_word["text"] + " " if code_word else "") + label_text)
            continue

        # Establish value column anchor from the first value we see.
        if state.value_anchor is None:
            # The amount column is the rightmost value on any data row.
            state.value_anchor = max(w["x1"] for w in full_value_words)

        # Flush + emit previous pending row.
        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r

        # The amount is the value closest to the anchor.
        value_word = _closest_value(full_value_words, state.value_anchor)
        if value_word is None:
            # No value at the anchor -- shouldn't happen if we passed the
            # `full_value_words` check above. Skip defensively.
            continue

        if is_grand:
            section_out = "summary"
            nces_code = "TOTAL"
            is_total = True
        else:
            section_out = state.section or "unknown"
            nces_code = code_word["text"] if code_word else "unknown"
            is_total = False

        row_data = {
            **base,
            "section": section_out,
            "nces_code": nces_code,
            "is_total": is_total,
            "item_label": label_text,
            "amount": parse_decimal(value_word["text"]),
            "amount_text": value_word["text"],
        }
        state.pending_row = row_data
        state.pending_row_top = row_top


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
