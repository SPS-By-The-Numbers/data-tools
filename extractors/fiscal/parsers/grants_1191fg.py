"""Parse one OSPI Report 1191FG Grants Administration PDF.

The form is a multi-page recipient-keyed report listing every grant
under active administration plus per-funding-line detail. See
`schemas/grants_1191fg.py` for the structure summary.

Output is long-form -- one row per printed line that carries the four
financial columns (funding / paid_adj / curr_paymt / balance):
  - section='grant_detail' for each per-(proj, pom, obj_sub) row.
  - section='grant_total' for the GRANT TOTAL line at the end of a
    grant block.
  - section='district_total' for the closing DISTRICT TOTALS line.

Special cases the parser absorbs:
  - Banner repeats every page (7 lines), including a column-header
    line ('PROJ POM OBJ/SUB FUNDING PAID/ADJ CURR PAYMT BALANCE').
    Skipped except for the first occurrence.
  - Recipient identifier line wraps when the recipient name is long
    ('SEATTLE PUBLIC' on one line then 'SCHOOLS' on the next).
  - 2013-14 grants embed the period in the description (no separate
    period token). The parser leaves `grant_period` blank in that
    case.
  - College and state_agency files in this corpus are header-only --
    they produce 0 rows by design.
"""

import logging
import re
from typing import Iterator, List, Optional, Tuple

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, merge_split_leading_digit,
    parse_decimal, read_pdf_lines,
)


logger = logging.getLogger(__name__)


_LEAF_RE = re.compile(r"^1191FG\s+Grants\s+Administration$", re.IGNORECASE)

# Header / banner detection.
_REPORT_DATE_RE = re.compile(
    r"GRANTS\s+ADMINISTRATIONS?\s+FOR\s+(\S+)", re.IGNORECASE,
)
_RECIPIENT_RE = re.compile(r"\bDISTRICT\s+NO\.\s+(\d{3,5})\b")

_BANNER_LINES_RE = re.compile(
    r"^(REPORT\s+1191FG|SUPERINTENDENT\s+OF\s+PUBLIC\s+INSTRUCTION|"
    r"GRANTS\s+ADMINISTRATIONS?\s+FOR|DISTRICT\s+PAYMENTS|"
    r"PROJ\s+POM\s+OBJ/SUB|PAGE\s+\d+\s+OF\s+\d+)",
    re.IGNORECASE,
)

# Top-of-grant header. The closing token is always OPEN or CLOSED;
# the token before it (if all-digit 2-4 char) is the grant period.
# Description is optional -- a handful of grants in the corpus print
# only id+code+status (e.g. 'GRANT 0654132 SCHSUCCESS OPEN'). Failing
# to match those caused their detail rows to be misattributed to the
# preceding grant.
_GRANT_HEADER_RE = re.compile(
    r"^GRANT\s+(\S+)\s+(\S+?)(?:\s+(.*?))?\s+(OPEN|CLOSED)\s*$",
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(r"^\d{2,4}$")

# REV / EXPEND line: "REV 6146 EXPEND 7,439.82"
_REV_EXPEND_RE = re.compile(
    r"^REV\s+(\S+)\s+EXPEND\s+([\d,]+(?:\.\d+)?|-)\s*$",
    re.IGNORECASE,
)

_GRANT_TOTAL_RE = re.compile(r"^GRANT\s+TOTAL\b", re.IGNORECASE)
_DISTRICT_TOTAL_RE = re.compile(r"^DISTRICT\s+TOTALS?\b", re.IGNORECASE)

# A numeric value token on a detail / total row. Allows comma-grouped
# decimals, bare decimals, integers, and the '-' null marker.
_VALUE_TOKEN_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$|^-$")


def parse_grants_1191fg_pdf(info: FiscalFilename) -> Iterator[dict]:
    if not _LEAF_RE.match(info.leaf):
        return

    raw_lines = read_pdf_lines(info.path)
    lines = [collapse_numeric_paren_spaces(merge_split_leading_digit(ln))
             for ln in raw_lines]

    report_date_text = ""
    body_ccddd: Optional[int] = None
    for ln in lines[:30]:
        if not report_date_text:
            m = _REPORT_DATE_RE.search(ln)
            if m:
                report_date_text = m.group(1).strip()
        if body_ccddd is None:
            m = _RECIPIENT_RE.search(ln)
            if m:
                body_ccddd = int(m.group(1))
        if report_date_text and body_ccddd is not None:
            break

    org_type = info.org_type or ""
    ccddd = info.ccddd if info.ccddd is not None else 0
    if org_type == "esd" and body_ccddd is not None:
        # ESD files live under apportionment/<year>/esd/<esd>/<member>/
        # and replicate per member; the body CCDDD is the ESD's own.
        ccddd = body_ccddd

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": ccddd,
        "county": "",
        "district": "",
        "org_type": org_type,
        "report_date_text": report_date_text,
        "_source": _source_path(info.path),
        "_source_table": "fiscal_1191fg_grants",
    }

    # Per-grant context updated as we walk the grant blocks.
    grant_ctx: dict = {}
    grant_seq = 0

    i = 0
    while i < len(lines):
        ln = lines[i]
        if _BANNER_LINES_RE.match(ln):
            i += 1
            continue

        m = _GRANT_HEADER_RE.match(ln)
        if m:
            grant_seq += 1
            project_id = m.group(1)
            project_code = m.group(2)
            middle = (m.group(3) or "").strip()
            status = m.group(4).upper()
            # Period is the trailing token of `middle` if all-digit 2-4 chars.
            period = ""
            description = middle
            tail = middle.rsplit(None, 1)
            if len(tail) == 2 and _PERIOD_RE.match(tail[1]):
                description = tail[0]
                period = tail[1]
            grant_ctx = {
                "grant_seq": grant_seq,
                "project_id": project_id,
                "project_code": project_code,
                "project_description": description,
                "grant_period": period,
                "grant_status": status,
                "revenue_account": "",
                "prior_expend": None,
            }
            i += 1
            continue

        m = _REV_EXPEND_RE.match(ln)
        if m and grant_ctx:
            grant_ctx["revenue_account"] = m.group(1).strip()
            grant_ctx["prior_expend"] = parse_decimal(m.group(2))
            i += 1
            continue

        if _DISTRICT_TOTAL_RE.match(ln):
            tokens = ln.split()
            value_toks = [t for t in tokens if _VALUE_TOKEN_RE.match(t)]
            if len(value_toks) >= 4:
                yield {
                    **base,
                    **_empty_grant_ctx(),
                    "section": "district_total",
                    "grant_seq": 0,
                    **_amounts(value_toks[:4]),
                }
            i += 1
            continue

        if _GRANT_TOTAL_RE.match(ln) and grant_ctx:
            tokens = ln.split()
            value_toks = [t for t in tokens if _VALUE_TOKEN_RE.match(t)]
            if len(value_toks) >= 4:
                yield {
                    **base,
                    **grant_ctx,
                    "section": "grant_total",
                    "proj": "",
                    "pom": "",
                    "obj_sub": "",
                    **_amounts(value_toks[:4]),
                }
            i += 1
            continue

        # Otherwise: a grant detail row OR something to skip.
        # Detail row shape: '<proj> <pom> <obj_sub> <v1> <v2> <v3> <v4>'
        # where the last 4 tokens are numeric values.
        if grant_ctx:
            tokens = ln.split()
            if len(tokens) >= 7:
                values = tokens[-4:]
                if all(_VALUE_TOKEN_RE.match(t) for t in values):
                    head = tokens[:-4]
                    if len(head) >= 3:
                        # The first three head tokens are proj / pom / obj_sub.
                        # If the header has more than 3 tokens, fold the rest
                        # into obj_sub (haven't seen this in the corpus, but
                        # defensive against multi-word obj_sub codes).
                        proj, pom = head[0], head[1]
                        obj_sub = " ".join(head[2:])
                        yield {
                            **base,
                            **grant_ctx,
                            "section": "grant_detail",
                            "proj": proj,
                            "pom": pom,
                            "obj_sub": obj_sub,
                            **_amounts(values),
                        }
                        i += 1
                        continue
        i += 1


def _empty_grant_ctx() -> dict:
    return {
        "grant_seq": 0,
        "project_id": "",
        "project_code": "",
        "project_description": "",
        "grant_period": "",
        "grant_status": "",
        "revenue_account": "",
        "prior_expend": None,
    }


def _amounts(value_toks: List[str]) -> dict:
    return {
        "funding": parse_decimal(value_toks[0]),
        "paid_adj": parse_decimal(value_toks[1]),
        "curr_paymt": parse_decimal(value_toks[2]),
        "balance": parse_decimal(value_toks[3]),
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
