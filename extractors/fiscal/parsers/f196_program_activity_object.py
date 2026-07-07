"""Parse the Program/Activity/Object Report sub-report of OSPI F-196
All Pages PDFs.

The sub-report is 2 pages of three side-by-side summary tables:
  - PROGRAM EXPENDITURE SUMMARY (leftmost band, x0 <~ 270)
  - ACTIVITY EXPENDITURE SUMMARY (middle band, ~270 < x0 < ~530)
  - OBJECT EXPENDITURE SUMMARY (rightmost band, x0 > ~530)

Each table has columns NO. / TITLE / AMOUNT. The 3 tables share the
page but their rows do NOT align vertically -- Program has ~33 rows,
Activity has ~30, Object has 10. So we parse each column band
independently.

Parsing approach:

  1. Locate the sub-report pages via the title regex.
  2. Find the 3 column bands from the second-row header ('NO. PROGRAM
     TITLE AMOUNT' x 3 side-by-side). The AMOUNT column x1 in each band
     becomes the column anchor for that band's value column.
  3. Group words by y (small tolerance), then split each row into per-band
     sub-rows using x-position. Each per-band sub-row is either:
       - A data row: leading numeric code + label + trailing amount.
       - A wrap continuation: only label tokens (code and amount absent).
         These accumulate onto the previous data row's label.
       - A TOTAL row: 'TOTAL ALL PROGRAMS' / 'TOTAL ALL ACTIVITIES' /
         'TOTAL ALL OBJECTS' with no leading code but a trailing amount.

Quirks handled:

  - Labels wrap across two visual lines. Example: 'Basic Education -
    Dropout / Reengagement' where 'Reengagement' is on the next visual
    row of the PROGRAM band with no code or amount.
  - Tribal compact schools use 'E.S.D. SPI' -- title regex uses \\w+.
  - Value-wrap fragments and sign-placeholder wraps are reused from
    the f196_all_pages patterns for large-district totals.
  - The value token '.00' (small credit) parses to 0.00 via parse_decimal.
"""

import logging
import re
from typing import Iterator, List, Optional, Tuple

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_SUBREPORT_TITLE_RE = re.compile(
    r"E\.S\.D\.\s*\w+\s+Program/Activity/Object\s+Report",
    re.IGNORECASE,
)

_BREAKDOWN_ORDER = ["program", "activity", "object"]

# Header cell labels used to establish column bands. Each summary table
# has NO. + <Type> TITLE + AMOUNT columns.
_HEADER_LABELS = {
    "program":  re.compile(r"^PROGRAM\s+EXPENDITURE\s+SUMMARY$", re.IGNORECASE),
    "activity": re.compile(r"^ACTIVITY\s+EXPENDITURE\s+SUMMARY$", re.IGNORECASE),
    "object":   re.compile(r"^OBJECT\s+EXPENDITURE\s+SUMMARY$",  re.IGNORECASE),
}

# Grand-total row per breakdown. No `$` anchor -- the row also carries
# the trailing amount token.
_TOTAL_LABELS = {
    "program":  re.compile(r"^TOTAL\s+ALL\s+PROGRAMS?\b",   re.IGNORECASE),
    "activity": re.compile(r"^TOTAL\s+ALL\s+ACTIVITIES\b",  re.IGNORECASE),
    "object":   re.compile(r"^TOTAL\s+ALL\s+OBJECTS\b",     re.IGNORECASE),
}

# Row-level regexes.
_CODE_RE = re.compile(r"^\d{1,3}$")

# Value / fragment regexes (mirroring the other f196 parsers).
_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")

# The 'value' tokens include the truncated '.00' case where the tens
# digit is 0 -- parse_decimal handles it, but for classification we
# match a broader form.
_VALUE_TOKEN_RE = re.compile(r"^-?\.?\d[\d,]*\.\d+$|^-?\d[\d,]*\.\d+$")

_Y_TOLERANCE = 2.0
_WRAP_FRAGMENT_MAX_Y_GAP = 14.0

# Fallback band split when header detection is unable to pin exact x0/x1
# boundaries (defensive; the two form vintages we've seen both have
# clean headers).
_DEFAULT_BAND_BREAKS = (270.0, 530.0)


def parse_f196_program_activity_object_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_program_activity_object",
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

        first_words = pdf.pages[sub_pages[0]].extract_words(use_text_flow=True)
        d = _district_from_words(first_words)
        if d:
            base["district"] = d

        # Determine band boundaries from the header row on the first page.
        band_x_ranges = _find_band_ranges(first_words)

        # Per-breakdown state (label buf + last-emitted-row wrap-info + amount anchor).
        band_states = {
            k: _BandState(anchor_x1=band_x_ranges[k][2])
            for k in _BREAKDOWN_ORDER
        }

        for pg_idx in sub_pages:
            words = pdf.pages[pg_idx].extract_words(use_text_flow=True)
            yield from _parse_page(words, base, band_x_ranges, band_states)

        # Flush any trailing pending rows / label suffixes.
        for k in _BREAKDOWN_ORDER:
            band_states[k].flush_suffix_into_pending()
            for r in band_states[k].emit_pending():
                yield r


# ---- internal helpers ------------------------------------------------------


class _BandState:
    def __init__(self, anchor_x1: float):
        self.anchor_x1 = anchor_x1
        self.label_buf: List[str] = []
        self.pending_row: Optional[dict] = None
        self.pending_row_top: Optional[float] = None
        self.pending_wrap: bool = False  # True when parent value looks truncated

    def flush_suffix_into_pending(self) -> None:
        if self.pending_row and self.label_buf:
            suffix = " ".join(self.label_buf).strip()
            if suffix:
                joined = (self.pending_row["item_label"] + " " + suffix).strip()
                self.pending_row["item_label"] = re.sub(r"\s+", " ", joined)
        self.label_buf.clear()

    def emit_pending(self):
        if self.pending_row is None:
            return []
        out = [self.pending_row]
        self.pending_row = None
        self.pending_row_top = None
        self.pending_wrap = False
        return out


def _district_from_words(words) -> Optional[str]:
    text = " ".join(w["text"] for w in words[:30])
    m = re.search(r"REPORT\s+F196\s+(.+?)\s+No\.\s*\d+", text, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _find_band_ranges(words) -> dict:
    """Return {breakdown_kind: (x_start, x_end, amount_x1)}.

    Uses the first-page header line ('NO. PROGRAM TITLE AMOUNT' x 3
    side-by-side) to locate each band. The three 'NO.' tokens mark the
    left edges; each band's 'AMOUNT' token's x1 is the value-column
    anchor. If any header token is missing, fall back to sensible
    default band breaks (defensive; the two vintages we've seen both
    have clean headers).
    """
    # Find the 'NO.' tokens at the header row (top ~= same for all 3).
    no_tokens = [w for w in words if w["text"] == "NO."]
    amount_tokens = [w for w in words if w["text"] == "AMOUNT"]
    if len(no_tokens) < 3 or len(amount_tokens) < 3:
        # Fallback: split by fixed x breaks and put amount anchors at
        # rough positions (the actual first-values row will re-anchor).
        return {
            "program":  (0.0, _DEFAULT_BAND_BREAKS[0], 268.0),
            "activity": (_DEFAULT_BAND_BREAKS[0], _DEFAULT_BAND_BREAKS[1], 520.0),
            "object":   (_DEFAULT_BAND_BREAKS[1], 900.0, 772.0),
        }

    # Sort by x0, take the first 3.
    no_tokens = sorted(no_tokens, key=lambda w: w["x0"])[:3]
    amount_tokens = sorted(amount_tokens, key=lambda w: w["x0"])[:3]
    kinds = _BREAKDOWN_ORDER
    ranges = {}
    for i, k in enumerate(kinds):
        x_start = no_tokens[i]["x0"] - 5
        x_end = (no_tokens[i + 1]["x0"] - 2 if i + 1 < 3 else 900.0)
        ranges[k] = (x_start, x_end, amount_tokens[i]["x1"])
    return ranges


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


def _is_page_header_row(text: str) -> bool:
    return bool(
        text.startswith("REPORT F196")
        or _SUBREPORT_TITLE_RE.search(text)
        or text.startswith("COUNTY:")
        or text.startswith("E.S.D.")
        or re.match(r"^Page\s+\d+\s+of\s+\d+\s*$", text)
        or "For the Year Ended" in text
        or "For The Year Ended" in text
    )


def _row_in_band(row_words, band_range) -> List[dict]:
    x_start, x_end, _ = band_range
    return [w for w in row_words if x_start <= w["x0"] < x_end]


def _parse_page(words, base, band_x_ranges, band_states) -> Iterator[dict]:
    rows = _group_rows(words)

    for row in rows:
        row_top = min(w["top"] for w in row)
        text = " ".join(w["text"] for w in row).strip()
        if not text or _is_page_header_row(text):
            continue

        # Skip the header-band row(s) themselves.
        if any(pat.search(text) for pat in _HEADER_LABELS.values()):
            continue
        if re.search(r"NO\.\s+(PROGRAM|ACTIVITY|OBJECT)\s+TITLE\s+AMOUNT",
                     text, re.IGNORECASE):
            continue

        for kind in _BREAKDOWN_ORDER:
            sub_words = _row_in_band(row, band_x_ranges[kind])
            if not sub_words:
                continue
            yield from _handle_band_row(sub_words, row_top, kind, base,
                                        band_states[kind])


def _handle_band_row(sub_words, row_top, kind, base,
                     st: _BandState) -> Iterator[dict]:
    sub_text = " ".join(w["text"] for w in sub_words).strip()
    if not sub_text:
        return

    # Grand-total row: label matches TOTAL ALL <KIND> and there is a
    # trailing full-value token (no leading numeric code).
    if _TOTAL_LABELS[kind].search(sub_text):
        value_words = [w for w in sub_words if _FULL_VALUE_RE.match(w["text"])]
        if value_words:
            # Flush any pending row + suffix.
            st.flush_suffix_into_pending()
            for r in st.emit_pending():
                yield r
            row = _build_row(base, kind, "TOTAL", sub_text, value_words[-1],
                             is_total=True)
            st.pending_row = row
            st.pending_row_top = row_top
            return

    # Detail / wrap-continuation row: check for a leading numeric code
    # (first non-value token in x0-order that matches ^\d{1,3}$).
    code_word = None
    for w in sub_words:
        if _CODE_RE.match(w["text"]) and not _FULL_VALUE_RE.match(w["text"]):
            code_word = w
            break

    value_words = [w for w in sub_words if _FULL_VALUE_RE.match(w["text"])]
    fragment_words = [w for w in sub_words
                      if _WRAP_FRAGMENT_RE.match(w["text"])
                      and not _FULL_VALUE_RE.match(w["text"])
                      and w is not code_word]

    # Wrap-fragment absorption -- rare on this sub-report but supported
    # for large-district totals whose 10-figure amounts overflow the
    # column width. See f196_all_pages for the pattern.
    if (
        st.pending_row is not None
        and st.pending_row_top is not None
        and (row_top - st.pending_row_top) <= _WRAP_FRAGMENT_MAX_Y_GAP
        and fragment_words
        and st.pending_wrap
    ):
        # Concat first fragment onto the pending row's value.
        for frag in fragment_words:
            existing = st.pending_row["value_text"]
            if not existing:
                continue
            merged = existing + frag["text"]
            st.pending_row["value_text"] = merged
            st.pending_row["value"] = parse_decimal(merged)
            st.pending_wrap = _is_truncated_value(merged)
        # A wrap row also often carries a label continuation.
        label_tokens = [w for w in sub_words
                        if not _FULL_VALUE_RE.match(w["text"])
                        and not _WRAP_FRAGMENT_RE.match(w["text"])
                        and w is not code_word]
        label_text = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_tokens).strip())
        if label_text:
            st.label_buf.append(label_text)
        return

    # No code + no value + only label = wrap-label continuation.
    if code_word is None and not value_words:
        label_tokens = sub_words
        label_text = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_tokens).strip())
        if label_text:
            st.label_buf.append(label_text)
        return

    # Full data row: emit any pending suffix onto the previous row first.
    st.flush_suffix_into_pending()
    for r in st.emit_pending():
        yield r

    # Extract label tokens = everything between code and the value.
    code = code_word["text"] if code_word else ""
    label_tokens = [w for w in sub_words
                    if w is not code_word and not _FULL_VALUE_RE.match(w["text"])
                    and not _WRAP_FRAGMENT_RE.match(w["text"])]
    label_text = re.sub(r"\s+", " ",
                        " ".join(w["text"] for w in label_tokens).strip())
    if not value_words:
        # A code without a value is unusual (should have printed .00 at
        # minimum). Treat as pure label so a later row can supply the value.
        if label_text:
            st.label_buf.append((f"{code} " + label_text).strip() if code else label_text)
        return

    value_word = value_words[-1]  # last value in this band = the AMOUNT column
    row = _build_row(base, kind, code, label_text, value_word, is_total=False)
    st.pending_row = row
    st.pending_row_top = row_top
    st.pending_wrap = _is_truncated_value(value_word["text"])


def _build_row(base, kind, code, label_text, value_word, is_total):
    return {
        **base,
        "breakdown_kind": kind,
        "code": code,
        "is_total": is_total,
        "item_label": label_text,
        "value": parse_decimal(value_word["text"]),
        "value_text": value_word["text"],
    }


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
