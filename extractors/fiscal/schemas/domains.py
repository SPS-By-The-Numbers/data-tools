"""Fiscal-corpus dimension + domain tables.

Currently just `d_fiscal_source` -- a row per scraped source file, so the
repeated `_source` path column on each fact CSV can be replaced with a
small integer `_source_id` foreign key (mirrors `d_stars_source`).
"""

from .common import AUDIT_FIELDS


D_FISCAL_SOURCE = {
    "name": "d_fiscal_source",
    "doc": (
        "Dimension table for the _source path column on every fiscal fact "
        "table. Each row corresponds to a single scraped PDF (or other "
        "document) under data/fiscal/. The _source path repeats up to "
        "~60x per row across fact tables; replacing it with the integer "
        "source_id FK cuts substantial size from the CSV outputs."
    ),
    "fields": [
        {
            "name": "source_id",
            "field_type": "int",
            "is_primary_key": True,
            "doc": (
                "Sequential integer assigned in sorted-path order. "
                "Stable as long as the corpus is stable; new files appended "
                "at the end keep existing IDs intact."
            ),
        },
        {
            "name": "source_path",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Path relative to data/fiscal/, joined with '/'. Unique "
                "across the corpus (filenames like 'Apportionment for "
                "April.pdf' repeat across district / year directories, so "
                "the path components are required to disambiguate)."
            ),
        },
        {
            "name": "report_type",
            "field_type": "string",
            "doc": (
                "Top-level directory under data/fiscal/: apportionment, "
                "fiscal, state_institutions, esd_allocations, "
                "county_treasurer, state_agencies_schools_colleges, "
                "technical_colleges."
            ),
        },
        {
            "name": "school_year",
            "field_type": "string",
            "doc": "School year from the second-level path segment (e.g. '2024-2025').",
        },
        {
            "name": "class_of",
            "field_type": "int",
            "doc": "End year of school_year as an int (e.g. 2025).",
        },
        {
            "name": "org_type",
            "field_type": "string",
            "doc": (
                "For Apportionment files: district / esd / college / "
                "state_agency. For Fiscal: district. Empty for flat report "
                "types whose path has no org cascade."
            ),
        },
        {
            "name": "ccddd",
            "field_type": "int",
            "doc": (
                "OSPI county-and-district code. Populated for District / "
                "ESD-member / state-institution files; NULL for colleges, "
                "state agencies, and the flat report types where the path "
                "carries no district code."
            ),
        },
        {
            "name": "org_code",
            "field_type": "string",
            "doc": (
                "Raw code from the org directory ('{code}_{slug}'). Kept "
                "as string because some codes are <5 digits (e.g. ESD "
                "codes are 3 digits)."
            ),
        },
        {
            "name": "org_slug",
            "field_type": "string",
            "doc": "Slugified org name from the org directory.",
        },
        {
            "name": "esd_code",
            "field_type": "string",
            "doc": (
                "For Apportionment ESD-member rows, the parent ESD's "
                "code; otherwise NULL."
            ),
        },
        {
            "name": "esd_slug",
            "field_type": "string",
            "doc": "Parent ESD's slug, for ESD-member rows.",
        },
        {
            "name": "leaf",
            "field_type": "string",
            "doc": "Filename stem (no extension).",
        },
        {
            "name": "extension",
            "field_type": "string",
            "doc": (
                "File extension (lowercase, no leading dot). Empty for the "
                "no-extension OSPI downloads under county_treasurer, "
                "state_agencies_schools_colleges, and technical_colleges."
            ),
        },
    ] + AUDIT_FIELDS,
}


ALL_SCHEMAS = [D_FISCAL_SOURCE]
