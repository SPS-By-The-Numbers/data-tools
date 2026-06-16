#!python3
"""Walk data/fiscal/apportionment/, parse each monthly Statement of
Apportionment PDF (District, College, State Agency, ESD-level).

ESD-level files live under apportionment/<year>/esd/<esd_dir>/<member>/
and are *replicated* across every member-district subdir of a given ESD
(the OSPI source materializes the same file under each member). The
walker dedupes by (year, esd_dir, filename) so each unique ESD file is
yielded once.

Usage:
    python3 -m extractors.fiscal.extract_apportionment_monthly \
        data/fiscal/apportionment/ --format csv > out_fiscal/fiscal_apportionment_monthly.csv
"""

import re
from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "org_type", "month", "month_seq", "report_date_text",
    "revenue_account", "revenue_description",
    "annual_allotment", "adjustment_allotment", "percent_due",
    "allot_due", "paid_previously", "allotment_for_month",
    "_source", "_source_table",
]


# Either 'Apportionment for September.pdf' (district/college/agency)
# or 'Apportionment 17801 (ESD 121) for September.pdf' (ESD-level).
_APPT_RE = re.compile(
    r"^Apportionment\s+(?:\d+\s+\(ESD\s+\d+\)\s+)?for\s+\w+\.pdf$",
    re.IGNORECASE,
)


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    # Pass 1: District / College / State Agency files (no dedup needed).
    for p in sorted(root.rglob("Apportionment for *.pdf")):
        if p.is_file() and "/esd/" not in str(p):
            yield p
    # Pass 2: ESD-level files. Same file replicated under every member dir,
    # so dedup by (year, esd_dir, filename) and only emit the alphabetically
    # first member subdir's copy of each.
    seen_esd = set()
    for p in sorted(root.rglob("Apportionment*.pdf")):
        if not p.is_file():
            continue
        if "/esd/" not in str(p):
            continue
        if not _APPT_RE.match(p.name):
            continue
        parts = p.parts
        try:
            i = parts.index("esd")
        except ValueError:
            continue
        if i < 1 or i + 1 >= len(parts):
            continue
        year = parts[i - 1]
        esd_dir = parts[i + 1]
        key = (year, esd_dir, p.name)
        if key in seen_esd:
            continue
        seen_esd.add(key)
        yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.apportionment_monthly",
        parse_fn_name="parse_apportionment_monthly_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
