from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS

RC_SQSS_SCHEMA = {
    "name": "rc_sqss",
    "doc": "State Student Quality data behind the WA Report Card reports",
    "fields": [
        {
            "name": "rc_sqss_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key"),
        },

        *SCHOOL_YEAR_DISTRICT_FIELDS,

        {
            "name": "school_code",
            "field_type": "int",
            "is_logical_key": True,
            "doc": "OSPI location code for school"
        },

        {
            "name": "student_group_type",
            "field_type": "string",
            "is_logical_key": True,
            "doc": 'Demographic Grouping. E.g, Race, Section 504, SWD'
        },

        {
            "name": "student_group",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ('Demographic Group. Used with student_group_type. '
                    'For group type Race, may be All, Asian, Black, White, '
                    'etc. For s504 may be "Section 504" and "Non Section 504"')
        },

        {
            "name": "grade_level",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ('Grade this test is for. Includes "All Grades" as a level')
        },

        {
            "name": "dataasof",
            "field_type": "timestamp",
            "doc": 'When this data was last updaed'
        },

        {
            "name": "dat",
            "field_type": "string",
            "doc": 'Disclosure Avoidance Technique. E.g., None, N < 10, etc. '
        },

        {
            "name": "measure",
            "field_type": "string",
            "is_logical_key": True,
            "doc": ("Measure type: Ninth Grade on Track, Regular Attendance, "
                    "and Dual Credit. The remaining fields must be "
                    "interpreted based on the measure")

        },

        {
            "name": "percent",
            "field_type": "decimal",
            "doc": "The Numerator/Denominator, with DAT applied as necessary."
        },

        {
            "name": "numerator",
            "field_type": "decimal",
            "doc": "Count of students. Blank if supressed."
        },

        {
            "name": "denominator",
            "field_type": "decimal",
            "doc": "Count of students. Blank if supressed."
        },

        {
            "name": "num_taking_ap",
            "field_type": "int",
            "doc": ("Count of students taking 1 or more AP courses. "
                    "Blank if supressed.")
        },

        {
            "name": "pct_taking_ap",
            "field_type": "decimal",
            "doc": ("Percent of students taking 1 or more AP. "
                    "Blank if supressed.")
        },

        {
            "name": "num_taking_ib",
            "field_type": "int",
            "doc": ("Count of students taking 1 or more IB courses. "
                    "Blank if supressed.")
        },

        {
            "name": "pct_taking_ib",
            "field_type": "decimal",
            "doc": ("Percent of students taking 1 or more IB. "
                    "Blank if supressed.")
        },

        {
            "name": "num_taking_cihs",
            "field_type": "int",
            "doc": ("Count of students taking 1 or more College in Highschool "
                    "courses. Blank if supressed.")
        },

        {
            "name": "pct_taking_cihs",
            "field_type": "decimal",
            "doc": ("Percent of students taking 1 or more College in "
                    "Highschool courses. Blank if supressed.")
        },

        {
            "name": "num_taking_cambridge",
            "field_type": "int",
            "doc": ("Count of students taking 1 or more Cambridge courses. "
                    "Blank if supressed.")
        },

        {
            "name": "pct_taking_cambridge",
            "field_type": "decimal",
            "doc": ("Percent of students taking 1 or more Cambridge courses. "
                    "Blank if supressed.")
        },

        {
            "name": "num_taking_cte",
            "field_type": "int",
            "doc": ("Count of students taking 1 or more CTE or tech prep "
                    "courses. Blank if supressed.")
        },

        {
            "name": "pct_taking_cte",
            "field_type": "decimal",
            "doc": ("Percent of students taking 1 or more CTE or tech prep "
                    "courses. Blank if supressed.")
        },

        {
            "name": "num_taking_runningstart",
            "field_type": "int",
            "doc": ("Count of students taking 1 or more Running Start "
                    "courses. Blank if supressed.")
        },

        {
            "name": "pct_taking_runningstart",
            "field_type": "decimal",
            "doc": ("Percent of students taking 1 or more Running Start "
                    "courses. Blank if supressed.")
        },

        *AUDIT_FIELDS
    ]
}

ALL_SCHEMAS = [
    RC_SQSS_SCHEMA,
]
