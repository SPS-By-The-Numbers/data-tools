"""Parse the Financial Edit Report sub-report of OSPI F-196 All Pages
PDFs.

The sub-report is 2 pages (pp 82-84 typical) listing OSPI's automated
data-quality checks per fund. Layout:

    Type | Number | Message | Amount 1 | Amount 2

Fund grouping: each fund's edits are preceded by an ALL-CAPS fund
header ('GENERAL FUND', 'ASSOCIATED STUDENT BODY FUND', etc). A fund
with no flagged edits prints '<Fund Name>: Cleared all edits' -- a
single sentinel line.

Parsing approach:
  - Locate the sub-report pages via banner regex.
  - Group words into rows.
  - Skip page-frame rows.
  - Track fund state via ALL-CAPS fund-header rows.
  - Skip the column-header row 'Type Number Message Amount 1 Amount 2'.
  - Detect 'Cleared all edits' sentinel -> emit is_cleared=True row.
  - Detect edit rows: leading Type token at x0=20 + Number token at
    x0=143 + message tokens at x0>=215 + up to 2 amounts at x1~664/772.
  - Continuation rows (only tokens at x0>=215, no leading Type): append
    to the current edit's message.

Values may be blank (some edits print one amount only). Positional
column-anchor extraction handles this.
"""

import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_BANNER_RE = re.compile(r"Financial\s+Edit\s+Report", re.IGNORECASE)

# Fund-header patterns. Canonical slug per printed header.
_FUND_HEADERS = [
    ("general",               re.compile(r"^GENERAL\s+FUND$")),
    ("asb",                   re.compile(r"^ASSOCIATED\s+STUDENT\s+BODY\s+FUND$")),
    ("debt_service",          re.compile(r"^DEBT\s+SERVICE\s+FUND$")),
    ("capital_projects",      re.compile(r"^CAPITAL\s+PROJECTS\s+FUND$")),
    ("transportation_vehicle", re.compile(r"^TRANSPORTATION\s+VEHICLE\s+FUND$")),
    ("permanent",             re.compile(r"^PERMANENT\s+FUND$")),
    ("fiduciary",             re.compile(r"^PRIVATE\s+PURPOSE\s+TRUST(?:\s*[\/,]\s*OTHER\s+TRUST)?\s+FUND$")),
]

# 'Cleared all edits' sentinel row. The fund name prefix varies with
# the printed fund label -- match anything ending in ': Cleared all edits'.
_CLEARED_RE = re.compile(r":\s+Cleared\s+all\s+edits$", re.IGNORECASE)

# Column-header row.
_COL_HEADER_RE = re.compile(
    r"^Type\s+Number\s+Message\s+Amount\s+1\s+Amount\s+2$", re.IGNORECASE)

# Edit-type tokens (only these are treated as leading Type on an
# edit row). Older vintages (2013-14 through 2015-16) print 'Info' /
# 'Warn' abbreviations; newer vintages use full 'Informational' /
# 'Warning'. Both are recognized and canonicalized.
_EDIT_TYPE_CANONICAL = {
    "info": "informational",
    "informational": "informational",
    "warn": "warning",
    "warning": "warning",
    "error": "error",
    "fatal": "fatal",
}

# Page-frame rows.
_PAGE_FRAME_PATTERNS = [
    re.compile(r"^REPORT\s+F196\b", re.IGNORECASE),
    re.compile(r"^E\.S\.D\.\s+\w+\s+Financial\s+Edit\s+Report", re.IGNORECASE),
    re.compile(r"^COUNTY:\s+\S+", re.IGNORECASE),
    re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE),
    re.compile(r"^Apportionment\s+Report\s+copyright", re.IGNORECASE),
    re.compile(r"^\(http://", re.IGNORECASE),
]

_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")
_EDIT_NUMBER_RE = re.compile(r"^\d+\.\d+$")

_COL_TOLERANCE = 10.0
_Y_TOLERANCE = 2.0

# Message column x0 minimum. Two vintages: 2013-14 puts message at
# x0=164; 2023-24 puts it at x0=215. Lower bound catches both without
# absorbing the Number column (at x0=92 or x0=143).
_MESSAGE_X0_MIN = 150.0

# Amount column x0 minimum. Amounts are at x0 >= ~500 in both vintages;
# 400 gives us safety margin without absorbing message-column tokens.
_AMOUNT_X0_MIN = 400.0

_MAX_PAGES = 6


def parse_f196_edit_report_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_edit_report",
    }

    with pdfplumber.open(info.path) as pdf:
        pages = _find_pages(pdf)
        if not pages:
            return

        first_words = pdf.pages[pages[0]].extract_words(use_text_flow=True)
        d = _district_from_words(first_words)
        if d:
            base["district"] = d

        state = _ParseState()
        for pg_idx in pages:
            words = pdf.pages[pg_idx].extract_words(use_text_flow=True)
            yield from _parse_page(words, base, state)
        # Flush any pending edit at end of last page.
        r = state.emit_pending()
        if r:
            yield r


class _ParseState:
    def __init__(self):
        self.column_anchors: Optional[tuple] = None  # (amount_1_x1, amount_2_x1)
        self.fund: Optional[str] = None
        self.fund_seq: int = 0  # 0-based edit sequence within current fund
        self.pending_edit: Optional[dict] = None
        self.message_buf: List[str] = []
        self.emitted_funds: set = set()

    def flush_message_buf(self):
        if self.pending_edit and self.message_buf:
            suffix = " ".join(self.message_buf).strip()
            if suffix:
                joined = (self.pending_edit["message"] + " " + suffix).strip()
                self.pending_edit["message"] = re.sub(r"\s+", " ", joined)
        self.message_buf.clear()

    def emit_pending(self):
        self.flush_message_buf()
        if self.pending_edit is None:
            return None
        edit = self.pending_edit
        self.pending_edit = None
        return edit

    def start_edit(self, fund, edit_type, edit_number, message,
                   amount_1, amount_2, base):
        seq = self.fund_seq
        self.fund_seq += 1
        self.pending_edit = {
            **base,
            "fund": fund,
            "edit_seq": seq,
            "edit_type": edit_type,
            "edit_number": edit_number,
            "message": message,
            "is_cleared": False,
            "amount_1": amount_1,
            "amount_2": amount_2,
        }

    def change_fund(self, new_fund):
        self.fund = new_fund
        self.fund_seq = 0


def _find_pages(pdf) -> List[int]:
    out: List[int] = []
    for i, page in enumerate(pdf.pages):
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


def _match_fund_header(text: str) -> Optional[str]:
    for name, pat in _FUND_HEADERS:
        if pat.match(text):
            return name
    return None


def _parse_page(words, base, state: _ParseState) -> Iterator[dict]:
    rows = _group_rows(words)

    for row in rows:
        text = " ".join(w["text"] for w in row).strip()
        if not text or _is_page_frame(text):
            continue

        # Column-header row.
        if _COL_HEADER_RE.match(text):
            continue

        # Fund-section header row -- transitions state.
        new_fund = _match_fund_header(text)
        if new_fund is not None:
            r = state.emit_pending()
            if r:
                yield r
            state.change_fund(new_fund)
            continue

        # 'Cleared all edits' sentinel.
        if _CLEARED_RE.search(text) and state.fund is not None and \
                state.fund not in state.emitted_funds:
            r = state.emit_pending()
            if r:
                yield r
            yield {
                **base,
                "fund": state.fund,
                "edit_seq": 0,
                "edit_type": "cleared",
                "edit_number": "",
                "message": "Cleared all edits",
                "is_cleared": True,
                "amount_1": None,
                "amount_2": None,
            }
            state.emitted_funds.add(state.fund)
            state.fund_seq = 1  # any subsequent rows for this fund get seq 1+
            continue

        # Classify tokens.
        first = row[0]
        first_text = first["text"]
        first_x0 = first["x0"]

        canonical_type = _EDIT_TYPE_CANONICAL.get(first_text.lower())
        is_edit_row = first_x0 < 100 and canonical_type is not None

        if is_edit_row:
            # Emit prior pending, then start new edit.
            r = state.emit_pending()
            if r:
                yield r

            edit_type = canonical_type
            # Find edit number: 2nd non-header token that matches the
            # edit-number regex.
            edit_number = ""
            for w in row[1:]:
                if _EDIT_NUMBER_RE.match(w["text"]):
                    edit_number = w["text"]
                    break

            # Message tokens: everything at x0 >= 200 that isn't a value.
            message_tokens = [w for w in row
                              if w["x0"] >= _MESSAGE_X0_MIN
                              and not _FULL_VALUE_RE.match(w["text"])]
            message_text = re.sub(r"\s+", " ",
                                  " ".join(w["text"] for w in message_tokens).strip())

            # Values: full-value tokens whose x0 is in the amount-column
            # region. The edit_number token (e.g. '1.545' at x0=92 or
            # x0=143) matches _FULL_VALUE_RE too; the x0 filter excludes
            # it.
            value_words = [w for w in row
                           if _FULL_VALUE_RE.match(w["text"])
                           and w["x0"] >= _AMOUNT_X0_MIN]
            amount_1 = None
            amount_2 = None
            if len(value_words) >= 2:
                # Sort by x0; the two rightmost are our amounts.
                value_words = sorted(value_words, key=lambda w: w["x1"])
                amount_1 = parse_decimal(value_words[-2]["text"])
                amount_2 = parse_decimal(value_words[-1]["text"])
                # Establish column anchors on first edit-row seen.
                if state.column_anchors is None:
                    state.column_anchors = (value_words[-2]["x1"], value_words[-1]["x1"])
            elif len(value_words) == 1:
                # Single value -- attribute by x-proximity to known anchors.
                w = value_words[0]
                if state.column_anchors is not None:
                    a1, a2 = state.column_anchors
                    if abs(w["x1"] - a1) < abs(w["x1"] - a2):
                        amount_1 = parse_decimal(w["text"])
                    else:
                        amount_2 = parse_decimal(w["text"])
                else:
                    # Default to amount_1 if we can't tell.
                    amount_1 = parse_decimal(w["text"])

            state.start_edit(state.fund or "unknown",
                             edit_type, edit_number, message_text,
                             amount_1, amount_2, base)
            continue

        # Continuation row: only message tokens (no leading edit type).
        # Append to current edit's message buffer.
        if state.pending_edit is not None:
            cont_tokens = [w for w in row
                           if w["x0"] >= _MESSAGE_X0_MIN
                           and not _FULL_VALUE_RE.match(w["text"])]
            cont_text = re.sub(r"\s+", " ",
                               " ".join(w["text"] for w in cont_tokens).strip())
            if cont_text:
                state.message_buf.append(cont_text)


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
