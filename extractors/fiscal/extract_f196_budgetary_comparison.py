#!python3
"""Walk data/fiscal/fiscal/, parse the Budgetary Comparison Schedule
sub-report (~pp 7-16, 2 pages per fund x 5 funds) of each F-196 All
Pages PDF.

Populates `fiscal_f196_budgetary_comparison` -- per-fund Final Budget /
Actual / Variance line items. The Final Budget column is the new datum
not captured elsewhere (F-195 captures Original Budget; F-196 SUMMARY/
Revenues capture Actual). 2013-14 through 2024-25, 3,724 files.

Usage:
    python3 -m extractors.fiscal.extract_f196_budgetary_comparison \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f196_budgetary_comparison.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "fund", "section", "sub_section", "item_code", "column_kind",
    "is_section_total",
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
        parse_fn_module="extractors.fiscal.parsers.f196_budgetary_comparison",
        parse_fn_name="parse_f196_budgetary_comparison_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
