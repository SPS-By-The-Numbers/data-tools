"""Shared helpers for STARS PDF/DOCX parsing."""

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional


# OSPI PDFs use a mix of em-dash, en-dash, and hyphen, sometimes with extra
# spaces, between the two halves of a school-year span. Normalize all of them
# to "YYYY-YY" or "YYYY-YYYY" before further parsing.
_YEAR_SPAN_RE = re.compile(r"(\d{4})\s*[-–—]\s*(\d{2,4})")


def normalize_school_year(s: str) -> Optional[str]:
    """Turn '2014-15' / '2022— 23' / '2014-2015' into 'YYYY-YYYY'.

    Returns None if the input doesn't look like a school-year span.
    """
    if s is None:
        return None
    m = _YEAR_SPAN_RE.search(s)
    if not m:
        return None
    start = m.group(1)
    end = m.group(2)
    if len(end) == 2:
        century = start[:2]
        end_full = f"{century}{end}"
        # Century rollover (1999-00 -> 1999-2000).
        if int(end_full) < int(start):
            end_full = f"{int(century) + 1}{end}"
        end = end_full
    return f"{start}-{end}"


def class_of_from_school_year(school_year: str) -> Optional[int]:
    """Extract the int end-year. '2024-2025' -> 2025."""
    if school_year is None:
        return None
    m = re.match(r"^\d{4}-(\d{4})$", school_year)
    return int(m.group(1)) if m else None


def parse_decimal(s) -> Optional[Decimal]:
    """Parse a numeric token from a STARS PDF.

    Handles currency ($), thousands separators, trailing %, '- N' (space
    after minus), bare leading dot (.0), and '-' / '—' as null.
    """
    if s is None:
        return None
    s = str(s).strip()
    if s in ("", "-", "—", "–", "%"):
        return None
    # Strip currency, commas, percent, surrounding whitespace.
    s = s.replace("$", "").replace(",", "").replace("%", "").strip()
    # "- 7.54" -> "-7.54"
    s = re.sub(r"^-\s+", "-", s)
    # Bare leading dot: ".0" -> "0.0"
    if s.startswith("."):
        s = "0" + s
    elif s.startswith("-."):
        s = "-0" + s[1:]
    # Trailing dot ("1.") -- means the file truncated the trailing zero.
    if s.endswith("."):
        s = s + "0"
    elif s == "-":
        return None
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def normalize_pdf_text(s: str) -> str:
    """Collapse em/en-dashes to hyphens and runs of whitespace to single space."""
    if s is None:
        return ""
    s = re.sub(r"[—–]", "-", s)
    s = re.sub(r"[ ]", " ", s)
    return s


def read_pdf_lines(path: Path) -> list:
    """Extract every non-empty text line from a PDF in document order.

    Uses pdfplumber's text-flow extraction so cells in the same visual row
    end up on a single line. Each line is `normalize_pdf_text`-cleaned and
    stripped before being yielded.
    """
    import pdfplumber  # local import: avoid hard dep when only DOCX is used.
    lines = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = normalize_pdf_text(page.extract_text() or "")
            for ln in text.split("\n"):
                ln = ln.strip()
                if ln:
                    lines.append(ln)
    return lines


_DOCX_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def read_docx_lines(path: Path) -> list:
    """Extract every non-empty paragraph from a DOCX in document order.

    OSPI's DOCX renderings nest tables inside tables to lay out the report.
    python-docx's top-level `.paragraphs` / `.tables` views only see the
    outermost wrapper, so we walk the underlying XML tree for every
    `<w:p>` descendant -- this yields one line per cell in document order.
    """
    import docx  # local import.
    doc = docx.Document(path)
    lines = []
    for p in doc.element.body.iter(f"{_DOCX_W_NS}p"):
        text = "".join(
            (t.text or "")
            for t in p.iter(f"{_DOCX_W_NS}t")
        )
        text = text.strip()
        if text:
            lines.append(text)
    return lines


def read_lines(path: Path) -> list:
    """Dispatch to read_pdf_lines / read_docx_lines based on file extension."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf_lines(path)
    if suffix == ".docx":
        return read_docx_lines(path)
    raise ValueError(f"Unsupported file extension {suffix!r} for {path.name!r}")


def tokenize_value_line(line: str) -> list:
    """Split a numeric value line into one token per cell.

    Reassembles tokens that PDF text extraction tends to fragment:
        '$ 3,754.29'  -> '$3,754.29'    (currency space-separation)
        '- 7.54%'     -> '-7.54%'       (negative change percentage)

    The minus merge intentionally requires the value to end in '%': a
    standalone '-' between numeric tokens in the value row is OSPI's null
    marker (e.g. ".0 - .0 .0 %" or "- .19 .75 294.74%"). Merging those into
    the next token mis-attributes a missing cell as a small negative value.
    """
    line = re.sub(r"\$\s*(\d|\.)", r"$\1", line)
    line = re.sub(r"-\s+([\d.][\d.,]*%)", r"-\1", line)
    return line.split()
