#!python3
"""Walk data/fiscal/fiscal/, parse the Financial Edit Report sub-report
of each F-196 All Pages PDF.

Populates `fiscal_f196_edit_report` -- per-fund per-edit data-quality
check results (edit type, number, message, up to 2 supporting amounts,
plus is_cleared markers for funds with no flagged edits). 2013-14
through 2024-25, 3,724 files.

Usage:
    python3 -m extractors.fiscal.extract_f196_edit_report \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f196_edit_report.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "fund", "edit_seq", "edit_type", "edit_number", "message",
    "is_cleared", "amount_1", "amount_2",
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
        parse_fn_module="extractors.fiscal.parsers.f196_edit_report",
        parse_fn_name="parse_f196_edit_report_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
