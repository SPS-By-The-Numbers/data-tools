"""Parse the Statement of Fiduciary Net Position + Statement of Changes
in Fiduciary Net Position sub-reports of OSPI F-196 All Pages PDFs.

Two adjacent 1-page sub-reports (pp 20-21 typical, pp 17-18 in 2013-14):

  - **net_position**: balance-sheet-shape with sections
      ASSETS / LIABILITIES / NET POSITION
    plus per-section TOTAL rows.
  - **changes**: income-statement-shape with sections
      ADDITIONS (Contributions + Investment Income + Other Additions)
      / DEDUCTIONS / net change / beginning / corrections / ending

Both sub-reports print two fund columns per row. **GASB 84 vintage
drift**: pre-2019-20 shows ('Private Purpose Trust', 'Other Trust');
2019-20+ shows ('Custodial Funds', 'Private Purpose Trust') -- both
NAMES and COLUMN ORDER changed. The parser detects the column mapping
from the presence of 'Custodial' in the page header and normalizes to
canonical fund names ('private_purpose_trust', 'custodial_funds').

Parsing approach mirrors f196_balance_sheet.py:
  - Locate sub-report pages via banner regex.
  - Extract words per page (use_text_flow=True).
  - Group rows by y-tolerance.
  - Filter page-frame rows.
  - Section state machine on uppercase section-header rows
    ('ASSETS:', 'LIABILITIES:', 'NET POSITION:', 'ADDITIONS:',
    'DEDUCTIONS:').
  - Sub-section header rows ('Contributions:', 'Investment Income:',
    'Other Additions:', 'Held in trust for:', 'Restricted for:') are
    consumed as no-ops -- they don't change section state.
  - Column anchors from first row with 2 full values.
  - Item rows: label + up to 2 values. Blank cells emit NULL.
  - TOTAL / summary rows classified by leading keyword.
  - Multi-line labels absorbed via label_buf.
"""

import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_CANONICAL_FUNDS_NEW = ("custodial_funds", "private_purpose_trust")
_CANONICAL_FUNDS_OLD = ("private_purpose_trust", "custodial_funds")

_BANNER_NP_RE = re.compile(
    r"Statement\s+O[fF]\s+Fiduciary\s+Net\s+Position", re.IGNORECASE)
_BANNER_CHG_RE = re.compile(
    r"Statement\s+of\s+Changes\s+in\s+Fiduciary\s+Net\s+Position", re.IGNORECASE)

# Section-header regexes. Sub-section headers (Contributions:, ...) are
# consumed as no-ops; they don't transition state.
_NP_SECTIONS = [
    ("assets",       re.compile(r"^ASSETS:?$", re.IGNORECASE)),
    ("liabilities",  re.compile(r"^LIABILITIES:?$", re.IGNORECASE)),
    ("net_position", re.compile(r"^NET\s+POSITION:?$", re.IGNORECASE)),
]

_CHG_SECTIONS = [
    ("additions",  re.compile(r"^ADDITIONS:?$", re.IGNORECASE)),
    ("deductions", re.compile(r"^DEDUCTIONS:?$", re.IGNORECASE)),
]

# Sub-section headers to consume as no-ops (label-only, don't change state).
_SUBSECTION_HEADER_RE = re.compile(
    r"^(?:Held\s+in\s+trust\s+for:|Restricted\s+for:|"
    r"Contributions:|Investment\s+Income:|Other\s+Additions:)$",
    re.IGNORECASE)

# TOTAL / summary row patterns. Ordering matters -- more specific first.
_NP_TOTAL_PATTERNS = [
    (re.compile(r"^TOTAL\s+ASSETS$", re.IGNORECASE),
     "assets", "total_assets"),
    (re.compile(r"^TOTAL\s+LIABILITIES$", re.IGNORECASE),
     "liabilities", "total_liabilities"),
    (re.compile(r"^TOTAL\s+NET\s+POSITION$", re.IGNORECASE),
     "net_position", "total_net_position"),
]

_CHG_TOTAL_PATTERNS = [
    (re.compile(r"^TOTAL\s+CONTRIBUTIONS$", re.IGNORECASE),
     "additions", "total_contributions"),
    (re.compile(r"^Net\s+Investment\s+Income$", re.IGNORECASE),
     "additions", "net_investment_income"),
    (re.compile(r"^Total\s+Other\s+Additions$", re.IGNORECASE),
     "additions", "total_other_additions"),
    (re.compile(r"^TOTAL\s+ADDITIONS$", re.IGNORECASE),
     "additions", "total_additions"),
    (re.compile(r"^TOTAL\s+DEDUCTIONS$", re.IGNORECASE),
     "deductions", "total_deductions"),
    (re.compile(r"^Net\s+Increase\s*\(Decrease\)$", re.IGNORECASE),
     "summary", "net_increase_decrease"),
    # Beginning balance -- 3 vintages:
    #   2013-14:   'Net Position--Beginning'
    #   2020-21:   'Net Position--Prior Year August Beginning' (GASB 84 transition)
    #   2023-24+:  'Net Position - Beginning Balance'
    (re.compile(r"^Net\s+Position[\s\-]+(?:Prior\s+Year\s+August\s+)?Beginning(?:\s+Balance)?$",
                re.IGNORECASE),
     "summary", "beginning_balance"),
    # GASB 84 transition-year extras (2020-21 only; typically 0.00):
    (re.compile(r"^Prior\s+Year\s+F-196\s+Manual\s+Revision$", re.IGNORECASE),
     "summary", "prior_year_manual_revision"),
    (re.compile(r"^Net\s+Position\s*-\s*Total$", re.IGNORECASE),
     "summary", "intermediate_net_position_total"),
    (re.compile(r"^(?:Prior\s+Year\(s\)\s+Corrections\s+or\s+Restatements|Accounting\s+Changes\s+and\s+Error\s+Corrections)$",
                re.IGNORECASE),
     "summary", "corrections"),
    (re.compile(r"^NET\s+POSITION[\s\-]*ENDING$", re.IGNORECASE),
     "summary", "ending_balance"),
]

# Page-frame rows.
_PAGE_FRAME_PATTERNS = [
    re.compile(r"^REPORT\s+F196\b", re.IGNORECASE),
    re.compile(r"^Washtucna|Seattle|Issaquah\b"),  # matches first-line district header when banner is on line 2
    re.compile(r"^E\.S\.D\.\s+\w+\s+Statement\s+", re.IGNORECASE),
    re.compile(r"^COUNTY:\s+\S+", re.IGNORECASE),
    re.compile(r"^Fiduciary\s+Funds$", re.IGNORECASE),
    re.compile(r"^For\s+the\s+Year\s+Ended", re.IGNORECASE),
    re.compile(r"^August\s+\d+,\s*\d{4}$"),
    re.compile(r"^Page\s+\d+\s+of\s+\d+$", re.IGNORECASE),
    # Column-header rows (variable across vintages)
    re.compile(r"^Private$"),
    re.compile(r"^Custodial\s+Purpose$"),
    re.compile(r"^Funds\s+Trust$"),
    re.compile(r"^Purpose\s+Trust\s+Other\s+Trust$"),
]

_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")

_COL_TOLERANCE = 10.0
_Y_TOLERANCE = 2.0
_MAX_PAGES = 3  # defensive cap; sub-reports are 2 adjacent pages


def parse_f196_fiduciary_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_fiduciary",
    }

    with pdfplumber.open(info.path) as pdf:
        for i, page in enumerate(pdf.pages):
            if i > 30:
                break
            t = page.extract_text() or ""
            first_lines = t.split("\n", 5)[:5]
            header_text = " ".join(first_lines)
            if _BANNER_NP_RE.search(header_text):
                statement = "net_position"
                total_patterns = _NP_TOTAL_PATTERNS
                section_headers = _NP_SECTIONS
            elif _BANNER_CHG_RE.search(header_text):
                statement = "changes"
                total_patterns = _CHG_TOTAL_PATTERNS
                section_headers = _CHG_SECTIONS
            else:
                continue

            words = page.extract_words(use_text_flow=True)
            fund_map = _detect_fund_columns(words)
            if not base["district"]:
                d = _district_from_words(words)
                if d:
                    base["district"] = d
            yield from _parse_page(words, base, statement, section_headers,
                                   total_patterns, fund_map)


def _detect_fund_columns(words) -> tuple:
    """Return the (col_1_fund, col_2_fund) canonical mapping for the page.

    Detected by scanning the first ~10 rows for the token 'Custodial' --
    if present, use the post-GASB-84 order (custodial_funds first,
    private_purpose_trust second). Otherwise use the pre-GASB-84 order
    (private_purpose_trust first, other_trust-aka-custodial second).
    """
    top_words = [w for w in words if w["top"] < 130]
    text = " ".join(w["text"] for w in top_words)
    if re.search(r"Custodial", text, re.IGNORECASE):
        return _CANONICAL_FUNDS_NEW
    return _CANONICAL_FUNDS_OLD


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


def _match_section_header(text: str, section_headers) -> Optional[str]:
    for name, pat in section_headers:
        if pat.match(text):
            return name
    return None


def _match_total_row(text: str, total_patterns):
    for pat, section, code in total_patterns:
        if pat.match(text):
            return (section, code)
    return None


def _slugify(label: str) -> str:
    s = label.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _parse_page(words, base, statement, section_headers, total_patterns,
                fund_map) -> Iterator[dict]:
    rows = _group_rows(words)

    column_anchors: Optional[List[float]] = None
    section: Optional[str] = None
    pending_rows: Optional[List[dict]] = None
    label_buf: List[str] = []

    def flush_suffix():
        nonlocal pending_rows
        if pending_rows and label_buf:
            suffix = " ".join(label_buf).strip()
            if suffix:
                for r in pending_rows:
                    joined = (r["item_label"] + " " + suffix).strip()
                    r["item_label"] = re.sub(r"\s+", " ", joined)
                    if not r["is_total"]:
                        r["item_code"] = _slugify(r["item_label"]) or "unknown"
        label_buf.clear()

    def emit():
        nonlocal pending_rows
        out = pending_rows or []
        pending_rows = None
        return out

    for row in rows:
        text = " ".join(w["text"] for w in row).strip()
        if not text or _is_page_frame(text):
            continue

        # Section header.
        new_section = _match_section_header(text, section_headers)
        if new_section is not None:
            flush_suffix()
            for r in emit():
                yield r
            section = new_section
            continue

        # Sub-section header (no state change).
        if _SUBSECTION_HEADER_RE.match(text):
            flush_suffix()
            for r in emit():
                yield r
            continue

        full_value_words = [w for w in row if _FULL_VALUE_RE.match(w["text"])]
        label_words = [w for w in row
                       if not _FULL_VALUE_RE.match(w["text"])
                       and not _WRAP_FRAGMENT_RE.match(w["text"])]
        label_text = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_words).strip())

        # Pure label continuation.
        if not full_value_words:
            if label_text:
                label_buf.append(label_text)
            continue

        # Establish column anchors from the first 2-value row.
        if column_anchors is None:
            if len(full_value_words) != 2:
                # Defer -- some rows have only 1 value if the other fund's
                # cell is blank. Buffer as label continuation and wait.
                if label_text:
                    label_buf.append(label_text)
                continue
            column_anchors = [w["x1"] for w in full_value_words]

        # Flush + emit previous.
        flush_suffix()
        for r in emit():
            yield r

        # Classify as detail vs summary/TOTAL.
        total_match = _match_total_row(label_text, total_patterns)
        if total_match is not None:
            section_out, item_code = total_match
            is_total = True
        else:
            section_out = section or "unknown"
            item_code = _slugify(label_text) or "unknown"
            is_total = False

        new_rows: List[dict] = []
        for col_idx, anchor in enumerate(column_anchors):
            fund = fund_map[col_idx]
            matched = _closest_value(full_value_words, anchor)
            new_rows.append({
                **base,
                "statement": statement,
                "section": section_out,
                "item_code": item_code,
                "fund": fund,
                "is_total": is_total,
                "item_label": label_text,
                "amount": parse_decimal(matched["text"]) if matched else None,
            })
        pending_rows = new_rows

    flush_suffix()
    for r in emit():
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
