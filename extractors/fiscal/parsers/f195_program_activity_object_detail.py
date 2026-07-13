"""Parse the per-program `OBJECTS OF EXPENDITURE` sub-report (GF9-XX)
of OSPI Form F-195 Budget.

One page per General Fund program (Seattle 2024-25: pp 25-83, 59 pages
of per-program breakdown), each presenting an Activity x Object cross-
tab. Layout:

    Seattle Public Schools District No.001
    OBJECTS OF EXPENDITURE
    PROGRAM 01 - Basic Education         <- program banner (first page only)
    (0) (1) (2) (3) (4) (5) (7) (8) (9)   <- column-code header
    Debit Credit Cert. Class. Employee Supplies / Purchased  (8)  Capital
    Activity Total Transfer Transfer Salaries Salaries Benefits Materials Services Travel Outlay
    21 Supv Inst 16,786,640 37,061 4,894,635 6,800,710 3,549,080 ...     <- detail rows
    22 Lrn Resrc 11,618,625 110 8,215,957 217,831 2,730,439 ...
    ...
    Total 512,654,221 1,338,988 324,702,917 37,021,256 ...                 <- program subtotal
    FTE Program Staff 2,534.040 319.514                                    <- program FTE totals
    Form F-195 Page 25 of 186 GF9-01: 1 of 59                              <- footer

Detects GF9-XX pages by 3 signals: `OBJECTS OF EXPENDITURE` in the
header, absence of `PROGRAM SUMMARY BY OBJECT` (which would be the
GF9 roll-up), and absence of `SALARY EXHIBIT` (GF9-201-XX / GF9-301-XX).

Detail-row activity codes:
  - 2013-14 / 2014-15 vintage: `21 Supv Inst 5,035,544 ...`
  - 2019-20+ vintage:          `21 | Supv Inst 5,035,544 ...` (pipe separator)

Program banner is on the FIRST page of a program's page span; subsequent
continuation pages omit it (Seattle 2024-25 has multi-page programs like
Program 11 spanning pp 29-30, Program 12 spanning pp 31-32). Continuation
pages inherit the current program state.

Uses positional column-anchor extraction (`extract_words(use_text_flow=
True)`, group by y-tolerance, bin each value word by x1 into 10 columns:
Activity Total + 9 objects). Anchors are established from the first row
with 10 numeric value tokens; some detail rows (e.g. `29 Pmt to SD 0 0`)
print only 2 values with 8 columns left blank.
"""

import logging
import re
from typing import Iterator, List, Optional, Tuple

from ..filename import FiscalFilename
from .common import parse_decimal, normalize_pdf_text


logger = logging.getLogger(__name__)


_TITLE = "OBJECTS OF EXPENDITURE"
_TITLE_EXCLUDE_SUMMARY = "PROGRAM SUMMARY BY OBJECT"
_TITLE_EXCLUDE_SALARY = "SALARY EXHIBIT"

# Program banner (first page of each program). Accepts alphanumeric
# codes to defensively cover any future 2-char codes; historically all
# are 2-digit numeric.
_PROGRAM_BANNER_RE = re.compile(
    r"^PROGRAM\s+([0-9A-Z]{2})\s*-\s*(.+?)\s*$", re.IGNORECASE
)

# Detail row: leading 2-digit activity code, optional ` | ` separator,
# then the activity name. Some detail rows (e.g. `29 Pmt to SD 0 0`)
# print only 2 numeric values with 8 columns blank.
_ACTIVITY_CODE_RE = re.compile(r"^(\d{2})\s*(?:\|\s*)?(.*)$")

# Program-total subtotal row (bare `Total` label).
_TOTAL_RE = re.compile(r"^Total\b", re.IGNORECASE)

# FTE row: `FTE Program Staff <cert-fte> <class-fte>` (2020-21+) /
# `FTE PROGRAM STAFF <cert-fte> <class-fte>` (2013-14 / 2014-15 all caps).
_FTE_RE = re.compile(r"^FTE\s+Program\s+Staff\b", re.IGNORECASE)

# Value token.
_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$")

# Footer / boilerplate to skip.
_FOOTER_RE = re.compile(
    r"^Form\s+(?:F-195|RP-195)", re.IGNORECASE
)
_HEADER_BANNER_RES = [
    re.compile(r"^FY\s+\d{4}", re.IGNORECASE),
    re.compile(r"District\s+No", re.IGNORECASE),
    re.compile(r"^Seattle\s+Public\s+Schools", re.IGNORECASE),
    re.compile(r"^Run[:\s]", re.IGNORECASE),
]
# Column-header rows (labels only, no values).
_HEADER_COL_LABEL_RES = [
    re.compile(r"^\(0\)\s+\(1\)", re.IGNORECASE),
    re.compile(r"^Debit\s+Credit\s+Cert", re.IGNORECASE),
    re.compile(r"^Activity\s+Total\s+Transfer", re.IGNORECASE),
]

_Y_TOLERANCE = 2.5
_COL_TOLERANCE = 12.0

# Program-code -> section slug (mirrors f195_program_summary_by_object).
_PROGRAM_CODE_TO_SECTION = {
    # Regular Instruction
    "01": "regular_instruction",
    "02": "regular_instruction",
    "03": "regular_instruction",
    "09": "regular_instruction",
    # Federal Special Purpose / Federal Stimulus (varies by vintage)
    "11": "federal_special_purpose",
    "12": "federal_special_purpose",
    "13": "federal_special_purpose",
    "14": "federal_special_purpose",
    "18": "federal_special_purpose",
    "19": "federal_special_purpose",
    # Special Education Instruction
    "21": "special_education_instruction",
    "22": "special_education_instruction",
    "23": "special_education_instruction",
    "24": "special_education_instruction",
    "25": "special_education_instruction",
    "26": "special_education_instruction",
    "29": "special_education_instruction",
    # Vocational Instruction
    "31": "vocational_instruction",
    "34": "vocational_instruction",
    "38": "vocational_instruction",
    "39": "vocational_instruction",
    # Skill Center Instruction
    "45": "skill_center_instruction",
    "46": "skill_center_instruction",
    "47": "skill_center_instruction",
    # Compensatory Education (50s and 60s)
    "51": "compensatory_education", "52": "compensatory_education",
    "53": "compensatory_education", "54": "compensatory_education",
    "55": "compensatory_education", "56": "compensatory_education",
    "57": "compensatory_education", "58": "compensatory_education",
    "59": "compensatory_education", "61": "compensatory_education",
    "62": "compensatory_education", "63": "compensatory_education",
    "64": "compensatory_education", "65": "compensatory_education",
    "67": "compensatory_education", "68": "compensatory_education",
    "69": "compensatory_education",
    # Other Instructional Programs
    "71": "other_instructional_programs",
    "73": "other_instructional_programs",
    "74": "other_instructional_programs",
    "76": "other_instructional_programs",
    "78": "other_instructional_programs",
    "79": "other_instructional_programs",
    # Community Services
    "81": "community_services",
    "86": "community_services",
    "88": "community_services",
    "89": "community_services",
    # Support Services
    "97": "support_services",
    "98": "support_services",
    "99": "support_services",
}


def _group_rows(words, y_tol=_Y_TOLERANCE) -> List[List[dict]]:
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


def _closest_column(x1: float, anchors: List[float]) -> Optional[int]:
    best_idx = None
    best_d = _COL_TOLERANCE
    for i, a in enumerate(anchors):
        d = abs(x1 - a)
        if d <= best_d:
            best_idx = i
            best_d = d
    return best_idx


def _row_text(row) -> str:
    return re.sub(r"\s+", " ", " ".join(w["text"] for w in row).strip())


def _is_boilerplate_row(text: str) -> bool:
    if not text:
        return True
    if text == _TITLE:
        return True
    if _FOOTER_RE.match(text):
        return True
    if any(pat.search(text) for pat in _HEADER_BANNER_RES):
        return True
    if any(pat.match(text) for pat in _HEADER_COL_LABEL_RES):
        return True
    return False


def _is_gf9_program_page(text: str) -> bool:
    if _TITLE not in text:
        return False
    if _TITLE_EXCLUDE_SUMMARY in text:
        return False
    if _TITLE_EXCLUDE_SALARY.upper() in text.upper():
        return False
    return True


def _extract_program_banner(rows) -> Optional[Tuple[str, str]]:
    for row in rows[:10]:
        text = _row_text(row)
        m = _PROGRAM_BANNER_RE.match(text)
        if m:
            return m.group(1).upper(), re.sub(r"\s+", " ", m.group(2).strip())
    return None


_DISTRICT_BANNER_RE = re.compile(
    r"^\s*(.+?)\s+(?:District\s+No\.?\s*0*\d+|No\.\s*0*\d+)\s*$"
)


def _extract_district_from_text(text: str) -> str:
    for line in text.split("\n")[:6]:
        m = _DISTRICT_BANNER_RE.match(line)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def parse_f195_program_activity_object_detail_pdf(
    info: FiscalFilename,
) -> Iterator[dict]:
    """Yield rows from GF9-XX pages of one F-195 Budget PDF."""
    import pdfplumber

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f195_program_activity_object_detail",
    }

    # First pass: collect all GF9-XX pages' grouped rows + establish
    # column anchors from the first row of 10 numeric value tokens.
    pages_to_process: List[Tuple[List[List[dict]], Optional[Tuple[str, str]]]] = []
    column_anchors: Optional[List[float]] = None

    with pdfplumber.open(info.path) as pdf:
        entered = False
        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            if not _is_gf9_program_page(text):
                if entered:
                    # GF9-XX per-program section is contiguous. Once we
                    # leave it, stop scanning (defensive early-exit --
                    # salary exhibits follow immediately).
                    break
                continue
            entered = True

            if not base["district"]:
                base["district"] = _extract_district_from_text(text)
            words = page.extract_words(use_text_flow=True)

            grouped = _group_rows(words)
            banner = _extract_program_banner(grouped)
            pages_to_process.append((grouped, banner))

            if column_anchors is None:
                for row in grouped:
                    value_words = [
                        w for w in row
                        if _VALUE_TOKEN_RE.match(w["text"])
                        and w["x0"] >= 100
                    ]
                    if len(value_words) == 10:
                        column_anchors = [w["x1"] for w in value_words]
                        break

    if not pages_to_process:
        return
    if column_anchors is None:
        logger.warning(
            "%s: GF9-XX has no 10-value row; skipping file",
            info.path.name,
        )
        return

    seen = {}
    current_program: Optional[Tuple[str, str]] = None

    for grouped, banner in pages_to_process:
        if banner is not None:
            current_program = banner
        if current_program is None:
            # Continuation page whose first program page we missed
            # (defensive). Skip until a banner is seen.
            continue
        program_code, program_label = current_program
        section = _PROGRAM_CODE_TO_SECTION.get(program_code, "unknown")

        for row in grouped:
            text = _row_text(row)
            if _is_boilerplate_row(text):
                continue

            m_banner = _PROGRAM_BANNER_RE.match(text)
            if m_banner:
                current_program = (
                    m_banner.group(1).upper(),
                    re.sub(r"\s+", " ", m_banner.group(2).strip()),
                )
                program_code, program_label = current_program
                section = _PROGRAM_CODE_TO_SECTION.get(program_code, "unknown")
                continue

            value_words = [
                w for w in row
                if _VALUE_TOKEN_RE.match(w["text"])
                and w["x0"] >= 100
            ]
            if not value_words:
                continue

            first_value_x0 = min(w["x0"] for w in value_words)
            label_words = [w for w in row if w["x0"] < first_value_x0]
            label_text = _row_text(label_words)
            if not label_text:
                continue

            # FTE row: has 2 values (cert FTE + class FTE), not 10.
            if _FTE_RE.match(label_text):
                # Bin FTE values by column anchor. FTE cert lands at
                # column 3 (object 2 -- Cert. Salaries) and FTE class
                # at column 4 (object 3 -- Class. Salaries), by
                # x-anchor of the printed header.
                fte_cert = None
                fte_class = None
                for vw in value_words:
                    idx = _closest_column(vw["x1"], column_anchors)
                    if idx == 3:
                        fte_cert = parse_decimal(vw["text"])
                    elif idx == 4:
                        fte_class = parse_decimal(vw["text"])
                key = (program_code, "fte_program_staff", "")
                if key in seen:
                    continue
                row_out = {
                    **base,
                    "section": section,
                    "program_code": program_code,
                    "activity_code": "",
                    "row_kind": "fte_program_staff",
                    "program_label": program_label,
                    "activity_label": "",
                    "activity_total": None,
                    "object_0_debit_transfer": None,
                    "object_1_credit_transfer": None,
                    "object_2_cert_salaries": None,
                    "object_3_class_salaries": None,
                    "object_4_employee_benefits": None,
                    "object_5_supplies_materials": None,
                    "object_7_purchased_services": None,
                    "object_8_travel": None,
                    "object_9_capital_outlay": None,
                    "fte_cert": fte_cert,
                    "fte_class": fte_class,
                }
                seen[key] = row_out
                continue

            # Program-total row: `Total <values>`.
            is_program_total = bool(_TOTAL_RE.match(label_text))
            activity_code = ""
            activity_label = ""
            if not is_program_total:
                m_act = _ACTIVITY_CODE_RE.match(label_text)
                if m_act is None:
                    # Row starts with something else (label continuation,
                    # etc.). Skip.
                    continue
                activity_code = m_act.group(1)
                activity_label = re.sub(r"\s+", " ", m_act.group(2).strip())

            # Bin each value word into the 10 columns.
            binned: List[Optional[dict]] = [None] * 10
            for vw in value_words:
                idx = _closest_column(vw["x1"], column_anchors)
                if idx is not None and binned[idx] is None:
                    binned[idx] = vw

            def _v(i):
                return parse_decimal(binned[i]["text"]) if binned[i] else None

            row_kind = "program_total" if is_program_total else "detail"
            key = (program_code, row_kind, activity_code)
            if key in seen:
                # Older vintages sometimes list an activity twice
                # (OSPI form-internal quirk documented for salary
                # exhibits and expenditure_by_program). First-write-wins.
                continue

            row_out = {
                **base,
                "section": section,
                "program_code": program_code,
                "activity_code": activity_code,
                "row_kind": row_kind,
                "program_label": program_label,
                "activity_label": activity_label,
                "activity_total":              _v(0),
                "object_0_debit_transfer":     _v(1),
                "object_1_credit_transfer":    _v(2),
                "object_2_cert_salaries":      _v(3),
                "object_3_class_salaries":     _v(4),
                "object_4_employee_benefits":  _v(5),
                "object_5_supplies_materials": _v(6),
                "object_7_purchased_services": _v(7),
                "object_8_travel":             _v(8),
                "object_9_capital_outlay":     _v(9),
                "fte_cert": None,
                "fte_class": None,
            }
            seen[key] = row_out

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
