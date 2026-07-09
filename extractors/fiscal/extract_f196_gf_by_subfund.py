#!python3
"""Walk data/fiscal/fiscal/, parse the 'Statement of Revenues,
Expenditures, and Changes in Fund Balance - General Fund, By Sub-Fund'
sub-report of each F-196 All Pages PDF.

Populates `fiscal_f196_gf_by_subfund` -- General Fund broken out by
Sub-Fund 10 (Basic Ed) vs Sub-Fund 11 (Non-Basic-Ed) vs General Fund
total. 2019-20 through 2024-25 only -- the sub-report did not exist
before 2019-20.

Usage:
    python3 -m extractors.fiscal.extract_f196_gf_by_subfund \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f196_gf_by_subfund.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "section", "sub_section", "item_code", "fund", "is_total",
    "item_label", "amount",
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
        parse_fn_module="extractors.fiscal.parsers.f196_gf_by_subfund",
        parse_fn_name="parse_f196_gf_by_subfund_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
