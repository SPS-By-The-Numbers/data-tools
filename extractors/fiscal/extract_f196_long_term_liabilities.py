#!python3
"""Walk data/fiscal/fiscal/, parse the Schedule of Long-Term Liabilities
sub-report of each F-196 All Pages PDF.

Populates `fiscal_f196_long_term_liabilities` -- per-district
long-term debt roll-forward (beg + issued - redeemed = end), plus
the current portion (Amount Due Within One Year), per liability item
(bonds, leases, notes, compensated absences, pension liabilities, ...).
2013-14 through 2024-25, 3,724 files. Handles both per-fund (2013-14
through 2018-19, 4 pages) and combined (2019-20+, 1 page) form
vintages.

Usage:
    python3 -m extractors.fiscal.extract_f196_long_term_liabilities \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f196_long_term_liabilities.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "fund", "section", "item_code", "is_total", "item_label",
    "beginning_outstanding", "amount_increased", "amount_decreased",
    "ending_outstanding", "amount_due_within_one_year",
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
        parse_fn_module="extractors.fiscal.parsers.f196_long_term_liabilities",
        parse_fn_name="parse_f196_long_term_liabilities_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
