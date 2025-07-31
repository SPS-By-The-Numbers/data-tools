AUDIT_FIELDS = [
    {
        "name": "_source",
        "field_type": "string",
        "doc": "Source file for data",
    },
    {
        "name": "_source_table",
        "field_type": "string",
        "doc": "Original table name",
    }
]

SCHOOL_YEAR_DISTRICT_FIELDS = [
    {
        "name": "school_year",
        "field_type": "string",
        "is_logical_key": True,
        "doc": "school year for data",
    },

    {
        "name": "school_starting_year",
        "field_type": "int",
        "doc": ("[convenience] The starting school year as an integer. "
                "Makes sorting and comparisons easier.")
    },

    {
        "name": "ccddd",
        "field_type": "int",
        "is_logical_key": True,
        "doc": "OSPI county and district code",
    },

    {
        "name": "county",
        "field_type": "string",
        "doc": "County Name",
    },

    {
        "name": "district",
        "field_type": "string",
        "doc": "District Name",
    },
]
