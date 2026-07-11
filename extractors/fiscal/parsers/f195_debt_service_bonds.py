"""Parse the `DEBT SERVICE FUND BUDGET DETAIL OF OUTSTANDING BONDS`
sub-report (DS4) of OSPI Form F-195 Budget.

Layout:
  A. VOTED BONDS
    <MM-DD-YYYY> <amount_original> <amount_outstanding>
    ...
    TOTAL VOTED BONDS <sum_original> <sum_outstanding>
  B. NONVOTED BONDS
    <MM-DD-YYYY> <amount_original> <amount_outstanding>
    ...
    TOTAL NONVOTED BONDS <sum_original> <sum_outstanding>
  TOTAL ALL BONDS <combined_original> <combined_outstanding>

Sections may be empty (no per-bond detail rows). All-uppercase phrases
`A. VOTED BONDS` and `B. NONVOTED BONDS` are the section markers.

Simple text-line parsing suffices -- the 2-value cross-tab has no
XXXXX / blank-cell ambiguity, and every row's leading label is
distinct enough to disambiguate (a date pattern for detail rows,
`TOTAL ...` for total rows).
"""

import logging
import re
from typing import Iterator, List, Optional

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, parse_decimal, normalize_pdf_text,
)


logger = logging.getLogger(__name__)


_TITLE = "DEBT SERVICE FUND BUDGET DETAIL OF OUTSTANDING BONDS"

_SECTION_A_RE = re.compile(r"^A\.\s+VOTED\s+BONDS\s*$", re.IGNORECASE)
_SECTION_B_RE = re.compile(r"^B\.\s+NONVOTED\s+BONDS\s*$", re.IGNORECASE)
_TOTAL_A_RE = re.compile(r"^TOTAL\s+VOTED\s+BONDS\b", re.IGNORECASE)
_TOTAL_B_RE = re.compile(r"^TOTAL\s+NONVOTED\s+BONDS\b", re.IGNORECASE)
_TOTAL_ALL_RE = re.compile(r"^TOTAL\s+ALL\s+BONDS\b", re.IGNORECASE)

# Detail row: date + 2 numeric values. Bond issue date is printed as
# MM-DD-YYYY (some 2013-14 files use MM/DD/YYYY -- accept both).
_DATE_RE = re.compile(r"^(\d{2}[-/]\d{2}[-/]\d{4})$")
_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$")

# Header rows to skip.
_HEADER_LINES_SUBSTRINGS = (
    "Date of Issue",
    "Amount of Original Issue",
    "Amount of Orignal Issue",  # 2013-14 typo
    "Estimated Amount Outstanding",
    "September 1",
)
_FOOTER_RE = re.compile(r"^Form\s+F-195\s+Page\s+\d", re.IGNORECASE)
_FOOTNOTE_RE = re.compile(r"^\d+/\s")


def _parse_value(vtext):
    if not vtext:
        return None
    return parse_decimal(vtext)


def _last_n_values(tokens: List[str], n: int) -> Optional[List[str]]:
    if len(tokens) < n:
        return None
    last = tokens[-n:]
    if all(_VALUE_TOKEN_RE.match(t) for t in last):
        return last
    return None


def parse_f195_debt_service_bonds_pdf(info: FiscalFilename) -> Iterator[dict]:
    """Yield DS4 rows for one F-195 Budget PDF."""
    import pdfplumber

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f195_debt_service_bonds",
    }

    rows_out: List[dict] = []
    section: Optional[str] = None
    section_seq = 0
    entered = False
    in_footnote = False

    with pdfplumber.open(info.path) as pdf:
        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            if _TITLE not in text:
                if entered:
                    break
                continue
            entered = True

            raw_lines = [ln for ln in
                         (l.strip() for l in text.split("\n")) if ln]
            lines = [collapse_numeric_paren_spaces(ln) for ln in raw_lines]

            # District name (once).
            for j, ln in enumerate(lines[:6]):
                if ln == _TITLE:
                    for k in range(max(0, j - 2), j):
                        m = re.match(
                            r"^(.*?) School District No\.?\s*\d+",
                            lines[k]
                        )
                        if m:
                            base["district"] = m.group(1).strip()
                            break
                    break

            in_footnote = False
            for ln in lines:
                if ln == _TITLE:
                    continue
                if _FOOTER_RE.match(ln):
                    continue
                if _FOOTNOTE_RE.match(ln):
                    in_footnote = True
                    continue
                if in_footnote:
                    continue
                if any(hs in ln for hs in _HEADER_LINES_SUBSTRINGS):
                    continue

                # Section markers.
                if _SECTION_A_RE.match(ln):
                    section = "voted_bonds"; section_seq = 0
                    continue
                if _SECTION_B_RE.match(ln):
                    section = "nonvoted_bonds"; section_seq = 0
                    continue

                # Strip trailing footnote markers (` 2/`, ` 4/`) from
                # TOTAL rows before extracting the trailing 2 values.
                ln_stripped = re.sub(r"\s+\d+/\s*$", "", ln)

                # TOTAL rows.
                if _TOTAL_A_RE.match(ln_stripped):
                    tail = _last_n_values(ln_stripped.split(), 2)
                    if tail is not None:
                        rows_out.append(_mk_row(
                            base, "voted_bonds", 0, True,
                            None, tail[0], tail[1],
                        ))
                    continue
                if _TOTAL_B_RE.match(ln_stripped):
                    tail = _last_n_values(ln_stripped.split(), 2)
                    if tail is not None:
                        rows_out.append(_mk_row(
                            base, "nonvoted_bonds", 0, True,
                            None, tail[0], tail[1],
                        ))
                    continue
                if _TOTAL_ALL_RE.match(ln_stripped):
                    tail = _last_n_values(ln_stripped.split(), 2)
                    if tail is not None:
                        rows_out.append(_mk_row(
                            base, "summary", 0, True,
                            None, tail[0], tail[1],
                        ))
                    continue

                # Detail row: (optional date) + 2 values. Common case
                # is `MM-DD-YYYY <original> <outstanding>`; a small
                # number of files (~4) omit the date and print just
                # `<original> <outstanding>` -- treat those as detail
                # rows with `date_of_issue=NULL` as long as we're in
                # section A or B.
                if section is None:
                    continue
                tokens = ln.split()
                if len(tokens) < 2:
                    continue
                date_tok = None
                if _DATE_RE.match(tokens[0]) and len(tokens) >= 3:
                    date_tok = tokens[0]
                # For dateless rows, require exactly 2 tokens (2 values)
                # to avoid mis-classifying labels or wrap rows.
                elif len(tokens) != 2:
                    continue
                tail = _last_n_values(tokens, 2)
                if tail is None:
                    continue
                section_seq += 1
                rows_out.append(_mk_row(
                    base, section, section_seq, False,
                    date_tok, tail[0], tail[1],
                ))

    # Dedup by logical key.
    seen = {}
    for r in rows_out:
        seen[(r["section"], r["item_seq"])] = r
    for r in seen.values():
        yield r


def _mk_row(base, section, seq, is_total, date, amt_orig, amt_out):
    return {
        **base,
        "section": section,
        "item_seq": seq,
        "is_total": is_total,
        "date_of_issue": date,
        "amount_original": _parse_value(amt_orig),
        "amount_outstanding": _parse_value(amt_out),
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
