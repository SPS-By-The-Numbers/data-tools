"""Parse the Resource to Program Expenditure Report - General Fund
sub-report of OSPI F-196 All Pages PDFs.

The sub-report is 2 pages listing every General-Fund program with a
4-column decomposition:

    Program Expenditures | State Resources | Federal Resources
        | Other Resources

grouped into three sections:

  1. REGULAR INSTRUCTIONAL PROGRAMS (was 'BASIC EDUCATION PROGRAMS'
     pre-~2016-17)
  2. OTHER INSTRUCTIONAL PROGRAMS
  3. OTHER PROGRAMS

Each section closes with a `TOTAL <section-name>` row. The report
closes with a `TOTALS` grand-total row across all sections.

Parsing approach:

  - Locate R2P pages via a banner regex on the first ~3 lines. The
    TOC page (page 1) also mentions the phrase in its list of
    sub-reports; restricting the match to the banner rows filters
    those out.
  - Extract words with `use_text_flow=True`.
  - Group into rows, skip page-frame rows.
  - Section state machine on uppercase-only header rows.
  - Column anchors from the first row with 4 full values (typically
    '01 Basic Education').
  - Item rows: leading 2-digit code + label + 4 values. Multi-line
    labels are absorbed into a pending row's suffix.
  - TOTAL rows: leading 'TOTAL' + section keywords, or the bare
    'TOTALS' grand total.

Quirks handled:

  - Section-name drift ('BASIC EDUCATION PROGRAMS' /
    'REGULAR INSTRUCTIONAL PROGRAMS') canonicalized to a stable slug.
  - 2013-14 form banner splits 'General Fund' and 'Resource to Program
    Expenditure Report' across two banner lines (lines 2 and 3);
    2023-24 form joins them on line 2. Banner detection accepts both.
"""

import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_COLUMN_NAMES = [
    "program_expenditures",
    "state_resources",
    "federal_resources",
    "other_resources",
]

_BANNER_RE = re.compile(r"Resource\s+to\s+Program\s+Expenditure", re.IGNORECASE)

# Section headers. Canonical slugs on the left; regexes match both the
# old 'BASIC EDUCATION PROGRAMS' and the newer 'REGULAR INSTRUCTIONAL
# PROGRAMS' labels.
_SECTION_HEADERS = [
    ("regular_instructional",
     re.compile(r"^(?:BASIC\s+EDUCATION|REGULAR\s+INSTRUCTIONAL)\s+PROGRAMS$",
                re.IGNORECASE)),
    ("other_instructional",
     re.compile(r"^OTHER\s+INSTRUCTIONAL\s+PROGRAMS$", re.IGNORECASE)),
    ("other_programs",
     re.compile(r"^OTHER\s+PROGRAMS$", re.IGNORECASE)),
]

# TOTAL row patterns. Ordering not critical (each is disambiguated by
# the section keyword). The whole-report grand-total row is a bare
# 'TOTALS'.
_TOTAL_PATTERNS = [
    (re.compile(r"^TOTAL\s+(?:BASIC\s+(?:EDUCATION|EDUCATIONAL)|REGULAR\s+INSTRUCTIONAL)\s+PROGRAMS$",
                re.IGNORECASE),
     "regular_instructional", "TOTAL"),
    (re.compile(r"^TOTAL\s+OTHER\s+INSTRUCTIONAL\s+PROGRAMS$", re.IGNORECASE),
     "other_instructional", "TOTAL"),
    (re.compile(r"^TOTAL\s+OTHER\s+PROGRAMS$", re.IGNORECASE),
     "other_programs", "TOTAL"),
    (re.compile(r"^TOTALS$", re.IGNORECASE),
     "summary", "total"),
]

# Page-frame rows to skip.
_PAGE_FRAME_PATTERNS = [
    re.compile(r"^REPORT\s+F196\b", re.IGNORECASE),
    re.compile(r"^E\.S\.D\.\s+\w+\s+(General\s+Fund|Resource\s+to\s+Program)", re.IGNORECASE),
    re.compile(r"^COUNTY:\s+\d+\s+\w+", re.IGNORECASE),
    re.compile(r"^For\s+the\s+Year\s+Ended", re.IGNORECASE),
    re.compile(r"^Fiscal\s+Year\s+\d{4}", re.IGNORECASE),
    re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE),
    # Column headers (2 lines: 'Program State Federal Other' + 'Expenditures Resources Resources Resources')
    re.compile(r"^Program\s+State\s+Federal\s+Other$", re.IGNORECASE),
    re.compile(r"^Expenditures\s+Resources\s+Resources\s+Resources$", re.IGNORECASE),
]

_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")
_CODE_RE = re.compile(r"^\d{2}$")

_COL_TOLERANCE = 8.0
_Y_TOLERANCE = 2.0
_WRAP_FRAGMENT_MAX_Y_GAP = 14.0
_MAX_PAGES = 4  # defensive cap; the sub-report is typically 2 pages


def _is_truncated_value(value_text: str) -> bool:
    """True when a printed value is missing its trailing digit(s) -- the
    form always prints to 2 decimals, so a decimal suffix shorter than 2
    signals overflow (Seattle 10-figure values on the R2P grand total).
    """
    if not value_text:
        return False
    dot = value_text.rfind(".")
    if dot < 0:
        return False
    return len(value_text) - dot - 1 < 2


def parse_f196_resource_to_program_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_resource_to_program",
    }

    with pdfplumber.open(info.path) as pdf:
        r2p_pages = _find_r2p_pages(pdf)
        if not r2p_pages:
            return

        first_words = pdf.pages[r2p_pages[0]].extract_words(use_text_flow=True)
        d = _district_from_words(first_words)
        if d:
            base["district"] = d

        state = _ParseState()
        for pg_idx in r2p_pages:
            words = pdf.pages[pg_idx].extract_words(use_text_flow=True)
            yield from _parse_page(words, base, state)

        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r


class _ParseState:
    def __init__(self):
        self.column_anchors: Optional[List[float]] = None
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
        # Strip the parser-local `<name>_text` keys used only by the
        # wrap-fragment absorber -- they aren't part of the CSV schema.
        row = {k: v for k, v in self.pending_row.items() if not k.endswith("_text")}
        self.pending_row = None
        self.pending_row_top = None
        return [row]

    def try_absorb_wrap(self, row, row_top) -> bool:
        """Trailing-digit value-wrap absorption. On 10-figure values
        (Seattle GF $1B+), the trailing 1-2 digits overflow the printed
        column width and wrap to the next visual row at the same x1.
        The pending row's value_text ends short of 2 decimal places; the
        next row's bare digit fragment at the same x1 finishes it.
        """
        if (
            self.pending_row is None
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
        for col_idx, name in enumerate(_COLUMN_NAMES):
            existing = self.pending_row.get(f"{name}_text", "")
            if not existing or not _is_truncated_value(existing):
                continue
            anchor = self.column_anchors[col_idx]
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
            self.pending_row[f"{name}_text"] = merged
            self.pending_row[name] = parse_decimal(merged)
            absorbed = True
        return absorbed


def _find_r2p_pages(pdf) -> List[int]:
    """Return 0-indexed page numbers of the R2P sub-report.

    The TOC page (page 1) also mentions 'Resource to Program
    Expenditure' as a sub-report title in its list -- filter that out
    by requiring the banner phrase to appear in the first 3 lines of
    the page.
    """
    out: List[int] = []
    for i, page in enumerate(pdf.pages):
        if i > 100:  # this sub-report is deep in the doc but not that deep
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


def _match_total_row(label_text: str):
    for pat, section, code in _TOTAL_PATTERNS:
        if pat.match(label_text):
            return (section, code)
    return None


def _parse_page(words, base, state: _ParseState) -> Iterator[dict]:
    rows = _group_rows(words)

    for row in rows:
        row_top = min(w["top"] for w in row)
        text = " ".join(w["text"] for w in row).strip()
        if not text or _is_page_frame(text):
            continue

        # Section header row.
        new_section = _match_section_header(text)
        if new_section is not None:
            state.flush_suffix_into_pending()
            for r in state.emit_pending():
                yield r
            state.section = new_section
            continue

        # Wrap-fragment absorption -- Seattle-scale 10-figure values
        # overflow the printed column width and the trailing digit wraps
        # to the next visual row at the same x1. Consume the fragment
        # into the pending row and skip further handling of this row.
        if state.try_absorb_wrap(row, row_top):
            continue

        # Classify tokens.
        full_value_words = [w for w in row if _FULL_VALUE_RE.match(w["text"])]
        code_word = None
        for w in row:
            if _CODE_RE.match(w["text"]) and not _FULL_VALUE_RE.match(w["text"]):
                # Only treat the FIRST 2-digit token at low x0 as the code
                # -- avoid picking up in-label tokens like '(ALE)' or
                # 'ESSER II'.
                if w["x0"] < 40:
                    code_word = w
                    break

        label_tokens = [w for w in row
                        if w is not code_word
                        and not _FULL_VALUE_RE.match(w["text"])
                        and not _WRAP_FRAGMENT_RE.match(w["text"])]
        label_text = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_tokens).strip())

        # Pure label continuation (no values, no code).
        if not full_value_words and code_word is None:
            if label_text:
                state.label_buf.append(label_text)
            continue

        # Establish column anchors from the first row with 4 full values.
        if state.column_anchors is None:
            if len(full_value_words) != len(_COLUMN_NAMES):
                if label_text:
                    state.label_buf.append(label_text)
                continue
            state.column_anchors = [w["x1"] for w in full_value_words]

        # Flush previous pending suffix + emit.
        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r

        # Classify as detail vs total row.
        total_match = _match_total_row(label_text)
        if total_match is not None:
            section_out, item_code = total_match
            is_total = True
        else:
            section_out = state.section or "unknown"
            item_code = code_word["text"] if code_word else "unknown"
            is_total = False

        row_data = {
            **base,
            "section": section_out,
            "item_code": item_code,
            "is_total": is_total,
            "item_label": label_text,
        }
        for col_idx, name in enumerate(_COLUMN_NAMES):
            matched = _closest_value(full_value_words, state.column_anchors[col_idx])
            row_data[name] = parse_decimal(matched["text"]) if matched else None
            # Keep the raw text for the wrap-fragment absorber to inspect.
            row_data[f"{name}_text"] = matched["text"] if matched else ""
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
