"""Parse the REPORT F-196 SUMMARY block from F-196 All Pages PDFs.

Each `F-196 All Pages.pdf` is the full annual financial statement (~70-90
pages: Balance Sheet, per-sub-fund Statement of Revenues/Expenditures,
Budgetary Comparison, Long-Term Liabilities, Object/Activity/Program
reports). Page 2 carries the F-196 SUMMARY -- a 7-fund x 7-item matrix
that's identical in shape to the standalone audited 'F-196 Summary' doc
(`f196_summary.py`, retired in favor of this parser) and to the older
F-196 Unaudited filing (`f196_unaudited.py`, retained for the parallel
apportionment-corpus doc).

Three parsing quirks the standalone-Summary parser did NOT have to absorb:

  1. Cell-blanking in older vintages. Through ~2020-21, the form leaves
     non-applicable cells truly blank (most commonly ASB and Permanent
     on 'Other Financing Uses', and Transportation Vehicle on the same).
     The 2021-22+ audited Summary doc fills those with explicit 0.00.
     The trailing-7-tokens heuristic the standalone parser uses snaps
     to the wrong column when fewer than 7 values are printed -- so
     this parser does positional column-anchor extraction instead
     (same approach as `f196_unaudited.py`).

  2. Value-wrap fragments (trailing-digit overflow). On very large
     districts (Seattle 2018-19 etc), a 10-figure value like
     `1,164,926,695.83` overflows the printed column width and the
     trailing digit(s) wrap to the next visual line at the same x-column.
     `extract_words()` reports the wrap fragment as its own row ~9pt
     below the parent value, at the same x1.

  3. Sign-placeholder wraps (full-body overflow). When a NEGATIVE value
     is too wide, the leading `-` sign sometimes prints alone at the
     column on the parent row and the entire digit body (commas,
     decimals, the lot) wraps to the next line at the same x. Observed
     on Excess of Revenues rows for several large districts (Everett
     2020-21 debt_service `-11,863,885.53`, Bellevue 2021-22, etc).

The post-merge logic absorbs both wrap shapes: any column whose value
ended up NULL (or whose pending row carries a sign placeholder) gets
fed by the next visual row's full-value or fragment word at the same
x1, with the sign prepended.

Per-item label wrapping (e.g. "Total Revenues and Other Financing /
Sources") is handled by accumulating label-only rows as a suffix on the
most-recently-emitted item, same as `f196_unaudited.py`.

The page-2 SUMMARY block always has Prior Year(s) Corrections as a
fully-populated 7-column row, which gives a stable column anchor even
when 'Other Financing Uses' (the row before it) is blank-heavy. The
first row to fill all 7 columns establishes the anchors.
"""

import logging
import re
from typing import Iterator, List, Optional

import pdfplumber

from ..filename import FiscalFilename
from .common import parse_decimal


logger = logging.getLogger(__name__)


_FUND_ORDER = [
    "general", "asb", "debt_service", "capital_projects",
    "transportation_vehicle", "permanent", "total",
]

_ITEM_CODES = [
    "total_revenues_and_other_financing_sources",
    "total_expenditures",
    "other_financing_uses",
    "excess_of_revenues_over_expenditures",
    "beginning_total_fund_balance",
    "corrections_or_restatements",
    "ending_total_fund_balance",
]

_HEADER_RE = re.compile(r"REPORT\s+F-196\s+SUMMARY", re.IGNORECASE)
_END_RE = re.compile(r"^(Locked\s+Date|Not\s+Locked|Page\s+\d+\s+of\s+\d+|Certification\s+Page)",
                     re.IGNORECASE)

# A fully-formed value: F-196 SUMMARY always prints values to 2 decimal
# places (e.g. '0.00', '951,818,093.18'), so a decimal point is mandatory.
# Requiring it cleanly separates real values from bare-digit wrap
# fragments like '3' or '83' (which match _WRAP_FRAGMENT_RE instead).
_FULL_VALUE_RE = re.compile(r"^-?\d[\d,]*\.\d+$")
# A wrap-fragment is 1-3 bare digits (no comma, no decimal): the truncated
# tail of a parent value that the printed column couldn't fit.
_WRAP_FRAGMENT_RE = re.compile(r"^\d{1,3}$")
# A lone '-' (hyphen / minus / em-dash family already collapsed by
# normalize_pdf_text upstream). Used as a sign placeholder when the
# digit body of a negative value wraps to the next visual line.
_SIGN_PLACEHOLDER_RE = re.compile(r"^-$")

# Column anchor matching: tolerance in points between a value's right edge
# (x1) and an established column anchor. Columns are ~80pt apart, so 6pt is
# conservative.
_COL_TOLERANCE = 6.0

# y-tolerance for grouping words into one logical row. The 'Beginning Total
# Fund Balance' label and its value sometimes render ~1pt off-baseline; 2pt
# absorbs that without collapsing adjacent items (item rows are ~12-20pt apart).
_Y_TOLERANCE = 2.0

# Maximum vertical distance from a value row down to a wrap-fragment row at
# the same x1. Empirically wrap fragments are ~9pt below; the next item row
# is ~20pt below. 14pt splits the difference safely.
_WRAP_FRAGMENT_MAX_Y_GAP = 14.0

# Cap how many pages we scan for the SUMMARY block. Page 2 is the universal
# location, but allow a small safety margin for any vintage drift.
_MAX_PAGES_TO_SCAN = 5


def parse_f196_all_pages_pdf(info: FiscalFilename) -> Iterator[dict]:
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f196_summary",
    }

    with pdfplumber.open(info.path) as pdf:
        for pg_idx, page in enumerate(pdf.pages):
            if pg_idx >= _MAX_PAGES_TO_SCAN:
                return
            words = page.extract_words()
            if not words:
                continue
            joined = " ".join(w["text"] for w in words)
            if not _HEADER_RE.search(joined):
                continue

            district = _district_from_words(words)
            if district:
                base["district"] = district

            yield from _parse_summary_page(words, base)
            return


def _district_from_words(words) -> Optional[str]:
    """Pull the district name from the 'REPORT F196 <name> No. NNN' banner."""
    text = " ".join(w["text"] for w in words[:30])
    m = re.search(r"REPORT\s+F196\s+(.+?)\s+No\.\s*\d+", text, re.IGNORECASE)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _group_rows(words, y_tol=_Y_TOLERANCE) -> List[List[dict]]:
    """Group words into logical rows by y-position (with tolerance).

    pdfplumber's `extract_words()` does not merge near-aligned baselines on
    its own; the F-196 SUMMARY has at least one item where the value row
    renders ~1pt above its label.
    """
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


def _parse_summary_page(words, base) -> Iterator[dict]:
    rows = _group_rows(words)

    # Locate the REPORT F-196 SUMMARY header row.
    header_idx = None
    for i, row in enumerate(rows):
        text = " ".join(w["text"] for w in row)
        if _HEADER_RE.search(text):
            header_idx = i
            break
    if header_idx is None:
        return

    column_anchors: Optional[List[float]] = None
    position = 0
    label_buf: List[str] = []
    # pending_rows holds the most-recently-emitted item's rows so we can:
    #   (a) attach trailing label fragments as suffix, and
    #   (b) merge wrap-fragment / wrap-body values back into the parent.
    pending_rows: Optional[List[dict]] = None
    # Per-column metadata for wrap absorption. Each entry is one of:
    #   None              -- column has no pending wrap obligation
    #   {"sign": "-"}     -- a lone '-' placeholder printed here; the digit
    #                        body is expected on the next visual line at the
    #                        same x1. The merged value will be sign + body.
    pending_wrap_meta: Optional[List[Optional[dict]]] = None
    pending_row_top: Optional[float] = None

    def _flush_suffix_into_pending():
        nonlocal pending_rows
        if pending_rows and label_buf:
            suffix = " ".join(label_buf).strip()
            if suffix:
                for r in pending_rows:
                    joined = (r["item_label"] + " " + suffix).strip()
                    r["item_label"] = re.sub(r"\s+", " ", joined)
        label_buf.clear()

    def _emit_pending():
        nonlocal pending_rows, pending_wrap_meta, pending_row_top
        rows_out = pending_rows or []
        pending_rows = None
        pending_wrap_meta = None
        pending_row_top = None
        return rows_out

    for row in rows[header_idx + 1:]:
        if position >= len(_ITEM_CODES):
            break

        row_top = min(w["top"] for w in row)
        text = " ".join(w["text"] for w in row).strip()
        if _END_RE.match(text):
            break

        full_value_words = [w for w in row if _FULL_VALUE_RE.match(w["text"])]
        fragment_words = [w for w in row
                          if _WRAP_FRAGMENT_RE.match(w["text"])
                          and not _FULL_VALUE_RE.match(w["text"])]
        sign_words = [w for w in row if _SIGN_PLACEHOLDER_RE.match(w["text"])]
        # Label text is anything that's not a numeric/sign token.
        label_words = [w for w in row
                       if not _FULL_VALUE_RE.match(w["text"])
                       and not _WRAP_FRAGMENT_RE.match(w["text"])
                       and not _SIGN_PLACEHOLDER_RE.match(w["text"])]
        label_text = re.sub(r"\s+", " ",
                            " ".join(w["text"] for w in label_words).strip())

        # ---- Wrap-continuation absorption ----------------------------------
        # A row is treated as wrap continuation of the previous item when:
        #   (a) we have a pending row with at least one column awaiting wrap
        #       data (NULL value with a sign-placeholder marker), OR
        #   (b) the pending row's value at this column is a trailing-digit
        #       truncation (no decimal-2-places suffix; a wrap fragment will
        #       finish it),
        # AND the current row's numeric words map to those columns,
        # AND the vertical gap is small.
        if (
            pending_rows is not None
            and pending_wrap_meta is not None
            and column_anchors is not None
            and pending_row_top is not None
            and (row_top - pending_row_top) <= _WRAP_FRAGMENT_MAX_Y_GAP
        ):
            anchor_for_col = [(column_anchors[i] if pending_wrap_meta[i] is not None
                                                  or _is_truncated_value(
                                                      pending_rows[i]["value_text"])
                               else None)
                              for i in range(len(_FUND_ORDER))]
            absorbed_any = False
            # Sign-placeholder + full-value-body wrap. The next-line word at
            # the placeholder's x is the digit body; merged value = sign + body.
            for vw in full_value_words:
                target_idx = _closest_column_index(vw["x1"], anchor_for_col)
                if target_idx is None:
                    continue
                meta = pending_wrap_meta[target_idx]
                if meta is None or "sign" not in meta:
                    continue
                merged = meta["sign"] + vw["text"]
                pending_rows[target_idx]["value_text"] = merged
                pending_rows[target_idx]["value"] = parse_decimal(merged)
                pending_wrap_meta[target_idx] = None
                anchor_for_col[target_idx] = None
                absorbed_any = True
            # Trailing-digit-fragment wrap. Append fragment to existing text.
            for frag in fragment_words:
                target_idx = _closest_column_index(frag["x1"], anchor_for_col)
                if target_idx is None:
                    continue
                existing = pending_rows[target_idx]["value_text"]
                if not existing:
                    continue
                merged = existing + frag["text"]
                pending_rows[target_idx]["value_text"] = merged
                pending_rows[target_idx]["value"] = parse_decimal(merged)
                pending_wrap_meta[target_idx] = None
                anchor_for_col[target_idx] = None
                absorbed_any = True

            if absorbed_any:
                # The row may also carry a label continuation ('Sources' etc.).
                if label_text:
                    label_buf.append(label_text)
                # Sign words that did NOT consume a wrapped body are discarded
                # (rare; would indicate yet another shape).
                continue
            # Nothing absorbed: fall through to the normal path.

        # If the row has no full values AND no usable sign placeholders,
        # treat it as a pure label continuation.
        if not full_value_words and not sign_words:
            if label_text:
                label_buf.append(label_text)
            continue

        # The row carries a new item's values. Establish column anchors from
        # the first row whose value count matches the expected column count
        # (which is always 7 on F-196 SUMMARY when the row is non-blank).
        if column_anchors is None:
            if len(full_value_words) != len(_FUND_ORDER):
                logger.warning(
                    "first F-196 SUMMARY value row in %s has %d values, "
                    "expected %d; deferring anchor detection",
                    base["_source"], len(full_value_words), len(_FUND_ORDER),
                )
                if label_text:
                    label_buf.append(label_text)
                continue
            column_anchors = [w["x1"] for w in full_value_words]

        # Emit any pending suffix into the previous item's rows, then yield them.
        _flush_suffix_into_pending()
        for r in _emit_pending():
            yield r

        full_label = label_text
        item_code = _ITEM_CODES[position]
        position += 1

        new_rows: List[dict] = []
        wrap_meta: List[Optional[dict]] = [None] * len(_FUND_ORDER)
        for col_idx, anchor in enumerate(column_anchors):
            fund = _FUND_ORDER[col_idx]
            matched = _closest_value(full_value_words, anchor)
            if matched is None:
                # Did we instead see a lone '-' sign placeholder at this anchor?
                # That means the value's digit body wrapped to the next line.
                sign = _closest_sign(sign_words, anchor)
                if sign is not None:
                    wrap_meta[col_idx] = {"sign": "-"}
                new_rows.append({
                    **base,
                    "item_code": item_code,
                    "fund": fund,
                    "item_label": full_label,
                    "value": None,
                    "value_text": "",
                })
            else:
                new_rows.append({
                    **base,
                    "item_code": item_code,
                    "fund": fund,
                    "item_label": full_label,
                    "value": parse_decimal(matched["text"]),
                    "value_text": matched["text"],
                })
        pending_rows = new_rows
        pending_wrap_meta = wrap_meta
        pending_row_top = row_top

    # Flush trailing suffix and final pending rows.
    _flush_suffix_into_pending()
    for r in _emit_pending():
        yield r


def _is_truncated_value(value_text: str) -> bool:
    """A printed value like '1,164,926,695.8' is missing its last digit --
    F-196 SUMMARY always prints to 2 decimal places. Detect by checking
    decimal-suffix length.
    """
    if not value_text:
        return False
    dot = value_text.rfind(".")
    if dot < 0:
        # F-196 always prints decimals; a comma-grouped int with no dot
        # would itself be unusual. Don't flag.
        return False
    return len(value_text) - dot - 1 != 2


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
    """Find a lone '-' word whose x1 is within tolerance of `anchor`."""
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
