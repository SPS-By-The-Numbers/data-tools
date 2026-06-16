"""Parse one OSPI Form F-483 Nonhigh Billing Summary PDF.

The form is a single-page report filed in two flavors:

  - F-483N: focal district is a nonhigh (K-8) district that sends
    students to one or more serving high districts.
  - F-483H: focal district is a serving high district that receives
    students from one or more sending nonhigh districts.

Form layout drifted at the 2019-20 statutory rewrite (RCW 28A.545.030
added the "lesser of either rate" provision). Both layouts share the
same per-line-item long-form output:

  - section='levy_per_aafte' captures the per-district levy / AAFTE
    calculation (items A-E on the form).
  - section='payable' captures the per-counterparty payable / billing
    calculation (items F-I in the pre-2019 form, F-J in the post-2019
    form).
  - section='payable_total' captures the Total row at the bottom of the
    payable section.

Column-letter assignments are NOT stable across the 2019 rewrite (e.g.
the levy in dollars moved from column A to column D; the May Billing
moved from column H to column I), so `item_code` uses a semantic slug
(`payable_levy`, `may_payable`, etc.) rather than the printed letter.
The printed letter is preserved in `item_label` for traceability.
"""

import logging
import re
from typing import Iterator, List, Optional

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, merge_split_leading_digit,
    parse_decimal, read_pdf_lines,
)


logger = logging.getLogger(__name__)


_LEAF_RE = re.compile(r"^Non-?High\s+Billing$", re.IGNORECASE)

_REPORT_KIND_RE = re.compile(r"REPORT\s+F-?483([NH])\b", re.IGNORECASE)
_TITLE_STATUS_RE = re.compile(
    r"\b(FINAL|INITIAL)\s+\d{4}-\d{2,4}\s+NONHIGH\s+BILLING\s+SUMMARY\b",
    re.IGNORECASE,
)
# Focal district header — three variants seen across the corpus:
#   "NON HIGH DISTRICT: 36101 DIXIE SCHOOL DISTRICT"      (post-2018 F-483N)
#   "SERVING HIGH DISTRICT: 21232 WINLOCK SCHOOL DISTRICT" (post-2018 F-483H)
#   "SUMMARY FOR: 27343 DIERINGER SCHOOL DISTRICT"         (pre-2018 F-483N)
_FOCAL_HEADER_RE = re.compile(
    r"^(?:NON\s*HIGH\s+DISTRICT|SERVING\s+HIGH\s+DISTRICT|SUMMARY\s+FOR):\s*"
    r"(\d{5})\s+(.+?)\s*$",
    re.IGNORECASE,
)

_LEVY_BANNER_RE = re.compile(r"^LEVY\s+PER\s+RESIDENT", re.IGNORECASE)
_PAYABLE_BANNER_RE = re.compile(r"^(PAYABLE|BILLABLE)\s+CALCULATION\b", re.IGNORECASE)

_END_RE = re.compile(
    r"^(SOURCES|COMMENTS\s+ON\s+REPORT|Data\s+in\s+columns)\b",
    re.IGNORECASE,
)

_LETTER_TOKEN_RE = re.compile(r"^([A-J])\.$")
_HEADER_LINE_RE = re.compile(r"^([A-J])\.\s+(\S.*?)\s+(\S+)\s*$")
_DISTRICT_CODE_RE = re.compile(r"^\d{5}$")
_TOTAL_ROW_RE = re.compile(r"^Totals?\b")

# Subject-role label lines. The new-form blocks print
#   "Nonhigh District [D ÷ C]" or "High District [D ÷ C]"
# right above the data rows. The old-form column-header sublines
# ("NONHIGH DISTRICT SENT YEAR BILLING ...") happen to match the same
# pattern, which is fine: they tag the right subject_role too.
_NONHIGH_LABEL_RE = re.compile(r"^NONHIGH\s+DISTRICT\b", re.IGNORECASE)
_HIGH_LABEL_RE = re.compile(r"^HIGH\s+DISTRICT\b", re.IGNORECASE)

_VALUE_TOKEN_RE = re.compile(
    r"^(?:"
    r"\$-"                                     # $- (null marker)
    r"|\$?-?\d[\d,]*(?:\.\d+)?"                # $1,234.56 / 1,234 / -2.50 / 0
    r"|\(-?\$?\d[\d,]*(?:\.\d+)?\)"            # (838,296.07)
    r"|,\d{3}(?:,\d{3})*(?:\.\d+)?"            # ',122,915.00' (column-boundary tail)
    r"|-"                                      # bare dash (null)
    r")$"
)

# Fragmentation: pdfplumber sometimes renders a value at a column
# boundary as `<leading-digit> <continuation>`. Two flavors:
#   - "Unambiguous" tails start with a comma, a decimal point, or are
#     a 1-2 digit decimal. Safe to merge whenever seen — these tokens
#     can't stand alone as a complete value.
#   - "Ambiguous" tails are themselves a valid thousands-grouped value
#     (e.g. `7,296.79` could be either the tail of `17,296.79` or a
#     standalone $7,296.79). Only merge these when the row has more
#     value tokens than the column count predicts.
_FRAG_LEAD_RE = re.compile(r"^\d$")
_FRAG_UNAMBIGUOUS_RE = re.compile(
    r"^(?:,\d{3}(?:,\d{3})*(?:\.\d+)?|\d{1,2}\.\d+|\.\d+)$"
)
_FRAG_AMBIGUOUS_RE = re.compile(r"^\d{1,3},\d{3}(?:,\d{3})*(?:\.\d+)?$")


# Letter -> semantic item_code per form variant. See module docstring
# for why letters aren't used directly as the item_code.
_LEVY_ITEMS = {
    "post_2019": {
        "A": "reported_resident_aafte",
        "B": "nonhigh_aafte",
        "C": "resident_aafte",
        "D": "payable_levy",
        "E": "levy_per_resident_aafte",
    },
    "pre_2019": {
        # Pre-2019 column order put the dollar levy at A and walked the
        # AAFTE breakdown across B-D; the 2019 rewrite reordered to put
        # the AAFTE inputs first and the levy at D.
        "A": "payable_levy",
        "B": "reported_resident_aafte",
        "C": "nonhigh_aafte",
        "D": "resident_aafte",
        "E": "levy_per_resident_aafte",
    },
}
_PAYABLE_ITEMS = {
    "post_2019": {
        "F": "sending_nonhigh_aafte",
        "G": "lesser_levy_rate_per_resident_aafte",
        "H": "total_school_year_payable",
        "I": "may_payable",
        "J": "november_payable",
    },
    "pre_2019": {
        # Pre-2019 form had no "lesser of two rates" column; the total
        # billing slot sat at G (the post-2019 column G).
        "F": "sending_nonhigh_aafte",
        "G": "total_school_year_payable",
        "H": "may_payable",
        "I": "november_payable",
    },
}


def parse_nonhigh_billing_pdf(info: FiscalFilename) -> Iterator[dict]:
    if not _LEAF_RE.match(info.leaf):
        return

    raw_lines = read_pdf_lines(info.path, max_pages=1)
    lines = [collapse_numeric_paren_spaces(merge_split_leading_digit(ln))
             for ln in raw_lines]

    # Header scan: report kind / status / focal district / form variant.
    report_kind = ""
    status = ""
    focal_ccddd = info.ccddd if info.ccddd is not None else 0
    district = ""
    form_variant = "pre_2019"

    for ln in lines[:20]:
        if not report_kind:
            m = _REPORT_KIND_RE.search(ln)
            if m:
                report_kind = "f483" + m.group(1).lower()
        if not status:
            m = _TITLE_STATUS_RE.search(ln)
            if m:
                status = m.group(1).capitalize()
        if not district:
            m = _FOCAL_HEADER_RE.match(ln)
            if m:
                if focal_ccddd == 0:
                    focal_ccddd = int(m.group(1))
                district = m.group(2).strip()
    for ln in lines:
        if _LEVY_BANNER_RE.match(ln):
            form_variant = "post_2019"
            break

    if not report_kind:
        return
    focal_role = "high" if report_kind == "f483h" else "nonhigh"
    counterparty_role = "nonhigh" if focal_role == "high" else "high"
    short_district = re.sub(r"\s+SCHOOL\s+DISTRICT\s*$", "", district,
                            flags=re.IGNORECASE)

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": focal_ccddd,
        "county": "",
        "district": district,
        "report_kind": report_kind,
        "status": status or "Final",
        "form_variant": form_variant,
        "_source": _source_path(info.path),
        "_source_table": "fiscal_nonhigh_billing",
    }

    # Walk body. Section defaults to levy_per_aafte (every variant of the
    # form opens with the levy block; the only switch is into payable).
    section = "levy_per_aafte"
    columns: List[str] = []
    subject_role: str = ""

    for ln in lines:
        if _END_RE.match(ln):
            break
        if _LEVY_BANNER_RE.match(ln):
            section = "levy_per_aafte"
            columns = []
            subject_role = ""
            continue
        if _PAYABLE_BANNER_RE.match(ln):
            section = "payable"
            columns = []
            subject_role = ""
            continue

        tokens = ln.split()
        if not tokens:
            continue

        # Column-header line: every token is "<letter>.".
        if all(_LETTER_TOKEN_RE.match(t) for t in tokens):
            letters = [_LETTER_TOKEN_RE.match(t).group(1) for t in tokens]
            columns = letters
            # Pre-2019 F-483N omits a banner; rely on letter set to switch.
            if "F" in letters and letters[0] != "A":
                section = "payable"
            elif letters[0] == "A":
                section = "levy_per_aafte"
            subject_role = ""
            continue

        # Subject-role hint line (case-insensitive — covers both the
        # new-form 'Nonhigh District [D ÷ C]' label and the old-form
        # column-header subline 'NONHIGH DISTRICT SENT YEAR BILLING ...').
        non5 = not (tokens and _DISTRICT_CODE_RE.match(tokens[0]))
        if non5 and _NONHIGH_LABEL_RE.match(ln):
            subject_role = "nonhigh"
            continue
        if non5 and _HIGH_LABEL_RE.match(ln):
            subject_role = "high"
            continue

        # Header-style item (pre-2018 F-483H levy section: "A. Certified ... $499,500").
        if section == "levy_per_aafte" and not columns:
            m = _HEADER_LINE_RE.match(ln)
            if m and not _LETTER_TOKEN_RE.match(tokens[-1]):
                letter = m.group(1)
                vtext = m.group(3).strip()
                value = parse_decimal(_strip_value_prefix(vtext))
                code = _LEVY_ITEMS[form_variant].get(letter)
                if code is None:
                    continue
                yield {
                    **base,
                    "section": "levy_per_aafte",
                    "subject_role": focal_role,
                    "subject_ccddd": focal_ccddd,
                    "subject_name": short_district,
                    "is_focal": True,
                    "item_code": code,
                    "item_label": letter,
                    "value": value,
                    "value_text": vtext,
                }
                continue

        # District data row: starts with a 5-digit CCDDD.
        if tokens and _DISTRICT_CODE_RE.match(tokens[0]) and columns:
            row_ccddd = int(tokens[0])
            name_toks: List[str] = []
            value_toks: List[str] = []
            for t in tokens[1:]:
                if not value_toks and not _VALUE_TOKEN_RE.match(t):
                    name_toks.append(t)
                else:
                    value_toks.append(t)
            value_toks = _merge_value_fragments(value_toks, len(columns))
            row_name = " ".join(name_toks)
            row_role = (subject_role if subject_role
                        else (focal_role if row_ccddd == focal_ccddd
                              else counterparty_role))
            is_focal = (row_ccddd == focal_ccddd)
            for col, vt in zip(columns, value_toks):
                sec_for_item = ("levy_per_aafte" if col in "ABCDE"
                                else "payable")
                code = (_LEVY_ITEMS[form_variant].get(col)
                        if sec_for_item == "levy_per_aafte"
                        else _PAYABLE_ITEMS[form_variant].get(col))
                if code is None:
                    continue
                val = (None if vt in ("-", "$-")
                       else parse_decimal(_strip_value_prefix(vt)))
                yield {
                    **base,
                    "section": sec_for_item,
                    "subject_role": row_role,
                    "subject_ccddd": row_ccddd,
                    "subject_name": row_name,
                    "is_focal": is_focal,
                    "item_code": code,
                    "item_label": col,
                    "value": val,
                    "value_text": vt,
                }
            continue

        # Total row at the bottom of the payable section.
        if tokens and _TOTAL_ROW_RE.match(tokens[0]) and columns:
            value_toks = _merge_value_fragments(
                [t for t in tokens[1:] if _VALUE_TOKEN_RE.match(t)]
            )
            for col, vt in zip(_total_columns(columns, len(value_toks)),
                               value_toks):
                code = _PAYABLE_ITEMS[form_variant].get(col)
                if code is None:
                    continue
                val = (None if vt in ("-", "$-")
                       else parse_decimal(_strip_value_prefix(vt)))
                yield {
                    **base,
                    "section": "payable_total",
                    "subject_role": "",
                    "subject_ccddd": 0,
                    "subject_name": "",
                    "is_focal": False,
                    "item_code": code,
                    "item_label": col,
                    "value": val,
                    "value_text": vt,
                }
            continue


def _total_columns(columns: List[str], n_values: int) -> List[str]:
    """Decide which letters the Total row's positional values map to.

    The Total row aggregates the per-counterparty rows but the form
    drops the column for any item that doesn't sum:
      - Pre-2018 F-483N block 2 [E,F,G,H,I]: drops E (per-counterparty
        rate). 4 totalled values = F, G, H, I.
      - Pre-2018 F-483H [F,G,H,I]: nothing dropped. 4 totalled values.
      - Post-2018 [F,G,H,I,J]: drops G (per-counterparty rate). 4
        totalled values = F, H, I, J. INITIAL files also drop J
        (November billing not yet computed) → 3 values = F, H, I.
    """
    if columns and columns[0] == "E":
        candidates = [c for c in columns if c != "E"]
    elif "J" in columns:
        candidates = [c for c in columns if c != "G"]
    else:
        candidates = list(columns)
    return candidates[:n_values]


def _merge_value_fragments(tokens: List[str],
                           expected_count: Optional[int] = None) -> List[str]:
    """Glue `(<leading_digit>, <continuation>)` token pairs back together.

    pdfplumber's column-based extraction sometimes splits a value at a
    page-column boundary, leaving the leading digit as one token and the
    rest as another. The end-of-line-only `merge_split_leading_digit`
    pass in `common.py` doesn't catch mid-line fragmentation.

    Two-pass design (see _FRAG_*_RE for the regex pair):
      - Pass 1: merge unambiguous tails (leading-comma, leading-dot,
        1-2 digit decimals). These tokens can't stand alone as a value.
      - Pass 2: merge ambiguous tails (thousands-grouped numbers that
        could be either a fragment or a complete value) only if the
        token count still exceeds `expected_count`. Skip Pass 2 when
        `expected_count` is None (e.g. for total rows where the
        column-count target depends on which letters were dropped).
    """
    out: List[str] = []
    i = 0
    while i < len(tokens):
        if (i + 1 < len(tokens)
                and _FRAG_LEAD_RE.fullmatch(tokens[i])
                and _FRAG_UNAMBIGUOUS_RE.fullmatch(tokens[i + 1])):
            out.append(tokens[i] + tokens[i + 1])
            i += 2
        else:
            out.append(tokens[i])
            i += 1
    if expected_count is None or len(out) <= expected_count:
        return out
    merged: List[str] = []
    excess = len(out) - expected_count
    i = 0
    while i < len(out):
        if (excess > 0 and i + 1 < len(out)
                and _FRAG_LEAD_RE.fullmatch(out[i])
                and _FRAG_AMBIGUOUS_RE.fullmatch(out[i + 1])):
            merged.append(out[i] + out[i + 1])
            i += 2
            excess -= 1
        else:
            merged.append(out[i])
            i += 1
    return merged


def _strip_value_prefix(s: str) -> str:
    s = s.strip()
    if s.startswith("$"):
        s = s[1:]
    return s


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
