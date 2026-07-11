"""Parse the `SUMMARY OF FTE CERTIFICATED AND CLASSIFIED STAFF COUNTS BY
ACTIVITY` sub-report (GF15) of OSPI Form F-195 Budget PDFs.

Sub-report layout (1-2 pages, ~30 activity rows + 6 total rows):

    Col 1: No. of FTE Certificated Staff  (right edge x1 ~ 331)
    Col 2: % to Total (Certificated)      (right edge x1 ~ 412)
    Col 3: No. of FTE Classified Staff    (right edge x1 ~ 493)
    Col 4: % to Total (Classified)        (right edge x1 ~ 574)

grouped into 5 activity sections that match GF11:
  1. TEACHING ACTIVITIES
  2. TEACHING SUPPORT
  3. OTHER SUPPORT ACTIVITIES
  4. UNIT ADMINISTRATION
  5. CENTRAL ADMINISTRATION

Each section closes with a `TOTAL <section>` row; the sub-report closes
with `TOTAL FTE STAFF`.

**Parses via POSITIONAL extraction** (`extract_words(use_text_flow=True)`
+ column anchors set from the grand-total row) rather than by counting
trailing tokens. Reason: the 2013-14 / 2014-15 vintage of this form
inconsistently prints XXXXX vs bare-blank for zero-staff activities;
a token-count parser would mis-bin the 2-4 value tokens on rows where
one staff type is entirely blank (e.g. `12 | Superintendent's Office
0.516 3.98` where cert=0.516 but class-side is bank -- not XXXXX).

Both F-195 Budget and F-195 Budget Overview contain this sub-report on
2016-17+ vintages; the older vintages have it only in the Budget PDF.
The walker picks one physical source per district-year (Overview when
available, Budget otherwise) to avoid mid-year snapshot divergence
between the two source kinds.
"""

import logging
import re
from typing import Iterator, List, Optional

from ..filename import FiscalFilename
from .common import parse_decimal, normalize_pdf_text


logger = logging.getLogger(__name__)


_TITLE = "SUMMARY OF FTE CERTIFICATED AND CLASSIFIED STAFF COUNTS BY ACTIVITY"

# Section-header exact strings (uppercase).
_SECTION_HEADERS = [
    ("TEACHING ACTIVITIES",      "teaching_activities"),
    ("TEACHING SUPPORT",         "teaching_support"),
    ("OTHER SUPPORT ACTIVITIES", "other_support_activities"),
    ("UNIT ADMINISTRATION",      "unit_administration"),
    ("CENTRAL ADMINISTRATION",   "central_administration"),
]

# Per-section TOTAL row -> (section, activity_code slug).
_SECTION_TOTAL_RES = [
    (re.compile(r"^TOTAL\s+TEACHING\s+ACTIVIT(?:IE|E)S\b", re.IGNORECASE),
     "teaching_activities", "total_teaching_activities"),
    (re.compile(r"^TOTAL\s+TEACHING\s+SUPPORT\b", re.IGNORECASE),
     "teaching_support", "total_teaching_support"),
    (re.compile(r"^TOTAL\s+OTHER\s+SUPPORT\s+ACTIVIT(?:IE|E)S\b", re.IGNORECASE),
     "other_support_activities", "total_other_support_activities"),
    (re.compile(r"^TOTAL\s+UNIT\s+ADMINISTRATION\b", re.IGNORECASE),
     "unit_administration", "total_unit_administration"),
    (re.compile(r"^TOTAL\s+CENTRAL\s+ADMINISTRATION\b", re.IGNORECASE),
     "central_administration", "total_central_administration"),
]

_GRAND_TOTAL_RE = re.compile(r"^TOTAL\s+FTE\s+STAFF\b", re.IGNORECASE)

# Activity code prefix: 2-digit + optional `|` separator.
_OSPI_CODE_RE = re.compile(r"^(\d{2})\s*\|?\s+(.+)$")

# Value token (positive decimal + optional comma-grouping, or XXXXX).
_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$|^XXX+$")

# Rows to skip.
_COLUMN_MARKER_RE = re.compile(r"^\(\d\)(\s+\(\d\))+\s*$")
_HEADER_TOKENS = {
    "No.", "of", "FTE", "%", "to", "Certificated", "Classified", "Total",
    "Staff", "ACTIVITY",
}
_FOOTER_RE = re.compile(r"^Form\s+F-195\s+Page\s+\d", re.IGNORECASE)
_NOTE_RE = re.compile(r"^NOTE:\s", re.IGNORECASE)

# Positional tolerances.
_COL_TOLERANCE = 8.0
_Y_TOLERANCE = 2.5

# Fallback column anchors (right-edge x1), used when we hit a value
# row before finding a full 4-value row to derive dynamic anchors
# from. These are stable across vintages and fund PDFs (verified
# against files spanning 2013-14 through 2025-26). Order matches the
# 4 columns: cert_fte, cert_pct, class_fte, class_pct.
_FALLBACK_COLUMN_ANCHORS = [331.0, 412.0, 493.0, 574.0]


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


def _closest_column(x1, anchors):
    best_idx = None
    best_d = _COL_TOLERANCE
    for i, a in enumerate(anchors):
        d = abs(x1 - a)
        if d <= best_d:
            best_idx = i
            best_d = d
    return best_idx


def _parse_value(vtext):
    if not vtext or vtext.startswith("XXX"):
        return None
    return parse_decimal(vtext)


def _match_section_header(ln: str) -> Optional[str]:
    for needle, name in _SECTION_HEADERS:
        if ln == needle:
            return name
    return None


def _match_total_row(ln: str):
    for pat, section, code in _SECTION_TOTAL_RES:
        if pat.match(ln):
            return (section, code)
    if _GRAND_TOTAL_RE.match(ln):
        return ("summary", "total_fte_staff")
    return None


def parse_f195_staff_by_activity_pdf(info: FiscalFilename) -> Iterator[dict]:
    """Yield rows from GF15 pages of one F-195 Budget (or Overview) PDF."""
    import pdfplumber

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f195_staff_by_activity",
    }

    rows_out: List[dict] = []
    section: Optional[str] = None
    column_anchors: Optional[List[float]] = None
    in_note = False
    entered_gf15 = False

    with pdfplumber.open(info.path) as pdf:
        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            # Fast title detection (avoid parsing every page's words).
            title_seen = _TITLE in text
            if not title_seen:
                if entered_gf15:
                    break
                continue
            entered_gf15 = True

            words = page.extract_words(use_text_flow=True)
            # District from banner (once).
            if not base["district"]:
                banner = " ".join(w["text"] for w in words[:30])
                m = re.search(
                    r"(.+?)\s+School\s+District\s+No\.?\s*\d+",
                    banner
                )
                if m:
                    base["district"] = re.sub(r"\s+", " ",
                                              m.group(1)).strip()

            in_note = False
            grouped = _group_rows(words)

            for row in grouped:
                text_row = " ".join(w["text"] for w in row).strip()
                if not text_row:
                    continue
                if _FOOTER_RE.match(text_row):
                    continue
                if _NOTE_RE.match(text_row):
                    in_note = True
                    continue
                if in_note:
                    continue
                if _COLUMN_MARKER_RE.match(text_row):
                    continue

                # Skip column-header rows -- ones made up entirely of
                # known header tokens.
                if all(t in _HEADER_TOKENS
                       for t in text_row.replace(",", " ").split()):
                    continue

                # Skip the page-title row itself.
                if text_row.startswith(_TITLE):
                    continue

                # Section marker rows.
                new_section = _match_section_header(text_row)
                if new_section is not None:
                    section = new_section
                    continue

                # Value words = tokens matching _VALUE_TOKEN_RE AND
                # positioned in the value-column x-region (right half
                # of page). Excludes the leading OSPI activity code
                # (`27`, `13`, etc.) at x0 ~= 20, which would otherwise
                # match the value-token regex.
                value_words = [w for w in row
                               if _VALUE_TOKEN_RE.match(w["text"])
                               and w["x0"] >= 200]
                label_words = [w for w in row if w not in value_words]
                label_text = re.sub(
                    r"\s+", " ",
                    " ".join(w["text"] for w in label_words).strip()
                )

                # No values on this row -- pure label/wrap row; skip.
                if len(value_words) == 0:
                    continue

                # Establish column anchors from the first 4-value row
                # (usually `27 | Teaching`, which always has all 4
                # columns filled). Fall back to hardcoded anchors when
                # the first value-bearing row has fewer than 4 -- e.g.
                # 11054 Star SD 2013-14 whose only cert-side activity
                # is `27 | Teaching` printed as 2 values (no `XXXXX`
                # placeholders on the class side).
                if column_anchors is None:
                    if len(value_words) == 4:
                        column_anchors = [w["x1"] for w in value_words]
                    else:
                        column_anchors = list(_FALLBACK_COLUMN_ANCHORS)

                # Classify row: TOTAL vs detail.
                total_match = _match_total_row(label_text)
                if total_match is not None:
                    row_section, activity_code = total_match
                    is_total = True
                    item_label = label_text
                else:
                    if section is None:
                        continue
                    m = _OSPI_CODE_RE.match(label_text)
                    if m is None:
                        continue
                    activity_code = m.group(1)
                    item_label = re.sub(r"\s+", " ",
                                        m.group(2).strip())
                    row_section = section
                    is_total = False

                # Bin each value word into its column by right-edge x1.
                binned: List[Optional[dict]] = [None] * 4
                for vw in value_words:
                    idx = _closest_column(vw["x1"], column_anchors)
                    if idx is not None and binned[idx] is None:
                        binned[idx] = vw

                cert_v = _parse_value(binned[0]["text"]) if binned[0] else None
                cert_p = _parse_value(binned[1]["text"]) if binned[1] else None
                class_v = _parse_value(binned[2]["text"]) if binned[2] else None
                class_p = _parse_value(binned[3]["text"]) if binned[3] else None

                rows_out.append({
                    **base,
                    "section": row_section,
                    "activity_code": activity_code,
                    "is_total": is_total,
                    "item_label": item_label,
                    "certificated_fte": cert_v,
                    "certificated_pct_of_total": cert_p,
                    "classified_fte": class_v,
                    "classified_pct_of_total": class_p,
                })

    # Dedup by logical key (defensive -- walker already picks one source
    # kind per district-year, so this should be a no-op).
    seen = {}
    for r in rows_out:
        seen[(r["section"], r["activity_code"])] = r
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
