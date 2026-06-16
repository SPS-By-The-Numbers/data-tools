"""Shared field templates for fiscal fact tables.

Re-exports the SAFS `SCHOOL_YEAR_DISTRICT_FIELDS` and `AUDIT_FIELDS` so every
fiscal fact table joins to `d_ccddd` / SAFS budget/actuals on
`(class_of, ccddd)` exactly like the STARS tables do.
"""

from ...safs.schemas.common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS

__all__ = ["AUDIT_FIELDS", "SCHOOL_YEAR_DISTRICT_FIELDS"]
