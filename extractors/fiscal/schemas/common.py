"""Shared field templates for fiscal fact tables.

Re-exports the SAFS `SCHOOL_YEAR_DISTRICT_FIELDS` so every fiscal fact table
joins to `d_ccddd` / SAFS budget/actuals on `(class_of, ccddd)` exactly like
the STARS tables do.

`AUDIT_FIELDS` here describe the *exported* (AVRO/BigQuery) shape: a fact row
carries an integer `_source_id` foreign key into `d_fiscal_source` plus the
original `_source_table` name. This mirrors the post-`build_sources` CSVs.

Note the staging layer keeps the raw `_source` path string instead (parsers
emit paths, not ids); `extractors.bqload.staging` derives that staging variant
and the exporter joins `d_fiscal_source` to supply `source_id AS _source_id`.
"""

from ...safs.schemas.common import SCHOOL_YEAR_DISTRICT_FIELDS


# The raw path-string column emitted by every fiscal parser and held in the
# staging tables. The exporter maps it to `_source_id` via d_fiscal_source.
SOURCE_COLUMN = "_source"

# Dimension table + key that `_source_id` references.
SOURCE_DIM_TABLE = "d_fiscal_source"
SOURCE_DIM_KEY = "source_path"

AUDIT_FIELDS = [
    {
        "name": "_source_id",
        "field_type": "int",
        "doc": ("Foreign key into d_fiscal_source.source_id; identifies the "
                "PDF this row was parsed from."),
    },
    {
        "name": "_source_table",
        "field_type": "string",
        "doc": "Original sub-report / table name within the source PDF.",
    },
]

__all__ = [
    "AUDIT_FIELDS",
    "SCHOOL_YEAR_DISTRICT_FIELDS",
    "SOURCE_COLUMN",
    "SOURCE_DIM_TABLE",
    "SOURCE_DIM_KEY",
]
