"""Parse the 'Statement of Revenues, Expenditures, and Changes in Fund
Balance - General Fund, By Sub-Fund' sub-report of OSPI F-196 All
Pages PDFs.

The sub-report is 2 pages (pp 8-9 typical) with a 3-column layout:

    Sub-Fund 10 (Basic Ed) | Sub-Fund 11 (Non-Basic-Ed) | General Fund

grouped into these sections:

  1. REVENUES: (Local, State, Federal, Other + TOTAL REVENUES)
  2. EXPENDITURES:
     - CURRENT: (Regular Instruction, Special Education,
       Vocational Ed, Skills Center, Compensatory Programs, Other
       Instructional Programs, Federal Stimulus COVID-19, Community
       Services, Support Services, Student Activities/Other)
     - CAPITAL OUTLAY: (Sites, Buildings, Other)
     - DEBT SERVICE: (Principal, Interest and Other Charges,
       Bond/Levy Issuance)
     - TOTAL EXPENDITURES
  3. REVENUES OVER (UNDER) EXPENDITURES (single-row summary)
  4. OTHER FINANCING SOURCES (USES): (Bond Sales, Long-Term Financing,
     Transfers In, Transfers Out, Other Financing Uses, Other +
     TOTAL OTHER FINANCING SOURCES (USES))
  5. EXCESS OF REVENUES AND OTHER FINANCING SOURCES OVER (UNDER)
     EXPENDITURES AND OTHER FINANCING USES (multi-line summary)
  6. BEGINNING TOTAL FUND BALANCE
  7. Accounting Changes and Error Corrections
  8. ENDING TOTAL FUND BALANCE

**Sub-report introduced in 2019-20**; earlier files don't carry it.

Parsing approach mirrors f196_balance_sheet.py:
  - Locate the two pages via banner regex.
  - Extract words with use_text_flow=True.
  - Group rows by y-tolerance.
  - Filter page-frame rows.
  - Section state machine transitions on major-section headers.
  - Sub-section state tracks CURRENT / CAPITAL OUTLAY / DEBT SERVICE
    within EXPENDITURES.
  - Column anchors: 3 x1's from first row with 3 full values
    ('Local' revenue row).
  - Item rows: label + up to 3 values (blank cells emit NULL).
  - TOTAL rows classified by leading keyword.
  - Multi-line labels absorbed via label_buf.
"""

import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_FUND_ORDER = ["sub_fund_10", "sub_fund_11", "general_fund"]

_BANNER_RE = re.compile(
    r"Statement\s+of\s+Revenues.*?Changes\s+in\s+Fund\s+Balance\s*[-–]\s*General\s+Fund,\s*By\s+Sub[- ]Fund",
    re.IGNORECASE)

# Major-section headers.
_SECTION_HEADERS = [
    ("revenues",                     re.compile(r"^REVENUES:?$", re.IGNORECASE)),
    ("expenditures",                 re.compile(r"^EXPENDITURES:?$", re.IGNORECASE)),
    ("other_financing_sources_uses", re.compile(r"^OTHER\s+FINANCING\s+SOURCES\s*\(USES\):?$", re.IGNORECASE)),
]

# Sub-section headers within EXPENDITURES. The '(excluding Object 9)'
# annotation on CURRENT: is optional.
_SUBSECTION_HEADERS = [
    ("current",       re.compile(r"^CURRENT:\s*(?:\(excluding\s+Object\s+9\))?$", re.IGNORECASE)),
    ("capital_outlay", re.compile(r"^CAPITAL\s+OUTLAY:?$", re.IGNORECASE)),
    ("debt_service",  re.compile(r"^DEBT\s+SERVICE:?$", re.IGNORECASE)),
]

# Total / summary row patterns. Ordered: more-specific first.
_TOTAL_PATTERNS = [
    (re.compile(r"^TOTAL\s+REVENUES$", re.IGNORECASE),
     "revenues", "", "total_revenues"),
    (re.compile(r"^TOTAL\s+EXPENDITURES$", re.IGNORECASE),
     "expenditures", "", "total_expenditures"),
    (re.compile(r"^REVENUES\s+OVER\s*\(UNDER\)\s+EXPENDITURES:?$", re.IGNORECASE),
     "summary", "", "revenues_over_under_expenditures"),
    (re.compile(r"^TOTAL\s+OTHER\s+FINANCING\s+SOURCES\s*\(USES\):?$", re.IGNORECASE),
     "other_financing_sources_uses", "", "total_other_financing_sources_uses"),
    (re.compile(r"^EXCESS\s+OF\s+REVENUES\s+AND\s+OTHER\s+FINANCING\s+SOURCES", re.IGNORECASE),
     "summary", "", "excess_of_revenues_over_expenditures"),
    (re.compile(r"^BEGINNING\s+TOTAL\s+FUND\s+BALANCE$", re.IGNORECASE),
     "summary", "", "beginning_total_fund_balance"),
    (re.compile(r"^Accounting\s+Changes\s+and\s+Error\s+Corrections$", re.IGNORECASE),
     "summary", "", "corrections_or_restatements"),
    (re.compile(r"^ENDING\s+TOTAL\s+FUND\s+BALANCE$", re.IGNORECASE),
     "summary", "", "ending_total_fund_balance"),
]

_PAGE_FRAME_PATTERNS = [
    re.compile(r"^REPORT\s+F196\b", re.IGNORECASE),
    re.compile(r"^E\.S\.D\.\s+\w+\s+Statement\s+of\s+Revenues", re.IGNORECASE),
    re.compile(r"^COUNTY:\s+\S+", re.IGNORECASE),
    re.compile(r"^For\s+the\s+Year\s+Ended", re.IGNORECASE),
    re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE),
    # Column-header row.
    re.compile(r"^Sub-Fund\s+10\s+Sub-Fund\s+11\s+General\s+Fund$", re.IGNORECASE),
]

_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")

_COL_TOLERANCE = 8.0
_Y_TOLERANCE = 2.0
_WRAP_FRAGMENT_MAX_Y_GAP = 14.0
_MAX_PAGES = 4  # defensive; sub-report is 2 pages


def parse_f196_gf_by_subfund_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_gf_by_subfund",
    }

    with pdfplumber.open(info.path) as pdf:
        sub_pages = _find_pages(pdf)
        if not sub_pages:
            return

        first_words = pdf.pages[sub_pages[0]].extract_words(use_text_flow=True)
        d = _district_from_words(first_words)
        if d:
            base["district"] = d

        state = _ParseState()
        for pg_idx in sub_pages:
            words = pdf.pages[pg_idx].extract_words(use_text_flow=True)
            yield from _parse_page(words, base, state)

        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r


class _ParseState:
    def __init__(self):
        self.column_anchors: Optional[List[float]] = None
        self.section: Optional[str] = None
        self.sub_section: str = ""
        self.pending_rows: Optional[List[dict]] = None
        self.pending_row_top: Optional[float] = None
        self.pending_wrap: bool = False
        self.label_buf: List[str] = []

    def flush_suffix_into_pending(self) -> None:
        if self.pending_rows and self.label_buf:
            suffix = " ".join(self.label_buf).strip()
            if suffix:
                for r in self.pending_rows:
                    joined = (r["item_label"] + " " + suffix).strip()
                    r["item_label"] = re.sub(r"\s+", " ", joined)
                    if not r["is_total"]:
                        r["item_code"] = _slugify(r["item_label"]) or "unknown"
        self.label_buf.clear()

    def emit_pending(self):
        rows = self.pending_rows or []
        # Strip the internal `_text` field before yield.
        cleaned = [{k: v for k, v in r.items() if not k.endswith("_text")} for r in rows]
        self.pending_rows = None
        self.pending_row_top = None
        self.pending_wrap = False
        return cleaned

    def try_absorb_wrap(self, row, row_top) -> bool:
        if (
            self.pending_rows is None
            or self.pending_row_top is None
            or self.column_anchors is None
            or (row_top - self.pending_row_top) > _WRAP_FRAGMENT_MAX_Y_GAP
        ):
            return False
        fragment_words = [w for w in row
                          if _WRAP_FRAGMENT_RE.match(w["text"])
                          and not _FULL_VALUE_RE.match(w["text"])]
        if not fragment_words:
            return False
        absorbed = False
        for col_idx, anchor in enumerate(self.column_anchors):
            existing = self.pending_rows[col_idx].get("amount_text", "")
            if not existing or not _is_truncated_value(existing):
                continue
            best = None
            best_d = _COL_TOLERANCE
            for frag in fragment_words:
                d = abs(frag["x1"] - anchor)
                if d <= best_d:
                    best = frag
                    best_d = d
            if best is None:
                continue
            merged = existing + best["text"]
            self.pending_rows[col_idx]["amount_text"] = merged
            self.pending_rows[col_idx]["amount"] = parse_decimal(merged)
            absorbed = True
        return absorbed


def _find_pages(pdf) -> List[int]:
    out: List[int] = []
    for i, page in enumerate(pdf.pages):
        if i > 20:
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


def _match_section_header(text: str):
    for name, pat in _SECTION_HEADERS:
        if pat.match(text):
            return name
    return None


def _match_subsection_header(text: str):
    for name, pat in _SUBSECTION_HEADERS:
        if pat.match(text):
            return name
    return None


def _match_total_row(text: str):
    for pat, section, sub, code in _TOTAL_PATTERNS:
        if pat.match(text):
            return (section, sub, code)
    return None


def _slugify(label: str) -> str:
    s = label.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


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

        # Major-section header?
        new_section = _match_section_header(text)
        if new_section is not None:
            state.flush_suffix_into_pending()
            for r in state.emit_pending():
                yield r
            state.section = new_section
            state.sub_section = ""
            continue

        # Sub-section header (only meaningful inside EXPENDITURES)?
        new_sub = _match_subsection_header(text)
        if new_sub is not None:
            state.flush_suffix_into_pending()
            for r in state.emit_pending():
                yield r
            state.sub_section = new_sub
            continue

        # Wrap-fragment absorption.
        if state.try_absorb_wrap(row, row_top):
            continue

        full_value_words = [w for w in row if _FULL_VALUE_RE.match(w["text"])]
        label_words = [w for w in row
                       if not _FULL_VALUE_RE.match(w["text"])
                       and not _WRAP_FRAGMENT_RE.match(w["text"])]
        label_text = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_words).strip())

        # Pure label continuation (no values).
        if not full_value_words:
            if label_text:
                state.label_buf.append(label_text)
            continue

        # Establish column anchors from first row with 3 full values.
        if state.column_anchors is None:
            if len(full_value_words) != len(_FUND_ORDER):
                if label_text:
                    state.label_buf.append(label_text)
                continue
            state.column_anchors = [w["x1"] for w in full_value_words]

        # Flush pending suffix + emit.
        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r

        # Classify as detail vs total/summary.
        total_match = _match_total_row(label_text)
        if total_match is not None:
            section_out, sub_out, item_code = total_match
            is_total = True
        else:
            section_out = state.section or "unknown"
            sub_out = state.sub_section if section_out == "expenditures" else ""
            item_code = _slugify(label_text) or "unknown"
            is_total = False

        new_rows: List[dict] = []
        for col_idx, anchor in enumerate(state.column_anchors):
            fund = _FUND_ORDER[col_idx]
            matched = _closest_value(full_value_words, anchor)
            new_rows.append({
                **base,
                "section": section_out,
                "sub_section": sub_out,
                "item_code": item_code,
                "fund": fund,
                "is_total": is_total,
                "item_label": label_text,
                "amount": parse_decimal(matched["text"]) if matched else None,
                "amount_text": matched["text"] if matched else "",
            })
        state.pending_rows = new_rows
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
