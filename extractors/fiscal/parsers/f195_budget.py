"""Parse OSPI Form F-195 Budget PDFs (and F-195 Budget Overview).

A single F-195 Budget PDF is a 100-200 page compound document with
~30 distinct sub-reports. This parser is structured to grow sub-report
by sub-report; **Phase 1** captures only:

  - SUMMARY OF X FUND BUDGET (one occurrence per fund: General, ASB,
    Debt Service, Capital Projects, Transportation Vehicle).

Each value-bearing line on those pages has 3 trailing numeric tokens
(`Actual <YY-2>`, `Budget <YY-1>`, `Budget <YY>`). The parser emits 3
rows per item (one per data column).

The page title-line drives sub-report detection: only pages whose
title line matches a recognized header are scanned for value lines.
The F-195 Budget Overview also contains these same SUMMARY pages
(pages ~5 through ~39), so this parser runs against both source kinds.
"""

import logging
import re
from typing import Iterator, List, Optional

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, parse_decimal, read_pdf_lines,
)


logger = logging.getLogger(__name__)


# Map page title -> (sub_report, fund). Extend as new sub-reports come online.
_PAGE_TITLE_TO_CONTEXT = {
    "SUMMARY OF GENERAL FUND BUDGET":              ("fund_summary", "general"),
    "SUMMARY OF ASSOCIATED STUDENT BODY FUND BUDGET": ("fund_summary", "asb"),
    "SUMMARY OF DEBT SERVICE FUND BUDGET":         ("fund_summary", "debt_service"),
    "SUMMARY OF CAPITAL PROJECTS FUND BUDGET":     ("fund_summary", "capital_projects"),
    "SUMMARY OF TRANSPORTATION VEHICLE FUND BUDGET": ("fund_summary", "transportation_vehicle"),
}

# Section markers within fund_summary pages.
_SECTION_MARKERS = [
    ("REVENUES AND OTHER FINANCING SOURCES", "revenues"),
    ("REVENUES",                              "revenues"),
    ("EXPENDITURES",                          "expenditures"),
    ("BEGINNING FUND BALANCE",                "beginning_fund_balance"),
    ("ENDING FUND BALANCE",                   "ending_fund_balance"),
]

# Year-column header line. Some vintages use soft-hyphen which is normalized
# to ASCII '-' in common.py.
_YEAR_COLS_RE = re.compile(
    r"^\s*(\d{4}-\d{4})\s+(\d{4}-\d{4})\s+(\d{4}-\d{4})\s*$"
)
# Column-kind header (`Actual Budget Budget`).
_KIND_RE = re.compile(r"^\s*(Actual)\s+(Budget)\s+(Budget)\s*$")

# Item prefix patterns.
# OSPI account code: 2-4 digits, optional `|` separator. Covers revenue codes
# ('1000', '1100', '4499') and expenditure program codes ('00', '10', '20',
# '50 and 60'). TVF expenditure rows omit the `|`.
_OSPI_CODE_RE = re.compile(r"^(\d{2,4}(?:\s+and\s+\d{2,4})?)(?:\s+\|)?\s+(.+)$")
_GL_CODE_RE = re.compile(r"^(G\.L\.\d+)\s+(.+)$")
_SECTION_LETTER_RE = re.compile(r"^([A-Z])\.\s+(.+)$")

# A single value token: optional minus, digits, possibly comma-grouped,
# optional decimal. 'XXXX' / 'XXXXX' marks n/a.
_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$|^XXX+$")

# Page-footer / banner noise lines to ignore.
_FOOTER_RE = re.compile(r"^Form\s+F-195\s+Page\s+\d", re.IGNORECASE)
_FOOTNOTE_LINE_RE = re.compile(r"^\d+/\s")


def _has_trailing_3_values(tokens: List[str]):
    """Return the last 3 tokens if they all look numeric / XXXXX, else None."""
    if len(tokens) < 4:
        return None
    last3 = tokens[-3:]
    if all(_VALUE_TOKEN_RE.match(t) for t in last3):
        return last3
    return None


def _strip_footnote_suffix(label: str) -> str:
    """Drop trailing '1/', '2/', etc. footnote markers."""
    return re.sub(r"\s*\d+/\s*$", "", label).strip()


def _classify_line(label_part: str):
    """Identify (item_code, normalized_label, derived_section) from a label prefix.

    derived_section is 'summary' for section-letter total rows (A./B./.../H.),
    None otherwise (so the caller keeps the active section).
    """
    s = label_part.strip()
    m = _GL_CODE_RE.match(s)
    if m:
        return m.group(1), _strip_footnote_suffix(m.group(2)), None
    m = _SECTION_LETTER_RE.match(s)
    if m:
        return m.group(1), _strip_footnote_suffix(m.group(2)), "summary"
    m = _OSPI_CODE_RE.match(s)
    if m:
        code = m.group(1).strip()
        return code, _strip_footnote_suffix(m.group(2)), None
    label = _strip_footnote_suffix(s)
    return _slugify_label(label), label, None


def _slugify_label(label: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", label.lower()).strip("_")
    return s


def parse_f195_budget_pdf(info: FiscalFilename) -> Iterator[dict]:
    """Yield long-form rows from one F-195 Budget (or Overview) PDF."""
    import pdfplumber

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f195_budget",
    }

    # We walk pages with pdfplumber directly (not read_pdf_lines) so we can
    # see the title on each page and skip non-target sub-reports cheaply.
    from .common import normalize_pdf_text
    with pdfplumber.open(info.path) as pdf:
        # Active sub-report context, persisted across pages of the same sub-report.
        sub_report: Optional[str] = None
        fund: Optional[str] = None
        section: Optional[str] = None
        year_cols: Optional[List[str]] = None
        column_kinds: Optional[List[str]] = None
        last_emitted_rows: Optional[List[dict]] = None
        label_buf: List[str] = []

        def _flush(rows_out):
            nonlocal last_emitted_rows, label_buf
            # Apply post-value label continuation to the last emitted item.
            if last_emitted_rows and label_buf:
                suffix = re.sub(r"\s+", " ", " ".join(label_buf).strip())
                if suffix:
                    for r in last_emitted_rows:
                        r["item_label"] = re.sub(
                            r"\s+", " ",
                            (r["item_label"] + " " + suffix).strip()
                        )
            label_buf = []
            for r in (last_emitted_rows or []):
                rows_out.append(r)
            last_emitted_rows = None

        rows_out: List[dict] = []

        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            raw_lines = [ln for ln in (l.strip() for l in text.split("\n")) if ln]
            # Note: do NOT apply merge_split_leading_digit here. That helper is
            # for 1191SI's column-fragmented dollar values; on F-195 Budget it
            # would wrongly merge adjacent value tokens whenever the preceding
            # value is a single digit (e.g. '... 634 0 4,362,430' would collapse
            # the trailing '0 4,362,430' into a single token '04,362,430' and
            # the line would silently lose its first value).
            lines = [collapse_numeric_paren_spaces(ln) for ln in raw_lines]
            if not lines:
                continue

            # Page title: ordinarily the third non-empty line ('FY YYYY-YYYY Run:...',
            # district, TITLE). On multi-page sub-reports in 2013-14 onwards a
            # 'Continued' line gets inserted between the FY banner and the district
            # name, pushing the title to line 4 (and the district name down). Scan
            # the first 6 lines for a recognized title rather than locking to a
            # fixed index.
            page_title = ""
            title_idx = -1
            for j, ln in enumerate(lines[:6]):
                if ln in _PAGE_TITLE_TO_CONTEXT:
                    page_title = ln
                    title_idx = j
                    break

            # If we leave the active sub-report (different title), flush and reset.
            new_ctx = _PAGE_TITLE_TO_CONTEXT.get(page_title)
            if new_ctx is None:
                # Non-target page. Drop pending label continuation (footnote
                # spillage); flush any emitted rows.
                label_buf = []
                _flush(rows_out)
                sub_report = None
                fund = None
                section = None
                year_cols = None
                column_kinds = None
                continue

            new_sub_report, new_fund = new_ctx
            # District name appears one or two lines above the title (depending
            # on whether a 'Continued' banner is present).
            if not base["district"]:
                for k in range(max(0, title_idx - 2), title_idx):
                    m_dist = re.match(r"^(.*?) School District No\.\d+", lines[k])
                    if m_dist:
                        base["district"] = m_dist.group(1).strip()
                        break

            # If we transition into a new fund / sub_report, flush and reset.
            if new_sub_report != sub_report or new_fund != fund:
                label_buf = []
                _flush(rows_out)
                sub_report = new_sub_report
                fund = new_fund
                section = None
                year_cols = None
                column_kinds = None

            # Per-page state: once we encounter a footnote starter ('1/ ...',
            # '2/ ...'), the rest of the page is footnote text (potentially
            # multi-line, with no continuation marker). Stop accumulating
            # label continuation so it doesn't bleed onto the last emitted item.
            in_footnote_zone = False

            # Walk content lines on this page (skip header lines up through title).
            for ln in lines[title_idx + 1:]:
                # End-of-content footer.
                if _FOOTER_RE.match(ln):
                    continue
                # Standalone footnote text -- enter the footnote zone.
                if _FOOTNOTE_LINE_RE.match(ln):
                    in_footnote_zone = True
                    continue
                if in_footnote_zone:
                    # Subsequent lines of multi-line footnote text; ignore.
                    continue

                # Column kind row (`Actual Budget Budget`).
                m = _KIND_RE.match(ln)
                if m:
                    column_kinds = ["actual", "budget", "budget"]
                    continue

                # Year-column row.
                m = _YEAR_COLS_RE.match(ln)
                if m:
                    year_cols = [m.group(1), m.group(2), m.group(3)]
                    continue

                # Section marker.
                matched_section = None
                for needle, name in _SECTION_MARKERS:
                    if ln == needle:
                        matched_section = name
                        break
                if matched_section is not None:
                    # New section starts: flush any pending rows / continuation.
                    _flush(rows_out)
                    section = matched_section
                    continue

                # Value-bearing line: trailing 3 numeric tokens.
                tokens = ln.split()
                last3 = _has_trailing_3_values(tokens)
                if last3 is None:
                    # Non-value line: skip the column-marker line `(1) (2) (3)`,
                    # treat anything else as a post-value label continuation
                    # (for items whose label wraps across multiple printed lines).
                    if re.match(r"^\(\d\)(\s+\(\d\))+\s*$", ln):
                        continue
                    label_buf.append(ln)
                    continue

                # Value line -- flush any pending continuation onto the previous
                # item, then emit the prior item and start the new one.
                _flush(rows_out)

                if year_cols is None or column_kinds is None or section is None:
                    # Defensive: we landed on a value line before seeing the
                    # year-column header or section marker. Skip rather than
                    # emit bad rows.
                    logger.warning(
                        "%s: value line before context (year_cols=%s "
                        "section=%s): %r",
                        info.path.name, year_cols, section, ln,
                    )
                    continue

                label_part = " ".join(tokens[:-3]).strip()
                if not label_part:
                    continue
                item_code, item_label, derived_section = _classify_line(label_part)
                # For section-letter total rows (A./B./...), tag the row as
                # 'summary' so totals don't collide on item_code with sibling
                # items in the surrounding section.
                row_section = "summary" if derived_section == "summary" else section

                rows = []
                for offset, (year, kind, vtext) in enumerate(
                    zip(year_cols, column_kinds, last3)
                ):
                    value = None if vtext.startswith("XXX") else parse_decimal(vtext)
                    rows.append({
                        **base,
                        "sub_report": sub_report,
                        "fund": fund,
                        "section": row_section,
                        "item_code": item_code,
                        "data_year_offset": offset - 2,  # -2, -1, 0
                        "data_school_year": year,
                        "data_class_of": int(year.split("-")[1]),
                        "column_kind": kind,
                        "item_label": item_label,
                        "value": value,
                        "value_text": vtext,
                    })
                last_emitted_rows = rows

            # End of page: drop any unapplied wrap continuation. fund_summary
            # value labels don't wrap across page boundaries (only within a
            # page) -- anything left in label_buf at this point is either
            # footnote text or an unrecognized line.
            label_buf = []

        # End of document: flush.
        _flush(rows_out)

    # Dedup by logical key: a value-bearing item code may appear on multiple
    # pages of the same sub-report (page boundaries). Last write wins.
    # In practice the SUMMARY pages don't repeat items across pages; this
    # is a defensive measure for robust ingestion.
    seen = {}
    for r in rows_out:
        key = (r["sub_report"], r["fund"], r["section"],
               r["item_code"], r["data_year_offset"])
        seen[key] = r
    for r in seen.values():
        yield r


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
