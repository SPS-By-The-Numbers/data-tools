"""Parse the F-196 All Pages per-PROGRAM Activity x Object cross-tab
sub-report.

One page per General Fund program (Seattle 2024-25: pp 43+, ~33 pages
per file), each presenting the same 10-column Activity x Object cross-
tab as the F-195 Budget GF9-XX budget side. Layout:

    REPORT F196  Seattle Public Schools No. 001  RUN DATE: 12/9/2025
    E.S.D. 121  PROGRAM 01 - Basic Education    RUN TIME: 12:11:56 AM
    COUNTY: 17 King                              For the Year Ended August 31, 2025
    (0) (1) (2) (3) (4) (5) (7) (8) (9)                <- column-code header
    Debit Credit Cert. Class. Employee Supplies / Purchased  Capital
    Activity Total Transfer Transfer Salaries Salaries Benefits Materials Services Travel Outlay
    21 Supv Inst 13,984,694.56 51,865.80 5,949,583.26 ...
    22 Lrn Resrc 11,788,212.21 2,878.99 8,307,654.49 ...
    ...
    01 Total 489,664,037.00 1,818,907.18 327,772,585.70 33,795,626.69 ...
    Page 43 of 95

Detects per-PROGRAM pages by the `E.S.D. <n> PROGRAM XX - <name>`
banner combined with the Activity Total column header (distinguishes
from the p32-33 rollup which has 'PROGRAM EXPENDITURE SUMMARY').

Wrap-tail handling: 10-figure General Fund totals (Seattle-scale,
~$490M) overflow their column width and wrap the trailing 1-2 digits
to the next visual line at the same x-position. Example:
    27 Teaching 338,232,927.7 1,716,095. 243,934,328.00 ...
    9 68
The `9` and `68` are trailing fragments that merge onto the previous
row at matching x-anchors. Detected as rows containing only 1-3 small
numeric tokens (1-3 digits, no thousands comma) in the value region.

Column values are decimal dollars-and-cents in F-196 (not integer as
in F-195 Budget). No `FTE Program Staff` row (F-196 is actuals; FTE
isn't reported here).
"""

import logging
import re
from typing import Iterator, List, Optional, Tuple

from ..filename import FiscalFilename
from .common import parse_decimal, normalize_pdf_text


logger = logging.getLogger(__name__)


# Page-detection markers.
_ACTIVITY_TOTAL_MARKER = "Activity Total"
# The per-PROGRAM banner: `E.S.D. 121 PROGRAM 01 - Basic Education`.
_PROGRAM_BANNER_LINE_RE = re.compile(
    r"PROGRAM\s+([0-9A-Z]{2})\s*-\s*(.+?)(?=\s+RUN\s+(?:TIME|DATE)|\n|$)",
    re.IGNORECASE,
)
# Rollup title (from f196_program_activity_object) -- exclude those pages.
_ROLLUP_TITLE = "PROGRAM EXPENDITURE SUMMARY"

# Detail row: `NN <activity name>` where NN is a 2-digit activity code
# in the leftmost x0 region.
_ACTIVITY_CODE_RE = re.compile(r"^(\d{2})\s+(.*)$")

# Program-total row: `NN Total <values>` where NN is the current program
# code. We match on the "Total" keyword and validate NN separately.
_PROGRAM_TOTAL_RE = re.compile(
    r"^(\d{2})\s+Total\b", re.IGNORECASE
)

# Value tokens.
_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d{2}$")   # canonical (2 decimals)
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")          # bare 1-3 digit tail
# Value token accepts canonical (`123,456.78`), truncated-with-dot
# (`123,456.`), truncated-with-one-decimal (`123,456.7`), and integer
# (`0` / `123`). The wrap-tail merger fixes truncated forms; the anchor-
# binning treats them as value words either way.
_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d*)?$")

# Footer / boilerplate.
_PAGE_FOOTER_RE = re.compile(r"^Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)
_REPORT_HEADER_RE = re.compile(r"^REPORT\s+F196\b", re.IGNORECASE)
_COUNTY_LINE_RE = re.compile(r"^COUNTY\s*:", re.IGNORECASE)
_ESD_LINE_RE = re.compile(r"^E\.S\.D\.", re.IGNORECASE)
_HEADER_COL_LABEL_RES = [
    re.compile(r"^\(0\)\s+\(1\)", re.IGNORECASE),
    re.compile(r"^Debit\s+Credit\s+Cert", re.IGNORECASE),
    re.compile(r"^Activity\s+Total\s+Transfer", re.IGNORECASE),
]

_Y_TOLERANCE = 2.5
_COL_TOLERANCE = 12.0
_WRAP_MAX_Y_GAP = 14.0

# Program-code -> section slug (mirrors f195_program_summary_by_object
# and f195_program_activity_object_detail).
_PROGRAM_CODE_TO_SECTION = {
    # Regular Instruction
    "01": "regular_instruction",
    "02": "regular_instruction",
    "03": "regular_instruction",
    "09": "regular_instruction",
    # Federal Special Purpose / Federal Stimulus
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
    # Compensatory Education
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


def _row_top(row) -> float:
    return min(w["top"] for w in row)


def _is_boilerplate_row(text: str) -> bool:
    if not text:
        return True
    if _REPORT_HEADER_RE.match(text):
        return True
    if _COUNTY_LINE_RE.match(text):
        return True
    if _ESD_LINE_RE.match(text):
        return True
    if _PAGE_FOOTER_RE.match(text):
        return True
    if "For the Year Ended" in text or "For The Year Ended" in text:
        return True
    if any(pat.match(text) for pat in _HEADER_COL_LABEL_RES):
        return True
    return False


def _is_per_program_page(text: str) -> bool:
    if _ACTIVITY_TOTAL_MARKER not in text:
        return False
    if _ROLLUP_TITLE in text:
        return False
    if not _PROGRAM_BANNER_LINE_RE.search(text):
        return False
    return True


def _extract_program_banner(text: str) -> Optional[Tuple[str, str]]:
    for line in text.split("\n")[:5]:
        m = _PROGRAM_BANNER_LINE_RE.search(line)
        if m:
            return m.group(1).upper(), re.sub(r"\s+", " ", m.group(2).strip())
    return None


_DISTRICT_BANNER_RE = re.compile(
    r"^REPORT\s+F196\s+(.+?)\s+No\.\s*0*\d+", re.IGNORECASE
)


def _extract_district_from_text(text: str) -> str:
    for line in text.split("\n")[:5]:
        m = _DISTRICT_BANNER_RE.match(line)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


_COUNTY_RE = re.compile(r"^COUNTY\s*:\s*\d+\s+(.+?)\s+For\s+(?:the|The)\s+Year", re.IGNORECASE)


def _extract_county_from_text(text: str) -> str:
    for line in text.split("\n")[:6]:
        m = _COUNTY_RE.match(line)
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def _is_continuation_row(row) -> bool:
    """Return True if this row appears to be a wrap continuation of a
    preceding data row -- no label content in the leftmost region, all
    tokens are numeric-ish (either bare fragments like `30`, `96` or
    full-value tokens like `8,513,020.` that overflowed into a wrap
    line).

    Big-district complex rows (e.g. Seattle program 97 Maintenance)
    wrap across THREE visual lines with a mix of tail fragments and
    late-column values that got pushed onto the next line due to
    column overflow. We treat those wrap lines uniformly: no leading
    label word (nothing at x0 < 90), only value/fragment tokens.
    """
    if not row:
        return False
    for w in row:
        # Any label word (x0 in the leftmost region) disqualifies this
        # as a wrap continuation.
        if w["x0"] < 90:
            return False
        # Every token must be a value or fragment; a stray `-` sign or
        # label text disqualifies.
        if not (_WRAP_FRAGMENT_RE.match(w["text"])
                or _VALUE_TOKEN_RE.match(w["text"])):
            return False
    return True


def parse_f196_program_activity_object_detail_pdf(
    info: FiscalFilename,
) -> Iterator[dict]:
    """Yield rows from per-PROGRAM cross-tab pages of one F-196 All
    Pages PDF."""
    import pdfplumber

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_program_activity_object_detail",
    }

    pages_to_process: List[Tuple[List[List[dict]], Optional[Tuple[str, str]]]] = []
    column_anchors: Optional[List[float]] = None

    with pdfplumber.open(info.path) as pdf:
        entered = False
        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            if not _is_per_program_page(text):
                if entered:
                    break
                continue
            entered = True

            if not base["district"]:
                base["district"] = _extract_district_from_text(text)
            if not base["county"]:
                base["county"] = _extract_county_from_text(text)

            words = page.extract_words(use_text_flow=True)
            grouped = _group_rows(words)
            banner = _extract_program_banner(text)
            pages_to_process.append((grouped, banner))

            if column_anchors is None:
                for row in grouped:
                    value_words = [
                        w for w in row
                        if _FULL_VALUE_RE.match(w["text"])
                        and w["x0"] >= 90
                    ]
                    if len(value_words) == 10:
                        column_anchors = [w["x1"] for w in value_words]
                        break

    if not pages_to_process:
        return
    if column_anchors is None:
        logger.warning(
            "%s: F-196 per-PROGRAM has no 10-value row; skipping file",
            info.path.name,
        )
        return

    seen = {}
    current_program: Optional[Tuple[str, str]] = None

    for grouped, banner in pages_to_process:
        if banner is not None:
            current_program = banner
        if current_program is None:
            continue
        program_code, program_label = current_program
        section = _PROGRAM_CODE_TO_SECTION.get(program_code, "unknown")

        # Track the just-emitted row so we can absorb wrap-tail fragments
        # onto its value cells at matching x-anchors.
        pending_row: Optional[dict] = None
        pending_top: Optional[float] = None
        pending_binned: Optional[List[Optional[dict]]] = None
        pending_is_truncated: List[bool] = [False] * 10

        for row in grouped:
            text = _row_text(row)
            if _is_boilerplate_row(text):
                continue

            row_top = _row_top(row)

            # Wrap continuation of a preceding row. Big-district rows
            # (e.g. Seattle program 97) wrap across up to 3 visual
            # lines with a mix of tail fragments AND late-column full-
            # value tokens. Handle both cases positionally.
            if (pending_row is not None
                    and pending_top is not None
                    and (row_top - pending_top) <= _WRAP_MAX_Y_GAP
                    and _is_continuation_row(row)):
                for tok in row:
                    idx = _closest_column(tok["x1"], column_anchors)
                    if idx is None:
                        continue
                    field_name = _FIELD_ORDER[idx]
                    current_text = pending_row.get("_text_" + field_name)
                    if current_text is None:
                        # Column was blank on the parent row -- fill it
                        # with this token (which may itself be truncated
                        # and get further-merged on the next wrap line).
                        pending_row[field_name] = parse_decimal(tok["text"])
                        pending_row["_text_" + field_name] = tok["text"]
                        pending_is_truncated[idx] = _is_truncated(tok["text"])
                        # Extend the wrap-anchor y so a downstream tail
                        # fragment can still merge onto this new value.
                        pending_top = row_top
                    elif pending_is_truncated[idx]:
                        # Column value was printed truncated on the
                        # parent -- merge this tail onto it.
                        merged = current_text + tok["text"]
                        pending_row[field_name] = parse_decimal(merged)
                        pending_row["_text_" + field_name] = merged
                        pending_is_truncated[idx] = _is_truncated(merged)
                        pending_top = row_top
                    # else: parent value was already canonical; skip.
                continue

            # A concrete data row (either detail or program_total).
            value_words = [
                w for w in row
                if _VALUE_TOKEN_RE.match(w["text"])
                and w["x0"] >= 90
            ]
            if not value_words:
                # Might be a wrap-tail-with-no-preceding-parent (rare) or
                # just a boilerplate line the filter missed.
                continue

            first_value_x0 = min(w["x0"] for w in value_words)
            label_words = [w for w in row if w["x0"] < first_value_x0]
            label_text = _row_text(label_words)
            if not label_text:
                continue

            # Standalone sign tokens (`-` or `+`) sit at the value-
            # column x-position, separated from their value which may
            # be printed on a wrap line below. Collect them so the
            # binned column can be signed on emit.
            sign_by_col = [None] * 10  # 'neg' | 'pos' | None
            for w in row:
                if w["text"] in ("-", "+") and w["x0"] >= 90:
                    idx = _closest_column(w["x1"], column_anchors)
                    if idx is not None:
                        sign_by_col[idx] = "neg" if w["text"] == "-" else "pos"

            is_program_total = False
            activity_code = ""
            activity_label = ""

            m_total = _PROGRAM_TOTAL_RE.match(label_text)
            if m_total:
                # `NN Total` -- program total row. NN should equal the
                # current program_code; if it doesn't, treat as detail
                # (defensive).
                if m_total.group(1) == program_code:
                    is_program_total = True
                else:
                    # Unusual -- fall through to detail parsing.
                    pass

            if not is_program_total:
                m_act = _ACTIVITY_CODE_RE.match(label_text)
                if m_act is None:
                    continue
                activity_code = m_act.group(1)
                activity_label = re.sub(r"\s+", " ", m_act.group(2).strip())
                # Guard: if the label happens to be `NN Total <label>`
                # for a program other than the current one, skip.

            # Bin each value word into the 10 columns.
            binned: List[Optional[dict]] = [None] * 10
            for vw in value_words:
                idx = _closest_column(vw["x1"], column_anchors)
                if idx is not None and binned[idx] is None:
                    binned[idx] = vw

            row_kind = "program_total" if is_program_total else "detail"
            key = (program_code, row_kind, activity_code)
            if key in seen:
                continue

            def _v(i):
                return parse_decimal(binned[i]["text"]) if binned[i] else None

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
            }
            # Stash per-column source-text so we can wrap-merge later.
            for i, field_name in enumerate(_FIELD_ORDER):
                row_out["_text_" + field_name] = binned[i]["text"] if binned[i] else None

            seen[key] = row_out
            pending_row = row_out
            pending_top = row_top
            pending_binned = binned
            pending_is_truncated = [
                _is_truncated(binned[i]["text"]) if binned[i] else False
                for i in range(10)
            ]
            # Stash the sign vector on the pending row so we apply it
            # after any wrap-merges finish populating the value.
            pending_row["_signs"] = sign_by_col

    for r in seen.values():
        # Apply any collected sign vectors: standalone `-` at a value-
        # column position on the parent row negates whatever value ends
        # up in that column (possibly from a wrap line below).
        signs = r.pop("_signs", None) or [None] * 10
        for i, field_name in enumerate(_FIELD_ORDER):
            if signs[i] == "neg":
                v = r.get(field_name)
                if v is not None and v > 0:
                    r[field_name] = -v
            r.pop("_text_" + field_name, None)
        yield r


_FIELD_ORDER = [
    "activity_total",
    "object_0_debit_transfer",
    "object_1_credit_transfer",
    "object_2_cert_salaries",
    "object_3_class_salaries",
    "object_4_employee_benefits",
    "object_5_supplies_materials",
    "object_7_purchased_services",
    "object_8_travel",
    "object_9_capital_outlay",
]


def _is_truncated(value_text: str) -> bool:
    """A canonical F-196 value has exactly 2 decimal digits.
    Anything else (0 or 1 decimals, or trailing `.`) is a wrapped fragment."""
    if not value_text:
        return False
    dot = value_text.rfind(".")
    if dot < 0:
        return False
    return (len(value_text) - dot - 1) != 2


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
