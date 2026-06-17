#!python3
"""Walk data/fiscal/fiscal/, parse the Report of Revenues and Other
Financing Sources sub-report (typically pp 23-29) of each F-196 All
Pages PDF.

Populates `fiscal_f196_revenues` -- per-OSPI-4-digit-account-code
revenue detail per fund. 2013-14 through 2024-25, 3,724 files.

Usage:
    python3 -m extractors.fiscal.extract_f196_revenues data/fiscal/fiscal/
        --format csv > out_fiscal/fiscal_f196_revenues.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "section", "revenue_account", "fund",
    "is_section_total", "is_grand_total",
    "item_label", "value", "value_text",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("F-196 All Pages.pdf")):
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.f196_revenues",
        parse_fn_name="parse_f196_revenues_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
