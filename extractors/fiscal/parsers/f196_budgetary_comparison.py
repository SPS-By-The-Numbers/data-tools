"""Parse the Budgetary Comparison Schedule sub-report of OSPI F-196
All Pages PDFs.

Each F-196 All Pages PDF includes the Budgetary Comparison Schedule as
a contiguous block of ~10 pages: 2 pages per fund x 5 funds (General,
ASB, Debt Service, Capital Projects, Transportation Vehicle). Each
2-page block prints:

  Page 1: REVENUES (Local/State/Federal/Other) -> TOTAL REVENUES
          EXPENDITURES
            CURRENT (Regular Instruction, Special Education, ...)
            CAPITAL OUTLAY (Sites, Building, Equipment, ...)
            DEBT SERVICE (Bond/Levy, Principal, Interest and Other Charges)
          TOTAL EXPENDITURES
          REVENUES OVER (UNDER) EXPENDITURES        (sometimes wraps to p2)
  Page 2: OTHER FINANCING SOURCES (USES) detail rows
          TOTAL OTHER FINANCING SOURCES (USES)
          EXCESS OF REVENUES/OTHER FINANCING SOURCES OVER (UNDER) ...
          BEGINNING TOTAL FUND BALANCE
          Prior Year(s) Corrections or Restatements (or 'Accounting Changes
            and Error Corrections' in 2024-25+)
          ENDING TOTAL FUND BALANCE

The 3 printed columns are FINAL BUDGET / ACTUAL / VARIANCE
(Variance = Final Budget - Actual, signed POSITIVE/NEGATIVE per the
form's convention -- positive = favorable, negative = unfavorable).

Parsing quirks specific to this sub-report:

  1. **pdfplumber column-overlay bug**. On some pages the column header
     'Final Budget' text renders at the same y as a value row, and the
     default `extract_words()` merges chars: e.g. on Seattle 2018-19
     Capital Projects page 2, the variance value `85,307,151.46`
     overlays the 'Final Budget' header and emerges as
     `F8i5n,a3l0 7B,u1d5g1e.t4 6`. We work around by calling
     `extract_words(use_text_flow=True)` which follows the natural
     text-flow order from the PDF content stream and separates the
     two streams cleanly.
  2. **Per-fund page-2 layout drift**. The 'REVENUES OVER (UNDER)
     EXPENDITURES' summary row sits at the end of page 1 on some funds
     (older vintages, smaller funds) and at the top of page 2 on others
     (Capital Projects, all funds in 2024-25+). The parser processes
     both pages as one logical block per fund and emits rows wherever
     they appear.
  3. **No printed account codes**. Unlike the Report of Revenues sub-
     report, this form prints only labels (Local, State, Regular
     Instruction, Principal, ...) -- no 4-digit OSPI codes. Item codes
     are slugs derived from the labels.
  4. **Variable item presence per fund**. The form prints ALL of CURRENT/
     CAPITAL OUTLAY/DEBT SERVICE items on every fund's expenditures
     page even when most are blank for that fund (ASB has only
     student_activities_other populated; Capital Projects has only
     CAPITAL OUTLAY populated; etc). The parser emits rows for the
     items it sees on the form regardless of blanks; consumers see
     NULL `value` for unprinted cells.
  5. **'Prior Year(s) Corrections or Restatements' row omits the
     variance column**. The variance is always 0 so the form prints
     only Final Budget + Actual. The parser emits the row with
     `column_kind='variance'`, `value=NULL`.
  6. **Label drift**. 'Prior Year(s) Corrections or Restatements' ->
     'Accounting Changes and Error Corrections' in 2024-25+ vintages.
     Item code 'corrections_or_restatements' is used for both
     (consumers join on item_code, not label).
  7. **Tribal compact schools use 'E.S.D. SPI'**. ~44 schools (CCDDD
     ending in 9XX) sit under direct OSPI oversight; the sub-report
     title regex uses `\\w+` after E.S.D. to match either form.
"""

import logging
import re
from typing import Iterator, List, Optional, Tuple

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_FUND_ORDER = [
    "general", "asb", "debt_service", "capital_projects", "transportation_vehicle",
]

# Match the sub-report banner. \w+ after E.S.D. handles tribal schools' SPI.
_SUBREPORT_TITLE_RE = re.compile(
    r"E\.S\.D\.\s*\w+\s+Budgetary\s+Comparison\s+Schedule",
    re.IGNORECASE,
)

# Page-title -> fund. The fund name appears either on the title line
# (2024-25+: 'Budgetary Comparison Schedule - General Fund') or on the
# COUNTY line (2013-14 through 2023-24: 'COUNTY: 17 King General Fund').
_FUND_PATTERNS = [
    (re.compile(r"Associated\s+Student\s+Body\s+Fund", re.IGNORECASE), "asb"),
    (re.compile(r"Debt\s+Service\s+Fund", re.IGNORECASE),            "debt_service"),
    (re.compile(r"Capital\s+Projects\s+Fund", re.IGNORECASE),        "capital_projects"),
    (re.compile(r"Transportation\s+Vehicle\s+Fund", re.IGNORECASE),  "transportation_vehicle"),
    # General Fund last because the other names also contain 'Fund' and we
    # match top-to-bottom.
    (re.compile(r"\bGeneral\s+Fund\b", re.IGNORECASE),               "general"),
]

# Section + sub-section header detection. Detection order matters --
# 'EXPENDITURES' is a prefix of 'TOTAL EXPENDITURES', so the TOTAL form
# is checked first.
#
# Format: (regex, section, sub_section). sub_section is "" except for
# the three expenditures sub-headers.
_SECTION_HEADERS = [
    (re.compile(r"^REVENUES\s*:\s*$",                             re.IGNORECASE), "revenues",                       ""),
    (re.compile(r"^EXPENDITURES\s*$",                             re.IGNORECASE), "expenditures",                   ""),
    (re.compile(r"^CURRENT\s*:\s*$",                              re.IGNORECASE), "expenditures",                   "current"),
    (re.compile(r"^CAPITAL\s+OUTLAY\s*:\s*$",                     re.IGNORECASE), "expenditures",                   "capital_outlay"),
    (re.compile(r"^DEBT\s+SERVICE\s*:\s*$",                       re.IGNORECASE), "expenditures",                   "debt_service"),
    (re.compile(r"^OTHER\s+FINANCING\s+SOURCES\s*\(USES\)\s*:?\s*$",
                                                                  re.IGNORECASE), "other_financing_sources_uses",   ""),
]

# Item labels -> canonical (section, sub_section, item_code, is_section_total).
# This drives the row-classification logic.
_ITEM_RULES: List[Tuple[re.Pattern, str, str, str, bool]] = [
    # REVENUES detail
    (re.compile(r"^Local$",   re.IGNORECASE), "revenues", "", "local",   False),
    (re.compile(r"^State$",   re.IGNORECASE), "revenues", "", "state",   False),
    (re.compile(r"^Federal$", re.IGNORECASE), "revenues", "", "federal", False),
    (re.compile(r"^Other$",   re.IGNORECASE), "revenues", "", "other",   False),
    (re.compile(r"^TOTAL\s+REVENUES$", re.IGNORECASE), "summary", "", "total_revenues", True),

    # EXPENDITURES CURRENT detail
    (re.compile(r"^Regular\s+Instruction$",        re.IGNORECASE), "expenditures", "current", "regular_instruction",         False),
    (re.compile(r"^Special\s+Education$",          re.IGNORECASE), "expenditures", "current", "special_education",           False),
    (re.compile(r"^Vocational\s+Education$",       re.IGNORECASE), "expenditures", "current", "vocational_education",        False),
    (re.compile(r"^Skill\s+Center$",               re.IGNORECASE), "expenditures", "current", "skill_center",                False),
    (re.compile(r"^Compensatory\s+Programs$",      re.IGNORECASE), "expenditures", "current", "compensatory_programs",       False),
    (re.compile(r"^Other\s+Instructional\s+Programs$",
                                                  re.IGNORECASE), "expenditures", "current", "other_instructional_programs",False),
    (re.compile(r"^Federal\s+Stimulus(\s+COVID-19)?$",
                                                  re.IGNORECASE), "expenditures", "current", "federal_stimulus_covid_19",   False),
    (re.compile(r"^Community\s+Services$",         re.IGNORECASE), "expenditures", "current", "community_services",          False),
    (re.compile(r"^Support\s+Services$",           re.IGNORECASE), "expenditures", "current", "support_services",            False),
    (re.compile(r"^Student\s+Activities/Other$",   re.IGNORECASE), "expenditures", "current", "student_activities_other",    False),

    # EXPENDITURES CAPITAL OUTLAY detail
    (re.compile(r"^Sites$",                        re.IGNORECASE), "expenditures", "capital_outlay", "sites",                False),
    (re.compile(r"^Building$",                     re.IGNORECASE), "expenditures", "capital_outlay", "building",             False),
    (re.compile(r"^Equipment$",                    re.IGNORECASE), "expenditures", "capital_outlay", "equipment",            False),
    (re.compile(r"^Instructional\s+Technology$",   re.IGNORECASE), "expenditures", "capital_outlay", "instructional_technology", False),
    (re.compile(r"^Energy$",                       re.IGNORECASE), "expenditures", "capital_outlay", "energy",               False),
    (re.compile(r"^Sales\s+and\s+Lease$",          re.IGNORECASE), "expenditures", "capital_outlay", "sales_and_lease",      False),
    (re.compile(r"^Transportation\s+Equipment$",   re.IGNORECASE), "expenditures", "capital_outlay", "transportation_equipment", False),
    # 'Other' under CAPITAL OUTLAY -- ambiguous with 'Other' under REVENUES.
    # We rely on the current section/sub_section tracker rather than a
    # global label rule for these. See `_classify_item`.

    # EXPENDITURES DEBT SERVICE detail
    (re.compile(r"^Bond/Levy\s+Issuance(\s+and/or\s+Election)?$",
                                                  re.IGNORECASE), "expenditures", "debt_service", "bond_levy_issuance_election", False),
    (re.compile(r"^Principal$",                    re.IGNORECASE), "expenditures", "debt_service", "principal",              False),
    (re.compile(r"^Interest\s+and\s+Other\s+Charges$",
                                                  re.IGNORECASE), "expenditures", "debt_service", "interest_and_other_charges", False),

    (re.compile(r"^TOTAL\s+EXPENDITURES$", re.IGNORECASE), "summary", "", "total_expenditures", True),

    # Net of revenues-expenditures
    (re.compile(r"^REVENUES\s+OVER\s+\(UNDER\)\s+EXPENDITURES$",
                                                  re.IGNORECASE), "summary", "", "revenues_over_under_expenditures", False),

    # OTHER FINANCING SOURCES (USES) detail
    (re.compile(r"^Bond\s+Sales\s+and\s+Refunding\s+Bond\s+Sales$",
                                                  re.IGNORECASE), "other_financing_sources_uses", "", "bond_sales_and_refunding_bond_sales", False),
    (re.compile(r"^Long-Term\s+Financing$",        re.IGNORECASE), "other_financing_sources_uses", "", "long_term_financing",  False),
    (re.compile(r"^Transfers\s+In$",               re.IGNORECASE), "other_financing_sources_uses", "", "transfers_in",         False),
    (re.compile(r"^Transfers\s+Out\s*\(GL\s*536\)$",
                                                  re.IGNORECASE), "other_financing_sources_uses", "", "transfers_out",        False),
    (re.compile(r"^Other\s+Financing\s+Uses\s*\(GL\s*535\)$",
                                                  re.IGNORECASE), "other_financing_sources_uses", "", "other_financing_uses", False),

    (re.compile(r"^TOTAL\s+OTHER\s+FINANCING\s+SOURCES\s*\(USES\)$",
                                                  re.IGNORECASE), "summary", "", "total_other_financing_sources_uses", True),

    # Net of all above (multi-line label captured by main parser, this matches the joined label)
    (re.compile(r"^EXCESS\s+OF\s+REVENUES/OTHER\s+FINANCING\s+SOURCES\s+OVER\s+\(UNDER\)(\s+EXPENDITURES\s+AND\s+OTHER\s+FINANCING\s+USES)?$",
                                                  re.IGNORECASE), "summary", "", "excess_over_under", False),

    # FUND BALANCE rows
    (re.compile(r"^BEGINNING\s+TOTAL\s+FUND\s+BALANCE$",
                                                  re.IGNORECASE), "fund_balance", "", "beginning_total_fund_balance", False),
    (re.compile(r"^Prior\s+Year\(s\)\s+Corrections\s+or\s+Restatements$",
                                                  re.IGNORECASE), "fund_balance", "", "corrections_or_restatements", False),
    (re.compile(r"^Accounting\s+Changes\s+and\s+Error\s+Corrections$",
                                                  re.IGNORECASE), "fund_balance", "", "corrections_or_restatements", False),
    (re.compile(r"^ENDING\s+TOTAL\s+FUND\s+BALANCE$",
                                                  re.IGNORECASE), "fund_balance", "", "ending_total_fund_balance", False),
]

# Item labels that REQUIRE the current section/sub_section context to
# disambiguate (because the same label appears in multiple places).
_CONTEXTUAL_ITEMS = {
    ("revenues", "", "Other"): "other",
    ("expenditures", "capital_outlay", "Other"): "other",
}

# Column header detection. Used to suppress header tokens that may
# survive the text-flow extraction.
_COLUMN_HEADER_TOKENS = {
    "FINAL", "BUDGET", "ACTUAL", "(NEGATIVE)", "POSITIVE",
    "Variance", "with", "Final", "Budget",
}

# Tokens that should never reach the item label space (page noise).
_PAGE_HEADER_PREFIXES = (
    "REPORT F196", "E.S.D.", "COUNTY:", "RUN:", "RUN", "Page",
    "For the Year Ended", "For The Year Ended",
)

# Value-parsing regexes mirror f196_revenues.
_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")
_SIGN_PLACEHOLDER_RE = re.compile(r"^-$")

_COL_TOLERANCE = 8.0
_Y_TOLERANCE = 2.0
_WRAP_FRAGMENT_MAX_Y_GAP = 14.0

_COLUMN_KINDS = ["final_budget", "actual", "variance"]


def parse_f196_budgetary_comparison_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_budgetary_comparison",
    }

    with pdfplumber.open(info.path) as pdf:
        sub_pages: List[int] = []
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if _SUBREPORT_TITLE_RE.search(text):
                sub_pages.append(i)
            elif sub_pages:
                break

        if not sub_pages:
            return

        # District name from any sub-report page banner.
        first_words = pdf.pages[sub_pages[0]].extract_words(use_text_flow=True)
        d = _district_from_words(first_words)
        if d:
            base["district"] = d

        # Group pages by fund (each fund's banner appears on both its pages).
        # We iterate pages in order and emit; the current fund is updated when
        # the page title indicates a new fund.
        column_anchors = _find_column_anchors(pdf, sub_pages)
        if column_anchors is None:
            logger.warning(
                "no 3-value anchor row found in Budgetary Comparison for %s; "
                "skipping",
                base["_source"],
            )
            return

        # Per-fund state. State resets when the fund changes.
        state = _ParserState()
        current_fund: Optional[str] = None
        for pg_idx in sub_pages:
            words = pdf.pages[pg_idx].extract_words(use_text_flow=True)
            page_fund = _fund_for_page(words)
            if page_fund is not None and page_fund != current_fund:
                # Flush any pending state for the previous fund.
                state.flush_suffix_into_pending()
                for r in state.emit_pending():
                    yield r
                state.reset()
                current_fund = page_fund
            if current_fund is None:
                continue
            yield from _parse_page(words, base, current_fund, state,
                                   column_anchors)

        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r


# ---- internal helpers ------------------------------------------------------


class _ParserState:
    def __init__(self):
        self.current_section: Optional[str] = None
        self.current_sub_section: str = ""
        self.label_buf: List[str] = []
        self.pending_rows: Optional[List[dict]] = None
        self.pending_wrap_meta: Optional[List[Optional[dict]]] = None
        self.pending_row_top: Optional[float] = None

    def reset(self):
        self.current_section = None
        self.current_sub_section = ""
        self.label_buf.clear()
        self.pending_rows = None
        self.pending_wrap_meta = None
        self.pending_row_top = None

    def flush_suffix_into_pending(self) -> None:
        if self.pending_rows and self.label_buf:
            suffix = " ".join(self.label_buf).strip()
            if suffix:
                for r in self.pending_rows:
                    joined = (r["item_label"] + " " + suffix).strip()
                    r["item_label"] = re.sub(r"\s+", " ", joined)
        self.label_buf.clear()

    def emit_pending(self):
        rows_out = self.pending_rows or []
        self.pending_rows = None
        self.pending_wrap_meta = None
        self.pending_row_top = None
        return rows_out


def _district_from_words(words) -> Optional[str]:
    text = " ".join(w["text"] for w in words[:30])
    m = re.search(r"REPORT\s+F196\s+(.+?)\s+No\.\s*\d+", text, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _fund_for_page(words) -> Optional[str]:
    """Identify which fund's Budgetary Comparison this page is for.

    With `use_text_flow=True` the page header doesn't always appear in
    the leading words -- text-flow order follows the PDF content stream,
    which can place the title label after the body labels. Search the
    full word list rather than a leading slice.
    """
    text = " ".join(w["text"] for w in words)
    for pat, slug in _FUND_PATTERNS:
        if pat.search(text):
            return slug
    return None


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


def _find_column_anchors(pdf, sub_pages) -> Optional[List[float]]:
    """Find a row with exactly 3 full-value tokens; use their x1 as the
    column anchors. The TOTAL REVENUES row on every fund's page 1 has
    all 3 values populated (no fund leaves them all blank).
    """
    for pg_idx in sub_pages:
        words = pdf.pages[pg_idx].extract_words(use_text_flow=True)
        for row in _group_rows(words):
            full_values = [w for w in row if _FULL_VALUE_RE.match(w["text"])]
            if len(full_values) == 3:
                return [w["x1"] for w in full_values]
    return None


def _is_page_header_row(text: str) -> bool:
    return bool(
        any(text.startswith(p) for p in _PAGE_HEADER_PREFIXES)
        or _SUBREPORT_TITLE_RE.search(text)
        or re.match(r"^Variance\s+with\s*$",   text, re.IGNORECASE)
        or re.match(r"^Final\s+Budget\s*$",    text, re.IGNORECASE)
        or re.match(r"^POSITIVE\s*$",          text, re.IGNORECASE)
        or re.match(r"^FINAL\s+BUDGET\s+ACTUAL\s+\(NEGATIVE\)\s*$",
                    text, re.IGNORECASE)
    )


def _classify_item(label: str, current_section: Optional[str],
                   current_sub_section: str
                   ) -> Optional[Tuple[str, str, str, bool]]:
    """Map an item label to (section, sub_section, item_code, is_section_total).
    Returns None if the label doesn't match any known item.
    """
    # Contextual disambiguation first.
    key = (current_section, current_sub_section, label)
    if key in _CONTEXTUAL_ITEMS:
        return (current_section, current_sub_section, _CONTEXTUAL_ITEMS[key], False)
    for pat, sec, sub, code, is_total in _ITEM_RULES:
        if pat.match(label):
            return (sec, sub, code, is_total)
    return None


def _parse_page(words, base, current_fund: str, state: _ParserState,
                column_anchors: List[float]) -> Iterator[dict]:
    rows = _group_rows(words)

    for row in rows:
        row_top = min(w["top"] for w in row)
        text = " ".join(w["text"] for w in row).strip()
        if not text or _is_page_header_row(text):
            continue

        full_value_words = [w for w in row if _FULL_VALUE_RE.match(w["text"])]
        fragment_words = [w for w in row
                          if _WRAP_FRAGMENT_RE.match(w["text"])
                          and not _FULL_VALUE_RE.match(w["text"])]
        sign_words = [w for w in row if _SIGN_PLACEHOLDER_RE.match(w["text"])]
        label_words = [w for w in row
                       if not _FULL_VALUE_RE.match(w["text"])
                       and not _WRAP_FRAGMENT_RE.match(w["text"])
                       and not _SIGN_PLACEHOLDER_RE.match(w["text"])
                       and w["text"] not in _COLUMN_HEADER_TOKENS]
        label_text = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_words).strip())

        # Section / sub-section header (label-only)?
        if not full_value_words and not fragment_words and not sign_words:
            for pat, sec, sub in _SECTION_HEADERS:
                if pat.match(label_text):
                    state.flush_suffix_into_pending()
                    for r in state.emit_pending():
                        yield r
                    state.current_section = sec
                    if sec == "expenditures" and sub:
                        # sub-section under expenditures
                        state.current_sub_section = sub
                    elif sec == "expenditures":
                        state.current_sub_section = ""
                    else:
                        state.current_sub_section = ""
                    break
            else:
                # Pure label that isn't a section header -- probably a
                # multi-line item-label continuation.
                if label_text:
                    state.label_buf.append(label_text)
            continue

        # Wrap-continuation absorption (same pattern as Phase 1/2a).
        if (
            state.pending_rows is not None
            and state.pending_wrap_meta is not None
            and state.pending_row_top is not None
            and (row_top - state.pending_row_top) <= _WRAP_FRAGMENT_MAX_Y_GAP
        ):
            anchor_for_col = [
                (column_anchors[i]
                 if state.pending_wrap_meta[i] is not None
                    or _is_truncated_value(state.pending_rows[i]["value_text"])
                 else None)
                for i in range(len(_COLUMN_KINDS))
            ]
            absorbed_any = False
            for vw in full_value_words:
                idx = _closest_column_index(vw["x1"], anchor_for_col)
                if idx is None:
                    continue
                meta = state.pending_wrap_meta[idx]
                if meta is None or "sign" not in meta:
                    continue
                merged = meta["sign"] + vw["text"]
                state.pending_rows[idx]["value_text"] = merged
                state.pending_rows[idx]["value"] = parse_decimal(merged)
                state.pending_wrap_meta[idx] = None
                anchor_for_col[idx] = None
                absorbed_any = True
            for frag in fragment_words:
                idx = _closest_column_index(frag["x1"], anchor_for_col)
                if idx is None:
                    continue
                existing = state.pending_rows[idx]["value_text"]
                if not existing:
                    continue
                merged = existing + frag["text"]
                state.pending_rows[idx]["value_text"] = merged
                state.pending_rows[idx]["value"] = parse_decimal(merged)
                state.pending_wrap_meta[idx] = None
                anchor_for_col[idx] = None
                absorbed_any = True
            if absorbed_any:
                if label_text:
                    state.label_buf.append(label_text)
                continue

        # Item row. Need a known item; otherwise treat label as a
        # multi-line continuation suffix.
        classification = _classify_item(label_text, state.current_section,
                                        state.current_sub_section)
        if classification is None:
            if label_text:
                state.label_buf.append(label_text)
            continue

        section, sub_section, item_code, is_section_total = classification

        state.flush_suffix_into_pending()
        for r in state.emit_pending():
            yield r

        new_rows, wrap_meta = _build_value_rows(
            base,
            fund=current_fund,
            section=section,
            sub_section=sub_section,
            item_code=item_code,
            is_section_total=is_section_total,
            item_label=label_text,
            full_value_words=full_value_words,
            sign_words=sign_words,
            column_anchors=column_anchors,
        )
        state.pending_rows = new_rows
        state.pending_wrap_meta = wrap_meta
        state.pending_row_top = row_top


def _build_value_rows(base, fund, section, sub_section, item_code,
                      is_section_total, item_label, full_value_words,
                      sign_words, column_anchors):
    rows: List[dict] = []
    wrap_meta: List[Optional[dict]] = [None] * len(_COLUMN_KINDS)
    for col_idx, anchor in enumerate(column_anchors):
        column_kind = _COLUMN_KINDS[col_idx]
        matched = _closest_value(full_value_words, anchor)
        if matched is None:
            sign = _closest_sign(sign_words, anchor)
            if sign is not None:
                wrap_meta[col_idx] = {"sign": "-"}
            rows.append({
                **base,
                "fund": fund,
                "section": section,
                "sub_section": sub_section,
                "item_code": item_code,
                "column_kind": column_kind,
                "is_section_total": is_section_total,
                "item_label": item_label,
                "value": None,
                "value_text": "",
            })
        else:
            rows.append({
                **base,
                "fund": fund,
                "section": section,
                "sub_section": sub_section,
                "item_code": item_code,
                "column_kind": column_kind,
                "is_section_total": is_section_total,
                "item_label": item_label,
                "value": parse_decimal(matched["text"]),
                "value_text": matched["text"],
            })
    return rows, wrap_meta


def _closest_value(value_words, anchor) -> Optional[dict]:
    best = None
    best_d = _COL_TOLERANCE
    for w in value_words:
        d = abs(w["x1"] - anchor)
        if d <= best_d:
            best = w
            best_d = d
    return best


def _closest_sign(sign_words, anchor) -> Optional[dict]:
    best = None
    best_d = _COL_TOLERANCE
    for w in sign_words:
        d = abs(w["x1"] - anchor)
        if d <= best_d:
            best = w
            best_d = d
    return best


def _closest_column_index(x1: float, anchor_x1s: List[Optional[float]]) -> Optional[int]:
    best_idx = None
    best_d = _COL_TOLERANCE
    for i, a in enumerate(anchor_x1s):
        if a is None:
            continue
        d = abs(x1 - a)
        if d <= best_d:
            best_idx = i
            best_d = d
    return best_idx


def _is_truncated_value(value_text: str) -> bool:
    if not value_text:
        return False
    dot = value_text.rfind(".")
    if dot < 0:
        return False
    return len(value_text) - dot - 1 != 2


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
