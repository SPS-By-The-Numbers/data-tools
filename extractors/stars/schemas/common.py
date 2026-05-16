"""Shared schema fragments for STARS fact tables.

STARS tables reuse SCHOOL_YEAR_DISTRICT_FIELDS from extractors.safs.schemas
(school_year/class_of/ccddd/county/district) so they join cleanly to d_ccddd.
"""

from ...safs.schemas.common import (
    AUDIT_FIELDS,
    SCHOOL_YEAR_DISTRICT_FIELDS,
)


__all__ = ["AUDIT_FIELDS", "SCHOOL_YEAR_DISTRICT_FIELDS"]
