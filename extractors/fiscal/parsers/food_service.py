"""Parse one OSPI Report 1800SUM Food Service Program Summary PDF.

The form is stable across 2013-14 -> 2024-25. Five sections:
  1. Revenues       -- 5 items + TOTAL REVENUES
  2. Expenditures   -- 7 items x (Direct / Object 1 Allocation / Net) + total
  3. Indirect       -- Unrestricted Indirect Rate (%), Applied Indirect ($)
  4. Summary        -- TOTAL EXPENDITURES, Excess (Deficit) of Revenues
  5. Carryforward   -- 5 annual balances + Net Balance Carryforward + 3 Months' Avg
"""

import logging
import re
from typing import Iterator, Optional, Tuple

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, is_na, merge_split_leading_digit,
    parse_decimal, read_pdf_lines,
)


logger = logging.getLogger(__name__)


_HEADER_RE = re.compile(
    r"^Food\s+Service\s+Program\s+-\s+Summary\s+of\s+Results\s+of\s+Operations"
    r"\s+School\s+Year\s+(\d{4}-\d{4})\s*$",
    re.IGNORECASE,
)
_DISTRICT_RE = re.compile(r"^(\d{5})\s+(.+?)\s*$")

# Canonical label -> (section, item_code) for items where label is unique.
# Labels are matched as a normalized prefix of the line (case-insensitive,
# whitespace-collapsed) so we don't have to enumerate every value-suffix variant.
_REVENUE_ITEMS = [
    ("paid_lunches",         "Paid Lunches"),
    ("state_payment",        "State Payment"),
    ("federal_payment",      "Federal Payment"),
    ("federal_commodities",  "Federal Commodities"),
    ("other_payments",       "Other Payments"),
    ("total_revenues",       "TOTAL REVENUES"),
]

# Expenditure rows -- each carries 3 numeric tokens (Direct, Object1, Net),
# possibly followed by a trailing `*` flag on the net token.
_EXPENDITURE_ITEMS = [
    ("salaries_benefits",      "Salaries & Benefits"),
    ("supplies",               "Supplies"),
    ("purchased_services",     "Purchased Services"),
    ("food_supplies",          "Food - Supplies"),
    ("food_purchased_services","Food - Purchased Services"),
    ("travel_other",           "Travel & Other"),
    ("capital_outlay",         "Capital Outlay"),
    ("total_direct",           "Total Direct Expenditures"),
]

_INDIRECT_ITEMS = [
    ("unrestricted_indirect_rate", "Unrestricted Indirect Rate"),
    ("applied_indirect",           "Applied Indirect Expenditures"),
]

# Single-value summary items. Note that "Excess (Deficit) of Revenues Over"
# is sometimes broken across two lines; we match the rejoined-line version.
_SUMMARY_ITEMS = [
    ("total_expenditures",  "TOTAL EXPENDITURES"),
    ("excess_deficit",      "Excess (Deficit) of Revenues Over"),
]

_CARRYFORWARD_YEAR_RE = re.compile(
    r"^(\d{4})-(\d{2,4})\s+(Balance|Deficit|Net Balance Carryforward|Net Deficit Carryforward)\s+(.*)$",
    re.IGNORECASE,
)
_THREE_MONTHS_RE = re.compile(
    r"^3\s*Months'?\s+Average\s+Expenditures\s+(.*)$",
    re.IGNORECASE,
)


def _strip_asterisk(token: str) -> Tuple[str, bool]:
    if token.endswith("*"):
        return token[:-1].strip(), True
    return token, False


def _value_tokens(rest: str):
    """Split the value portion of an expenditure line into 3 cells.

    OSPI prints these as `$XXX $XXX $XXX [*]`. After PDF text extraction
    we have a single line with all three `$`-prefixed tokens; split on
    whitespace, but treat a trailing standalone `*` as a flag on the last
    cell.
    """
    rest = rest.strip()
    tokens = rest.split()
    # Trailing asterisk applies to the last numeric token.
    trailing_star = False
    if tokens and tokens[-1] == "*":
        trailing_star = True
        tokens = tokens[:-1]
    elif tokens and tokens[-1].endswith("*"):
        tokens[-1], trailing_star = _strip_asterisk(tokens[-1])
    return tokens, trailing_star


def _normalize_label(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _normalize_year_span(s: str) -> str:
    """'2018-19' -> '2018-2019'. Already-4-digit tails pass through."""
    m = re.match(r"^(\d{4})-(\d{2,4})$", s)
    if not m:
        return s
    start, end = m.group(1), m.group(2)
    if len(end) == 2:
        end = start[:2] + end
    return f"{start}-{end}"


def parse_food_service_pdf(info: FiscalFilename) -> Iterator[dict]:
    """Yield one dict per line item extracted from the PDF."""
    raw_lines = read_pdf_lines(info.path)
    lines = [collapse_numeric_paren_spaces(merge_split_leading_digit(ln))
             for ln in raw_lines]

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_food_service",
    }

    section: Optional[str] = None
    seen_expenditures_header = False
    saw_carryforward_subheader = False

    for ln in lines:
        # Detect district line (e.g. '01109 Washtucna School District').
        if not base["district"]:
            m = _DISTRICT_RE.match(ln)
            if m and int(m.group(1)) == (info.ccddd or -1):
                base["district"] = m.group(2)
                continue

        # Section markers.
        if ln.strip() == "Revenues":
            section = "revenues"
            continue
        if ln.startswith("Expenditures") and "Direct Expenditures" in ln:
            section = "expenditures"
            seen_expenditures_header = True
            continue
        if ln.startswith("Indirect Expenditures"):
            section = "indirect"
            continue
        if ln.startswith("TOTAL EXPENDITURES"):
            section = "summary"
            # Falls through so the line is emitted as an item.
        elif ln.startswith("Annual Net Balance Carryover"):
            section = "carryforward"
            saw_carryforward_subheader = True
            continue
        elif ln.strip() == "New Balances":
            continue

        if section == "revenues":
            yielded = _try_emit_revenue(ln, base)
            if yielded:
                yield yielded
                continue
        if section == "expenditures":
            yielded = _try_emit_expenditure(ln, base)
            if yielded is not None:
                yield from yielded
                continue
        if section == "indirect":
            yielded = _try_emit_indirect(ln, base)
            if yielded is not None:
                yield from yielded
                if yielded:
                    # After "Applied Indirect Expenditures" we expect summary next.
                    if yielded[-1]["item_code"] == "applied_indirect":
                        section = None  # next "TOTAL EXPENDITURES" triggers summary
                continue
        if ln.startswith("TOTAL EXPENDITURES"):
            yielded = _emit_summary_total(ln, base)
            if yielded:
                yield yielded
            section = "summary"
            continue
        if section == "summary":
            yielded = _try_emit_summary(ln, base)
            if yielded:
                yield yielded
                # The older form (pre 2018-19) jumps straight from summary to
                # carryforward without a subheader; promote on first year row.
                continue
        # Carryforward section (also reachable from "summary" via year-row
        # promotion).
        m = _CARRYFORWARD_YEAR_RE.match(ln)
        if m:
            section = "carryforward"
            yielded = _emit_carryforward_year(m, base)
            if yielded:
                yield yielded
                continue
        m = _THREE_MONTHS_RE.match(ln)
        if m:
            section = "carryforward"
            yielded = _emit_three_months(m, base)
            if yielded:
                yield yielded
                continue


def _try_emit_revenue(ln: str, base: dict):
    for code, label in _REVENUE_ITEMS:
        prefix = label
        if ln.startswith(prefix):
            rest = ln[len(prefix):].strip()
            value_text = rest.replace("$", "").strip()
            value = parse_decimal(value_text)
            return {
                **base,
                "section": "revenues",
                "item_code": code,
                "subkey": "",
                "item_label": label,
                "value": value,
                "value_text": value_text,
                "is_indirect_calc": "",
            }
    return None


def _try_emit_expenditure(ln: str, base: dict):
    for code, label in _EXPENDITURE_ITEMS:
        if ln.startswith(label):
            rest = ln[len(label):].strip()
            tokens, star = _value_tokens(rest)
            # Strip leading `$` from each token before parsing.
            clean = [t.lstrip("$").strip() for t in tokens]
            rows = []
            subkeys = ["direct", "object1_alloc", "net"]
            for sk, tok in zip(subkeys, clean):
                rows.append({
                    **base,
                    "section": "expenditures",
                    "item_code": code,
                    "subkey": sk,
                    "item_label": label,
                    "value": parse_decimal(tok),
                    "value_text": tok,
                    "is_indirect_calc": (sk == "net" and star),
                })
            return rows
    return None


def _try_emit_indirect(ln: str, base: dict):
    for code, label in _INDIRECT_ITEMS:
        if ln.startswith(label):
            rest = ln[len(label):].strip()
            value_text = rest.replace("$", "").strip()
            # Indirect rate prints as '37.50%' -- strip the trailing %.
            stripped = value_text.rstrip("%").strip()
            return [{
                **base,
                "section": "indirect",
                "item_code": code,
                "subkey": "",
                "item_label": label,
                "value": parse_decimal(stripped),
                "value_text": value_text,
                "is_indirect_calc": "",
            }]
    return None


def _emit_summary_total(ln: str, base: dict):
    rest = ln[len("TOTAL EXPENDITURES"):].strip()
    value_text = rest.replace("$", "").strip()
    return {
        **base,
        "section": "summary",
        "item_code": "total_expenditures",
        "subkey": "",
        "item_label": "TOTAL EXPENDITURES",
        "value": parse_decimal(value_text),
        "value_text": value_text,
        "is_indirect_calc": "",
    }


def _try_emit_summary(ln: str, base: dict):
    # Excess (Deficit) of Revenues Over (Under) Expenditures -- one printed line
    # in newer forms (single-line), two lines in older forms (label + value).
    if ln.startswith("Excess (Deficit) of Revenues Over"):
        # Two cases:
        # 1) "Excess (Deficit) of Revenues Over (Under) Expenditures $ (47,075)"
        # 2) "Excess (Deficit) of Revenues Over" then on next line "$ (47,075)"
        m = re.search(r"\$\s*\(?\s*-?\s*[\d,.]+\s*\)?\s*$", ln)
        if m:
            value_text = m.group(0).replace("$", "").strip()
            return {
                **base,
                "section": "summary",
                "item_code": "excess_deficit",
                "subkey": "",
                "item_label": "Excess (Deficit) of Revenues Over (Under) Expenditures",
                "value": parse_decimal(value_text),
                "value_text": value_text,
                "is_indirect_calc": "",
            }
        # No value on this line -- two-line case. Defer to a "$ ..." line below.
        return None
    # Bare "$ NNN" line is the deferred value for excess_deficit (older form).
    if ln.startswith("$") and re.match(r"^\$\s*\(?-?\s*[\d,.]+\)?\s*$", ln):
        value_text = ln.replace("$", "").strip()
        return {
            **base,
            "section": "summary",
            "item_code": "excess_deficit",
            "subkey": "",
            "item_label": "Excess (Deficit) of Revenues Over (Under) Expenditures",
            "value": parse_decimal(value_text),
            "value_text": value_text,
            "is_indirect_calc": "",
        }
    return None


def _emit_carryforward_year(m, base: dict):
    year_raw = f"{m.group(1)}-{m.group(2)}"
    year = _normalize_year_span(year_raw)
    kind = m.group(3).strip()
    value_text = m.group(4).replace("$", "").strip()
    val = parse_decimal(value_text)
    if "Carryforward" in kind:
        return {
            **base,
            "section": "carryforward",
            "item_code": "net_balance_carryforward",
            "subkey": "",
            "item_label": f"{year_raw} {kind}",
            "value": val,
            "value_text": value_text,
            "is_indirect_calc": "",
        }
    return {
        **base,
        "section": "carryforward",
        "item_code": "annual_balance",
        "subkey": year,
        "item_label": f"{year_raw} {kind}",
        "value": val,
        "value_text": value_text,
        "is_indirect_calc": "",
    }


def _emit_three_months(m, base: dict):
    value_text = m.group(1).replace("$", "").strip()
    return {
        **base,
        "section": "carryforward",
        "item_code": "three_months_avg_expenditures",
        "subkey": "",
        "item_label": "3 Months' Average Expenditures",
        "value": parse_decimal(value_text),
        "value_text": value_text,
        "is_indirect_calc": "",
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
