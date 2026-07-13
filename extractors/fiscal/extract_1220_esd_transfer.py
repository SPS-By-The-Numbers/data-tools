#!python3
"""Walk data/fiscal/apportionment/*/esd/, parse each 1220 Special
Education Allocation PDF as an OSPI Report 1220TR ESD SpEd Transfer
of Allocation.

Populates `fiscal_1220_sped_transfer` -- per-ESD per-member-district
transfer amounts for Accounts 3121 / 4121 / 4122. Coverage 2013-14
through 2016-17 (~120 files pre-dedup, ~30 unique ESD-year reports
post-dedup).

Usage:
    python3 -m extractors.fiscal.extract_1220_esd_transfer \\
        data/fiscal/apportionment/ --format csv \\
        > out_fiscal/fiscal_1220_sped_transfer.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "esd_code", "esd_number",
    "row_kind", "member_ccddd", "member_name",
    "acct_3121_special_ed_general_app",
    "acct_4121_special_education",
    "acct_4122_special_ed_infants",
    "_source", "_source_table",
]


def _walker(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("1220 Special Education Allocation.pdf")):
        if "/esd/" not in str(p):
            continue
        if p.is_file():
            yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.sped_1220_esd_transfer",
        parse_fn_name="parse_sped_1220_esd_transfer_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
