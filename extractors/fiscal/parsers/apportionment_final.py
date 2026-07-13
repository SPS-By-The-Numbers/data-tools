"""Parse OSPI Report 1191F Final Apportionment Summary PDFs.

Only files under `apportionment/YYYY-YYYY/district/{ccddd}_{slug}/`
with leaf name `Final Apportionment Summary` are 1191F files. Same
file also appears under `esd/{esd_dir}/{ccddd}_{slug}/` but its
content there is a 1191SI State Institution report, not 1191F -- the
scraper reused the same filename convention. Skip ESD-path files.

The 1191F is a 50-60 page compound doc. This parser is HEADLINE-ONLY:
we detect section banners (`Apportionment Final Account XXXX`) and
capture the printed final total lines per account:

  - "Total Amount to be Paid ... in Account XXXX $"    (Account 3100)
  - "Total Amount Due $"                                (all accounts)
  - "Calculated Allotment $" / "D. Calculated Allotment $" (all)
  - "Total Allocation for Special Education Program 21 $" (SpEd)

Intermediate derivation is deliberately skipped.
"""

import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_LEAF_RE = re.compile(r"^Final\s+Apportionment\s+Summary$", re.IGNORECASE)

# Section banner: e.g. "Apportionment Final Account 3100" or
# "Apportionment Final Account 4198 & 419801" (two accounts) or
# "Apportionment Final Account 4199 & 4499".
_ACCOUNT_BANNER_RE = re.compile(
    r"Apportionment\s+Final\s+Account\s+(\d+(?:\s*&\s*\d+)?)",
    re.IGNORECASE)

# Sub-report code at page top: e.g. "1191F", "1191EEF", "1191MSCTEF",
# "1191SCF", "1191FSF", "1191SEF", "1191TRNF", "1191CTER", "1191CTE".
_SUB_REPORT_RE = re.compile(r"\b(1191[A-Z]+F?E?R?)\b")

# Sub-report -> primary account_code mapping. When a total line falls
# inside a sub-report whose default account differs from the last
# "Apportionment Final Account XXXX" banner (e.g. LAP / HC / TBIP
# sub-reports print no per-account banner and inherit 4121 by
# adjacency), override attribution using this map.
_SUB_REPORT_ACCOUNT_MAP = {
    "1191F":        "3100",   # main General Apportionment
    "1191EDF":      "3100",   # District enrollment / financials
    "1191EEF":      "3100",   # Elementary Enrollment
    "1191EMF":      "3100",   # Middle School Enrollment
    "1191EHF":      "3100",   # High School Enrollment
    "1191CTEF":     "3100",   # HS CTE Enrollment
    "1191MSCTEF":   "3100",   # MS CTE Enrollment
    "1191MSCTER":   "3100",   # MS CTE Recovery
    "1191SCF":      "3100",   # Skill Center
    "1191MSOCF":    "3100",   # Other Compensation-adjacent items
    "1191FSF":      "4198",   # Food Service (Lunch)
    "1191SEF":      "4121",   # Special Education
    "1191SPEDF":    "4121",   # Special Ed alt banner
    "1191SNF":      "4174",   # LAP / Learning Assistance + adjacencies
    "1191LAP":      "4174",   # Learning Assistance Program
    "1191HCF":      "4176",   # Highly Capable
    "1191TBIP":     "4165",   # Transitional Bilingual
    "1191TRNF":     "4199",   # Transportation Operations
    "1191CTER":     "3100",   # CTE Indirect Cost Recovery (final rule)
}

# Total-line patterns. The value is the last dollar amount on the line.
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


def parse_apportionment_final_pdf(info: FiscalFilename) -> Iterator[dict]:
    if not _LEAF_RE.match(info.leaf):
        return
    # ESD-path files are actually 1191SI, not 1191F.
    if info.org_type != "district":
        return

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_apportionment_final",
    }

    current_account = ""
    current_sub_report = ""
    item_counters: dict = {}  # (account) -> next ordinal

    with pdfplumber.open(info.path) as pdf:
        # District from first page.
        first_page = pdf.pages[0]
        first_text = first_page.extract_text() or ""
        d = _district_from_text(first_text)
        if d:
            base["district"] = d
        cnty = _county_from_text(first_text)
        if cnty:
            base["county"] = cnty

        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            page_no = page_idx + 1

            for raw_line in text.split("\n"):
                line = raw_line.strip()
                if not line:
                    continue

                # Sub-report code (page banner). First page prints:
                #   "2018-2019 School Year State of Washington 1191F"
                # Continuation pages print just the code:
                #   "1191F"
                # Some pages start "Report 1191CTER State of Washington ...".
                if (line.startswith(("1191", "Report 1191"))
                        or "School Year State of Washington" in line):
                    m_sr = _SUB_REPORT_RE.search(line)
                    if m_sr:
                        current_sub_report = m_sr.group(1)

                # Account banner.
                m_acc = _ACCOUNT_BANNER_RE.search(line)
                if m_acc:
                    # Take just the first account number for grouping.
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

                # Extract trailing value.
                m_val = _TRAILING_VALUE_RE.search(line)
                if not m_val:
                    continue

                value = parse_decimal(m_val.group(1))
                item_label = re.sub(r"\s+", " ",
                                    _TRAILING_VALUE_RE.sub("", line).strip())

                # Prefer a sub-report-driven account if we know it
                # differs from the last-seen banner (LAP / HC / TBIP
                # are inside a Special Ed banner in the source layout).
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
    for line in text.split("\n")[:6]:
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
