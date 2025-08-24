from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS

ENROLLMENT_SCHEMA = {
    "name": "enrollment",
    "doc": "Represents historical enrollment for a district or esd",
    "fields": [
        {
            "name": "enrollment_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key"),
        },

        *SCHOOL_YEAR_DISTRICT_FIELDS,

        {
            "name": "report_type",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "Seems to always be final in enrollment",
        },
        {
            "name": "enrollment_domain",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "The domain of the metric such as K-12 or ALE."
        },
        {
            "name": "grade_category",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ("The specific metric in the enrollment_domain. Usuall a "
                    "grade or a range of grades. Can also be HS Voc, etc..")
        },
        {
            "name": "amount",
            "field_type": "decimal",
            "doc": ("The value for this row. Usually the enrollment. Units "
                    "are defined by the enrollment_domain")
        },

        *AUDIT_FIELDS
    ]
}

ALL_SCHEMAS = [
    ENROLLMENT_SCHEMA,
]
