"""Parse OSPI Form F-195 Budget PDFs (and F-195 Budget Overview).

A single F-195 Budget PDF is a 100-200 page compound document with
~30 distinct sub-reports. This parser handles a growing set of them,
all funneling into the single `fiscal_f195_budget` table (keyed on
`sub_report`):

  - `fund_summary` -- SUMMARY OF X FUND BUDGET (one occurrence per
    fund: General, ASB, Debt Service, Capital Projects, Transportation
    Vehicle).
  - `expenditure_by_program` -- EXPENDITURE BY PROGRAM (GF8).
  - `expenditure_by_object_summary` -- SUMMARY OF GENERAL FUND
    EXPENDITURES BY OBJECT OF EXPENDITURE (GF10).
  - `expenditure_by_activity_summary` -- SUMMARY OF GENERAL FUND
    EXPENDITURES BY ACTIVITY (GF11).
  - `enrollment_and_staff_counts` -- FY ENROLLMENT AND STAFF COUNTS
    (GF1).
  - `financial_summary` -- GENERAL FUND FINANCIAL SUMMARY (Budget
    Summary rollup).

Sub-reports come in two column shapes:

  - `3col`: three trailing value tokens per line (Actual/Budget/Budget
    or Average/Budget/Budget). `pct_of_total` is NULL on all rows.
  - `6col`: six trailing tokens per line, alternating value/pct
    (Actual/%Total/Budget/%Total/Budget/%Total). Emits 3 rows per line
    -- one per data year -- carrying both `value` and `pct_of_total`.

The page-title dispatch drives sub-report detection: only pages whose
title line matches a recognized header are scanned for value lines.
The F-195 Budget Overview also contains most of these sub-reports
across its pages, so this parser runs against both source kinds --
overlap is deduped by the (sub_report, fund, section, item_code,
data_year_offset) key at the end of `parse_f195_budget_pdf`.
"""

import logging
import re
from typing import Iterator, List, Optional, Tuple

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, parse_decimal, read_pdf_lines,
)


logger = logging.getLogger(__name__)


# ---- Per-sub-report configuration ------------------------------------------
#
# Each config carries:
#   - sub_report / fund: dimensions on the emitted rows.
#   - layout: '3col' or '6col'.
#   - column_kinds: list of 3 strings (per data-year column). '6col' rows
#     have an extra pct-of-total token between adjacent value tokens, but
#     we still emit 3 rows per line (one per data year), with pct_of_total
#     as an additional column.
#   - sections: list of (uppercase page-line needle, canonical section slug).
#     Encountering a needle transitions the current section. Order matters
#     only for tie-breaking; matches are exact-string.
#   - default_section: the section slug active before any section marker
#     is seen (used for sub-reports without leading marker rows).
#   - column_kind_re: regex that matches the column-kind header row on
#     the page (drives detection of when we've locked into the layout).
#
# `_PAGE_TITLE_TO_CONFIG` maps the page title line to the config.

_FUND_SUMMARY_SECTIONS = [
    ("REVENUES AND OTHER FINANCING SOURCES", "revenues"),
    ("REVENUES",                              "revenues"),
    ("EXPENDITURES",                          "expenditures"),
    ("BEGINNING FUND BALANCE",                "beginning_fund_balance"),
    ("ENDING FUND BALANCE",                   "ending_fund_balance"),
]

_GF8_SECTIONS = [
    ("REGULAR INSTRUCTION",              "regular_instruction"),
    ("FEDERAL SPECIAL PURPOSE FUNDING",  "federal_special_purpose"),
    ("FEDERAL STIMULUS",                 "federal_stimulus"),
    ("SPECIAL EDUCATION INSTRUCTION",    "special_education_instruction"),
    ("VOCATIONAL EDUCATION INSTRUCTION", "vocational_instruction"),
    ("SKILL CENTER INSTRUCTION",         "skill_center_instruction"),
    ("SKILLS CENTER INSTRUCTION",        "skill_center_instruction"),
    # 2013-14 through ~2018-19 form typo: 'INSTUCTION' (missing R).
    ("COMPENSATORY EDUCATION INSTRUCTION", "compensatory_education"),
    ("COMPENSATORY EDUCATION INSTUCTION",  "compensatory_education"),
    ("OTHER INSTRUCTIONAL PROGRAMS", "other_instructional_programs"),
    ("COMMUNITY SERVICES",           "community_services"),
    ("SUPPORT SERVICES",             "support_services"),
]

_GF11_SECTIONS = [
    ("TEACHING ACTIVITIES",       "teaching_activities"),
    ("TEACHING SUPPORT",          "teaching_support"),
    ("OTHER SUPPORT ACTIVITIES",  "other_support_activities"),
    ("UNIT ADMINISTRATION",       "unit_administration"),
    ("CENTRAL ADMINISTRATION",    "central_administration"),
]

# GF1 section headers include trailing parenthetical guidance ("A. FTE
# ENROLLMENT COUNTS (calculate to two decimal places)") that varies
# across vintages -- match by leading letter + keyword rather than
# exact-string.
_GF1_SECTION_RES = [
    (re.compile(r"^A\.\s+FTE\s+ENROLLMENT\s+COUNTS\b", re.IGNORECASE),
     "enrollment_counts"),
    (re.compile(r"^B\.\s+STAFF\s+COUNTS\b", re.IGNORECASE),
     "staff_counts"),
]

# Column-kind header regexes. '_3COL_KIND_RE' also matches 'Average
# Budget Budget' (used on GF1's enrollment/staff page) and tolerates
# trailing footnote markers ('Average 1/ Budget 2/ Budget 3/').
_3COL_KIND_RE = re.compile(
    r"^\s*(Actual|Average)(?:\s+\d+/)?\s+(Budget)(?:\s+\d+/)?\s+(Budget)(?:\s+\d+/)?\s*$"
)
# The 6-col column-kind header comes in three vintages:
#
# GF10/GF11 (all vintages):
#   'Actual % of Budget % of Budget % of'
# Financial Summary (2020-21+):
#   'Actual % of Total Budget % of Total Budget % of Total'
# Financial Summary (2013-14 through ~2018-19):
#   'Actual Budget (4) Budget (6)'  -- % of Total tokens on the year row
#
# For the 2013-14 form, the '(4)' and '(6)' column-index markers are
# inline with the labels; we tolerate 1-2 parenthesized indices in
# between. The 'Actual [Budget] [Budget]' skeleton is the invariant.
_6COL_KIND_LINE1_RE = re.compile(
    r"^\s*(Actual)(?:\s+%\s+of(?:\s+Total)?)?(?:\s+\(\d\))?\s+"
    r"(Budget)(?:\s+%\s+of(?:\s+Total)?)?(?:\s+\(\d\))?\s+"
    r"(Budget)(?:\s+%\s+of(?:\s+Total)?)?(?:\s+\(\d\))?\s*$"
)


def _mk_3col(sub_report, fund, sections, default_section=None,
             column_kinds=("actual", "budget", "budget")):
    return {
        "sub_report": sub_report,
        "fund": fund,
        "layout": "3col",
        "column_kinds": list(column_kinds),
        "sections": list(sections),
        "default_section": default_section,
    }


def _mk_6col(sub_report, fund, sections, default_section=None,
             column_kinds=("actual", "budget", "budget")):
    return {
        "sub_report": sub_report,
        "fund": fund,
        "layout": "6col",
        "column_kinds": list(column_kinds),
        "sections": list(sections),
        "default_section": default_section,
    }


_PAGE_TITLE_TO_CONFIG = {
    # ---- fund_summary (all 5 funds) ----
    "SUMMARY OF GENERAL FUND BUDGET":
        _mk_3col("fund_summary", "general", _FUND_SUMMARY_SECTIONS),
    "SUMMARY OF ASSOCIATED STUDENT BODY FUND BUDGET":
        _mk_3col("fund_summary", "asb", _FUND_SUMMARY_SECTIONS),
    "SUMMARY OF DEBT SERVICE FUND BUDGET":
        _mk_3col("fund_summary", "debt_service", _FUND_SUMMARY_SECTIONS),
    "SUMMARY OF CAPITAL PROJECTS FUND BUDGET":
        _mk_3col("fund_summary", "capital_projects", _FUND_SUMMARY_SECTIONS),
    "SUMMARY OF TRANSPORTATION VEHICLE FUND BUDGET":
        _mk_3col("fund_summary", "transportation_vehicle", _FUND_SUMMARY_SECTIONS),
    # ---- GF8 EXPENDITURE BY PROGRAM ----
    "EXPENDITURE BY PROGRAM":
        _mk_3col("expenditure_by_program", "general", _GF8_SECTIONS),
    # ---- GF10 SUMMARY OF GF EXPENDITURES BY OBJECT ----
    "SUMMARY OF GENERAL FUND EXPENDITURES BY OBJECT OF EXPENDITURE":
        _mk_6col("expenditure_by_object_summary", "general", [],
                 default_section="objects"),
    # ---- GF11 SUMMARY OF GF EXPENDITURES BY ACTIVITY ----
    "SUMMARY OF GENERAL FUND EXPENDITURES BY ACTIVITY":
        _mk_6col("expenditure_by_activity_summary", "general", _GF11_SECTIONS),
    # ---- GF1 FY ENROLLMENT AND STAFF COUNTS ----
    "FY ENROLLMENT AND STAFF COUNTS":
        dict(_mk_3col("enrollment_and_staff_counts", "general", [],
                      column_kinds=("average", "budget", "budget")),
             sections_re=_GF1_SECTION_RES),
    # ---- General Fund Financial Summary ----
    # Mixed shape: first 2 sub-sections carry 3 trailing values, last 3
    # sub-sections carry 6. Handled by dynamic-length value detection.
    # The sub-section markers are matched via a specialized regex list
    # (see `_match_financial_summary_section`) inside the parse loop.
    "GENERAL FUND FINANCIAL SUMMARY":
        _mk_6col("financial_summary", "general", [], default_section=None),
}


# ---- Line-classification patterns ------------------------------------------

# OSPI account / program / activity code prefix: 2-4 digits, optional
# ' and NN' compound (COMPENSATORY EDUCATION total on GF8 is '50 and 60'),
# optional `|` separator (present on most rows, absent on TVF1
# expenditure rows).
_OSPI_CODE_RE = re.compile(r"^(\d{2,4}(?:\s+and\s+\d{2,4})?)(?:\s+\|)?\s+(.+)$")
_GL_CODE_RE = re.compile(r"^(G\.L\.\d+)\s+(.+)$")
_SECTION_LETTER_RE = re.compile(r"^([A-Z])\.\s+(.+)$")
# Object code, printed as '(0)', '(1)', '(2)', ..., '(9)'. GF10 objects.
_OBJECT_CODE_RE = re.compile(r"^\((\d)\)\s+(.+)$")
# Numbered enrollment/staff items, e.g. '1. Kindergarten', '18. TOTAL K-12'.
_NUMBERED_ITEM_RE = re.compile(r"^(\d{1,2})\.\s+(.+)$")

# Value tokens: signed integers with optional commas / decimals; or an
# 'XXXXX' n/a marker; or a percentage/decimal with fractional digits
# (0.02, -0.05, 43.20, etc). '$-' also occurs as a null marker on some
# older-vintage rows.
_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$|^XXX+$|^\$-$")

# Year-column row on 3-col pages: exactly 3 space-separated YYYY-YYYY.
_3COL_YEAR_RE = re.compile(
    r"^\s*(\d{4}-\d{4})\s+(\d{4}-\d{4})\s+(\d{4}-\d{4})\s*$"
)
# Year-column row on 6-col pages: interleaved 'Total <year>' triples
# (e.g. '2022-2023 Total 2023-2024 Total 2024-2025 Total').
_6COL_YEAR_INLINE_RE = re.compile(
    r"(\d{4}-\d{4})\s+Total\s+(\d{4}-\d{4})\s+Total\s+(\d{4}-\d{4})\s+Total"
)
# 2013-14 Financial Summary year row shape:
#   '2011-2012 (2) % of Total1 2012-2013 % of Total2 2013-2014 % of Total3'
# Three year tokens interleaved with '(N)' column indices, '% of Total<N>'
# labels, or nothing. Captures the 3 years permissively.
_INTERLEAVED_YEAR_RE = re.compile(
    r"(\d{4}-\d{4})\b.*?(\d{4}-\d{4})\b.*?(\d{4}-\d{4})\b"
)

# Page-footer / banner noise lines to ignore.
_FOOTER_RE = re.compile(r"^Form\s+F-195\s+Page\s+\d", re.IGNORECASE)
_FOOTNOTE_LINE_RE = re.compile(r"^\d+/\s")
# Enumeration marker row like '(1) (2) (3)' or '(1) (2) (3) (4) (5) (6)'.
_COLUMN_MARKER_RE = re.compile(r"^\(\d\)(\s+\(\d\))+\s*$")


def _tail_values(tokens: List[str], layout: str):
    """Return the trailing value tokens for a value-bearing row.

    For '3col', expect exactly 3 trailing tokens. For '6col', accept
    either 6 or 3 (the top sub-sections of financial_summary are
    3-token even though the page itself is 6-col).

    For 6-col rows, if a row has 4 or 5 trailing value tokens (a
    2-year data-sparse form -- observed on some vintages of very small
    districts' F-195 filings where the prior-actual column is
    entirely missing), a naive 3-tail match would silently mis-align
    the values against the wrong data years. Reject those rows by
    checking that tokens[-4] is NOT a value token (i.e. the 3-tail
    kind of row has a *label* word 4 back from the end).
    """
    if len(tokens) < 4:
        return None
    if layout == "3col":
        last = tokens[-3:]
        if all(_VALUE_TOKEN_RE.match(t) for t in last):
            return last
        return None
    # 6col: prefer 6-tail; fall back to 3-tail for mixed-shape pages.
    if len(tokens) >= 7:
        last6 = tokens[-6:]
        if all(_VALUE_TOKEN_RE.match(t) for t in last6):
            return last6
    last3 = tokens[-3:]
    if all(_VALUE_TOKEN_RE.match(t) for t in last3):
        # If token[-4] is also a value, we're looking at a 4+ value row
        # in a form where the 6-tail didn't match -- decoding as 3-tail
        # would silently misalign values against the wrong data-year
        # columns. Reject.
        if len(tokens) >= 4 and _VALUE_TOKEN_RE.match(tokens[-4]):
            return None
        return last3
    return None


def _strip_footnote_suffix(label: str) -> str:
    """Drop trailing '1/', '2/', etc. footnote markers."""
    return re.sub(r"\s*\d+/\s*$", "", label).strip()


def _classify_line(label_part: str, sub_report: str
                   ) -> Tuple[str, str, Optional[str]]:
    """Identify (item_code, normalized_label, derived_section) from a
    label prefix.

    `derived_section` is 'summary' only for section-letter total rows
    (A./B./.../H.) in fund_summary. Total detection on other sub-reports
    (GF8/GF10/GF11 per-group totals, financial_summary Total rows, GF1
    K-12 SUBTOTAL / TOTAL) is done downstream by matching the item_label
    against a "TOTAL" keyword.
    """
    s = label_part.strip()
    m = _GL_CODE_RE.match(s)
    if m:
        return m.group(1), _strip_footnote_suffix(m.group(2)), None
    m = _OBJECT_CODE_RE.match(s)
    if m:
        return m.group(1), _strip_footnote_suffix(m.group(2)), None
    m = _SECTION_LETTER_RE.match(s)
    if m:
        # Section-letter total rows are used by fund_summary (A. TOTAL
        # REVENUES, B. TOTAL EXPENDITURES, ...). GF1 also uses A/B as
        # SECTION markers but those are the section-header rows, not
        # value rows -- they're consumed as section markers before
        # reaching this classifier.
        derived = "summary" if sub_report == "fund_summary" else None
        return m.group(1), _strip_footnote_suffix(m.group(2)), derived
    m = _NUMBERED_ITEM_RE.match(s)
    if m and sub_report == "enrollment_and_staff_counts":
        return m.group(1), _strip_footnote_suffix(m.group(2)), None
    m = _OSPI_CODE_RE.match(s)
    if m:
        code = m.group(1).strip()
        return code, _strip_footnote_suffix(m.group(2)), None
    label = _strip_footnote_suffix(s)
    return _slugify_label(label), label, None


def _slugify_label(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", label.lower()).strip("_")


def _is_total_label(label: str) -> bool:
    """Detect a TOTAL / SUBTOTAL row by its stripped-label content.

    Used to route section-group and grand-total rows to `section='summary'`
    on sub-reports that don't use section-letter conventions (all except
    fund_summary).

    Notably careful about mixed-case labels: financial_summary's data
    rows include mixed-case labels like 'Total Revenues and Other
    Financing' or 'Total K-12 FTE Enrollment Counts' -- these are data
    points, NOT summary rollups, so they should stay in their natural
    section. We only accept:
      - all-uppercase 'TOTAL ...' / 'SUBTOTAL ...' rows (GF8/GF10/GF11
        per-group and grand totals -- 'TOTAL REGULAR INSTRUCTION',
        'TOTAL EXPENDITURES', 'TOTAL TEACHING ACTIVITIES', 'TOTAL K-12',
        'SUBTOTAL' from GF1);
      - dashed 'Total - X' rows (financial_summary grand totals like
        'Total - Program Groups', 'Total - Activity Groups', 'Total -
        Objects').
    """
    stripped = label.strip()
    if not stripped:
        return False
    if stripped.startswith("Total - "):
        return True
    if not (stripped.startswith("TOTAL") or stripped.startswith("SUBTOTAL")):
        return False
    # All-uppercase (letters only checked -- digits/spaces/punctuation
    # allowed to accommodate 'TOTAL K-12' etc).
    return stripped == stripped.upper()


def parse_f195_budget_pdf(info: FiscalFilename) -> Iterator[dict]:
    """Yield long-form rows from one F-195 Budget (or Overview) PDF."""
    import pdfplumber

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f195_budget",
    }

    from .common import normalize_pdf_text
    with pdfplumber.open(info.path) as pdf:
        # Active sub-report context, persisted across pages of the same
        # sub-report (some span 2-3 pages).
        cfg: Optional[dict] = None
        section: Optional[str] = None
        year_cols: Optional[List[str]] = None
        column_kinds_actual: Optional[List[str]] = None
        last_emitted_rows: Optional[List[dict]] = None
        label_buf: List[str] = []

        def _flush(rows_out):
            nonlocal last_emitted_rows, label_buf
            if last_emitted_rows and label_buf:
                suffix = re.sub(r"\s+", " ", " ".join(label_buf).strip())
                if suffix:
                    for r in last_emitted_rows:
                        r["item_label"] = re.sub(
                            r"\s+", " ",
                            (r["item_label"] + " " + suffix).strip()
                        )
            label_buf = []
            for r in (last_emitted_rows or []):
                rows_out.append(r)
            last_emitted_rows = None

        rows_out: List[dict] = []

        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            raw_lines = [ln for ln in (l.strip() for l in text.split("\n")) if ln]
            # Note: do NOT apply merge_split_leading_digit here. That helper is
            # for 1191SI's column-fragmented dollar values; on F-195 Budget it
            # would wrongly merge adjacent value tokens whenever the preceding
            # value is a single digit (e.g. '... 634 0 4,362,430' would collapse
            # the trailing '0 4,362,430' into a single token '04,362,430' and
            # the line would silently lose its first value).
            lines = [collapse_numeric_paren_spaces(ln) for ln in raw_lines]
            if not lines:
                continue

            # Page title: ordinarily the third non-empty line ('FY YYYY-YYYY Run:...',
            # district, TITLE). On multi-page sub-reports a 'Continued' line gets
            # inserted between the FY banner and the district name, pushing the
            # title down. Scan the first 6 lines for a recognized title rather
            # than locking to a fixed index.
            page_title = ""
            title_idx = -1
            for j, ln in enumerate(lines[:6]):
                if ln in _PAGE_TITLE_TO_CONFIG:
                    page_title = ln
                    title_idx = j
                    break

            new_cfg = _PAGE_TITLE_TO_CONFIG.get(page_title)
            if new_cfg is None:
                # Non-target page. Drop pending label continuation
                # (footnote spillage); flush any emitted rows.
                label_buf = []
                _flush(rows_out)
                cfg = None
                section = None
                year_cols = None
                column_kinds_actual = None
                continue

            # District name appears one or two lines above the title.
            if not base["district"]:
                for k in range(max(0, title_idx - 2), title_idx):
                    m_dist = re.match(r"^(.*?) School District No\.\d+", lines[k])
                    if m_dist:
                        base["district"] = m_dist.group(1).strip()
                        break

            # If we transition sub-report / fund, flush and reset.
            if (cfg is None
                or cfg["sub_report"] != new_cfg["sub_report"]
                or cfg["fund"] != new_cfg["fund"]):
                label_buf = []
                _flush(rows_out)
                cfg = new_cfg
                section = cfg.get("default_section")
                year_cols = None
                column_kinds_actual = None

            in_footnote_zone = False

            for ln in lines[title_idx + 1:]:
                if _FOOTER_RE.match(ln):
                    continue
                # Standalone footnote text -- enter the footnote zone.
                if _FOOTNOTE_LINE_RE.match(ln):
                    in_footnote_zone = True
                    continue
                if in_footnote_zone:
                    continue

                # Column-kind header row. Try both variants regardless
                # of the config's declared layout -- Financial Summary
                # is 'mixed' (its header names 6 columns but its top
                # sub-sections have 3 trailing values).
                if _3COL_KIND_RE.match(ln) or _6COL_KIND_LINE1_RE.match(ln):
                    column_kinds_actual = list(cfg["column_kinds"])
                    continue

                # Year-column row. Try both the 6-col 'Total'-interleaved
                # form and the bare 3-year form (financial_summary has a
                # 6-col header but uses the bare year row). The row also
                # appears at the top of every continuation page (so
                # unconditionally consume it, don't gate on `year_cols
                # is None` -- otherwise it leaks into label_buf on the
                # 2nd+ page of a multi-page sub-report). The 2013-14
                # Financial Summary intersperses the year triple with
                # inline column indices and 'Total<N>' fragments (see
                # `_INTERLEAVED_YEAR_RE`) -- match that as a last resort
                # after the strict forms, and only for the two 6-col
                # sub-reports so we don't accidentally consume a
                # value-bearing row whose label happens to contain 3
                # year-shaped tokens.
                m6 = _6COL_YEAR_INLINE_RE.search(ln)
                if m6:
                    year_cols = [m6.group(1), m6.group(2), m6.group(3)]
                    continue
                m3 = _3COL_YEAR_RE.match(ln)
                if m3:
                    year_cols = [m3.group(1), m3.group(2), m3.group(3)]
                    continue
                if (cfg["layout"] == "6col"
                    and _tail_values(ln.split(), cfg["layout"]) is None):
                    mI = _INTERLEAVED_YEAR_RE.search(ln)
                    if mI:
                        year_cols = [mI.group(1), mI.group(2), mI.group(3)]
                        continue

                # Section marker (uppercase page-line matching one of
                # the configured section needles).
                matched_section = None
                for needle, name in cfg["sections"]:
                    if ln == needle:
                        matched_section = name
                        break
                if matched_section is None:
                    for pat, name in cfg.get("sections_re", ()):
                        if pat.match(ln):
                            matched_section = name
                            break
                if matched_section is not None:
                    _flush(rows_out)
                    section = matched_section
                    continue

                # Financial-summary sub-section markers span 2 physical
                # lines on older vintages ('ENROLLMENT AND STAFFING' +
                # 'SUMMARY') -- matched via a specialized regex list.
                if cfg["sub_report"] == "financial_summary":
                    fs_section = _match_financial_summary_section(ln)
                    if fs_section is not None:
                        _flush(rows_out)
                        section = fs_section
                        continue

                # Value-bearing line.
                tokens = ln.split()
                tail = _tail_values(tokens, cfg["layout"])
                if tail is None:
                    if _COLUMN_MARKER_RE.match(ln):
                        continue
                    label_buf.append(ln)
                    continue

                _flush(rows_out)

                # Missing-context inference: pdfplumber occasionally
                # renders the column-kind or year row in a shape our
                # regexes don't catch (a specific 2013-14 vintage of
                # GF10/GF11 headers surfaces this most often). Rather
                # than skip the value line, backfill year_cols from
                # info.class_of (offsets -2/-1/0 are stable) and
                # column_kinds_actual from the sub-report config's
                # default.
                if year_cols is None:
                    coy = info.class_of
                    if coy is not None:
                        year_cols = [
                            f"{coy - 3}-{coy - 2}",
                            f"{coy - 2}-{coy - 1}",
                            f"{coy - 1}-{coy}",
                        ]
                if column_kinds_actual is None:
                    column_kinds_actual = list(cfg["column_kinds"])
                if section is None:
                    logger.warning(
                        "%s: value line before section context "
                        "(cfg=%s): %r",
                        info.path.name, cfg["sub_report"], ln,
                    )
                    continue

                label_part = " ".join(tokens[:-len(tail)]).strip()
                if not label_part:
                    continue

                item_code, item_label, derived_section = _classify_line(
                    label_part, cfg["sub_report"]
                )
                if derived_section == "summary":
                    row_section = "summary"
                elif (cfg["sub_report"] != "fund_summary"
                      and _is_total_label(item_label)):
                    row_section = "summary"
                else:
                    row_section = section

                # Split `tail` into (value, pct_of_total) per data year.
                if len(tail) == 6:
                    value_texts = [tail[0], tail[2], tail[4]]
                    pct_texts = [tail[1], tail[3], tail[5]]
                else:
                    value_texts = list(tail)
                    pct_texts = [None, None, None]

                rows = []
                for offset in range(3):
                    year = year_cols[offset]
                    kind = column_kinds_actual[offset]
                    vtext = value_texts[offset]
                    ptext = pct_texts[offset]
                    value = _parse_value(vtext)
                    pct = _parse_value(ptext) if ptext is not None else None
                    rows.append({
                        **base,
                        "sub_report": cfg["sub_report"],
                        "fund": cfg["fund"],
                        "section": row_section,
                        "item_code": item_code,
                        "data_year_offset": offset - 2,
                        "data_school_year": year,
                        "data_class_of": int(year.split("-")[1]),
                        "column_kind": kind,
                        "item_label": item_label,
                        "value": value,
                        "value_text": vtext,
                        "pct_of_total": pct,
                    })
                last_emitted_rows = rows

            # End of page: drop any unapplied wrap continuation.
            label_buf = []

        _flush(rows_out)

    # Dedup by logical key.
    seen = {}
    for r in rows_out:
        key = (r["sub_report"], r["fund"], r["section"],
               r["item_code"], r["data_year_offset"])
        seen[key] = r
    for r in seen.values():
        yield r


# ---- financial_summary sub-section detection -------------------------------
#
# The GENERAL FUND FINANCIAL SUMMARY page has 5 stacked sub-sections. The
# form prints them as uppercase headers, but the label lines wrap across
# 2 physical lines on some vintages (2013-14 splits 'ENROLLMENT AND
# STAFFING\nSUMMARY' and 'EXPENDITURE SUMMARY BY PROGRAM\nGROUPS'). We
# use a bag-of-keywords matcher so a header that spans lines is caught by
# either its top or its bottom fragment.

_FINANCIAL_SUMMARY_SECTIONS = [
    ("enrollment_and_staffing",
     re.compile(r"^ENROLLMENT\s+AND\s+STAFFING(?:\s+SUMMARY)?$", re.IGNORECASE)),
    ("enrollment_and_staffing",
     re.compile(r"^SUMMARY$", re.IGNORECASE)),  # wrap-continuation
    ("financial",
     re.compile(r"^FINANCIAL\s+SUMMARY$", re.IGNORECASE)),
    ("program_groups",
     re.compile(r"^EXPENDITURE\s+SUMMARY\s+BY\s+PROGRAM(?:\s+GROUPS)?$",
                re.IGNORECASE)),
    ("program_groups",
     re.compile(r"^GROUPS$", re.IGNORECASE)),  # wrap-continuation
    ("activity_groups",
     re.compile(r"^EXPENDITURE\s+SUMMARY\s+BY\s+ACTIVITY(?:\s+GROUPS)?$",
                re.IGNORECASE)),
    ("activity_groups",
     re.compile(r"^ACTIVITY\s+GROUPS$", re.IGNORECASE)),
    ("objects",
     re.compile(r"^EXPENDITURE\s+SUMMARY\s+BY\s+OBJECTS?$", re.IGNORECASE)),
]


def _match_financial_summary_section(ln: str) -> Optional[str]:
    # Cheap uppercase-alpha gate -- section headers are always ALL CAPS
    # (and short). Skips any line containing lowercase, punctuation,
    # or a digit, which rules out label wraps like 'Counts', 'Total
    # Revenues and Other Financing', etc.
    if not ln:
        return None
    if not all((c.isupper() or c.isspace()) for c in ln):
        return None
    for name, pat in _FINANCIAL_SUMMARY_SECTIONS:
        if pat.match(ln):
            return name
    return None


def _parse_value(vtext):
    if vtext is None:
        return None
    if vtext.startswith("XXX"):
        return None
    if vtext == "$-":
        return None
    return parse_decimal(vtext)


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
