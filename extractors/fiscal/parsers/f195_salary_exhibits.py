"""Parse the `SALARY EXHIBIT[S] -- CERTIFICATED / CLASSIFIED EMPLOYEES`
sub-reports (GF9-201-XX, GF9-301-XX, CP-7, CP-8) of OSPI Form F-195
Budget PDFs.

Layout per page (one page per program, sometimes 2-4 pages for
Basic Education / District-wide Support / etc):

    SALARY EXHIBIT[S] -- CERTIFICATED EMPLOYEES     <- exhibit_kind banner
    PROGRAM 01 - Basic Education                    <- program banner
    ACTIVITY CODE  TITLE OF POSITION  FTE  ...      <- column headers
    01-21-005 OTHER SALARY ITEMS  0.000  0  0  0.00  519,517  112,620  406,897
    01-21-120 DEPUTY/ASSISTANT SUPERINTENDENT  1.000  275,882 ...
    ...
    ACTIVITY CODE 21 TOTAL  24.990   4,894,635  2,567,553  2,327,082
    ...
    PROGRAM TOTAL  <fte>  <total_salary>  [<state> <local>]

Certificated column shape:
    Legacy (2013-14 through 2018-19): FTE  HIGH  LOW  AVG  TOTAL          (5 cols)
    Modern (2019-20+):                FTE  HIGH  LOW  AVG  TOTAL STATE LOCAL (7 cols)

Classified column shape:
    Legacy: FTE  HOURS  HIGH  LOW  AVG  TOTAL          (6 cols)
    Modern: FTE  HOURS  HIGH  LOW  AVG  TOTAL STATE LOCAL (8 cols)

**Positional column-anchor extraction** via `extract_words(use_text_flow=
True)` -- required because subtotal rows leave the HIGH/LOW/AVG (and
HOURS for classified) columns blank; token-count parsing would mis-bin
the 4 numeric values onto the wrong columns.

**Trailing-digit wrap merging** -- large districts (Seattle, ...) have
FTE values like `2,040.610` and HOURS values like `394,766.40` that
overflow the printed column and wrap the trailing digit to the next
visual line at the same x1. The post-merge step absorbs any orphan
1-3 char digit rows whose x1 matches a column anchor into the
preceding row's value at that column.
"""

import logging
import re
from typing import Iterator, List, Optional, Tuple

from ..filename import FiscalFilename
from .common import parse_decimal, normalize_pdf_text


logger = logging.getLogger(__name__)


_TITLE_CERT_RES = [
    re.compile(r"SALARY EXHIBITS? -- CERTIFICATED EMPLOYEES", re.IGNORECASE),
]
_TITLE_CLASS_RES = [
    re.compile(r"SALARY EXHIBITS? -- CLASSIFIED EMPLOYEES", re.IGNORECASE),
]

_PROGRAM_BANNER_RE = re.compile(
    r"^PROGRAM\s+([0-9A-Z]{2})\s*-\s*(.+?)\s*$", re.IGNORECASE
)

# `PP-AA-DDD` code where PP is 2-digit or `CP`, AA is 2-digit or `CP`,
# DDD is 3-digit.
_DUTY_CODE_RE = re.compile(r"^([0-9A-Z]{2})-([0-9A-Z]{2})-(\d{3})\b")

_ACTIVITY_TOTAL_RE = re.compile(
    r"^ACTIVITY\s+CODE\s+([0-9A-Z]{2})\s+TOTAL\b", re.IGNORECASE
)
_PROGRAM_TOTAL_RE = re.compile(r"^PROGRAM\s+TOTAL\b", re.IGNORECASE)

_NO_DATA_RE = re.compile(
    r"NO\s+(?:CERTIFICATED|CLASSIFIED)\s+SALARY\s+DATA\s+FOR\s+THIS\s+PROGRAM",
    re.IGNORECASE,
)

_FOOTNOTE_STARTER_RE = re.compile(r"^\d\s*/\s+", re.IGNORECASE)
_FOOTER_RE = re.compile(
    r"^Form\s+(?:F-195|RP-195)", re.IGNORECASE
)

_VALUE_TOKEN_RE = re.compile(r"^-?\d[\d,]*(?:\.\d+)?$")

_Y_TOLERANCE = 2.5
_COL_TOLERANCE = 10.0
_WRAP_MAX_Y_GAP = 14.0


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
        if a is None:
            continue
        d = abs(x1 - a)
        if d <= best_d:
            best_idx = i
            best_d = d
    return best_idx


def _row_top(row):
    return min(w["top"] for w in row)


def _looks_like_wrap_only_row(row) -> bool:
    """True if a row consists only of 1-3 numeric tokens in the value
    region (x0 > 250) with no label content.

    Salary exhibit values that overflow their column wrap in two shapes:

      1. **Tail wrap** -- FTE / HOURS `394,766.40` prints `394,766.4`
         then the trailing `0` wraps to the NEXT visual line at the
         same x1. The next row has only that 1 bare-digit token.

      2. **Body wrap** -- FTE `1,037.300` prints the digit body
         `1,037.30` on the PREVIOUS visual line at the FTE column's
         x1 and the trailing `0` on the detail row's y at the same
         x1. The previous row has only that 1 numeric-with-decimal
         token.
    """
    if not row or len(row) > 3:
        return False
    for w in row:
        if not _VALUE_TOKEN_RE.match(w["text"]):
            return False
        # Must be positioned in the value column region (not a leftmost
        # label like an OSPI 2-digit activity code at x0 ~= 60).
        if w["x0"] < 250:
            return False
    return True


def _extract_program_banner(row) -> Optional[Tuple[str, str]]:
    """Return (program_code, program_label) if this row is a PROGRAM banner."""
    text = re.sub(r"\s+", " ",
                  " ".join(w["text"] for w in row).strip())
    m = _PROGRAM_BANNER_RE.match(text)
    if m:
        return m.group(1).upper(), re.sub(r"\s+", " ", m.group(2).strip())
    return None


def parse_f195_salary_exhibits_pdf(info: FiscalFilename) -> Iterator[dict]:
    """Yield rows from GF9-201-XX / GF9-301-XX / CP-7 / CP-8 pages of one
    F-195 Budget PDF."""
    import pdfplumber

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_f195_salary_exhibits",
    }

    rows_out: List[dict] = []
    seen: dict = {}
    # Column anchors persist across continuation pages of the same
    # (fund, exhibit_kind, program). Older vintages (2013-14, 2014-15)
    # continue a program's subtotals onto a second page without any
    # further detail rows -- without carried anchors the subtotal
    # rows would be silently dropped.
    anchors_by_program: dict = {}

    with pdfplumber.open(info.path) as pdf:
        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            upper = text.upper()

            is_cert = any(pat.search(text) for pat in _TITLE_CERT_RES)
            is_class = any(pat.search(text) for pat in _TITLE_CLASS_RES)
            if not (is_cert or is_class):
                continue

            # Determine fund from PROGRAM banner. GF9-201/GF9-301 pages
            # emit `PROGRAM NN - <label>`; CP-7/CP-8 pages emit
            # `PROGRAM CP - Capital Projects`.
            if "PROGRAM CP -" in upper:
                fund = "capital_projects"
            else:
                fund = "general"

            exhibit_kind = "certificated" if is_cert else "classified"

            # Skip empty programs.
            if _NO_DATA_RE.search(text):
                continue

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

            _process_page(
                words, base, fund, exhibit_kind, seen, rows_out,
                anchors_by_program,
            )

    yield from rows_out


def _process_page(words, base, fund, exhibit_kind, seen, rows_out,
                  anchors_by_program):
    """Walk one salary-exhibit page and append records to `rows_out`.

    Column anchors are established from the first fully-populated
    detail row of each (fund, exhibit_kind, program). Once set, they
    persist across the program's continuation pages via
    `anchors_by_program`.
    """
    grouped = _group_rows(words)

    program_code: Optional[str] = None
    program_label: Optional[str] = None
    column_anchors: Optional[List[float]] = None
    n_cols_expected = _expected_col_count(exhibit_kind, base["class_of"])

    # First pass: absorb wrap-only rows into the preceding row's words.
    merged_rows = _merge_wrap_fragments(grouped)

    in_footnote = False

    for row in merged_rows:
        text_row = re.sub(
            r"\s+", " ",
            " ".join(w["text"] for w in row).strip()
        )
        if not text_row:
            continue
        if _FOOTER_RE.match(text_row):
            continue

        # Column-header rows -- skip lines that are purely
        # header tokens like "ACTIVITY CODE TITLE OF POSITION FTE ..."
        # or the wrapped "3/ ANNUAL RATE RATE SALARY 2/ SALARY SALARY"
        # or "RATE". Check BEFORE the footnote-starter regex, since
        # the wrapped header line begins with `3/` which would
        # otherwise be misread as a footnote body.
        if _is_column_header_row(text_row):
            continue

        # Footnote lines (`1/ The number of ...`) sit at the bottom of
        # each program's page span. Once we see one, the rest of the
        # page is footnote continuation text.
        if _FOOTNOTE_STARTER_RE.match(text_row):
            in_footnote = True
            continue
        if in_footnote:
            continue

        # PROGRAM banner
        banner = _extract_program_banner(row)
        if banner is not None:
            program_code, program_label = banner
            # Retrieve any previously-established anchors for this
            # (fund, kind, program) -- older-vintage continuation pages
            # (2013-14 / 2014-15) sometimes open on a subtotal row that
            # can't establish anchors on its own.
            column_anchors = anchors_by_program.get(
                (fund, exhibit_kind, program_code)
            )
            continue

        # Numeric tokens (candidates for value columns).
        value_words = [w for w in row
                       if _VALUE_TOKEN_RE.match(w["text"])
                       and w["x0"] >= 200]
        if not value_words:
            continue

        # Establish anchors from the first row with N numeric tokens
        # matching the expected column count for this vintage. Details
        # rows (which have all columns populated) come first on every
        # page for a NEW program. For continuation pages, anchors were
        # retrieved above from `anchors_by_program`.
        if column_anchors is None:
            if len(value_words) >= n_cols_expected:
                # Take the rightmost N tokens as the column anchors.
                anchor_words = sorted(
                    value_words, key=lambda w: w["x1"]
                )[-n_cols_expected:]
                column_anchors = [w["x1"] for w in anchor_words]
                if program_code is not None:
                    anchors_by_program[
                        (fund, exhibit_kind, program_code)
                    ] = column_anchors
            else:
                # Can't establish anchors yet -- skip this row and
                # wait for a fully-populated detail row.
                continue

        # Classify row.
        is_activity_total = bool(_ACTIVITY_TOTAL_RE.match(text_row))
        is_program_total = bool(_PROGRAM_TOTAL_RE.match(text_row))

        activity_code = ""
        duty_code = ""
        title = ""
        row_kind = ""

        if is_program_total:
            row_kind = "program_total"
        elif is_activity_total:
            m = _ACTIVITY_TOTAL_RE.match(text_row)
            activity_code = m.group(1).upper()
            row_kind = "activity_total"
        else:
            m = _DUTY_CODE_RE.match(text_row)
            if m is None:
                # Not a recognized data row -- e.g. label wrap for a
                # multi-line title. Skip.
                continue
            # program_code from the code is authoritative for detail
            # rows (in case we entered without a preceding banner --
            # happens on Overview vs Budget differences).
            code_prog = m.group(1).upper()
            if program_code is None:
                program_code = code_prog
            activity_code = m.group(2).upper()
            duty_code = m.group(3)
            row_kind = "detail"
            # Title = the rest of the label (everything between the
            # duty code and the first numeric value).
            first_value_x0 = min(w["x0"] for w in value_words)
            label_words = [w for w in row if w["x0"] < first_value_x0]
            label_text = re.sub(
                r"\s+", " ",
                " ".join(w["text"] for w in label_words).strip()
            )
            title = re.sub(_DUTY_CODE_RE, "", label_text).strip()

        if program_code is None:
            # No banner seen yet -- can happen if the page starts
            # mid-program (never observed in practice, but be safe).
            continue

        # Bin numeric tokens by right-edge x1 against column anchors.
        binned: List[Optional[str]] = [None] * n_cols_expected
        for vw in value_words:
            idx = _closest_column(vw["x1"], column_anchors)
            if idx is not None and binned[idx] is None:
                binned[idx] = vw["text"]

        parsed = [parse_decimal(v) if v is not None else None for v in binned]

        # Assemble the schema fields based on exhibit_kind + vintage.
        record = _build_record(
            base=base,
            fund=fund,
            exhibit_kind=exhibit_kind,
            program_code=program_code,
            program_label=program_label or "",
            activity_code=activity_code,
            duty_code=duty_code,
            row_kind=row_kind,
            title=title,
            values=parsed,
        )

        key = (
            record["school_year"], record["ccddd"], record["exhibit_kind"],
            record["fund"], record["program_code"], record["activity_code"],
            record["duty_code"], record["row_kind"],
        )
        if key in seen:
            continue
        seen[key] = True
        rows_out.append(record)


def _is_primary_row(row) -> bool:
    """Row starts with a recognizable label (`PP-AA-DDD`, `ACTIVITY
    CODE`, `PROGRAM TOTAL`, `PROGRAM NN`)."""
    text = re.sub(r"\s+", " ",
                  " ".join(w["text"] for w in row).strip())
    if _DUTY_CODE_RE.match(text):
        return True
    if _ACTIVITY_TOTAL_RE.match(text):
        return True
    if _PROGRAM_TOTAL_RE.match(text):
        return True
    return False


def _merge_wrap_fragments(rows):
    """Absorb orphan wrap-body / wrap-tail rows into their parent row.

    Two wrap shapes are handled:

      1. **Tail wrap** -- orphan row of 1-3 bare tokens (0, 40, ...)
         sitting BELOW a primary row at the same x1. The orphan tokens
         get APPENDED to the parent's value at that column.

      2. **Body wrap** -- orphan row with a `X,XXX.XX`-shaped value
         sitting ABOVE a primary row at the same x1. The orphan's text
         gets PREPENDED to the parent's value at that column. This
         happens on FTE / HOURS columns whose 3-decimal or 2-decimal
         values overflow the printed column width -- the digit body
         wraps to the previous visual line and only the trailing digit
         lands on the detail row's y.

    Orphans are attached to whichever adjacent row is a primary row
    (has a recognizable label prefix). Orphans that fall between two
    orphans, or with no adjacent primary, are discarded.
    """
    n = len(rows)
    consumed = [False] * n

    # First pass: attach each orphan to its nearest primary neighbor.
    for i, row in enumerate(rows):
        if consumed[i]:
            continue
        if not _looks_like_wrap_only_row(row):
            continue

        row_top = _row_top(row)

        # Prefer merging into the SUBSEQUENT primary row (body-wrap
        # case is more common for FTE / HOURS on large districts).
        after = None
        if i + 1 < n and _is_primary_row(rows[i + 1]):
            after_top = _row_top(rows[i + 1])
            if after_top - row_top <= _WRAP_MAX_Y_GAP:
                after = rows[i + 1]
        # Otherwise merge into the PREVIOUS primary row (tail-wrap).
        before = None
        if after is None and i > 0 and _is_primary_row(rows[i - 1]):
            before_top = _row_top(rows[i - 1])
            if row_top - before_top <= _WRAP_MAX_Y_GAP:
                before = rows[i - 1]

        if after is not None:
            _absorb_body_into_next(row, after)
            consumed[i] = True
        elif before is not None:
            _absorb_tail_into_prev(row, before)
            consumed[i] = True
        # Else: orphan with no primary neighbor -- drop.
        else:
            consumed[i] = True

    return [rows[i] for i in range(n) if not consumed[i]]


def _absorb_body_into_next(orphan_row, next_row):
    """Prepend each orphan token's text to the next row's value at the
    same x1."""
    for w in orphan_row:
        best = None
        best_d = _COL_TOLERANCE
        for pw in next_row:
            if not _VALUE_TOKEN_RE.match(pw["text"]):
                continue
            d = abs(pw["x1"] - w["x1"])
            if d <= best_d:
                best = pw
                best_d = d
        if best is not None:
            best["text"] = w["text"] + best["text"]


def _absorb_tail_into_prev(orphan_row, prev_row):
    """Append each orphan token's text to the previous row's value at
    the same x1."""
    for w in orphan_row:
        best = None
        best_d = _COL_TOLERANCE
        for pw in prev_row:
            if not _VALUE_TOKEN_RE.match(pw["text"]):
                continue
            d = abs(pw["x1"] - w["x1"])
            if d <= best_d:
                best = pw
                best_d = d
        if best is not None:
            best["text"] = best["text"] + w["text"]


_COL_HEADER_TOKENS = {
    "ACTIVITY", "CODE", "TITLE", "OF", "POSITION", "FTE",
    "HIGH", "LOW", "AVERAGE", "ANNUAL", "RATE", "TOTAL",
    "SALARY", "STATE", "LOCAL", "NUMBER", "HOURS", "HOURLY",
}


def _is_column_header_row(text_row: str) -> bool:
    """True if the row is entirely made of column-header tokens.

    Column headers can wrap across 3 physical lines
    (`ACTIVITY CODE TITLE OF POSITION FTE 1/, HIGH LOW ANNUAL AVERAGE
    ANNUAL TOTAL ANNUAL ANNUAL STATE ANNUAL LOCAL` / `3/ ANNUAL RATE
    RATE SALARY 2/ SALARY SALARY` / `RATE`). Any token that isn't a
    known header word or a footnote marker (1/, 2/, 3/) disqualifies.
    """
    tokens = text_row.replace(",", " ").split()
    if not tokens:
        return False
    for t in tokens:
        # Footnote markers
        if re.fullmatch(r"\d\s*/", t) or re.fullmatch(r"\d/", t):
            continue
        if re.fullmatch(r"[13]/,?", t):
            continue
        if t.upper() in _COL_HEADER_TOKENS:
            continue
        return False
    return True


def _expected_col_count(exhibit_kind: str, class_of: int) -> int:
    """Number of numeric columns per detail row.

    - Certificated: FTE HIGH LOW AVG TOTAL [STATE LOCAL]
    - Classified:   FTE HOURS HIGH LOW AVG TOTAL [STATE LOCAL]

    STATE/LOCAL split added in 2019-20 (`class_of >= 2020`).
    """
    modern = class_of >= 2020
    if exhibit_kind == "certificated":
        return 7 if modern else 5
    else:
        return 8 if modern else 6


def _build_record(*, base, fund, exhibit_kind, program_code, program_label,
                  activity_code, duty_code, row_kind, title, values):
    """Map the parsed column values into the schema fields."""
    modern = base["class_of"] >= 2020

    if exhibit_kind == "certificated":
        # Columns: FTE HIGH LOW AVG TOTAL [STATE LOCAL]
        fte = values[0] if len(values) > 0 else None
        high = values[1] if len(values) > 1 else None
        low = values[2] if len(values) > 2 else None
        avg = values[3] if len(values) > 3 else None
        total = values[4] if len(values) > 4 else None
        state = values[5] if modern and len(values) > 5 else None
        local = values[6] if modern and len(values) > 6 else None
        hours = None
    else:
        # Columns: FTE HOURS HIGH LOW AVG TOTAL [STATE LOCAL]
        fte = values[0] if len(values) > 0 else None
        hours = values[1] if len(values) > 1 else None
        high = values[2] if len(values) > 2 else None
        low = values[3] if len(values) > 3 else None
        avg = values[4] if len(values) > 4 else None
        total = values[5] if len(values) > 5 else None
        state = values[6] if modern and len(values) > 6 else None
        local = values[7] if modern and len(values) > 7 else None

    # Subtotal rows: HIGH/LOW/AVG (and HOURS for classified) are blank;
    # the 4 (or 3 for legacy) reported columns are FTE, TOTAL, [STATE,
    # LOCAL]. When we bin against the detail-row anchors, the subtotal's
    # values land in the FTE and TOTAL/STATE/LOCAL columns and the rate
    # columns end up None -- which is exactly what the schema wants.

    return {
        **base,
        "exhibit_kind": exhibit_kind,
        "fund": fund,
        "program_code": program_code,
        "activity_code": activity_code,
        "duty_code": duty_code,
        "row_kind": row_kind,
        "program_label": program_label,
        "title_of_position": title,
        "fte": fte,
        "number_of_hours": hours,
        "high_rate": high,
        "low_rate": low,
        "avg_rate": avg,
        "total_annual_salary": total,
        "state_annual_salary": state,
        "local_annual_salary": local,
    }


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
