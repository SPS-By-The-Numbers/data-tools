"""Shared PDF parsing helpers for the fiscal corpus.

Builds on `extractors.stars.parsers.common`; the fiscal forms have a few
PDF-text-extraction quirks the STARS tokenizer didn't have to deal with
(notably: leading single digits getting space-separated from their
thousands-comma tail, e.g. '1 8,673,029.13' for a value of 18,673,029.13).
"""

import re
from decimal import Decimal
from typing import Optional

from ...stars.parsers.common import (  # re-export
    normalize_school_year,
    class_of_from_school_year,
    read_docx_lines,
)
from ...stars.parsers.common import normalize_pdf_text as _stars_normalize_pdf_text
from ...stars.parsers.common import parse_decimal as _stars_parse_decimal

__all__ = [
    "normalize_school_year",
    "class_of_from_school_year",
    "normalize_pdf_text",
    "read_pdf_lines",
    "read_docx_lines",
    "read_lines",
    "parse_decimal",
    "merge_split_leading_digit",
    "collapse_numeric_paren_spaces",
    "is_na",
]


_FISCAL_DASH_CHARS_RE = re.compile(r"[­‐‑‒―−]")


def normalize_pdf_text(s: str) -> str:
    """Fiscal-side wrapper around STARS' `normalize_pdf_text`.

    Collapses several additional Unicode dash-family code points to ASCII '-'
    before STARS' own collapse runs:
      - U+00AD SOFT HYPHEN          (F-195F year headers in 2018-2021)
      - U+2010 HYPHEN               (1191SI year spans in 2015-2016)
      - U+2011 NON-BREAKING HYPHEN
      - U+2012 FIGURE DASH
      - U+2015 HORIZONTAL BAR
      - U+2212 MINUS SIGN

    Without these the school-year-span / value regexes silently fail on the
    affected vintages of OSPI PDFs.
    """
    if s is None:
        return ""
    return _stars_normalize_pdf_text(_FISCAL_DASH_CHARS_RE.sub("-", s))


def read_pdf_lines(path, max_pages=None):
    """pdfplumber-based line reader; re-implemented locally to use the
    fiscal-side `normalize_pdf_text` (which handles U+2010).

    Pass `max_pages=1` (etc.) when the parser only needs the leading pages
    -- big OSPI PDFs (the 40-pages-and-up monthly Apportionment is the
    bad case) spend almost all parse time inside pdfplumber rendering
    pages that we then throw away.
    """
    import pdfplumber
    lines = []
    with pdfplumber.open(path) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        for page in pages:
            text = normalize_pdf_text(page.extract_text() or "")
            for ln in text.split("\n"):
                ln = ln.strip()
                if ln:
                    lines.append(ln)
    return lines


def read_lines(path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf_lines(path)
    if suffix == ".docx":
        return read_docx_lines(path)
    raise ValueError(f"Unsupported file extension {suffix!r} for {path.name!r}")


# Patterns the per-fact parsers use to identify "no data printed" cells.
_NA_TOKENS = {"", "-", "—", "–", "N/A", "n/a", "NA", "%"}


def is_na(s: Optional[str]) -> bool:
    if s is None:
        return True
    return s.strip() in _NA_TOKENS


# A 1-digit + space + comma-grouped tail: '1 8,673,029.13' -> '18,673,029.13'.
# Requires the merged value to be at end-of-line so we don't accidentally
# merge label content with a value -- e.g. F-195F lines like
# '2. Grade 1 3,839.00 4,568.00 ...' would otherwise become
# '2. Grade 13,839.00 4,568.00 ...' since the "1" looks like a leading digit.
# 1191SI's fragmentation always lives at end-of-line so the constraint is safe.
_SPLIT_DIGIT_RE = re.compile(r"(?<![\d.])(\d)\s+(\d{1,3}(?:,\d{3})+(?:\.\d+)?)(?=\s*$)")
_SPLIT_DIGIT_NO_LEADING_COMMA = re.compile(r"(?<![\d.])(\d)\s+(,\d{3}(?:,\d{3})*(?:\.\d+)?)(?=\s*$)")

# Currency-prefixed leading-digit split: '$ 8 43' -> '$843', '$ 5 ,586' -> '$5,586'.
# Wider than the bare-context variant above because a leading `$` gives strong
# evidence that the merged token is a single value rather than two unrelated
# integers; lets us also catch the 2-3-digit bare tail (no thousands separator).
_DOLLAR_SPLIT_RE = re.compile(
    r"\$\s*(\d)\s+(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{2,3}|,\d{3}(?:,\d{3})*(?:\.\d+)?)"
)


def merge_split_leading_digit(s: str) -> str:
    """Repair column-based pdfplumber fragmentation of leading-digit dollar amounts.

    Patterns observed:
      '1 8,673,029.13'  -> '18,673,029.13'   (1191SI, no `$` in body)
      '1 ,610,929.52'   -> '1,610,929.52'    (1191SI)
      '$ 8 43'          -> '$843'            (Food Service, bare 2-3 digit tail)
      '$ 5 ,586'        -> '$5,586'          (Food Service)
      '$ 3 50,753'      -> '$350,753'        (Food Service)
      '$ -'             -> '$-'              (Food Service null marker)
    """
    s = _DOLLAR_SPLIT_RE.sub(r"$\1\2", s)
    s = _SPLIT_DIGIT_RE.sub(r"\1\2", s)
    s = _SPLIT_DIGIT_NO_LEADING_COMMA.sub(r"\1\2", s)
    # Collapse remaining `$<whitespace>` so downstream tokenizers treat each
    # dollar-prefixed cell as one token (e.g. the `$ -` null marker survives
    # the digit-merge passes and would otherwise split into two tokens).
    s = re.sub(r"\$\s+", "$", s)
    return s


# Matches a parenthesized numeric expression with optional leading minus and
# any amount of internal whitespace: `( 838,296.07)`, `(- 1,234.50 )`. The
# content has to be all-numeric (digits, commas, dots, an optional leading
# `-`), so label parens like `(A.2 + A.3)` are left alone.
_PAREN_NUMERIC_RE = re.compile(r"\(\s*-?\s*[\d][\d,.\s]*\)")


def collapse_numeric_paren_spaces(s: str) -> str:
    """Strip internal whitespace from parenthesized numeric expressions.

    `( 838,296.07)` -> `(838,296.07)`, `(- 1,234.50 )` -> `(-1,234.50)`.
    Useful as a preprocessing step before splitting a line into
    label / value at whitespace.
    """
    def _collapse(m):
        inner = re.sub(r"\s+", "", m.group(0)[1:-1])
        return "(" + inner + ")"
    return _PAREN_NUMERIC_RE.sub(_collapse, s)


def parse_decimal(s) -> Optional[Decimal]:
    """Fiscal-aware decimal parser.

    Handles everything `stars.parse_decimal` does, plus:
      - 'N/A' / 'NA' tokens -> None
      - Parenthesized negatives '(838,296.07)' -> -838296.07
      - 'value%' percent strings -> the underlying decimal (no /100 division)
    """
    if s is None:
        return None
    s = str(s).strip()
    if s in _NA_TOKENS or s.upper() in ("N/A", "NA"):
        return None
    # Parenthesized negative
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    return _stars_parse_decimal(s)
