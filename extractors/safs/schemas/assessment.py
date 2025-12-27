from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS

ASSESSMENT_RC_SCHEMA = {
    "name": "assessment_rc",
    "doc": "State assementment data behind the WA Report Card reports",
    "fields": [
        {
            "name": "assessment_rc_id",
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
            "name": "test_subject",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "Assessment subject. E.g., Math, ELA, Science"
        },

        {
            "name": "test_administration_group",
            "field_type": "string",
            "doc": ("Describes test type. General, Alternate, Other...but "
                    "the data seems to exactly repeat test_administration")
        },

        {
            "name": "test_administration",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "Test type. E.g., SBAC, AIM, WCAS"
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

        # Assessment info.
        {
            "name": "dat",
            "field_type": "string",
            "doc": 'Disclosure Avoidance Technique. E.g., None, N < 10, etc. '
        },

        {
            "name": "num_expected_no_prior",
            "field_type": "int",
            "doc": ('# students expected to take test EXCLUDING students who '
                    'previously passed this assement')
        },

        {
            "name": "num_expected_incl_prior",
            "field_type": "int",
            "doc": ('# students expected to take test INCLUDING students who '
                    'previously passed this assement')
        },

        {
            "name": "pct_participation",
            "field_type": "decimal",
            "doc": ('%% of students that scored at any level. Denominator is '
                    'num_expected_incl_prior')
        },

        {
            "name": "pct_noscore",
            "field_type": "decimal",
            "doc": ('%% of students with no score. Denominator is '
                    'num_expected_no_prior')
        },

        {
            "name": "pct_alternative",
            "field_type": "decimal",
            "doc": ('%% of students taking alternative assesmsents. '
                    'Denominator is Count of Students who scored in ay '
                    'proficiency level.')
        },

        # Assessment Summary.
        {
            "name": "num_met_standard",
            "field_type": "int",
            "doc": ('# students at level 3, and 4 profficiency. Includes the '
                    'count of students who passed in a previous test '
                    'administraiton. Is NULL with DAT')
        },
        {
            "name": "pct_met_standard",
            "field_type": "string",
            "doc": ('%% of students at level 3, and 4 profficiency. Includes '
                    'the count of students who passed in a previous test '
                    'administration. Denominator is num_expected_incl_prior.'
                    ' Is NULL with DAT')
        },

        {
            "name": "num_has_foundational",
            "field_type": "int",
            "doc": ('# students at level 2, 3, and 4 profficiency. Includes '
                    'the count of students who passed in a previous test '
                    'administration. Is NULL with DAT')
        },
        {
            "name": "pct_has_foundational",
            "field_type": "decimal",
            "doc": ('%% students at level 2, 3, and 4 profficiency. Includes '
                    'the count of students who passed in a previous test '
                    'administration. Denominator is num_expected_incl_prior.'
                    'Is NULL with DAT')
        },

        {
            "name": "pct_level_1",
            "field_type": "decimal",
            "doc": ('%% of students at level 1: not proficient. Denominator '
                    'is num_expected_incl_prior. Is NULL with DAT.')
        },

        {
            "name": "pct_level_2",
            "field_type": "decimal",
            "doc": ('%% of students at level 1: not proficient. Denominator '
                    'is num_expected_incl_prior. Is NULL with DAT.')
        },

        {
            "name": "pct_level_3",
            "field_type": "decimal",
            "doc": ('%% of students at level 1: not proficient. Denominator '
                    'is num_expected_incl_prior. Is NULL with DAT.')
        },

        {
            "name": "pct_level_4",
            "field_type": "decimal",
            "doc": ('%% of students at level 1: not proficient. Denominator '
                    'is num_expected_incl_prior. Is NULL with DAT.')
        },

        *AUDIT_FIELDS
    ]
}

ALL_SCHEMAS = [
    ASSESSMENT_RC_SCHEMA,
]
