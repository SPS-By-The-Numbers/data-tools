"""Parse a single OSPI Form 1191SI PDF.

Form 1191SI is a per-state-institution allocation worksheet -- 2 pages
(Allocation Calculation + Year-End Adjustment) of ~50 numbered line items.
The form's row layout drifts across years, so the parser captures items
verbatim by their printed numbering rather than coercing into a canonical
layout. See `schemas/state_institutions.py` for the resulting fact-table shape.

The State Summary file (`00000 State Summary 1191SI.pdf`) uses the same
layout but with the aggregate values; it's parsed exactly the same as a
per-institution file -- its CCDDD is the sentinel `0`.
"""

import logging
import re
from typing import Iterator, Optional

from ..filename import FiscalFilename
from .common import (
    collapse_numeric_paren_spaces, is_na, merge_split_leading_digit,
    parse_decimal, read_pdf_lines,
)


logger = logging.getLogger(__name__)


def _source_path(p) -> str:
    """Relative path from data/fiscal/ to `p`, used as the unique source key.

    Leaves the path absolute if the corpus root isn't present in the path
    components (mostly for adhoc one-file invocations from outside the tree).
    """
    parts = list(p.parts)
    try:
        idx = max(i for i, seg in enumerate(parts[:-1]) if seg == "fiscal" and parts[i+1] in {
            "apportionment", "fiscal", "state_institutions", "esd_allocations",
            "county_treasurer", "state_agencies_schools_colleges", "technical_colleges",
        })
    except ValueError:
        return str(p)
    return "/".join(parts[idx + 1:])


# Top-of-document header lines.
# OSPI cycles through several status words across years/revisions:
# Initial (forecast), Revised, Actual (post-actuals reissue), Final (2020-21).
_HEADER_ALLOC_RE = re.compile(
    r"^(Initial|Revised|Actual|Final)\s+\d{4}-\d{2,4}\s+School\s+Year\s+Allocation\s+for\s+Revenue\s+Account:\s*(.+?)\s*$",
    re.IGNORECASE,
)
_HEADER_INSTITUTION_RE = re.compile(
    r"^(.+?)\s+served\s+by\s+(.+?)\s+\((\d{5})\)\s*$",
    re.IGNORECASE,
)
# Leaf-filename split: '{ccddd} {name} 1191SI' -> (ccddd, name).
_LEAF_RE = re.compile(r"^(\d{5})\s+(.+?)\s+1191SI$")

# Section headers: single capital letter, period, then a "mostly all-caps"
# title. Done as a function rather than a regex because at least one form
# in the corpus has a lowercase-letter typo in the section title
# (`F. STATE INSTITUTiON PROFESSIONAL LEARNING DAYS` in 2018-19), and we
# can't tighten the "first word is all caps" check without also matching
# Section E's sub-items (`A. CIS and CAS Maintenance Allocation ...`),
# which start with a 3-letter uppercase acronym but have many lowercase
# letters overall.
_SECTION_LINE_RE = re.compile(r"^([A-Z])\.\s+(.+?)\s*$")
_SECTION_TITLE_LOWERCASE_TOLERANCE = 3


def _match_section_header(ln: str):
    m = _SECTION_LINE_RE.match(ln)
    if not m:
        return None
    letter, title = m.group(1), m.group(2).strip()
    if not title or not title[0].isupper() and not title[0].isdigit():
        return None
    if sum(1 for c in title if c.islower()) > _SECTION_TITLE_LOWERCASE_TOLERANCE:
        return None
    return letter, title

# Numbered item line: leading number + period + label, with optional leading
# asterisks (footnote markers OSPI sprinkles on a handful of rows per page).
_ITEM_NUMBERED_RE = re.compile(r"^\*{0,2}\s*(\d+)\.\s+(.+)$")

# Lettered sub-item line (used inside Section E for E.1.A, E.1.B, etc.).
_ITEM_LETTERED_RE = re.compile(r"^\*{0,2}\s*([A-Z])\.\s+(.+)$")


def _split_label_value(rest: str):
    """Split an item-line's text into (label, value_text, value).

    Strategy: the value is always the rightmost whitespace-separated token if
    it parses as a Decimal or matches an N/A token; otherwise the line is a
    label-only subheader (e.g. Section E's '1. Health Benefits') and we
    return value=None.
    """
    rest = rest.strip()
    if not rest:
        return rest, "", None
    parts = rest.rsplit(None, 1)
    if len(parts) < 2:
        return rest, "", None
    label, value_text = parts[0].strip(), parts[1].strip()
    if is_na(value_text):
        return label, value_text, None
    val = parse_decimal(value_text)
    if val is None:
        # Last token isn't numeric -- treat the whole line as a label-only row.
        return rest, "", None
    return label, value_text, val


def _parse_header(lines):
    """Walk top-of-document lines, returning (revenue_account, allocation_status,
    institution_name, served_by_district, header_end_idx).

    Stops scanning at the first line that matches a Section header (so all
    body lines remain to be processed by the caller).
    """
    revenue_account = ""
    allocation_status = ""
    institution_name = ""
    served_by_district = ""
    end_idx = 0
    for i, ln in enumerate(lines):
        if _match_section_header(ln):
            end_idx = i
            break
        m = _HEADER_ALLOC_RE.match(ln)
        if m:
            allocation_status = m.group(1).strip().capitalize()
            revenue_account = m.group(2).strip()
            continue
        m = _HEADER_INSTITUTION_RE.match(ln)
        if m:
            institution_name = m.group(1).strip()
            served_by_district = m.group(2).strip()
            continue
    else:
        # No section header found -- nothing parseable.
        end_idx = len(lines)
    return revenue_account, allocation_status, institution_name, served_by_district, end_idx


def parse_state_institutions_pdf(info: FiscalFilename) -> Iterator[dict]:
    """Yield one dict per item row extracted from `info.path`."""
    raw_lines = read_pdf_lines(info.path)
    # `read_pdf_lines` already normalizes em/en/Unicode dashes -> '-', so the
    # header regex below can rely on ASCII hyphens in the year span.
    lines = [collapse_numeric_paren_spaces(merge_split_leading_digit(ln))
             for ln in raw_lines]

    rev_acct, alloc_status, _body_inst, served_by, header_end = _parse_header(lines)

    # Institution name + ccddd come from the filename, not the body: the body
    # format varies across years (`X served by Y (ccddd)` vs ALL-CAPS prefixed
    # with the code vs 'THE STATE INSTITUTIONS STATE SUMMARY'), but the leaf
    # name is consistent post-reorg.
    leaf_m = _LEAF_RE.match(info.leaf)
    if leaf_m:
        inst_name = leaf_m.group(2)
    else:
        # Fallback: whatever the body header gave us, or empty string.
        inst_name = _body_inst

    section_letter: Optional[str] = None
    section_title: str = ""
    section_seq_by_letter = {}     # letter -> last seq assigned
    current_section_seq = 0
    in_notes = False
    e_top_item: Optional[str] = None   # within Section E, the current "1." / "2." subheader
    # Form 1191SI's sections progress A,B,C,...,K on page 1 and K,L,M on page 2,
    # so the section letter is monotonic except for K being allowed to repeat
    # once. Older forms (2013-14, 2014-15) write Section E sub-items in
    # all-caps ('A. MAINTENANCE ALLOCATION [...]') and these would otherwise
    # be picked up as bogus second-occurrence Section A/B/... headers; the
    # ordering check rejects them.
    highest_letter_seen: Optional[str] = None
    k_repeated = False

    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd if info.ccddd is not None else 0,
        "county": "",
        "district": served_by,
        "institution_name": inst_name,
        "revenue_account": rev_acct or "",
        "allocation_status": alloc_status or "",
        "_source": _source_path(info.path),
        "_source_table": "fiscal_state_institutions",
    }

    for ln in lines[header_end:]:
        # Section headers end the notes block and start a new section.
        hdr = _match_section_header(ln)
        if hdr:
            candidate_letter, _ = hdr
            if highest_letter_seen is not None:
                if candidate_letter < highest_letter_seen:
                    hdr = None  # backwards-going letter: not a real section header
                elif candidate_letter == highest_letter_seen:
                    if candidate_letter == "K" and not k_repeated:
                        k_repeated = True  # second K (page 2 year-end section)
                    else:
                        hdr = None  # other same-letter repeat is bogus
        if hdr:
            section_letter, section_title = hdr
            highest_letter_seen = section_letter
            current_section_seq = section_seq_by_letter.get(section_letter, 0) + 1
            section_seq_by_letter[section_letter] = current_section_seq
            in_notes = False
            e_top_item = None
            # Section I uniquely prints its formula + value on the header line
            # itself (`I. FORMULA ALLOCATION [ ... ] 0.00`). If the title ends
            # with a numeric/NA token, split it off and emit a section-level
            # item carrying that value.
            tail = section_title.rsplit(None, 1)
            if len(tail) == 2:
                candidate = tail[1]
                if is_na(candidate) or parse_decimal(candidate) is not None:
                    section_title = tail[0].strip()
                    yield {
                        **base,
                        "section_code": section_letter,
                        "section_seq": current_section_seq,
                        "section_title": section_title,
                        "item_path": "",
                        "item_label": section_title,
                        "value": parse_decimal(candidate),
                        "value_text": candidate,
                    }
            continue
        if section_letter is None:
            continue
        # OSPI prints "NOTES * :" / "NOTES ** :" blocks at the bottom of each
        # page with numbered prose entries that LOOK like form items. Suppress
        # them until the next section header (or end of document).
        if ln.startswith("NOTES"):
            in_notes = True
            continue
        if in_notes:
            continue
        # Skip the per-page banner lines (REPORT 1191SI ..., STATE OF WASHINGTON,
        # SUPERINTENDENT OF PUBLIC INSTRUCTION, repeated institution header).
        if (ln.startswith("Report 1191SI") or ln.startswith("REPORT 1191SI")
                or ln.startswith("STATE OF WASHINGTON")
                or ln.startswith("SUPERINTENDENT OF PUBLIC INSTRUCTION")):
            continue
        if _HEADER_INSTITUTION_RE.match(ln):  # repeated mid-document
            continue

        m = _ITEM_NUMBERED_RE.match(ln)
        if m:
            item_num, rest = m.group(1), m.group(2).strip()
            label, value_text, value = _split_label_value(rest)
            item_path = item_num
            yield {
                **base,
                "section_code": section_letter,
                "section_seq": current_section_seq,
                "section_title": section_title,
                "item_path": item_path,
                "item_label": label,
                "value": value,
                "value_text": value_text,
            }
            if section_letter == "E" and value is None:
                # Section E's "1. Health Benefits" / "2. Statutory Benefits"
                # are subheaders; remember the number so the following A-D
                # lines can be attributed as E.{num}.A-D.
                e_top_item = item_num
            else:
                # In other sections (or E.3 which has a value), a numbered
                # item closes any pending E-subheader.
                if section_letter != "E":
                    e_top_item = None
            continue

        m = _ITEM_LETTERED_RE.match(ln)
        if m:
            letter, rest = m.group(1), m.group(2).strip()
            if section_letter == "E" and e_top_item is not None:
                label, value_text, value = _split_label_value(rest)
                item_path = f"{e_top_item}.{letter}"
                yield {
                    **base,
                    "section_code": section_letter,
                    "section_seq": current_section_seq,
                    "section_title": section_title,
                    "item_path": item_path,
                    "item_label": label,
                    "value": value,
                    "value_text": value_text,
                }
                continue
            # Stray lettered line outside E -- log and skip.
            logger.debug("ignored lettered line outside section E: %r", ln)
            continue
        # Anything else is layout noise (formula tails, page numbers, etc.).
