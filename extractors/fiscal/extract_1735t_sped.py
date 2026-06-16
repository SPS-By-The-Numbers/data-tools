#!python3
"""Walk data/fiscal/apportionment/, parse 1735T Special Education PDFs.

Usage:
    python3 -m extractors.fiscal.extract_1735t_sped \
        data/fiscal/apportionment/ --format csv > out_fiscal/fiscal_1735t_sped_enrollment.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "grade", "month", "value", "value_text",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    # District-only (ESD aggregate would face the same multi-district issue as 1251).
    for p in sorted(root.rglob("1735T Special Education.pdf")):
        if p.is_file() and "/esd/" not in str(p):
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.sped_1735t",
        parse_fn_name="parse_1735t_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
