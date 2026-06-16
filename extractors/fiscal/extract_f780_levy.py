#!python3
"""Walk data/fiscal/apportionment/, parse each F-780 Levy Authority PDF.

Usage:
    python3 -m extractors.fiscal.extract_f780_levy \
        data/fiscal/apportionment/ --format csv > out_fiscal/fiscal_f780_levy.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "levy_year", "status",
    "section", "item_code", "item_label", "value", "value_text",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("F-780 *Levy Authority.pdf")):
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.f780_levy",
        parse_fn_name="parse_f780_levy_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
