"""Shared schema fragments for STARS fact tables.

STARS tables reuse SCHOOL_YEAR_DISTRICT_FIELDS from extractors.safs.schemas
(school_year/class_of/ccddd/county/district) so they join cleanly to d_ccddd.

`AUDIT_FIELDS` here describe the *exported* (AVRO/BigQuery) shape: a fact row
carries an integer `_source_id` foreign key into `d_stars_source` plus the
original `_source_table` name. This mirrors the post-`build_sources` CSVs.

The staging layer keeps the raw `_source` filename string instead (parsers
emit filenames, not ids); `extractors.bqload.staging` derives that staging
variant and the exporter joins `d_stars_source` to supply `source_id AS
_source_id`.
"""

from ...safs.schemas.common import SCHOOL_YEAR_DISTRICT_FIELDS


# The raw filename-string column emitted by every STARS parser and held in the
# staging tables. The exporter maps it to `_source_id` via d_stars_source.
SOURCE_COLUMN = "_source"

# Dimension table + key that `_source_id` references.
SOURCE_DIM_TABLE = "d_stars_source"
SOURCE_DIM_KEY = "source_filename"

AUDIT_FIELDS = [
    {
        "name": "_source_id",
        "field_type": "int",
        "doc": ("Foreign key into d_stars_source.source_id; identifies the "
                "PDF/DOCX this row was parsed from."),
    },
    {
        "name": "_source_table",
        "field_type": "string",
        "doc": "Original report/table name within the source file.",
    },
]

__all__ = [
    "AUDIT_FIELDS",
    "SCHOOL_YEAR_DISTRICT_FIELDS",
    "SOURCE_COLUMN",
    "SOURCE_DIM_TABLE",
    "SOURCE_DIM_KEY",
]
