#!python3
"""Parse pages 1-7 of an OSPI 1191F "Final Apportionment Summary" PDF.

These pages carry the prototypical-school Basic Education Allocation
derivation: the staff-unit FTE the state funded, the per-FTE salary and
benefit rates, and every subtotal that rolls up to the Guaranteed
Entitlement.  `extractors/fiscal/extract_apportionment_final.py` skips
all of it by design (it keeps headline account totals only), so this
module re-parses the same PDF for the detail.

Two outputs:

  items   -- one row per printed line item: section, subsection, ordinal,
             label, amount, plus the bracket formula and its numeric
             substitution as printed.
  params  -- the model drivers, recovered by zipping each formula's
             ``[Bracket Name]`` tokens against the numbers in the
             substitution line printed underneath it.  This is where
             ``School Generated CIS FTE``, ``CLS - Salary Inc``,
             ``Regionalization`` etc. come from.

Usage:
    python3 -m tools.duty_funding.parse_bea_pages <pdf> [--items out.csv]
                                                        [--params out.csv]
"""

import argparse
import csv
import re
import subprocess
import sys
from pathlib import Path

# "I. Computation for Guaranteed School-Generated Entitlement"
SECTION_RE = re.compile(r"^\s{0,6}([IVX]+)\.\s+(\S.*?)\s*$")
# "B. School Generated - Certificated Instructional Staff (CIS)"
SUBSECTION_RE = re.compile(r"^\s{0,6}([A-H])\.\s+(\S.*?)\s*$")
# "    1. School CIS Salary Maintenance Total        $      227,008,267.15"
ITEM_RE = re.compile(
    r"^\s{2,}(?:(\d+)\.\s+|([a-z])\.\s+)?"
    r"(\S.*?)\s{2,}\$?\s*(-?[\d,]+\.\d+)\s*$"
)
BRACKET_RE = re.compile(r"\[([^\]]+)\]")
NUMBER_RE = re.compile(r"-?\d[\d,]*\.\d+|-?\d[\d,]*(?![\d,.])")
# page furniture we never want to treat as content
NOISE_RE = re.compile(
    r"Page \d+ of \d+|Run \w+ \d+, \d{4}|^\s*1191F\s*$|"
    r"Superintendent of Public Instruction|State of Washington|"
    r"Estimated Funding Report|CCDDD|ESD \d+"
)
# Right-hand column banner, printed on the same line as some headings.
COLUMN_BANNER_RE = re.compile(r"\s{2,}(?:TOTALS|District Totals)\s*$")

ITEM_FIELDS = [
    "page", "section", "section_title", "subsection", "subsection_title",
    "ordinal", "label", "amount", "formula", "substitution",
]
PARAM_FIELDS = ["name", "value", "from_label", "page"]


def pages_for(pdf: Path, tag: str):
    """(first, last) page numbers carrying a sub-report tag such as '1191EDF'.

    The Final Apportionment Summary concatenates a dozen sub-reports whose
    page counts vary by district, so the range is found rather than assumed.
    Matches the tag in the page banner only, not a cross-reference in body
    text (Report 1191ED is cited from inside 1191CTEF, for instance).
    """
    out = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                         check=True, capture_output=True, text=True).stdout
    hits = [n for n, page in enumerate(out.split("\f"), start=1)
            if any(line.rstrip().endswith(tag) for line in page.split("\n"))]
    if not hits:
        raise SystemExit(f"{tag} not found in {pdf}")
    return hits[0], hits[-1]


def pdf_lines(pdf: Path, first: int = 1, last: int = 7):
    """pdftotext -layout, yielding (page_number, line)."""
    out = subprocess.run(
        ["pdftotext", "-layout", "-f", str(first), "-l", str(last), str(pdf), "-"],
        check=True, capture_output=True, text=True,
    ).stdout
    for offset, page in enumerate(out.split("\f")):
        for line in page.split("\n"):
            yield first + offset, line


def _num(text):
    return text.replace(",", "")


def parse(pdf: Path, first: int = 1, last: int = 7):
    items, params = [], []
    section = section_title = subsection = subsection_title = ""
    cur = None          # item currently collecting its formula lines
    pending = []        # raw continuation lines under `cur`

    def flush():
        """Attach collected formula/substitution lines to the open item."""
        if cur is None:
            return
        template = [ln for ln in pending if "[" in ln]
        subst = [ln for ln in pending if "[" not in ln and NUMBER_RE.search(ln)]
        cur["formula"] = " ".join(" ".join(template).split())
        cur["substitution"] = " ".join(" ".join(subst).split())
        names = BRACKET_RE.findall(cur["formula"])
        values = NUMBER_RE.findall(cur["substitution"])
        # The substitution mirrors the template token-for-token, so equal
        # counts mean we can name every number.  Unequal counts happen when
        # OSPI inlines a literal, and we simply skip those.
        if names and len(names) == len(values):
            for name, value in zip(names, values):
                params.append({
                    "name": name.strip(),
                    "value": _num(value),
                    "from_label": cur["label"],
                    "page": cur["page"],
                })
        items.append(cur)

    for page, line in pdf_lines(pdf, first, last):
        line = COLUMN_BANNER_RE.sub("", line)
        if not line.strip() or NOISE_RE.search(line):
            continue

        m = ITEM_RE.match(line)
        if m:
            flush()
            pending = []
            ordinal, letter, label, amount = m.groups()
            cur = {
                "page": page,
                "section": section, "section_title": section_title,
                "subsection": subsection, "subsection_title": subsection_title,
                "ordinal": ordinal or letter or "",
                "label": " ".join(label.split()),
                "amount": _num(amount),
                "formula": "", "substitution": "",
            }
            continue

        m = SECTION_RE.match(line)
        if m and not line.startswith("    "):
            flush()
            cur, pending = None, []
            section, section_title = m.group(1), " ".join(m.group(2).split())
            subsection = subsection_title = ""
            continue

        m = SUBSECTION_RE.match(line)
        if m and not line.startswith("    "):
            flush()
            cur, pending = None, []
            subsection, subsection_title = m.group(1), " ".join(m.group(2).split())
            continue

        if cur is not None:
            pending.append(line)

    flush()
    return items, params


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--first", type=int, default=1)
    ap.add_argument("--last", type=int, default=7)
    ap.add_argument("--items", type=Path, help="write line items here")
    ap.add_argument("--params", type=Path, help="write recovered model drivers here")
    args = ap.parse_args()

    items, params = parse(args.pdf, args.first, args.last)

    def write(path, fields, rows):
        handle = open(path, "w", newline="") if path else sys.stdout
        try:
            w = csv.DictWriter(handle, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        finally:
            if path:
                handle.close()

    if args.items or not args.params:
        write(args.items, ITEM_FIELDS, items)
    if args.params:
        write(args.params, PARAM_FIELDS, params)


if __name__ == "__main__":
    main()
