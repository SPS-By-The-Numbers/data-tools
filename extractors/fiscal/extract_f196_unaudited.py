#!python3
"""Walk data/fiscal/apportionment/, parse each F-196 Unaudited PDF (page-2
SUMMARY block only).

Usage:
    python3 -m extractors.fiscal.extract_f196_unaudited data/fiscal/apportionment/
        --format csv > out_fiscal/fiscal_f196_unaudited_summary.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "item_code", "fund",
    "item_label", "value", "value_text",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("F-196 Unaudited.pdf")):
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.f196_unaudited",
        parse_fn_name="parse_f196_unaudited_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
