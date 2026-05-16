"""Parser for STARS Operations Allocation Detail (form 1026A).

One-page (PDF) or one-document (DOCX) report per district per year. The
PDF lays each row out as one text line ("Land Area (Ln) 207.4 0.03765
0.20084"); the DOCX renders each cell as its own paragraph, so the same
row spans four lines ("Land Area (Ln)", "207.4", "0.03765", "0.20084").

We walk lines from either source, recognize item labels by regex, and
gather the next N numeric tokens from the current line and any
following lines until we hit the next item label. The number of tokens
expected per item is set by its `kind` -- the catalog below enumerates
every line item OSPI prints, with its canonical snake_case code and
how to interpret its numerics.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

from .common import parse_decimal, read_lines, tokenize_value_line
from ..filename import StarsFilename


logger = logging.getLogger(__name__)


# ---------- item catalog --------------------------------------------------

# Each entry: (item_code, section, label_match_pattern, kind).
#
# `kind` controls how the trailing tokens become column values:
#   'detail'   -> 3 numerics: item_value, coefficient, calculated_value
#   'non_high' -> 1 text ("Yes"/"No") then 2 numerics (coef, calculated_value).
#                 Text token is ignored; only coef + calc are recorded.
#   'calc'     -> 1 numeric -> calculated_value (e.g. A.1/A.2/A.3/A.5).
#   'amount'   -> 1 dollar amount -> amount.
#   'amount_rt'-> 2 dollar amounts: amount, then running_total.
#   'coef_rt'  -> 1 modifier (decimal) then 1 dollar running_total
#                 (Section C.1 Alt Calendar Modifier).
_ITEM_CATALOG = [
    # (item_code, section, label regex, kind)
    ("land_area",            "A", r"^Land Area \(Ln\)$",                                          "detail"),
    ("average_distance",     "A", r"^Average Distance$",                                           "detail"),
    ("destinations",         "A", r"^Destinations$",                                               "detail"),
    ("basic_program",        "A", r"^Basic Program \(Ln\)$",                                       "detail"),
    ("special_program",      "A", r"^Special Program \(Ln\)$",                                     "detail"),
    ("non_high_yes",         "A", r"^Non-High Yes$",                                               "non_high"),
    ("non_high_no",          "A", r"^Non-High No$",                                                "non_high"),
    ("a1_sum_calculated_values",          "A", r"^A\.1\.\s+Sum of Calculated Values$",            "calc"),
    ("a2_expected_allocation_constant",   "A", r"^A\.2\.\s+Expected Allocation Constant Value$",  "calc"),
    ("a3_expected_allocation_value",      "A", r"^A\.3\.\s+Expected Allocation Value$",           "calc"),
    ("a4_initial_allocation",             "A", r"^A\.4\.\s+Initial Allocation$",                  "amount"),
    ("a5_local_characteristics_factor",   "A", r"^A\.5\.\s+Local Characteristics Factor$",        "calc"),
    ("a6_calculated_expected_allocation", "A", r"^A\.6\.\s+CALCULATED EXPECTED ALLOCATION$",      "amount"),
    ("b1_non_high",                       "B", r"^B\.1\.\s+Non-High$",                            "amount"),
    ("b2_low_ridership",                  "B", r"^B\.2\.\s+Low Ridership$",                       "amount"),
    ("b3_transportation_coop",            "B", r"^B\.3\.\s+Transportation Co-op$",                "amount"),
    ("b4_esd",                            "B", r"^B\.4\.\s+ESD$",                                 "amount"),
    ("b5_other",                          "B", r"^B\.5\.\s+Other$",                               "amount"),
    ("b6_alternate_system_total",         "B", r"^B\.6\.\s+Alternate System Total$",              "amount_rt"),
    ("c1_alt_calendar_modifier",          "C", r"^C\.1\.\s+Alt Calendar Modifier$",               "coef_rt"),
    ("c2_car_mileage_reimbursement",      "C", r"^C\.2\.\s+Car Mileage Reimbursement$",           "amount"),
    ("c3_other_adjustments_total",        "C", r"^C\.3\.\s+Other Adjustments Total$",             "amount_rt"),
    ("d1_adjusted_allocation",            "D", r"^D\.1\.\s+Adjusted Allocation$",                 "amount"),
    ("d2_prior_year_expenditures",        "D", r"^D\.2\.\s+Prior Year Expenditures$",             "amount"),
    ("d3_federal_restricted_rate_indirects", "D", r"^D\.3\.\s+Federal Restricted Rate Indirects$","amount"),
    ("d4_adjusted_prior_year_expenditures",  "D", r"^D\.4\.\s+Adjusted Prior Year Expenditures$", "amount"),
    ("d5_lesser_of_adjusted_or_prior_year",  "D",
        r"^D\.5\.\s+Lesser of Adjusted Allocation or Adjusted Prior Year Expenditures$",          "amount"),
    ("d6_legislative_salary",             "D", r"^D\.6\.\s+Legislative Salary$",                  "amount"),
    ("d7_legislative_benefit",            "D", r"^D\.7\.\s+Legislative Benefit$",                 "amount"),
    ("d8_actual_allocation_amount",       "D", r"^D\.8\.\s+ACTUAL ALLOCATION AMOUNT$",            "amount"),
]


@dataclass
class _Item:
    code: str
    section: str
    pattern: re.Pattern
    kind: str


def _label_prefix_pattern(src: str) -> re.Pattern:
    """Drop a trailing '$' so the pattern matches as a line-leading prefix.

    PDFs render rows as "<label> <number> <number> ..." on one line; DOCXs
    put just "<label>" on its own line. A single prefix-match works for both.
    """
    if src.endswith("$"):
        src = src[:-1]
    return re.compile(src)


_ITEMS: List[_Item] = [
    _Item(code, section, _label_prefix_pattern(pat), kind)
    for code, section, pat, kind in _ITEM_CATALOG
]


def _match_item(line: str) -> Optional[Tuple[_Item, str]]:
    """If `line` starts with any item's label, return (item, post-label tail)."""
    for it in _ITEMS:
        m = it.pattern.match(line)
        if m:
            return it, line[m.end():].lstrip()
    return None


def _is_section_or_subheading(line: str) -> bool:
    """Lines like 'SECTION A - ...' or 'LEGISLATIVE ADJUSTMENTS' between rows."""
    return (
        line.startswith("SECTION ")
        or line.startswith("LEGISLATIVE ADJUSTMENTS")
        or line.startswith("Page ")
        or line.startswith("Run:")
        or line.startswith("State of Washington")
        or line.startswith("Superintendent of Public Instruction")
        or line.startswith("School Year ")
        or line.startswith("Operations Allocation Detail Report ")
        or line.startswith("Allocation Items")
        or line.startswith("Values")
        or line.startswith("Coefficient")
        or line.startswith("Calculated Value")
        or line.startswith("v1")
    )


def _gather_tokens_for(
    lines: List[str], start_idx: int, item: _Item, tail: str,
) -> Tuple[List[str], int]:
    """From `lines[start_idx]` onwards, return tokens until the next item.

    `tail` is the post-label text of the start line (already stripped of
    the leading label). Returns (tokens, next_idx) where next_idx points
    to the line where the next item label was matched (or len(lines) if
    EOF). Boilerplate lines (section headings, page chrome) are skipped.
    """
    tokens: List[str] = []
    if tail:
        tokens.extend(tokenize_value_line(tail))

    i = start_idx + 1
    while i < len(lines):
        ln = lines[i]
        if _match_item(ln) is not None:
            break
        if _is_section_or_subheading(ln):
            i += 1
            continue
        tokens.extend(tokenize_value_line(ln))
        i += 1
    return tokens, i


def _row_from_item(
    item: _Item, label: str, tokens: List[str], base: dict, source_name: str,
) -> Optional[dict]:
    """Convert (item, raw tokens) into a stars_operations_allocation row dict."""

    decs = [parse_decimal(t) for t in tokens]
    row = dict(base)
    row["section_code"] = item.section
    row["item_code"] = item.code
    row["item_label"] = label
    row["item_value"] = None
    row["coefficient"] = None
    row["calculated_value"] = None
    row["amount"] = None
    row["running_total"] = None

    if item.kind == "detail":
        if len(decs) < 3:
            logger.warning("%s: %s expected 3 numerics, got %d (%r)",
                           source_name, item.code, len(decs), tokens)
            return None
        row["item_value"], row["coefficient"], row["calculated_value"] = decs[:3]
    elif item.kind == "non_high":
        # Layout: "Yes"/"No" answer followed by coefficient and calc.
        # In tokens, the answer is a non-numeric token (parse_decimal -> None).
        # Just pick the last two numerics.
        numerics = [d for d in decs if d is not None]
        if len(numerics) < 2:
            logger.warning("%s: %s expected 2 numerics, got %d (%r)",
                           source_name, item.code, len(numerics), tokens)
            return None
        row["coefficient"], row["calculated_value"] = numerics[-2:]
    elif item.kind == "calc":
        if not decs or decs[0] is None:
            logger.warning("%s: %s expected 1 decimal, got %r",
                           source_name, item.code, tokens)
            return None
        row["calculated_value"] = decs[0]
    elif item.kind == "amount":
        if not decs or decs[0] is None:
            logger.warning("%s: %s expected 1 dollar amount, got %r",
                           source_name, item.code, tokens)
            return None
        row["amount"] = decs[0]
    elif item.kind == "amount_rt":
        if len(decs) < 2 or decs[0] is None or decs[1] is None:
            logger.warning("%s: %s expected 2 dollar amounts, got %r",
                           source_name, item.code, tokens)
            return None
        row["amount"], row["running_total"] = decs[0], decs[1]
    elif item.kind == "coef_rt":
        if len(decs) < 2 or decs[0] is None or decs[1] is None:
            logger.warning("%s: %s expected modifier + running_total, got %r",
                           source_name, item.code, tokens)
            return None
        row["coefficient"], row["running_total"] = decs[0], decs[1]
    else:  # unreachable
        return None
    return row


_BARE_SECTION_NUM_RE = re.compile(r"^[A-D]\.\d{1,2}\.$")


def _stitch_split_labels(lines: List[str]) -> List[str]:
    """Merge lines where a bare 'X.N.' marker was split from its label.

    OSPI's DOCX layout sometimes drops "X.N." on one line and the rest of
    the label on the next (notably 'D.8.' / 'ACTUAL ALLOCATION AMOUNT' in
    older years). Merge those pairs so the downstream label matcher sees
    a single 'D.8. ACTUAL ALLOCATION AMOUNT' line.
    """
    out: List[str] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        if _BARE_SECTION_NUM_RE.match(cur) and i + 1 < len(lines):
            out.append(f"{cur} {lines[i + 1]}")
            i += 2
        else:
            out.append(cur)
            i += 1
    return out


def parse_operations_allocation(info: StarsFilename) -> Iterator[dict]:
    """Yield stars_operations_allocation rows for one PDF or DOCX."""
    lines = _stitch_split_labels(read_lines(info.path))

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd,
        "county": None,
        "district": info.district_name,
        "_source": info.path.name,
        "_source_table": "stars_operations_allocation",
    }

    i = 0
    seen = set()
    while i < len(lines):
        match = _match_item(lines[i])
        if match is None:
            i += 1
            continue
        matched_item, tail = match
        if matched_item.code in seen:
            # Paranoid: OSPI's report doesn't repeat items.
            i += 1
            continue
        tokens, next_i = _gather_tokens_for(lines, i, matched_item, tail)
        # Use the stripped line as the human-readable label (the part before
        # any inline values would land in `tail`).
        label = lines[i][: len(lines[i]) - len(tail) - (1 if tail else 0)].rstrip()
        row = _row_from_item(matched_item, label, tokens, base, info.path.name)
        if row is not None:
            yield row
            seen.add(matched_item.code)
        i = next_i

    # Sanity-check: any expected item we never matched?
    missing = [it.code for it in _ITEMS if it.code not in seen]
    if not seen:
        # Zero items matched means this is one of OSPI's non-standard
        # 1026A variants -- tribal compacts (form "1026A (COMPACT)") and
        # charter schools both use a host-district-per-rider model with a
        # different line-item set. They produce no rows from this parser.
        is_compact = any("COMPACT" in ln for ln in lines)
        logger.info(
            "%s: no standard 1026A items matched -- likely %s; skipping",
            info.path.name, "COMPACT format" if is_compact else "non-standard format",
        )
    elif missing:
        logger.warning("%s: %d item(s) missing: %s",
                       info.path.name, len(missing), ",".join(missing))
