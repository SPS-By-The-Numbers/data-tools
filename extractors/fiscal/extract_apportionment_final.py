#!python3
"""Walk data/fiscal/apportionment/*/district/, parse each
Final Apportionment Summary PDF as OSPI Report 1191F.

Populates `fiscal_apportionment_final` -- headline-only per-Account
totals per district per year. Detail derivation (staffing units, per-
pupil formulas, etc.) is deliberately not parsed.

Usage:
    python3 -m extractors.fiscal.extract_apportionment_final \\
        data/fiscal/apportionment/ --format csv \\
        > out_fiscal/fiscal_apportionment_final.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "sub_report", "account_code", "item_ordinal", "item_label",
    "value", "page_number",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("Final Apportionment Summary.pdf")):
        # Only district-path files carry 1191F; ESD-path files with the
        # same filename are 1191SI. Guard by path segment.
        if "/district/" not in str(p):
            continue
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.apportionment_final",
        parse_fn_name="parse_apportionment_final_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
