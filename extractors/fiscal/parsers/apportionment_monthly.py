"""Parse page 1 of an OSPI monthly Statement of Apportionment PDF.

Page 1 lists one row per OSPI revenue account, with up to six numeric
columns:
  A. Annual Allotment
  B. Adjustment in Allotment (Previous/Current Year)
  C. Percent Due
  D. Allot Due  (= C*A + B)
  E. Paid Previously
  F. Allotment for <Month>  (the headline payment for the month)

Each row starts with a 4-7 digit revenue account code or one of the
sentinel labels 'Totals' / 'General Fund Only Total'. Descriptions
frequently wrap across 2-4 source lines; the parser buffers
continuations.

Not all rows print all six columns. The Totals row prints five values
in (A, B, D, E, F) order (no Percent Due since percentages don't sum).
'Allocation' / 'SUMMER' rows often print four values (A, B, C, D) when
E and F are both zero. The parser assigns values left-to-right and
NULLs the missing trailing columns -- consumers should treat NULL as
'not applicable' here, not as 'unknown'.
"""

import logging
import re
from typing import Iterator, List, Optional

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, is_na, merge_split_leading_digit,
    parse_decimal, read_pdf_lines,
)


logger = logging.getLogger(__name__)


MONTHS = ("September", "October", "November", "December",
          "January", "February", "March", "April",
          "May", "June", "July", "August")
_MONTH_SEQ = {m: i + 1 for i, m in enumerate(MONTHS)}

_LEAF_MONTH_RE = re.compile(r"\bfor\s+(" + "|".join(MONTHS) + r")$", re.IGNORECASE)

_TABLE_START_RE = re.compile(r"^Revenue\s+Description\s+Annual\b", re.IGNORECASE)
_TABLE_END_RE = re.compile(r"^Page\s+1\s+of\b", re.IGNORECASE)

_HEADER_TO_RE = re.compile(r"^To:?\s*(.+?)\s*$")
_HEADER_DATE_RE = re.compile(
    r"Apportionment\s+for\s+(\w+\s*,?\s*\d+\s+\d{4})", re.IGNORECASE,
)
_HEADER_CCDDD_RE = re.compile(r"^CCDDD\s+(\d{3,5})\s*$")

# A value token must contain a decimal point so we don't accidentally
# treat account codes (e.g. '4499') or year-fragments as values.
_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
_CODE_RE = re.compile(r"^\d{2,7}$")


def parse_apportionment_monthly_pdf(info: FiscalFilename) -> Iterator[dict]:
    # Page 1 carries everything we capture; the rest of the PDF (the
    # 40+ page Estimated Funding Report) is per-account derivation
    # detail we don't currently extract. Reading only page 1 is ~10-20x
    # faster than reading the full doc.
    raw_lines = read_pdf_lines(info.path, max_pages=1)
    lines = [collapse_numeric_paren_spaces(merge_split_leading_digit(ln))
             for ln in raw_lines]

    # Determine org_type for the fact row.
    if info.org_type == "district":
        org_type = "district"
    elif info.org_type == "college":
        org_type = "college"
    elif info.org_type == "state_agency":
        org_type = "state_agency"
    elif info.org_type == "esd":
        # ESD-level monthly file (the walker must have deduped these so we
        # see each unique file once). The path's ccddd is the parent member-
        # district's code; the body's CCDDD is the ESD's own. We override
        # `base['ccddd']` from the body below.
        org_type = "esd"
    else:
        return

    # Month from filename leaf (e.g. 'Apportionment for September').
    m = _LEAF_MONTH_RE.search(info.leaf)
    month = m.group(1).capitalize() if m else ""
    month_seq = _MONTH_SEQ.get(month, 0)

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "org_type": org_type,
        "month": month,
        "month_seq": month_seq,
        "report_date_text": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_apportionment_monthly",
    }

    # Header scan -- recipient name + report date + body CCDDD (for cross-check).
    body_ccddd: Optional[int] = None
    for ln in lines[:20]:
        if not base["district"]:
            m = _HEADER_TO_RE.match(ln)
            if m and not ln.startswith("Total"):
                base["district"] = m.group(1).strip()
        if not base["report_date_text"]:
            m = _HEADER_DATE_RE.search(ln)
            if m:
                base["report_date_text"] = m.group(1).strip()
        if body_ccddd is None:
            m = _HEADER_CCDDD_RE.match(ln)
            if m:
                body_ccddd = int(m.group(1))

    # For ESD-level files the path-derived ccddd is the parent member-
    # district's code (an artifact of how the OSPI source replicates the
    # same file under every member-district subdir). Override with the
    # body's CCDDD, which is the ESD's own code (e.g. 17801 for ESD 121).
    if org_type == "esd" and body_ccddd is not None:
        base["ccddd"] = body_ccddd

    # Table body parsing.
    in_table = False
    label_buf: List[str] = []
    last_row: Optional[dict] = None

    def _flush_post_to(row):
        if not row or not label_buf:
            label_buf.clear()
            return
        suffix = " ".join(label_buf).strip()
        label_buf.clear()
        if not suffix:
            return
        row["revenue_description"] = re.sub(
            r"\s+", " ", (row["revenue_description"] + " " + suffix).strip()
        )

    for ln in lines:
        if not in_table:
            if _TABLE_START_RE.match(ln):
                in_table = True
            continue
        if _TABLE_END_RE.match(ln):
            _flush_post_to(last_row)
            if last_row is not None:
                yield last_row
                last_row = None
            break

        tokens = ln.split()
        if not tokens:
            continue
        classification = _classify_row(tokens)
        if classification is None:
            # Continuation of the previous row's description.
            if last_row is not None:
                label_buf.append(ln.strip())
            continue

        _flush_post_to(last_row)
        if last_row is not None:
            yield last_row

        code, desc_tokens, value_tokens = classification
        description = " ".join(desc_tokens).strip()
        last_row = _build_row(base, code, description, value_tokens)

    _flush_post_to(last_row)
    if last_row is not None:
        yield last_row


def _classify_row(tokens: List[str]):
    """Return (code, description_tokens, value_tokens) or None for a continuation."""
    first = tokens[0]
    if _CODE_RE.match(first):
        code = first
        rest = tokens[1:]
    elif first == "Totals":
        code = "TOTALS"
        rest = tokens[1:]
    elif (len(tokens) >= 4 and tokens[0] == "General"
          and tokens[1] == "Fund" and tokens[2] == "Only" and tokens[3] == "Total"):
        code = "GENERAL_FUND_ONLY_TOTAL"
        rest = tokens[4:]
    else:
        return None
    desc_tokens: List[str] = []
    value_tokens: List[str] = []
    in_values = False
    for t in rest:
        if not in_values and _VALUE_RE.match(t):
            in_values = True
        if in_values:
            if _VALUE_RE.match(t):
                value_tokens.append(t)
            # else: ignore trailing text after the value block
        else:
            desc_tokens.append(t)
    return code, desc_tokens, value_tokens


def _build_row(base: dict, code: str, description: str, value_tokens: List[str]) -> dict:
    """Map raw value tokens to the six labeled columns (A-F).

    Most rows print 6 values in order (A, B, C, D, E, F).
    'Totals' rows print 5 values in (A, B, D, E, F) order (no Percent Due).
    'General Fund Only Total' prints 1 trailing value -- stored on D (allot_due).
    Sparse rows (e.g. SUMMER ALLOCATION) print fewer; assign left-to-right
    and NULL the missing trailing columns.
    """
    ann = adj = pct = due = paid = mth = None
    n = len(value_tokens)
    if code == "TOTALS" and n == 5:
        ann, adj, due, paid, mth = value_tokens
    elif code == "GENERAL_FUND_ONLY_TOTAL" and n >= 1:
        due = value_tokens[-1]
    elif n == 6:
        ann, adj, pct, due, paid, mth = value_tokens
    elif n == 5:
        ann, adj, pct, due, paid = value_tokens
    elif n == 4:
        ann, adj, pct, due = value_tokens
    elif n == 3:
        ann, adj, pct = value_tokens
    elif n == 2:
        ann, adj = value_tokens
    elif n == 1:
        ann = value_tokens[0]
    return {
        **base,
        "revenue_account": code,
        "revenue_description": description,
        "annual_allotment": parse_decimal(ann) if ann else None,
        "adjustment_allotment": parse_decimal(adj) if adj else None,
        "percent_due": parse_decimal(pct) if pct else None,
        "allot_due": parse_decimal(due) if due else None,
        "paid_previously": parse_decimal(paid) if paid else None,
        "allotment_for_month": parse_decimal(mth) if mth else None,
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
