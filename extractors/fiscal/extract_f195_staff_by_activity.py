#!python3
"""Walk data/fiscal/fiscal/, parse each F-195 Budget (and Overview) PDF's
`SUMMARY OF FTE CERTIFICATED AND CLASSIFIED STAFF COUNTS BY ACTIVITY`
sub-report (GF15).

Both F-195 Budget and F-195 Budget Overview contain this sub-report;
the parser dedups by logical key.

Usage:
    python3 -m extractors.fiscal.extract_f195_staff_by_activity \\
        data/fiscal/fiscal/ --format csv \\
        > out_fiscal/fiscal_f195_staff_by_activity.csv
"""

from pathlib import Path

from .parallel import run_extract


FIELDNAMES = [
    "school_year", "class_of", "ccddd", "county", "district",
    "section", "activity_code", "is_total", "item_label",
    "certificated_fte", "certificated_pct_of_total",
    "classified_fte", "classified_pct_of_total",
    "_source", "_source_table",
]


_OVERVIEW_HAS_GF15_FROM = 2017  # class_of


def _walker(root: Path):
    """Emit one PDF per district-year with a per-vintage source choice.

    Both source kinds contain GF15 from 2016-17 onwards, but the Overview
    is a different-time snapshot -- activities added mid-year appear
    only in the Budget, so mixing sources across the same file causes
    per-file identity checks (sum of details == grand total) to fail.
    Picking one source per district-year avoids that.

    Vintage split:
      - class_of >= 2017 (school year 2016-17+): use the ~41-page
        Overview -- 4x faster to scan than the ~186-page Budget.
      - class_of < 2017: use the ~186-page Budget -- older Overview
        omits GF15 entirely.
    """
    if root.is_file():
        yield root
        return
    per_dir: dict[Path, Path] = {}
    for pattern in ("F-195 Budget.pdf", "F-195 Budget Overview.pdf"):
        for p in sorted(root.rglob(pattern)):
            if not p.is_file():
                continue
            # Infer class_of from parent-parent directory name
            # (`<year>/<slug>/`).
            try:
                year_dir = p.parent.parent.name
                class_of = int(year_dir.split("-")[-1])
            except (ValueError, IndexError):
                class_of = 0
            prefer_overview = class_of >= _OVERVIEW_HAS_GF15_FROM
            is_overview = "Overview" in p.name
            wanted = (prefer_overview == is_overview)
            existing = per_dir.get(p.parent)
            if existing is None:
                per_dir[p.parent] = p
            else:
                # If we already have the wanted variant, keep it.
                # Otherwise replace with this one.
                existing_is_overview = "Overview" in existing.name
                if wanted and not (existing_is_overview == prefer_overview):
                    per_dir[p.parent] = p
    for p in sorted(per_dir.values()):
        yield p


def main():
    run_extract(
        parse_fn_module="extractors.fiscal.parsers.f195_staff_by_activity",
        parse_fn_name="parse_f195_staff_by_activity_pdf",
        fieldnames=FIELDNAMES,
        walker=_walker,
        description=__doc__,
    )


if __name__ == "__main__":
    main()
