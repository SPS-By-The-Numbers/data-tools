from . import common

AUDIT_FIELDS = [
    {
        "name": "school_year",
        "field_type": "string",
        "doc": "School year the record comes from",
    },
] + common.AUDIT_FIELDS


AUDIT_FIELDS_SCHOOL_YEAR_PK = [
    f if f['name'] != 'school_year' else f | {
        'is_logical_key': True,
        'is_primary_key': True,
    }
    for f in AUDIT_FIELDS]


def make_domain_table(domain, descriptive_name,
                      additional_fields=[],
                      is_school_year_lk=False,
                      primary_key_type='int',
                      primary_key_override=None,
                      source_descriptive_col_override=None,
                      description_col_override=None):
    description_col = domain
    if description_col_override is not None:
        description_col = description_col_override

    source_descriptive_col = description_col
    if source_descriptive_col_override is not None:
        source_descriptive_col = source_descriptive_col_override

    primary_key = f"{domain}_code"
    if primary_key_override is not None:
        primary_key = primary_key_override

    audit_fields = (AUDIT_FIELDS_SCHOOL_YEAR_PK
                    if is_school_year_lk else AUDIT_FIELDS)

    return {
        "name": f"d_{domain}",
        "doc": f"Domain table for OSPI {descriptive_name}",
        "fields": [
            {
                "name": primary_key,
                "source": primary_key,
                "field_type": primary_key_type,
                "is_primary_key": True,
                "is_logical_key": True,
                "doc": f"OSPI {descriptive_name} Code",
            },
            {
                "name": f"{description_col}",
                "source": f"{source_descriptive_col}",
                "field_type": "string",
                "doc": f"Human readable name for {descriptive_name}",
            },
        ] + additional_fields + audit_fields
    }


DOMAIN_PROGRAM = make_domain_table(
    'program', 'Program',
    source_descriptive_col_override="title",
    additional_fields=[
        {
            'name': 'ospi_revenue_description_spsbtn',
            'field_type': 'string',
            'doc': ("Grouping of programs from the OSPI Accounting Manual "
                    "plus inferred categories if programs aren't listed ")
        },
        {
            'name': 'ospi_revenue_description',
            'field_type': 'string',
            'doc': ("Grouping of programs from the OSPI Accounting Manual. "
                    "Programs not listed have a NULL.")
        },
        {
            'name': 'per_pupil_program',
            'field_type': 'string',
            'doc': ("Name for the program used in the OSPI per-pupil report")
        },
    ])

DOMAIN_ACTIVITY = make_domain_table(
    'activity', 'Activity',
    source_descriptive_col_override="description",
    additional_fields=[
        {
            'name': 'sps_activity_category',
            'field_type': 'string',
            'doc': ("Used in the SPS Budget.  The OSPI Activities in the "
                    "SPS Budget are divided into categories because most "
                    "folks think of the budgets in these groups")
        },
        {
            'name': 'simplfied_activity',
            'field_type': 'string',
            'doc': ("Our attempt to simplify categories into useful analysis "
                    "buckets. The sps_budget_activity_category tends to "
                    "group things in a way that obscures what's happening.")
        },
    ])

DOMAIN_OBJECT = make_domain_table(
    'object', 'Object',
    source_descriptive_col_override="description",
    additional_fields=[
        {
            'name': 'object_type',
            'field_type': 'string',
            'doc': "One of finance, compensation, or non-compensation.",
        },
    ])

DOMAIN_NCES = make_domain_table('nces', 'NCES')

DOMAIN_CCDDD = make_domain_table(
    'ccddd',
    'County and District',
    primary_key_override='ccddd',
    description_col_override="district",
    additional_fields=[
        {
            'name': 'county_code',
            'field_type': 'int',
            'doc': "OSPI code for the county this district is part of",
        },
        {
            'name': 'district_code',
            'field_type': 'int',
            'doc': ("OSPI code for the district. ccddd is almost always used "
                    "instead."),
        },
    ])

DOMAIN_COUNTY = make_domain_table('county', 'County')

DOMAIN_SCHOOL = make_domain_table(
    'school', 'School/Location designation',
    description_col_override="school_and_district",
    additional_fields=[
        {
            'name': 'ccddd',
            'field_type': 'int',
            'doc': "County District code for the district of this school",
        },
        {
            'name': 'school',
            'field_type': 'string',
            'doc': "Just the school name",
        },
        {
            'name': 'type',
            'field_type': 'string',
            'doc': "Type of school. Most often 'regular'. NULL if not known",
        },
        {
            'name': 'is_regular',
            'field_type': 'int',
            'doc': "1 if type is known to be regular. Convenience column",
        },
        {
            'name': 'region',
            'field_type': 'string',
            'doc': "NW, NE, Central, SW, SE, Other, Invalid",
        },
        {
            'name': 'is_district_office',
            'field_type': 'boolean',
            'doc': ("For easy filtering of whether or not this is the "
                    "district office 'school' for the district. note that "
                    "a number of expenses and staff are coded to schools that "
                    "should be district office and some things are centrally "
                    "managed are there. If you want to know what funds or "
                    "people are student facing, this is insufficient")
        },
    ])

DOMAIN_FUND = make_domain_table(
    'fund', 'Fund',
    additional_fields=[
        {
            'name': 'fund_des',
            'field_type': 'string',
            'doc': ("Fund short-code used in the f195 item tables instead of "
                    "a fund code. Not sure why there are alternte codes.")
        },
    ])

DOMAIN_SUBFUND = make_domain_table('sub_fund', 'Sub Fund')

DOMAIN_DUTY_ROOT = make_domain_table(
    'duty_root', 'Duty Root',
    primary_key_override='duty_root',
    description_col_override="duty_name",
    additional_fields=[
        {
            'name': 'original_duty_code_pattern',
            'field_type': 'string',
            'doc': ("The original pattern for the duty code that the "
                    "duty_root is inferred from. Pattern should match the "
                    "S275 reporting manual")
        },
        {
            'name': 'duty_name_category',
            'field_type': 'string',
            'doc': "The basic classification of the duty"
        },
        {
            'name': 'duty_name_description',
            'field_type': 'string',
            'doc': "Description of the duty name"
        },
    ])


DOMAIN_DUTY_SUFFIX = make_domain_table(
    'duty_suffix', 'Duty Suffix',
    primary_key_override='duty_suffix',
    description_col_override="duty_contract_type",
    additional_fields=[
        {
            'name': 'duty_contract_description',
            'field_type': 'string',
            'doc': "Description of the contract type"
        },
    ])

DOMAIN_REVENUE = make_domain_table(
    'revenue', 'Revenues',
    additional_fields=[
        {
            'name': 'category_code',
            'field_type': 'int',
            'doc': "category of the revenue code. It's the thousanths place"
        },
        {
            'name': 'category',
            'field_type': 'string',
            'doc': "Name of the category"
        },
        {
            'name': 'program_code',
            'field_type': 'int',
            'doc': ("Program this category is resricted to. Just the last "
                    "2 digits of the revenue_code. If 0, it's unrestricted.")
        },
    ])

DOMAIN_BUDGET_ITEM = make_domain_table(
    'budget_item', 'Budget Items',
    primary_key_type='string',
    primary_key_override='item_code',
    source_descriptive_col_override="description",
    description_col_override="description")

DOMAIN_ACTUALS_ITEM = make_domain_table(
    'actuals_item', 'Actuals Items',
    primary_key_type='string',
    primary_key_override='item_code',
    source_descriptive_col_override="description",
    description_col_override="description",
    additional_fields=[
        {
            'name': 'general_ledger_code_list',
            'field_type': 'string',
            'doc': ("Comma separted list of general ledger codes this item "
                    "corresponds to. May be empty."),
        },
        {
            'name': 'value_sources',
            'field_type': 'string',
            'doc': ("human-readable list of pages (eg 1,2,3 or 30-21) and "
                    "page codes (eg SLTL) for where the value came from. "
                    "May be empty"),
        },
        {
            'name': 'value_uses',
            'field_type': 'string',
            'doc': ("human-readable list of pages (eg 1,2,3 or 30-21) and "
                    "page codes (eg SLTL) for where the value came from. "
                    "May be empty"),
        },
        {
            'name': 'item_data_type',
            'field_type': 'string',
            'doc': ("Human readable type of the entered value (Eg Decimal, "
                    "Decimal (percentage), D, Yes/No, etc)"),
        },
        {
            'name': 'mode_of_input',
            'field_type': 'string',
            'doc': ("Human readable notes for how the data was collected (eg "
                    "User Input, Stored, stored, Calculated and Stored, "
                    "Calculated & Stored)"),
        },
        {
            'name': 'retained',
            'field_type': 'string',
            'doc': ("Human readable notes about retention -- whatever that "
                    "means (eg Y, Y (funds 7 & 8 only), "
                    "Y    (Funds 7 and 8 only), etc)"),
        },
        {
            'name': 'notes',
            'field_type': 'string',
            'doc': "Human readable notes about the field",
        },
    ])


ALL_SCHEMAS = [
    DOMAIN_PROGRAM,
    DOMAIN_ACTIVITY,
    DOMAIN_ACTUALS_ITEM,
    DOMAIN_BUDGET_ITEM,
    DOMAIN_OBJECT,
    DOMAIN_NCES,
    DOMAIN_CCDDD,
    DOMAIN_COUNTY,
    DOMAIN_FUND,
    DOMAIN_REVENUE,
    DOMAIN_SCHOOL,
    DOMAIN_SUBFUND,
    DOMAIN_DUTY_ROOT,
    DOMAIN_DUTY_SUFFIX,
]
