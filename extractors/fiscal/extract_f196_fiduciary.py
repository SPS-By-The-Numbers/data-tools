#!python3
"""Walk data/fiscal/fiscal/, parse the Statement of Fiduciary Net Position
+ Statement of Changes in Fiduciary Net Position sub-reports of each
F-196 All Pages PDF.

Populates `fiscal_f196_fiduciary` -- per-fund balance sheet + income
statement for the district's fiduciary funds (custodial_funds and
private_purpose_trust). 2013-14 through 2024-25, 3,724 files. Handles
GASB 84 column rename+swap (pre-2019-20: Private Purpose Trust +
Other Trust; 2019-20+: Custodial Funds + Private Purpose Trust).

Usage:
    python3 -m extractors.fiscal.extract_f196_fiduciary \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f196_fiduciary.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "statement", "section", "item_code", "fund", "is_total",
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
        parse_fn_module="extractors.fiscal.parsers.f196_fiduciary",
        parse_fn_name="parse_f196_fiduciary_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
