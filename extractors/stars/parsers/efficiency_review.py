"""Parser for STARS Efficiency Review (PDF, narrative).

The Efficiency Review is a multi-page narrative report written by a
Regional Transportation Coordinator for districts whose RER crossed
the 90% threshold relative to the prior year. Most of the document is
prose; this parser pulls a small set of structured numerics out of
the executive summary using regex, plus the threshold-band metadata
that is encoded into the scraper's filename subcategory.

Every field is best-effort: when the pattern doesn't match (rare
phrasing variations, redacted RTC names like "conducted by ." in
template placeholders), the corresponding column is left NULL.
"""

import logging
import re
from pathlib import Path
from typing import Iterator, Optional

import pdfplumber

from .common import normalize_pdf_text, parse_decimal
from ..filename import StarsFilename


logger = logging.getLogger(__name__)


# Match a decimal number, possibly with commas and a decimal point.
_NUM = r"[\d,]+(?:\.\d+)?"
# Trailing percent sign with optional space (OSPI sometimes prints "97. %").
_PCT_TAIL = r"%"

_FTE_RE = re.compile(
    r"full[- ]time equivalent enrollment for the\s+"
    r"(?P<review_year>\d{4}[-]\d{2,4}) school year\s+of\s+"
    r"(?P<fte>" + _NUM + r")\s+students",
    re.IGNORECASE,
)

_RIDERS_RE = re.compile(
    r"average of\s+(?P<basic>" + _NUM + r")\s+basic program riders\s+"
    r"and\s+(?P<special>" + _NUM + r")\s+special program riders",
    re.IGNORECASE,
)

_BUSES_COST_RE = re.compile(
    r"operated\s+(?P<buses>" + _NUM + r")\s+school buses[^.]*?"
    r"at a cost of\s+\$(?P<cost>" + _NUM + r")",
    re.IGNORECASE,
)

# "March 2017 relative efficiency rating (based on data from the 2015-16
# school year) was 100%" -- both "rating" and "score" variants seen.
# OSPI sometimes prints "97. %" with a space before the percent sign.
_RER_RE = re.compile(
    r"March\s+(?P<march_year>\d{4})\s+relative efficiency (?:rating|score)"
    r"[^.]*?was\s+(?P<pct>\.?\d[\d.]*)\s*" + _PCT_TAIL,
    re.IGNORECASE,
)

# Review issuance date appears on the cover page as a date on its own line.
_DATE_LINE_RE = re.compile(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$")

# Cover-page header naming the reviewed school year.
_COVER_YEAR_RE = re.compile(
    r"Transportation Efficiency Review of\s+"
    r"(?P<year>\d{4}[-]\d{2,4})\s+School Year",
    re.IGNORECASE,
)

# "RTC review was conducted by Rodney McKnight from Educational Service District 112."
# "The RTC review for Colville School District was conducted by Eric Engle."
# "The RTC review was conducted by ."  (template placeholder; name empty)
_RTC_RE = re.compile(
    r"RTC review(?:\s+for\s+[^.]+?)?\s+was conducted by\s+"
    r"(?P<name>[^.\n]+?)"
    r"(?:\s+from\s+(?P<esd>[^.\n]+?))?"
    r"\.",
    re.IGNORECASE,
)


_BAND_BY_KEYWORD = {"above": "above_90", "below": "below_90"}


def _parse_subcategory(subcat: Optional[str]):
    """Return (current_band, prior_band) from the filename subcategory."""
    if not subcat:
        return None, None
    cur = pri = None
    m = re.match(
        r"Current\s+(above|below)\s+90%\s+Prior\s+(above|below)\s+90%",
        subcat, re.IGNORECASE,
    )
    if m:
        cur = _BAND_BY_KEYWORD[m.group(1).lower()]
        pri = _BAND_BY_KEYWORD[m.group(2).lower()]
    return cur, pri


def _extract_rer_history(text: str):
    """Return (current, prior_1, prior_2) RERs by March year, latest first.

    The narrative typically mentions three March-year RER values: the
    current report's, plus the two prior years' for context. Sort by
    March year descending so current_rer is always the latest.
    """
    found = []
    for m in _RER_RE.finditer(text):
        try:
            yr = int(m.group("march_year"))
        except ValueError:
            continue
        val = parse_decimal(m.group("pct"))
        if val is None:
            continue
        found.append((yr, val))
    # Dedup by march_year (keep last occurrence -- usually a later mention
    # within the body overrides the exec-summary one if they differ).
    by_year = {}
    for yr, v in found:
        by_year[yr] = v
    sorted_desc = sorted(by_year.items(), key=lambda kv: -kv[0])
    cur = sorted_desc[0][1] if len(sorted_desc) > 0 else None
    p1 = sorted_desc[1][1] if len(sorted_desc) > 1 else None
    p2 = sorted_desc[2][1] if len(sorted_desc) > 2 else None
    return cur, p1, p2


def _extract_review_date(lines):
    """Find a bare date on its own line near the top of the document."""
    for ln in lines[:20]:
        s = ln.strip()
        if _DATE_LINE_RE.match(s):
            return s
    return None


def _clean_rtc_name(raw: Optional[str]) -> Optional[str]:
    """Trim and discard obvious template placeholders ('.', '«Field»', etc.)."""
    if raw is None:
        return None
    s = raw.strip()
    if not s or s in (".", ",") or s.startswith("«") or s.endswith("»"):
        return None
    return s


def parse_efficiency_review(info: StarsFilename) -> Iterator[dict]:
    """Yield exactly one stars_efficiency_review row per file."""
    if info.path.suffix.lower() != ".pdf":
        logger.warning("%s: efficiency_review parser only handles PDFs",
                       info.path.name)
        return

    with pdfplumber.open(info.path) as pdf:
        raw_pages = [page.extract_text() or "" for page in pdf.pages]
    full_text = "\n".join(normalize_pdf_text(p) for p in raw_pages)
    # Strip line-wrap newlines inside sentences for regex hits.
    flat_text = re.sub(r"\s+", " ", full_text)
    line_split = full_text.split("\n")

    current_band, prior_band = _parse_subcategory(info.org_type)

    fte_m = _FTE_RE.search(flat_text)
    riders_m = _RIDERS_RE.search(flat_text)
    bc_m = _BUSES_COST_RE.search(flat_text)
    rtc_m = _RTC_RE.search(flat_text)
    cur_rer, p1_rer, p2_rer = _extract_rer_history(flat_text)

    cover_m = _COVER_YEAR_RE.search(flat_text)
    review_year_text = (
        cover_m.group("year") if cover_m
        else fte_m.group("review_year") if fte_m
        else None
    )

    def _int_or_none(s):
        d = parse_decimal(s)
        return int(d) if d is not None else None

    yield {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd,
        "county": None,
        "district": info.district_name,
        "subcategory": info.org_type,
        "current_band": current_band,
        "prior_band": prior_band,
        "review_year_text": review_year_text,
        "review_date": _extract_review_date(line_split),
        "rtc_name": _clean_rtc_name(rtc_m.group("name")) if rtc_m else None,
        "rtc_esd": _clean_rtc_name(rtc_m.group("esd")) if rtc_m else None,
        "fte_enrollment": parse_decimal(fte_m.group("fte")) if fte_m else None,
        "basic_ride_equivalents": _int_or_none(riders_m.group("basic")) if riders_m else None,
        "special_ride_equivalents": _int_or_none(riders_m.group("special")) if riders_m else None,
        "buses": _int_or_none(bc_m.group("buses")) if bc_m else None,
        "total_cost": parse_decimal(bc_m.group("cost")) if bc_m else None,
        "current_rer": cur_rer,
        "prior_rer": p1_rer,
        "two_years_prior_rer": p2_rer,
        "_source": info.path.name,
        "_source_table": "stars_efficiency_review",
    }
