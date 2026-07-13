#!python3
"""Walk data/fiscal/apportionment/*/district/, parse each
`Apportionment for {Month}.pdf` and extract the Report 1191 Estimated
Funding Report headline totals from pages 3+.

Populates `fiscal_apportionment_monthly_estimated`. Page 1 of each
source PDF is the 1197 Statement of Apportionment (captured by
`extract_apportionment_monthly.py`); page 2 is a small Statement
summary tail. This parser skips pp 1-2.

Note: ~47K files in the corpus at ~60-70 pages each -- full-corpus run
takes several hours. Consider running on a subset (single school year
or single ESD) first to validate.

Usage:
    python3 -m extractors.fiscal.extract_apportionment_monthly_estimated \\
        data/fiscal/apportionment/ --format csv \\
        > out_fiscal/fiscal_apportionment_monthly_estimated.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district", "month",
    "sub_report", "account_code", "item_ordinal", "item_label",
    "value", "page_number",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("Apportionment for *.pdf")):
        # Only district-path files. ESD-path files may carry ESD-
        # aggregate variants ("Apportionment 34801 (ESD 113) for
        # April.pdf") that this parser is not tuned for.
        if "/district/" not in str(p):
            continue
        # Skip files whose leaf includes "(ESD" or a 5-digit code (ESD
        # aggregate) -- those live under district-path directories only
        # when the district is the college / state-agency variant.
        if "(ESD " in p.name:
            continue
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.apportionment_monthly_estimated",
        parse_fn_name="parse_apportionment_monthly_estimated_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
