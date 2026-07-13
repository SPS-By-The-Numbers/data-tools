"""Parse the OSPI Report 1191 Estimated Funding Report as printed on
pages 2+ of each monthly `Apportionment for {Month}.pdf`.

The structure is nearly identical to Report 1191F "Final Apportionment
Summary" (see `apportionment_final.py`): pp 3+ carry a compound 1191
report with per-account derivation of the district's estimated
apportionment as of month end. Page 1 is the 1197 Statement of
Apportionment (captured by `apportionment_monthly.py`); page 2 is the
Statement's small "General Fund Total" summary tail. This parser
captures pp 3+ and populates `fiscal_apportionment_monthly_estimated`.

**Attribution differences vs the Final version.**
Monthly sub-report codes drop the trailing "F" (Final): 1191 vs
1191F, 1191SE vs 1191SEF, 1191SN vs 1191SNF, 1191TRN vs 1191TRNF, etc.
Section banners print "Apportionment for {Month} DD, YYYY Account
XXXX" instead of "Apportionment Final Account XXXX". Total-line
patterns match both vintages verbatim.

Headline-only, same as `apportionment_final.py`.
"""

import calendar
import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_LEAF_RE = re.compile(r"^Apportionment\s+for\s+(\w+)\s*$", re.IGNORECASE)

# Section banner in monthly PDFs: "Apportionment for Month DD, YYYY
# Account XXXX" (may include "& YYYY" for joint accounts).
_ACCOUNT_BANNER_RE = re.compile(
    r"Apportionment\s+for\s+\w+\s+\d+,?\s+\d{4}\s+Account\s+(\d+(?:\s*&\s*\d+)?)",
    re.IGNORECASE)

# Sub-report code at page top (monthly variants drop trailing "F").
_SUB_REPORT_RE = re.compile(r"\b(1191[A-Z]*[A-Z0-9]*)\b")

# Sub-report -> primary account_code mapping for monthly variants.
_SUB_REPORT_ACCOUNT_MAP = {
    "1191":         "3100",   # General Apportionment
    "1191ED":       "3100",   # District Enrollment / Financials
    "1191EE":       "3100",   # Elementary Enrollment
    "1191EM":       "3100",   # Middle School Enrollment
    "1191EH":       "3100",   # High School Enrollment
    "1191CTE":      "3100",   # HS CTE Enrollment
    "1191MSCTE":    "3100",   # MS CTE Enrollment
    "1191SC":       "3100",   # Skill Center
    "1191MSOC":     "3100",   # Other Compensation-adjacent
    "1191TK":       "3100",   # Transition to Kindergarten (2024-25+)
    "1191FS":       "4198",   # Food Service (Lunch)
    "1191SE":       "4121",   # Special Education
    "1191SER":      "4121",   # Special Ed Recovery
    "1191SN":       "4174",   # LAP / Learning Assistance
    "1191TRN":      "4199",   # Transportation Operations
    "1191FG":       "419804", # Grants Administration (embedded standalone
                              # 1191FG report on later pages)
}

_TOTAL_LINE_PATTERNS = [
    re.compile(r"Total\s+Amount\s+to\s+be\s+Paid\s+.*?\bAccount\s+\d+\b", re.IGNORECASE),
    re.compile(r"Total\s+Amount\s+Due(?:\s+(?:For|in|20\d\d))?\b", re.IGNORECASE),
    re.compile(r"Calculated\s+Allotment\b", re.IGNORECASE),
    re.compile(r"Total\s+Allocation\s+for\s+Special\s+Education\s+Program", re.IGNORECASE),
    re.compile(r"Total\s+Special\s+Ed\s+Account\s+\d+\s+Alloc", re.IGNORECASE),
    re.compile(r"Total\s+K-12\s+Basic\s+Education\s+Allocation", re.IGNORECASE),
    re.compile(r"Total\s+CTE\s+Enhancement\s+Allocation", re.IGNORECASE),
]

_TRAILING_VALUE_RE = re.compile(
    r"\$\s*(-?\d[\d,]*(?:\.\d+)?)\s*$")

_REPORT_TYPES = {
    "apportionment", "fiscal", "state_institutions", "esd_allocations",
    "county_treasurer", "state_agencies_schools_colleges", "technical_colleges",
}

_MONTH_NAMES = {m.lower() for m in list(calendar.month_name)[1:]}


def parse_apportionment_monthly_estimated_pdf(
    info: FiscalFilename,
) -> Iterator[dict]:
    m_leaf = _LEAF_RE.match(info.leaf)
    if not m_leaf:
        return
    month = m_leaf.group(1).capitalize()
    if month.lower() not in _MONTH_NAMES:
        return
    if info.org_type != "district":
        return

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "month": month,
        "_source": _source_path(info.path),
        "_source_table": "fiscal_apportionment_monthly_estimated",
    }

    current_account = ""
    current_sub_report = ""
    item_counters: dict = {}

    with pdfplumber.open(info.path) as pdf:
        first_text = pdf.pages[0].extract_text() or ""
        d = _district_from_text(first_text)
        if d:
            base["district"] = d
        cnty = _county_from_text(first_text)
        if cnty:
            base["county"] = cnty

        # Skip pages 1-2 (Statement of Apportionment).
        for page_idx, page in enumerate(pdf.pages):
            if page_idx < 2:
                continue
            text = page.extract_text() or ""
            page_no = page_idx + 1

            for raw_line in text.split("\n"):
                line = raw_line.strip()
                if not line:
                    continue

                # Sub-report code (page banner).
                if (line.startswith(("1191", "Report 1191"))
                        or "School Year State of Washington" in line):
                    m_sr = _SUB_REPORT_RE.search(line)
                    if m_sr:
                        current_sub_report = m_sr.group(1)

                # Account banner.
                m_acc = _ACCOUNT_BANNER_RE.search(line)
                if m_acc:
                    first_acc = re.match(r"\d+", m_acc.group(1))
                    if first_acc:
                        current_account = first_acc.group(0)
                    continue

                # Any total-line pattern?
                is_total = False
                for pat in _TOTAL_LINE_PATTERNS:
                    if pat.search(line):
                        is_total = True
                        break
                if not is_total:
                    continue

                m_val = _TRAILING_VALUE_RE.search(line)
                if not m_val:
                    continue

                value = parse_decimal(m_val.group(1))
                item_label = re.sub(r"\s+", " ",
                                    _TRAILING_VALUE_RE.sub("", line).strip())

                sr_acct = _SUB_REPORT_ACCOUNT_MAP.get(current_sub_report)
                if sr_acct and sr_acct != current_account and current_account:
                    acc = sr_acct
                else:
                    acc = current_account or (sr_acct or "")
                ordinal = item_counters.get(acc, 0)
                item_counters[acc] = ordinal + 1
                yield {
                    **base,
                    "sub_report": current_sub_report,
                    "account_code": acc,
                    "item_ordinal": ordinal,
                    "item_label": item_label,
                    "value": value,
                    "page_number": page_no,
                }


def _district_from_text(text: str) -> Optional[str]:
    # First, look for the "To:District Name" line -- present on monthly
    # 1197 pp1 and never ambiguous.
    for line in text.split("\n")[:12]:
        m = re.search(r"^To:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    # Fallback: line ending with "... ESD NN" (matches the 1191F
    # vintage). Skip lines that also contain "Statement of Apportionment"
    # or "Capital Region" (those are the 1197 title, not a district line).
    for line in text.split("\n")[:12]:
        if "Statement of Apportionment" in line:
            continue
        m = re.match(r"(.+?)\s+ESD\s+\d+\s*$", line)
        if m:
            return m.group(1).strip()
    return None


def _county_from_text(text: str) -> Optional[str]:
    for line in text.split("\n")[:6]:
        m = re.match(r"(\w[\w\s]*?)\s+County\b", line)
        if m:
            return m.group(1).strip()
    return None


def _source_path(p) -> str:
    parts = list(p.parts)
    idx = -1
    for i, seg in enumerate(parts[:-1]):
        if seg == "fiscal" and i + 1 < len(parts) and parts[i + 1] in _REPORT_TYPES:
            idx = i
    if idx < 0:
        return str(p)
    return "/".join(parts[idx + 1:])
