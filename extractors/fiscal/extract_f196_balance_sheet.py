#!python3
"""Walk data/fiscal/fiscal/, parse the Balance Sheet - Governmental Funds
sub-report (pp 3-5 typical) of each F-196 All Pages PDF.

Populates `fiscal_f196_balance_sheet` -- per-fund assets, deferred
outflows, liabilities, deferred inflows, and fund balance for each
district per year. 2013-14 through 2024-25, 3,724 files.

Usage:
    python3 -m extractors.fiscal.extract_f196_balance_sheet \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f196_balance_sheet.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "section", "item_code", "fund", "is_total",
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
        parse_fn_module="extractors.fiscal.parsers.f196_balance_sheet",
        parse_fn_name="parse_f196_balance_sheet_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
