#!python3
"""Walk data/fiscal/apportionment/, parse each Non-High Billing.pdf.

Usage:
    python3 -m extractors.fiscal.extract_nonhigh_billing \
        data/fiscal/apportionment/ --format csv > out_fiscal/fiscal_nonhigh_billing.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "report_kind", "status", "form_variant",
    "section", "subject_role", "subject_ccddd", "subject_name", "is_focal",
    "item_code", "item_label", "value", "value_text",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("Non-High Billing.pdf")):
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.nonhigh_billing",
        parse_fn_name="parse_nonhigh_billing_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
