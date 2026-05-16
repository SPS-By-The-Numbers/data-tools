"""Parser for STARS Key Performance Indicators PDFs.

Each KPI PDF is a 9-page Technical Assistance Paper customized for one
district. The district-specific facts we extract are on pages 4-5:

  Page 4: "1. Basic program riders per basic program bus KPI" and
          "2. Special education riders per special education bus KPI"
  Page 5: "3. Average cost per rider KPI"

Each section shows the metric value for three trailing data years plus a
year-over-year change percentage (latest vs. prior). The cohort comparison
tables on pages 6-9 are skipped because each cohort district publishes its
own report; including the cohort tables would massively duplicate facts.

Yields dicts shaped for the stars_kpi schema (one row per metric per
data_year). The change_pct shows up as a synthetic metric with
data_class_of set to the latest data year.
"""

import logging
import re
from pathlib import Path
from typing import Iterator

import pdfplumber

from .common import (
    normalize_pdf_text,
    normalize_school_year,
    parse_decimal,
    tokenize_value_line,
)
from ..filename import StarsFilename


logger = logging.getLogger(__name__)


# Metric definitions in document order. Each entry pairs the section's
# leading number with our canonical metric_code.
_METRICS = [
    ("1", "basic_rider_kpi"),
    ("2", "sped_rider_kpi"),
    ("3", "cost_per_rider"),
]


# Year tokens in OSPI PDFs use a 4-digit start year and a 2-digit suffix,
# joined by an optional dash (hyphen/en-dash/em-dash) or just whitespace.
# Examples we've seen: "2014-15", "2022— 23", "2022 —23", "2016 17", "2019- 20".
# The trailing lookahead prevents matching "<year> <decimal>" (e.g., the year
# header running into a value like "2025 12.68").
_YEAR_TOKEN_RE = re.compile(r"\b\d{4}\s*[-–—]?\s*\d{2}(?![\d.])\b")


def _read_normalized_lines(pdf_path: Path) -> list:
    """Extract text from every page, normalize, return non-empty lines."""
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            for ln in text.split("\n"):
                ln = ln.strip()
                if ln:
                    lines.append(ln)
    return lines


def _find_section_start(lines: list, section_num: str, search_from: int = 0) -> int:
    """Return index of the first line of section `section_num`.

    A section start line begins with "<n>. " followed by a capital letter --
    this disambiguates from things like "1. 1. .0 .0 %" which can appear in
    a value row when all KPIs round to small decimals.
    """
    needle = f"{section_num}."
    for i in range(search_from, len(lines)):
        ln = lines[i]
        if (
            ln.startswith(needle + " ")
            and len(ln) > len(needle) + 1
            and ln[len(needle) + 1].isalpha()
        ):
            return i
    return -1


def _is_value_line(line: str) -> bool:
    """Heuristic: does this line look like a numeric value row?

    Year-header lines (`2014-15 2015-16 2016-17` or split forms like
    `2019- 20 2021- 22 2022- 23 Basic Rider KPI`), narrative paragraphs, and
    column-label lines (`Basic Rider KPI Basic Rider KPI`) should not match.
    A value line has 3-6 numeric tokens (at least 3 of which look like real
    metric values -- decimals, currency-formatted, or percentages -- to
    distinguish from year halves like `20` / `22` / `23`).
    """
    # A line that itself contains year-span tokens is always a header.
    if _YEAR_TOKEN_RE.search(line):
        return False
    tokens = tokenize_value_line(line)
    if not 3 <= len(tokens) <= 6:
        return False
    numeric = 0
    for t in tokens:
        v = parse_decimal(t)
        if v is None:
            continue
        # Real KPI values have a decimal point, a $, or a %. A bare 2- or
        # 4-digit integer is almost always a year fragment.
        if "." in t or "$" in t or "%" in t:
            numeric += 1
    return numeric >= 3


def _find_value_line(lines: list, start: int, limit: int = 15) -> int:
    """Index of the first plausible KPI value line at or after start+1."""
    for i in range(start + 1, min(start + 1 + limit, len(lines))):
        if _is_value_line(lines[i]):
            return i
    return -1


def _gather_year_tokens(lines: list, start: int, end: int) -> list:
    """Collect year-span tokens between section header and value line.

    The header tokens can wrap across multiple lines (notably in 2023-2024
    PDFs where "2019- 20" lives on its own line, then "2021- 22 2022- 23
    Basic Rider KPI" follows). Yields tokens in document order.
    """
    out = []
    for i in range(start, end):
        for m in _YEAR_TOKEN_RE.finditer(lines[i]):
            out.append(m.group(0))
    return out


def _extract_value_tokens(lines: list, value_idx: int) -> list:
    """Get value-line tokens, augmenting if change_pct wrapped onto the next line.

    In some 2023-2024 layouts the three per-year values share one line and
    the change_pct floats onto the next line, taking forms like:
        "5.29%"      (single token containing %)
        "6.8 %"      (number + bare percent sign)
        "- 5.7 %"    (negative sign + number + bare percent sign)
    Concatenate them whenever the joined string contains '%', so they parse
    as one signed-percentage token. The presence of '%' guards against
    accidentally hoovering up narrative text that happens to follow.
    """
    tokens = tokenize_value_line(lines[value_idx])
    if len(tokens) >= 4 or value_idx + 1 >= len(lines):
        return tokens
    next_tokens = tokenize_value_line(lines[value_idx + 1])
    if not next_tokens:
        return tokens
    joined = "".join(next_tokens)
    if "%" in joined:
        tokens.append(joined)
    return tokens


def _find_district_kpi_anchor(lines: list) -> int:
    """Return the index of the 'District KPI' heading line.

    Page 2 of every KPI PDF contains an intro bulleted list ("1. Basic ...,
    2. Special ..., 3. Average ...") that visually looks like our section
    headings but doesn't carry any data. The 'District KPI' subheading on
    page 4 introduces the actual district-specific metric blocks; anchoring
    on it skips the intro list cleanly.
    """
    for i, ln in enumerate(lines):
        # The heading is exactly "District KPI" on its own line.
        if ln.strip() == "District KPI":
            return i
    return -1


def parse_kpi_pdf(info: StarsFilename) -> Iterator[dict]:
    """Yield stars_kpi rows for one KPI PDF."""
    lines = _read_normalized_lines(info.path)

    # Common fields applied to every emitted row.
    base = {
        "school_year": info.school_year,
        "class_of": info.class_of,
        "ccddd": info.ccddd,
        # county and district are joinable via d_ccddd; leave empty here so
        # the from_pdfs driver can fill them in (or rely on d_ccddd join).
        "county": None,
        "district": info.district_name,
        "_source": info.path.name,
        "_source_table": "stars_kpi",
    }

    anchor = _find_district_kpi_anchor(lines)
    if anchor < 0:
        logger.warning("%s: 'District KPI' anchor not found", info.path.name)
        return

    # Fallback data years when the PDF doesn't include year labels: assume
    # (SY-3, SY-2, SY-1). The COVID gap (2020-2021 data) means 2022-2023+ PDFs
    # often substitute a pre-COVID year, so prefer parsed year labels when
    # available.
    latest_class_of = info.class_of - 1
    fallback_class_ofs = [latest_class_of - 2, latest_class_of - 1, latest_class_of]
    fallback_school_years = [f"{c - 1}-{c}" for c in fallback_class_ofs]

    search_from = anchor
    for section_num, metric_code in _METRICS:
        section_idx = _find_section_start(lines, section_num, search_from)
        if section_idx < 0:
            logger.warning(
                "%s: section %s (%s) header not found",
                info.path.name, section_num, metric_code,
            )
            continue
        value_idx = _find_value_line(lines, section_idx)
        if value_idx < 0:
            logger.warning(
                "%s: section %s (%s) value line not found near %d",
                info.path.name, section_num, metric_code, section_idx,
            )
            search_from = section_idx + 1
            continue

        # Years for this section: parse from lines between header and values.
        raw_years = _gather_year_tokens(lines, section_idx + 1, value_idx)
        if len(raw_years) >= 3:
            data_school_years = [normalize_school_year(y) for y in raw_years[:3]]
        else:
            data_school_years = list(fallback_school_years)
        data_class_ofs = [
            int(sy.split("-")[1]) if sy else None for sy in data_school_years
        ]

        tokens = _extract_value_tokens(lines, value_idx)
        if len(tokens) < 3:
            logger.warning(
                "%s: section %s (%s) value line has only %d tokens: %r",
                info.path.name, section_num, metric_code,
                len(tokens), lines[value_idx],
            )
            search_from = value_idx + 1
            continue

        for sy, dc, tok in zip(data_school_years, data_class_ofs, tokens[:3]):
            yield {
                **base,
                "metric_code": metric_code,
                "data_school_year": sy,
                "data_class_of": dc,
                "value": parse_decimal(tok),
            }
        if len(tokens) >= 4:
            yield {
                **base,
                "metric_code": f"{metric_code}_change_pct",
                "data_school_year": data_school_years[-1],
                "data_class_of": data_class_ofs[-1],
                "value": parse_decimal(tokens[3]),
            }
        search_from = value_idx + 1
