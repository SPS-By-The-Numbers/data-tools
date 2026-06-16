#!python3
"""Walk data/fiscal/apportionment/, parse each `1159 - K12 Staff
Ratios.pdf` into long-form rows for `fiscal_1159_staff_ratio`.

The 1159 report only ran for three school years (2013-14 through
2015-16); OSPI discontinued it after the SHB 2261 / McCleary funding
rewrite. Files only appear under `apportionment/<year>/district/`
(no ESD / college / state-agency variants), so the walker is a
simple `rglob` on the canonical leaf name.

Usage:
    python3 -m extractors.fiscal.extract_staff_ratio_1159 \\
        data/fiscal/apportionment/ --format csv > out_fiscal/fiscal_1159_staff_ratio.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "status", "report_date_text",
    "section", "item_code", "item_label",
    "value", "value_text",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("1159 - K12 Staff Ratios.pdf")):
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.staff_ratio_1159",
        parse_fn_name="parse_staff_ratio_1159_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
