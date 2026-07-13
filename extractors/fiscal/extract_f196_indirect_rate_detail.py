#!python3
"""Walk data/fiscal/fiscal/, parse the page-1 expenditures partition of
each F-196 All Pages PDF's Federal Restricted / Unrestricted Indirect
Cost Rate Schedule.

Populates `fiscal_f196_indirect_rate_detail`. Page 2 of each schedule
(the 14-line rate calculation) is captured by
`fiscal_f196_indirect_rate` -- see extract_f196_indirect_rate.py.

Usage:
    python3 -m extractors.fiscal.extract_f196_indirect_rate_detail \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f196_indirect_rate_detail.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "rate_kind", "row_kind", "activity_code", "activity_label",
    "total_expenditures", "capital_outlay", "debt_service",
    "distorting_items", "unallowable", "indirect_pool", "direct_base",
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
        parse_fn_module="extractors.fiscal.parsers.f196_indirect_rate_detail",
        parse_fn_name="parse_f196_indirect_rate_detail_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
