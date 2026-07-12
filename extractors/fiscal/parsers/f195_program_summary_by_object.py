"""Parse the `PROGRAM SUMMARY BY OBJECT OF EXPENDITURE` sub-report (GF9)
of OSPI Form F-195 Budget.

Layout (typically 2-4 pages, one row per program, sections grouped
by program family):

  Column headers (3 lines):
      Total (0) (1) (2) (3) (4) (5) (7) (8) (9)
      Object Debit Credit Cert. Class. Employee Supplies/ Purchased Travel Capital
      Program Transfer Transfer Salaries Salaries Benefits Materials Services Outlay

  Per-program row: `NN | <label> <total> <val_0> <val_1> ... <val_9>` (up to 10 values)
  Per-group TOTAL row: `TOTAL <group> <total> <val_0> ... <val_9>`

Object code 6 is deliberately skipped -- the 9 object columns are
(0, 1, 2, 3, 4, 5, 7, 8, 9).

**Uses positional column-anchor extraction** (`extract_words` +
column x-anchors set from the header row `Total (0) (1) (2) ...`).
Reason: the form leaves the Credit Transfer column (Object 1) blank
when a program has no credit transfer, so trailing-N-token parsing
mis-aligns values against the wrong columns. Positional binning
places each value word into its correct column regardless of blanks.

Section groups (matching `fiscal_f195_budget[expenditure_by_program]`)
are inferred from the per-group `TOTAL <group>` rows since GF9's page
layout doesn't emit standalone section-header rows. `section_seq`
tracks section order as they appear on the pages.
"""

import logging
import re
from typing import Iterator, List, Optional

from ..filename import FiscalFilename
from .common import parse_decimal, normalize_pdf_text


logger = logging.getLogger(__name__)


_TITLE = "PROGRAM SUMMARY BY OBJECT OF EXPENDITURE"

# TOTAL row -> (section slug, canonical item_label, per-group code).
# Note: the TOTAL label wraps across multiple physical lines on GF9
# ("TOTAL REGULAR" + "INSTRUCTION" on the next line), so the pattern
# only anchors on the leading distinctive tokens.
_TOTAL_RES = [
    (re.compile(r"^TOTAL\s+REGULAR\b", re.IGNORECASE),
     "regular_instruction", "TOTAL REGULAR INSTRUCTION", "00"),
    (re.compile(r"^TOTAL\s+FEDERAL\s+SPECIAL\b", re.IGNORECASE),
     "federal_special_purpose", "TOTAL FEDERAL SPECIAL PURPOSE FUNDING", "10"),
    (re.compile(r"^TOTAL\s+FEDERAL\s+STIMULUS\b", re.IGNORECASE),
     "federal_stimulus", "TOTAL FEDERAL STIMULUS", "10"),
    (re.compile(r"^TOTAL\s+SPECIAL\b", re.IGNORECASE),
     "special_education_instruction", "TOTAL SPECIAL EDUCATION INSTRUCTION", "20"),
    (re.compile(r"^TOTAL\s+VOCATIONAL\b", re.IGNORECASE),
     "vocational_instruction", "TOTAL VOCATIONAL EDUCATION INSTRUCTION", "30"),
    (re.compile(r"^TOTAL\s+SKILLS?\s+CENTER\b", re.IGNORECASE),
     "skill_center_instruction", "TOTAL SKILL CENTER INSTRUCTION", "40"),
    (re.compile(r"^TOTAL\s+COMPENSATORY\b", re.IGNORECASE),
     "compensatory_education", "TOTAL COMPENSATORY EDUCATION INSTRUCTION", "50 and 60"),
    (re.compile(r"^TOTAL\s+OTHER\s+INSTRUCTIONAL\b", re.IGNORECASE),
     "other_instructional_programs", "TOTAL OTHER INSTRUCTIONAL PROGRAMS", "70"),
    (re.compile(r"^TOTAL\s+COMMUNITY\b", re.IGNORECASE),
     "community_services", "TOTAL COMMUNITY SERVICES", "80"),
    (re.compile(r"^TOTAL\s+SUPPORT\b", re.IGNORECASE),
     "support_services", "TOTAL SUPPORT SERVICES", "90"),
]
_GRAND_TOTAL_RE = re.compile(
    r"^(?:TOTAL\s+PROGRAM\s+EXPENDITURES\b|OBJECT\s+TOTALS\b)",
    re.IGNORECASE
)

# Column-header row (used to derive column anchors positionally).
_HEADER_COLUMN_MARKER = "Total (0) (1) (2) (3) (4) (5) (7) (8) (9)"

# Program code prefix.
_PROGRAM_CODE_RE = re.compile(r"^(\d{2})\s*\|\s*(.*)$")

# Value token.
_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$")

# Positional tolerances.
_COL_TOLERANCE = 12.0
_Y_TOLERANCE = 2.5

_FOOTER_RE = re.compile(r"^Form\s+F-195\s+Page\s+\d", re.IGNORECASE)


# Program-code -> section slug. Derived from the OSPI program list
# (matches GF8 layout). Used to route detail rows into the correct
# section when the TOTAL boundary hasn't been seen yet.
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


# Per-section per-group TOTAL code (used to route bare-`TOTAL`-labeled
# rows to the correct group code).
_SECTION_TO_TOTAL_CODE = {
    "regular_instruction":           "00",
    "federal_special_purpose":       "10",
    "federal_stimulus":              "10",
    "special_education_instruction": "20",
    "vocational_instruction":        "30",
    "skill_center_instruction":      "40",
    "compensatory_education":        "50 and 60",
    "other_instructional_programs":  "70",
    "community_services":            "80",
    "support_services":              "90",
}


def _group_rows(words, y_tol=_Y_TOLERANCE):
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


def _parse_value(vtext):
    if not vtext:
        return None
    return parse_decimal(vtext)


def _match_total(label_text: str):
    for pat, section, canonical_label, code in _TOTAL_RES:
        if pat.match(label_text):
            return section, canonical_label, code
    if _GRAND_TOTAL_RE.match(label_text):
        return "summary", "TOTAL PROGRAM EXPENDITURES", "total_program_expenditures"
    return None


def parse_f195_program_summary_by_object_pdf(info: FiscalFilename) -> Iterator[dict]:
    import pdfplumber

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f195_program_summary_by_object",
    }

    rows_out: List[dict] = []
    entered = False

    # First pass: collect all GF9 pages' grouped rows, and discover
    # column anchors from the first row with 10 numeric value tokens.
    # Two-pass extraction lets us apply anchors uniformly across all
    # pages (a small district's first GF9 page may lack a 10-value row,
    # but the grand-total row on the last page always has 10).
    pages_to_process: List[List[List[dict]]] = []
    column_anchors: Optional[List[float]] = None

    with pdfplumber.open(info.path) as pdf:
        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            if _TITLE not in text:
                if entered:
                    break
                continue
            entered = True

            words = page.extract_words(use_text_flow=True)
            if not base["district"]:
                banner = " ".join(w["text"] for w in words[:30])
                m = re.search(
                    r"(.+?)\s+School\s+District\s+No\.?\s*\d+", banner
                )
                if m:
                    base["district"] = re.sub(
                        r"\s+", " ", m.group(1)
                    ).strip()

            grouped = _group_rows(words)
            pages_to_process.append(grouped)

            # Scan for 10-value row.
            if column_anchors is None:
                for row in grouped:
                    value_words = [w for w in row
                                   if _VALUE_TOKEN_RE.match(w["text"])
                                   and w["x0"] >= 100]
                    if len(value_words) == 10:
                        column_anchors = [w["x1"] for w in value_words]
                        break

    if column_anchors is None:
        # No 10-value row across the entire PDF. This is very rare --
        # skip file rather than emit rows with unknown column alignment.
        logger.warning(
            "%s: GF9 has no 10-value row; skipping file",
            info.path.name,
        )
        return

    # Section-tracking state: use the last detail row's program-code
    # section to route bare-`TOTAL`-prefix rows (e.g. compensatory
    # education's TOTAL row prints just `TOTAL <values>` because the
    # form wraps the group name to the next line, which my y-grouping
    # doesn't merge back onto the value row).
    current_section: Optional[str] = None

    for grouped in pages_to_process:
            for row in grouped:
                text_row = " ".join(w["text"] for w in row).strip()
                if not text_row:
                    continue
                if text_row == _TITLE:
                    continue
                if _FOOTER_RE.match(text_row):
                    continue

                # Value words: numeric tokens in the value region
                # (x0 > program-label region).
                value_words = [w for w in row
                               if _VALUE_TOKEN_RE.match(w["text"])
                               and w["x0"] >= 100]
                if not value_words:
                    continue

                # Label = tokens before the first value word.
                first_value_x0 = min(w["x0"] for w in value_words)
                label_words = [w for w in row if w["x0"] < first_value_x0]
                label_text = re.sub(
                    r"\s+", " ",
                    " ".join(w["text"] for w in label_words).strip()
                )
                if not label_text:
                    continue

                # Classify.
                is_total = False
                program_code: Optional[str] = None
                item_label: str = ""
                section: Optional[str] = None

                # Classification: TOTAL rows vs detail rows.
                # The compensatory-education TOTAL row prints only
                # `TOTAL` before its values (the group name wraps to
                # the next physical line, which y-grouping doesn't
                # merge). Federal Special Purpose / Federal Stimulus /
                # Special Education Instruction likewise print
                # shortened labels like `TOTAL FEDERAL`,
                # `TOTAL SPECIAL`. Route by whichever regex matches;
                # for the bare `TOTAL` case, route by `current_section`
                # (inferred from the most recent detail row's program
                # code).
                classified = False
                if (label_text.upper().startswith("TOTAL")
                    or label_text.upper().startswith("OBJECT TOTALS")):
                    total_match = _match_total(label_text)
                    if total_match is not None:
                        section, item_label, program_code = total_match
                        is_total = True
                        if section != "summary":
                            section = "summary"
                        classified = True
                    elif current_section is not None:
                        # Shortened / bare `TOTAL` label
                        # (e.g. `TOTAL FEDERAL`, `TOTAL SKILL`, or just
                        # `TOTAL`) -- the group name wraps to the next
                        # physical line, which y-grouping doesn't
                        # merge. Route by current section.
                        section = "summary"
                        program_code = _SECTION_TO_TOTAL_CODE.get(
                            current_section, "TOTAL"
                        )
                        item_label = f"TOTAL (group={current_section})"
                        is_total = True
                        classified = True

                if not classified:
                    # Program-code detail row.
                    m = _PROGRAM_CODE_RE.match(label_text)
                    if m is None:
                        continue
                    program_code = m.group(1)
                    item_label = m.group(2).strip()
                    section = _PROGRAM_CODE_TO_SECTION.get(program_code)
                    if section is None:
                        # Unknown program code -- happens rarely on
                        # newer program codes not in our map. Route
                        # to `unknown` and let TODO surface it.
                        section = "unknown"
                    current_section = section

                # Bin each value word into columns 0..9 (Total is col 0,
                # object 0 is col 1, ..., object 9 is col 9).
                binned: List[Optional[dict]] = [None] * 10
                for vw in value_words:
                    idx = _closest_column(vw["x1"], column_anchors)
                    if idx is not None and binned[idx] is None:
                        binned[idx] = vw

                rows_out.append({
                    **base,
                    "section": section,
                    "program_code": program_code,
                    "is_total": is_total,
                    "item_label": item_label,
                    "object_total":               _parse_value(binned[0]["text"]) if binned[0] else None,
                    "object_0_debit_transfer":    _parse_value(binned[1]["text"]) if binned[1] else None,
                    "object_1_credit_transfer":   _parse_value(binned[2]["text"]) if binned[2] else None,
                    "object_2_cert_salaries":     _parse_value(binned[3]["text"]) if binned[3] else None,
                    "object_3_class_salaries":    _parse_value(binned[4]["text"]) if binned[4] else None,
                    "object_4_employee_benefits": _parse_value(binned[5]["text"]) if binned[5] else None,
                    "object_5_supplies_materials": _parse_value(binned[6]["text"]) if binned[6] else None,
                    "object_7_purchased_services": _parse_value(binned[7]["text"]) if binned[7] else None,
                    "object_8_travel":            _parse_value(binned[8]["text"]) if binned[8] else None,
                    "object_9_capital_outlay":    _parse_value(binned[9]["text"]) if binned[9] else None,
                })

    # Dedup by logical key.
    seen = {}
    for r in rows_out:
        seen[(r["section"], r["program_code"])] = r
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
