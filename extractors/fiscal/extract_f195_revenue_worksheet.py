#!python3
"""Walk data/fiscal/fiscal/, parse each F-195 Budget PDF's REVENUE
WORK SHEET sub-report (GF13 / DS3 / CP5 / TVF3).

Each F-195 Budget PDF has up to 4 revenue-worksheet pages, one per
applicable fund. Overview does NOT contain these sub-reports.

Usage:
    python3 -m extractors.fiscal.extract_f195_revenue_worksheet \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f195_revenue_worksheet.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "fund", "part", "period", "period_label",
    "amount_1", "amount_2", "amount_3",
    "collection_pct", "amount_budgeted",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("F-195 Budget.pdf")):
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.f195_revenue_worksheet",
        parse_fn_name="parse_f195_revenue_worksheet_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
