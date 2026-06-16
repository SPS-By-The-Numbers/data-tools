"""Parse one OSPI Report 1220 Special Education Allocations PDF.

The form uses heavy dotted-leader formatting between labels and
values, which pdfplumber's standard text extraction collapses into
fragmented value tokens like '1..7..2.09' instead of '172.09'. Using
`extract_words(use_text_flow=True)` instead avoids the leader
contamination: dot-leaders become their own (large) tokens and values
land in clean separate tokens with intact bounding boxes.

The parser is a small state machine that walks lines top-to-bottom:
  - Tracks the current `section` based on form section headers.
  - Tracks `pending_item` for items whose label wraps across two
    lines (F, G): the value lands on the continuation line.
  - Tracks `last_letter` so that sub-items printed only as `1.`/`2.`/
    `3.` (under J) can be emitted as `J.1` / `J.2` / `J.3`.
  - Recognizes per-serving-district enrollment rows by the 5-digit
    CCDDD prefix; the TOTAL row anchors the matrix close-out.

Coverage scope: district-level files only. ESD-level 1220TR Transfer
of Allocation files (2013-14 through 2016-17, replicated under member
subdirs) use a different form and are not parsed here.
"""

import logging
import re
from typing import Iterator, List, Optional

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, merge_split_leading_digit,
    parse_decimal,
)


logger = logging.getLogger(__name__)


_LEAF_RE = re.compile(r"^1220\s+Special\s+Education\s+Allocation$", re.IGNORECASE)

# Header / status detection.
_REPORT_DATE_RE = re.compile(r"^Report\s+1220F?\b.*?(\S+-\S+-\S+)\s*$", re.IGNORECASE)
_TITLE_STATUS_RE = re.compile(
    r"^\s*\d{4}-\d{4}\s+Special\s+Education\s+Allocations?\s*[-–]?\s*(.+?)\s*$",
    re.IGNORECASE,
)
_RECIPIENT_RE = re.compile(r"^(\d{5})\s+(.+?)\s*$")

# Item letter prefix at start of line. `A.` ... `Z.` (single letter) or
# `AA.` (double letter for the last 4122 totals) or digit `1.`/`2.`/`3.`
# (J sub-items).
_LETTER_PREFIX_RE = re.compile(r"^([A-Z]{1,2}|[1-9])\.$")

# Section banners.
_SEC_4121_RE = re.compile(r"^Account\s+4121\b", re.IGNORECASE)
_SEC_3121_RE = re.compile(r"^Account\s+3121\b", re.IGNORECASE)
_SEC_4122_RE = re.compile(r"^Account\s+4122\b", re.IGNORECASE)
_SEC_SERVING_RE = re.compile(r"^ENROLLMENT\s+BY\s+SERVING\s+DISTRICT\b", re.IGNORECASE)
_SUM_TOTAL_ALLOC_RE = re.compile(r"^Total\s+Allocation\s+for\s+Special", re.IGNORECASE)
_SUM_PLD_PCT_RE = re.compile(r"^Percentage\s+Portion\s+of\s+BEA", re.IGNORECASE)
_SUM_PLD_PORTION_RE = re.compile(r"^Portion\s+of\s+PLD\b", re.IGNORECASE)

# Indented sub-item under H (not letter-prefixed).
_PLD_BEA_PORTION_RE = re.compile(
    r"^Portion\s+of\s+BEA\s+Rate\s+Attributed\s+to\s+PLD\b", re.IGNORECASE,
)

# Serving-district row: starts with a 5-digit CCDDD.
_CCDDD_RE = re.compile(r"^\d{5}$")
_TOTAL_ROW_RE = re.compile(r"^TOTAL$", re.IGNORECASE)

# Value-token recognizer. Accepts:
#   - `$` alone (currency marker)
#   - `-` alone (zero placeholder)
#   - signed comma-grouped numbers with optional decimal
#   - parenthesized negatives
#   - any of the above with a `%` suffix
# Doesn't accept tokens with embedded letters or with leading characters
# that aren't `$`, `(`, `-`, or a digit -- guards against label tokens
# like `(C/D)` (has paren but content isn't all-numeric) or `K-21` (has
# digit but starts with letter).
_VALUE_TOKEN_RE = re.compile(
    r"""^(?:
        \$|-|%
        |\$?\(?-?\$?[\d,]+(?:\.\d+)?\)?%?
    )$""",
    re.VERBOSE,
)
# Pure dot-leader tokens (possibly with a trailing `$` currency marker
# fused in). A token like `'.......-'` is NOT pure leader: the trailing
# `-` is the zero-placeholder value that `_strip_leading_leader` can
# recover.
_LEADER_RE = re.compile(r"^[.…]+\$?$")

# `<label-prefix><leader-dots><value>` decomposition. pdfplumber's
# token boundaries don't always split the dotted leader from its
# neighbours: some tokens are `'.........0.00'` (leader + value),
# others are `'Instruction.............28.12%'` (label + leader +
# value). The trailing value still parses cleanly once we identify it.
_DECOMPOSE_RE = re.compile(r"^(.*?)([.…]+)([\$\(\-\d].*)$")


def _decompose_token(text: str):
    """Split a token into (label_prefix, value).

    - `'25.10%'`                   -> `('', '25.10%')` (clean value)
    - `'Instruction......28.12%'`  -> `('Instruction', '28.12%')`
    - `'..........0.00'`           -> `('', '0.00')`
    - `'$8,345.56'`                -> `('', '$8,345.56')`
    - `'Enrollment'`               -> `('Enrollment', None)`

    Clean values are checked first so the decompose regex doesn't
    misinterpret an internal decimal point as the leader (e.g.
    `'25.10%'` getting split into `('25', '10%')`).
    """
    if _VALUE_TOKEN_RE.match(text):
        return "", text
    m = _DECOMPOSE_RE.match(text)
    if m:
        candidate = m.group(3)
        if _VALUE_TOKEN_RE.match(candidate):
            return m.group(1), candidate
    return text, None


# Per-section semantic item codes for Account 4122. The printed letters
# drifted across years (2013-14 through 2018-19 used Y/Z/AA;
# 2019-20+ uses V/W/X), so cross-year analysis on the printed letter is
# unreliable. The 3 items always appear in the same order; this map
# turns the position into a stable slug.
_4122_ITEM_CODES = (
    "age_0_2_allocation",
    "transfer_acct_4122",
    "total_acct_4122",
)


def parse_sped_1220_pdf(info: FiscalFilename) -> Iterator[dict]:
    if not _LEAF_RE.match(info.leaf):
        return
    # ESD-path files are the 1220TR Transfer of Allocation form, not
    # the per-district 1220. Skip cleanly.
    if info.org_type == "esd":
        return

    import pdfplumber  # local import — parsers/common doesn't expose word-level
    lines: List[List[dict]] = []
    with pdfplumber.open(info.path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(use_text_flow=True)
            lines.extend(_group_words_into_lines(words))

    # Header scan.
    report_date_text = ""
    status = ""
    focal_ccddd = info.ccddd if info.ccddd is not None else 0
    district = ""

    for words_line in lines[:8]:
        ln = " ".join(w["text"] for w in words_line)
        if not report_date_text:
            m = _REPORT_DATE_RE.match(ln)
            if m:
                report_date_text = m.group(1).strip()
        if not status:
            m = _TITLE_STATUS_RE.match(ln)
            if m:
                status = _normalize_status(m.group(1).strip())
        if not district:
            m = _RECIPIENT_RE.match(ln)
            if m and m.group(1) != info.school_year.split("-")[0]:
                code = int(m.group(1))
                if code == focal_ccddd or focal_ccddd == 0:
                    focal_ccddd = code
                    district = m.group(2).strip()

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": focal_ccddd,
        "county": "",
        "district": district,
        "status": status or "Final",
        "report_date_text": report_date_text,
        "_source": _source_path(info.path),
        "_source_table": "fiscal_1220_sped",
    }

    section: Optional[str] = None
    pending_item: Optional[str] = None
    pending_label: str = ""
    last_letter: Optional[str] = None
    sec_4122_pos: int = 0  # ordinal of items emitted in account_4122

    for words_line in lines:
        if not words_line:
            continue
        ln = " ".join(w["text"] for w in words_line)
        head = words_line[0]["text"]

        # Section transitions.
        if _SEC_4121_RE.match(ln):
            section = "account_4121"
            pending_item = None
            last_letter = None
            continue
        if _SEC_SERVING_RE.match(ln):
            section = "serving_district_enrollment"
            pending_item = None
            last_letter = None
            continue
        if _SEC_3121_RE.match(ln):
            section = "account_3121"
            pending_item = None
            last_letter = None
            continue
        if _SEC_4122_RE.match(ln):
            section = "account_4122"
            pending_item = None
            last_letter = None
            sec_4122_pos = 0
            continue

        # Summary three-liner (between 3121 and 4122). These items don't
        # have letter prefixes; they're recognized by leading text.
        if _SUM_TOTAL_ALLOC_RE.match(ln):
            section = "summary"
            row = _emit_with_value(base, "summary",
                                   "total_allocation_spe21",
                                   _strip_value_label(ln, _SUM_TOTAL_ALLOC_RE),
                                   words_line)
            if row:
                yield row
            pending_item = None
            last_letter = None
            continue
        if _SUM_PLD_PCT_RE.match(ln):
            row = _emit_with_value(base, "summary", "pld_pct",
                                   _strip_value_label(ln, _SUM_PLD_PCT_RE),
                                   words_line)
            if row:
                yield row
            continue
        if _SUM_PLD_PORTION_RE.match(ln):
            row = _emit_with_value(base, "summary", "pld_portion",
                                   _strip_value_label(ln, _SUM_PLD_PORTION_RE),
                                   words_line)
            if row:
                yield row
            continue

        # Indented "Portion of BEA Rate Attributed to PLD" under H.
        if section == "account_4121" and _PLD_BEA_PORTION_RE.match(ln):
            row = _emit_with_value(base, section,
                                   "pld_portion_bea_rate",
                                   _strip_value_label(ln, _PLD_BEA_PORTION_RE),
                                   words_line)
            if row:
                yield row
            continue

        # Serving-district per-row: starts with 5-digit CCDDD.
        if (section == "serving_district_enrollment"
                and _CCDDD_RE.match(head)):
            yield from _emit_serving_district_row(base, words_line, is_total=False)
            continue
        if section == "serving_district_enrollment" and _TOTAL_ROW_RE.match(head):
            yield from _emit_serving_district_row(base, words_line, is_total=True)
            continue

        # Letter-prefixed item line.
        if _LETTER_PREFIX_RE.match(head):
            letter = head.rstrip(".")
            label_words = words_line[1:]
            value_token, label_words_clean = _extract_trailing_value(label_words)
            label_text = _format_label(label_words_clean)
            # Sub-item under a parent letter (1./2./3. under J).
            if letter.isdigit() and last_letter:
                item_code = f"{last_letter}.{letter}"
            else:
                item_code = letter

            if value_token is None:
                # Parent / wrapped-label line — defer until the next
                # line carries a value.
                pending_item = item_code
                pending_label = label_text
                if not letter.isdigit():
                    last_letter = letter
                continue

            value, value_text = _parse_value(value_token)
            sec = section or "account_4121"
            # Account 4122 letter assignments drifted between vintages
            # (pre-2019: Y/Z/AA; post-2019: V/W/X). Use the positional
            # slug from `_4122_ITEM_CODES` so the same item carries the
            # same code across years.
            if sec == "account_4122":
                if sec_4122_pos < len(_4122_ITEM_CODES):
                    item_code = _4122_ITEM_CODES[sec_4122_pos]
                sec_4122_pos += 1
            yield {
                **base,
                "section": sec,
                "item_code": item_code,
                "item_label": label_text,
                "subject_ccddd": 0,
                "subject_name": "",
                "value": value,
                "value_text": value_text,
            }
            if not letter.isdigit():
                last_letter = letter
            pending_item = None
            continue

        # Continuation line for a pending wrapped-label item (F, G).
        if pending_item is not None and section in {"account_4121",
                                                    "account_3121",
                                                    "account_4122"}:
            value_token, label_words_clean = _extract_trailing_value(words_line)
            if value_token is not None:
                value, value_text = _parse_value(value_token)
                cont_label = _format_label(label_words_clean)
                joined = (pending_label + " / " + cont_label).strip(" /")
                yield {
                    **base,
                    "section": section,
                    "item_code": pending_item,
                    "item_label": joined,
                    "subject_ccddd": 0,
                    "subject_name": "",
                    "value": value,
                    "value_text": value_text,
                }
                pending_item = None
                continue


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _group_words_into_lines(words: List[dict], tol: float = 3.0) -> List[List[dict]]:
    """Bucket words by their `top` y-coordinate.

    Two words are on the same line if their tops differ by less than
    `tol` points. Each bucket is sorted left-to-right by `x0`.
    """
    buckets: List[List[dict]] = []
    bucket_tops: List[float] = []
    for w in words:
        placed = False
        for i, top in enumerate(bucket_tops):
            if abs(w["top"] - top) < tol:
                buckets[i].append(w)
                placed = True
                break
        if not placed:
            buckets.append([w])
            bucket_tops.append(w["top"])
    # Sort by top y, then sort each line by x0.
    order = sorted(range(len(buckets)), key=lambda i: bucket_tops[i])
    return [sorted(buckets[i], key=lambda w: w["x0"]) for i in order]


def _extract_trailing_value(words: List[dict]):
    """Find the trailing numeric value in a list of words.

    Returns (value_token, label_words). `label_words` is a list of
    `(word_dict_or_None, text)` pairs -- the dict reference is
    preserved for words that survived intact, with `None` and a
    plain-text label-prefix for the token whose tail held the value.
    """
    # Drop pure-leader tokens. A token with embedded leader+value
    # (e.g. `'Instruction.........28.12%'`) is NOT pure leader.
    clean = [w for w in words if not _LEADER_RE.match(w["text"])]
    if not clean:
        return None, []

    n = len(clean)

    # Try to decompose the last token.
    last_label, last_value = _decompose_token(clean[-1]["text"])
    if last_value is None:
        return None, [(w, w["text"]) for w in words]

    # Handle a trailing `$` currency marker. The actual value lives in
    # the token just before it.
    if last_value == "$":
        if n < 2:
            return None, [(w, w["text"]) for w in words]
        prev_label, prev_value = _decompose_token(clean[-2]["text"])
        if prev_value is None or prev_value == "$":
            return None, [(w, w["text"]) for w in words]
        label_words = [(w, w["text"]) for w in clean[: n - 2]]
        if prev_label:
            label_words.append((None, prev_label))
        return prev_value, label_words

    # `last_value` is the value itself. A `$` may live immediately
    # before; drop it.
    drop_n = 1
    if n >= 2:
        _, prev_value = _decompose_token(clean[-2]["text"])
        if prev_value == "$":
            drop_n = 2
    label_words = [(w, w["text"]) for w in clean[: n - drop_n]]
    if last_label:
        label_words.append((None, last_label))
    return last_value, label_words


def _format_label(tokens) -> str:
    """Join label tokens, accepting either word dicts or (word, text) pairs."""
    parts = []
    for t in tokens:
        if isinstance(t, tuple):
            _, text = t
        elif isinstance(t, dict):
            text = t["text"]
        else:
            text = str(t)
        if _LEADER_RE.match(text):
            continue
        parts.append(text)
    text = " ".join(parts)
    return re.sub(r"\s+", " ", text).strip(" .……")


def _parse_value(value_text: str):
    """Parse a value token to (decimal, value_text). NULL for the `-` placeholder."""
    if value_text in ("-", "$-"):
        return None, value_text
    cleaned = value_text.strip()
    raw = cleaned
    has_percent = cleaned.endswith("%")
    if has_percent:
        cleaned = cleaned[:-1]
    cleaned = cleaned.lstrip("$")
    cleaned = collapse_numeric_paren_spaces(merge_split_leading_digit(cleaned))
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    return parse_decimal(cleaned), raw


def _normalize_status(s: str) -> str:
    """Normalize the title-line status suffix.

    'Final' stays 'Final'. 'for <date>' becomes the date string (parsed
    to YYYY-MM-DD where possible, else left verbatim).
    """
    s = s.strip().strip(" -")
    if s.lower().startswith("for "):
        date = s[4:].strip()
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", date)
        if m:
            mo, da, yr = m.groups()
            yr_int = int(yr)
            if yr_int < 100:
                yr_int += 2000
            return f"{yr_int:04d}-{int(mo):02d}-{int(da):02d}"
        return date
    return s or "Final"


def _strip_value_label(ln: str, pat: re.Pattern) -> List[dict]:
    """Unused -- placeholder for label-strip from a regex anchor."""
    return []  # values come from `words_line` in emit_with_value


def _emit_with_value(base: dict, section: str, item_code: str,
                     _unused, words_line: List[dict]) -> Optional[dict]:
    value_token, label_words = _extract_trailing_value(words_line)
    if value_token is None:
        return None
    value, value_text = _parse_value(value_token)
    label_text = _format_label(label_words)
    return {
        **base,
        "section": section,
        "item_code": item_code,
        "item_label": label_text,
        "subject_ccddd": 0,
        "subject_name": "",
        "value": value,
        "value_text": value_text,
    }


def _emit_serving_district_row(base: dict, words_line: List[dict],
                               is_total: bool) -> Iterator[dict]:
    """Emit 4 rows (A/B/C/D enrollment counts) for one serving-district row."""
    # Collect value tokens from the right.
    clean = [w for w in words_line if not _LEADER_RE.match(w["text"])]
    values = []
    for w in reversed(clean):
        _, stripped = _decompose_token(w["text"])
        if stripped and _VALUE_TOKEN_RE.match(stripped) and stripped not in ("$", "-"):
            values.append(stripped)
            if len(values) == 4:
                break
        else:
            break
    if len(values) != 4:
        return
    values.reverse()
    if is_total:
        subject_ccddd = 0
        subject_name = ""
    else:
        subject_ccddd = int(clean[0]["text"])
        # Name = everything between the CCDDD and the 4 value tokens.
        name_tokens = clean[1: -4] if len(clean) >= 5 else []
        subject_name = " ".join(w["text"] for w in name_tokens)
    for letter, vt in zip(("A", "B", "C", "D"), values):
        value, value_text = _parse_value(vt)
        yield {
            **base,
            "section": "serving_district_enrollment",
            "item_code": letter,
            "item_label": "",
            "subject_ccddd": subject_ccddd,
            "subject_name": subject_name,
            "value": value,
            "value_text": value_text,
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
