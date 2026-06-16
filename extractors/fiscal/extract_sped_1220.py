#!python3
"""Walk data/fiscal/apportionment/, parse each district 1220 Special
Education Allocation PDF.

ESD-path files use the different 1220TR Transfer of Allocation form
and are skipped by the parser (returns no rows). The walker also
short-circuits them for clarity.

Usage:
    python3 -m extractors.fiscal.extract_sped_1220 \
        data/fiscal/apportionment/ --format csv > out_fiscal/fiscal_1220_sped.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "status", "report_date_text",
    "section", "item_code", "item_label",
    "subject_ccddd", "subject_name",
    "value", "value_text",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("1220 Special Education Allocation.pdf")):
        if not p.is_file():
            continue
        if "/esd/" in str(p):
            # ESD path → different form (1220TR). Skip.
            continue
        yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.sped_1220",
        parse_fn_name="parse_sped_1220_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
