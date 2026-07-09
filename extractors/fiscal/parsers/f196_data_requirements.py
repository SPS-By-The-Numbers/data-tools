"""Parse three Data Requirements sub-reports on OSPI F-196 All Pages
PDFs into a single combined fact table.

The three sub-reports (see schemas/f196_data_requirements.py for
detail):

  - **supplemental_reports** (p 66) -- items A-G with a value at the
    end of the first descriptive line.
  - **apportionment_recovery** (p 67) -- items 1-2 with sub-items
    a/b/c; item 2 (Indirect Rate for State Revenue Recoveries) is a
    SYSTEM CALCULATED ratio.
  - **federal_indirect_cost_data** (pp 68-71) -- items 1-33 grouped
    into 'DISTORTING ITEMS' (pp 68-69) and 'INDIRECT EXPENDITURES'
    (pp 70-71). Value is printed on the line AFTER the description.

Parsing approach:

  - Locate each sub-report by banner regex.
  - Parse pages as text (extract_text). Split into lines.
  - Identify item boundaries by leading item-code marker at the start
    of a line ('A.', 'B.', ..., '1.', '2.', 'a)', 'b)', 'c)').
  - Accumulate description across continuation lines until the next
    item marker or a value-only line.
  - Extract value: rightmost numeric on the first item line, OR the
    entire content of a value-only line (which may be 'Yes'/'No'
    for the certification item).
  - Track section state for federal_indirect_cost_data via ALL-CAPS
    section headers ('DISTORTING ITEMS' / 'INDIRECT EXPENDITURES').
"""

import logging
import re
from typing import Iterator, List, Optional, Tuple

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_BANNERS = [
    ("supplemental_reports",
     re.compile(r"Data\s+Requirements\s+for\s+Supplemental\s+Reports", re.IGNORECASE)),
    ("apportionment_recovery",
     re.compile(r"Data\s+Requirements\s+for\s+End\s+of\s+Year\s+Reporting\s+to\s+Apportionment", re.IGNORECASE)),
    ("federal_indirect_cost_data",
     re.compile(r"Data\s+Requirements\s+for\s+Calculating\s+Federal\s+Indirect\s+Cost\s+Rate", re.IGNORECASE)),
]

# Item-code marker at start of a line. Groups:
#   1 = code (like 'A', '1', '2a', 'a')
_ITEM_MARKER_RE = re.compile(
    r"^\s*([A-Za-z]|\d+)([\.\)])\s+(.*)$"
)
# Sub-item marker (e.g. 'a) Total All Programs') -- only recognized
# under specific parent items.
_SUB_ITEM_MARKER_RE = re.compile(r"^\s*([a-c])\)\s+(.*)$")

# Section headers within federal_indirect_cost_data.
_FIC_SECTION_HEADERS = {
    "distorting_items":       re.compile(r"^DISTORTING\s+ITEMS$", re.IGNORECASE),
    "indirect_expenditures":  re.compile(r"^INDIRECT\s+EXPENDITURES$", re.IGNORECASE),
}

# Value pattern: decimal with commas allowed, optional negative.
_VALUE_RE = re.compile(r"^-?\$?\s*\d[\d,]*\.\d+$")
# Textual value (e.g. Yes/No).
_TEXTUAL_VALUE_RE = re.compile(r"^(Yes|No)$", re.IGNORECASE)

_PAGE_FRAME_RE = re.compile(
    r"^(REPORT\s+F196\b|E\.S\.D\.\s+\w+\s+Data\s+Requirements|COUNTY:\s+\S+|"
    r"Fiscal\s+Year\s+\d|For\s+the\s+Year\s+Ended|Page\s+\d+\s+of\s+\d+\s*$)",
    re.IGNORECASE
)


def parse_f196_data_requirements_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_data_requirements",
    }

    with pdfplumber.open(info.path) as pdf:
        # Group pages per sub-report kind.
        pages_by_kind: List[Tuple[str, List[int]]] = []
        current_kind: Optional[str] = None
        current_pages: List[int] = []
        for i, page in enumerate(pdf.pages):
            t = page.extract_text() or ""
            first_lines = " ".join(t.split("\n", 3)[:3])
            matched_kind = None
            for kind, pat in _BANNERS:
                if pat.search(first_lines):
                    matched_kind = kind
                    break
            if matched_kind is None:
                if current_kind is not None:
                    pages_by_kind.append((current_kind, current_pages))
                    current_kind = None
                    current_pages = []
                continue
            if matched_kind != current_kind:
                if current_kind is not None:
                    pages_by_kind.append((current_kind, current_pages))
                current_kind = matched_kind
                current_pages = []
            current_pages.append(i)
        if current_kind is not None:
            pages_by_kind.append((current_kind, current_pages))

        # District from first sub-report page.
        if pages_by_kind:
            first_words = pdf.pages[pages_by_kind[0][1][0]].extract_words(
                use_text_flow=True)
            d = _district_from_words(first_words)
            if d:
                base["district"] = d

        for kind, pages in pages_by_kind:
            yield from _parse_kind(pdf, kind, pages, base)


def _district_from_words(words) -> Optional[str]:
    text = " ".join(w["text"] for w in words[:30])
    m = re.search(r"REPORT\s+F196\s+(.+?)\s+No\.\s*\d+", text, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _parse_kind(pdf, kind: str, page_indexes: List[int], base) -> Iterator[dict]:
    """Parse all pages of a single sub-report kind."""
    # Collect all non-frame lines across pages, preserving order.
    lines: List[str] = []
    for pg_idx in page_indexes:
        t = pdf.pages[pg_idx].extract_text() or ""
        for L in t.split("\n"):
            stripped = L.strip()
            if not stripped:
                continue
            if _PAGE_FRAME_RE.search(stripped):
                continue
            lines.append(stripped)

    section: str = ""
    pending_code: Optional[str] = None
    pending_label_parts: List[str] = []
    pending_value_text: Optional[str] = None

    def emit_if_ready():
        if pending_code is None:
            return None
        label = re.sub(r"\s+", " ",
                       " ".join(pending_label_parts).strip())
        if len(label) > 250:
            label = label[:247] + "..."
        row = {
            **base,
            "report_kind": kind,
            "section": section,
            "item_code": pending_code,
            "item_label": label,
            "value_text": pending_value_text or "",
            "value": parse_decimal(pending_value_text)
                     if pending_value_text and _VALUE_RE.match(pending_value_text.replace(" ", "").replace("$", ""))
                     else None,
        }
        return row

    for line in lines:
        # Skip section-name headers that aren't item lines.
        if kind == "federal_indirect_cost_data":
            hit = None
            for s_name, s_re in _FIC_SECTION_HEADERS.items():
                if s_re.match(line):
                    hit = s_name
                    break
            if hit is not None:
                r = emit_if_ready()
                if r:
                    yield r
                    pending_code = None
                    pending_label_parts = []
                    pending_value_text = None
                section = hit
                continue

        # 'Other Data Requirements and Certifications' header on p 66:
        # skip (it's a page-level title, not an item).
        if kind == "supplemental_reports" and \
                re.match(r"^Other\s+Data\s+Requirements", line, re.IGNORECASE):
            continue

        # Try to parse as a new item.
        m = _ITEM_MARKER_RE.match(line)
        if m:
            code, punct, rest = m.group(1), m.group(2), m.group(3)
            # For supplemental_reports: only 'A' through 'G' (single alpha
            # with '.') are top-level items.
            # For apportionment_recovery: '1' or '2' with '.' are top-level;
            # 'a)', 'b)', 'c)' with ')' are sub-items.
            # For federal_indirect_cost_data: '1' through '33+' with '.'.
            is_top_level = False
            is_sub_item = False
            if kind == "supplemental_reports":
                if len(code) == 1 and code.isalpha() and punct == ".":
                    is_top_level = True
            elif kind == "apportionment_recovery":
                if code.isdigit() and punct == ".":
                    is_top_level = True
                elif len(code) == 1 and code.isalpha() and punct == ")":
                    is_sub_item = True
            elif kind == "federal_indirect_cost_data":
                if code.isdigit() and punct == ".":
                    is_top_level = True

            if is_top_level or is_sub_item:
                # Emit previous pending item.
                r = emit_if_ready()
                if r:
                    yield r
                pending_code = code.upper() if kind == "supplemental_reports" else code
                if is_sub_item:
                    # Sub-item code like '2a' or '2b' (combined with
                    # parent). Simplify to the alphanumeric.
                    pending_code = code
                pending_label_parts = [rest]
                pending_value_text = None
                # If the value is at the end of this line, extract it.
                trailing_value = _extract_trailing_value(rest)
                if trailing_value is not None:
                    pending_value_text = trailing_value
                    # Strip the value from the label.
                    pending_label_parts = [rest[: -len(trailing_value)].rstrip()]
                continue

        # Continuation line or value-only line.
        if pending_code is None:
            continue
        # Check if the entire line is a value.
        if _VALUE_RE.match(line.replace(" ", "").replace("$", "")) or \
                _TEXTUAL_VALUE_RE.match(line):
            pending_value_text = line
            continue
        # Otherwise it's description continuation.
        # Also check for trailing value on continuation line.
        trailing_value = _extract_trailing_value(line)
        if trailing_value is not None:
            pending_value_text = trailing_value
            pending_label_parts.append(line[: -len(trailing_value)].rstrip())
        else:
            pending_label_parts.append(line)

    r = emit_if_ready()
    if r:
        yield r


def _extract_trailing_value(text: str) -> Optional[str]:
    """If `text` ends in a numeric or Yes/No token, return that token.
    Otherwise return None.
    """
    text = text.rstrip()
    # Find the last space-separated token.
    parts = text.rsplit(None, 1)
    if len(parts) < 2:
        return None
    tail = parts[1]
    if _VALUE_RE.match(tail.replace(",", "").replace("$", "")) or \
            _TEXTUAL_VALUE_RE.match(tail):
        return tail
    # Also check if the last token is a comma-formatted number.
    if _VALUE_RE.match(tail):
        return tail
    return None


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
