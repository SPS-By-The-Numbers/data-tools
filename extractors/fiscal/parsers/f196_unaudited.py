"""Parse the REPORT F-196 SUMMARY block from F-196 Unaudited PDFs.

Each F-196 Unaudited PDF is a ~28-page year-end financial statement
filed in mid-December before the audit. Page 2 carries the F-196
SUMMARY -- a 7-fund x 7-item matrix that's identical in shape to the
audited 'F-196 Summary' standalone doc parsed by `f196_summary.py`,
but with one twist: the older form leaves cells truly blank when the
fund/item combination doesn't apply (most commonly 'Other Financing
Uses' for ASB / Permanent), instead of filling with explicit 0.00.

The cell-blanking breaks the trailing-7-tokens heuristic
`f196_summary.py` uses (when a row has 5 instead of 7 values, the
parser snaps to the wrong column). This parser uses positional
extraction (`extract_words()` -> bin by right-edge x1) instead.

The page 2 SUMMARY block always has Prior Year(s) Corrections as a
fully-populated 7-column row, which we use as the column anchor.
Subsequent missing cells emit `value=NULL` rather than corrupting the
column alignment.
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

_ITEM_CODES = [
    "total_revenues_and_other_financing_sources",
    "total_expenditures",
    "other_financing_uses",
    "excess_of_revenues_over_expenditures",
    "beginning_total_fund_balance",
    "corrections_or_restatements",
    "ending_total_fund_balance",
]

_HEADER_RE = re.compile(r"REPORT\s+F-196\s+SUMMARY", re.IGNORECASE)
_END_RE = re.compile(r"^(Locked\s+Date|Not\s+Locked|Page\s+\d+\s+of\s+\d+)", re.IGNORECASE)
_NUMERIC_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$")

# Maximum horizontal distance from a value's right edge to a column anchor
# for the value to be assigned to that column. The columns are ~80pt apart;
# 6pt is conservative.
_COL_TOLERANCE = 6.0

# y-tolerance for grouping words into logical rows. The 'Beginning Total
# Fund Balance' label and its value row are ~1pt apart in the PDF;
# 2pt is enough to merge them without collapsing adjacent items.
_Y_TOLERANCE = 2.0


def parse_f196_unaudited_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_unaudited_summary",
    }

    with pdfplumber.open(info.path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            if not words:
                continue
            if not any(_HEADER_RE.search(w["text"]) for w in words):
                # Header is multi-word ('REPORT', 'F-196', 'SUMMARY'); check
                # the joined page text instead.
                joined = " ".join(w["text"] for w in words)
                if not _HEADER_RE.search(joined):
                    continue

            district = _district_from_words(words)
            if district:
                base["district"] = district

            yield from _parse_summary_page(words, base)
            return


def _district_from_words(words) -> Optional[str]:
    """Pull the district name from the 'REPORT F196 <name> No. NNN' banner.

    The banner is the first row of page 2; words are space-separated so we
    just scan the joined text for the regex.
    """
    text = " ".join(w["text"] for w in words[:30])
    m = re.search(r"REPORT\s+F196\s+(.+?)\s+No\.\s*\d+", text, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _group_rows(words, y_tol=_Y_TOLERANCE) -> List[List[dict]]:
    """Group words into logical rows by y-position (with tolerance).

    pdfplumber's `extract_words()` does not merge near-aligned baselines on
    its own, and the F-196 Summary block has at least one value row whose
    values render 1pt above the label (Beginning Total Fund Balance).
    """
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


def _parse_summary_page(words, base) -> Iterator[dict]:
    rows = _group_rows(words)

    # Locate the REPORT F-196 SUMMARY header row.
    header_idx = None
    for i, row in enumerate(rows):
        text = " ".join(w["text"] for w in row)
        if _HEADER_RE.search(text):
            header_idx = i
            break
    if header_idx is None:
        return

    column_anchors: Optional[List[float]] = None
    position = 0
    label_buf: List[str] = []
    # `pending_rows` holds the most-recently-emitted item's rows so that any
    # label-only lines between this and the NEXT value row can be appended to
    # its label as a suffix (multi-line item names like "Total Revenues and
    # Other Financing / Sources" wrap that way on the form).
    pending_rows: Optional[List[dict]] = None

    def _flush_suffix_into_pending():
        nonlocal pending_rows
        if pending_rows and label_buf:
            suffix = " ".join(label_buf).strip()
            if suffix:
                for r in pending_rows:
                    joined = (r["item_label"] + " " + suffix).strip()
                    r["item_label"] = re.sub(r"\s+", " ", joined)
        label_buf.clear()

    for row in rows[header_idx + 1:]:
        if position >= len(_ITEM_CODES):
            break

        text = " ".join(w["text"] for w in row).strip()
        if _END_RE.match(text):
            break

        numeric_words = [w for w in row if _NUMERIC_TOKEN_RE.match(w["text"])]
        label_words = [w for w in row if not _NUMERIC_TOKEN_RE.match(w["text"])]
        label_text = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_words).strip())

        if not numeric_words:
            if label_text:
                label_buf.append(label_text)
            continue

        if column_anchors is None:
            if len(numeric_words) != len(_FUND_ORDER):
                logger.warning(
                    "first F-196 SUMMARY value row has %d values, expected %d "
                    "(file: %s); skipping",
                    len(numeric_words), len(_FUND_ORDER), base["_source"],
                )
                return
            column_anchors = [w["x1"] for w in numeric_words]

        # Suffix lines accumulated since the previous value row belong to the
        # previous item. Flush them into pending_rows, then emit pending_rows.
        _flush_suffix_into_pending()
        if pending_rows:
            yield from pending_rows
            pending_rows = None

        full_label = label_text  # in-row label is the new item's prefix
        item_code = _ITEM_CODES[position]
        position += 1

        new_rows: List[dict] = []
        for col_idx, anchor in enumerate(column_anchors):
            fund = _FUND_ORDER[col_idx]
            matched = _closest_value(numeric_words, anchor)
            if matched is None:
                new_rows.append({
                    **base,
                    "item_code": item_code,
                    "fund": fund,
                    "item_label": full_label,
                    "value": None,
                    "value_text": "",
                })
            else:
                new_rows.append({
                    **base,
                    "item_code": item_code,
                    "fund": fund,
                    "item_label": full_label,
                    "value": parse_decimal(matched["text"]),
                    "value_text": matched["text"],
                })
        pending_rows = new_rows

    # Flush trailing suffix and final pending rows.
    _flush_suffix_into_pending()
    if pending_rows:
        yield from pending_rows


def _closest_value(numeric_words, anchor) -> Optional[dict]:
    best = None
    best_d = _COL_TOLERANCE
    for w in numeric_words:
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
