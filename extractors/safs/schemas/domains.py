from . import common

AUDIT_FIELDS = [
    {
        "name": "school_year",
        "field_type": "string",
        "doc": "School year the record comes from",
    },
] + common.AUDIT_FIELDS


def make_domain_table(domain, descriptive_name,
                      additional_fields=[],
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

    return {
        "name": f"d_{domain}",
        "doc": f"Domain table for OSPI {descriptive_name}",
        "fields": [
            {
                "name": primary_key,
                "source": primary_key,
                "field_type": "int",
                "is_primary_key": True,
                "doc": f"OSPI {descriptive_name} Code",
            },
            {
                "name": f"{description_col}",
                "source": f"{source_descriptive_col}",
                "field_type": "string",
                "doc": f"Human readable name for {descriptive_name}",
            },
        ] + additional_fields + AUDIT_FIELDS
    }


DOMAIN_PROGRAM = make_domain_table(
    'program', 'Program',
    source_descriptive_col_override="title",
    additional_fields=[
        {
            'name': 'sps_budget_program_category',
            'field_type': 'string',
            'doc': ("OSPI Programs in the SPS Budget are divided into "
                    "categories because most folks think of the budgets in "
                    "groups")
        },
        {
            'name': 'simplfied_program',
            'field_type': 'string',
            'doc': ("Our attempt to simplify categories into useful analysis "
                    "buckets. The sps_budget_program_category tends to "
                    "over-group things."),
        },
        {
            'name': 'short_description',
            'field_type': 'string',
            'doc': "Short description sometimes given by f196 domain tables.",
        },
        {
            'name': 'notes',
            'field_type': 'string',
            'doc': "Notes included by short description.",
        },
    ])

DOMAIN_ACTIVITY = make_domain_table(
    'activity', 'Activity',
    source_descriptive_col_override="description",
    additional_fields=[
        {
            'name': 'sps_budget_activity_category',
            'field_type': 'string',
            'doc': ("OSPI Activities in the SPS Budget are divided into "
                    "categories because most folks think of the budgets "
                    "in groups")
        },
        {
            'name': 'simplfied_activity',
            'field_type': 'string',
            'doc': ("Our attempt to simplify categories into useful analysis "
                    "buckets. The sps_budget_activity_category tends to "
                    "group things in a way that obscures what's happening.")
        },
        {
            'name': 'short_description',
            'field_type': 'string',
            'doc': "Short description sometimes given by f196 domain tables.",
        },
    ])

DOMAIN_OBJECT = make_domain_table(
    'object', 'Object',
    source_descriptive_col_override="description",
    additional_fields=[
        {
            'name': 'is_compensation',
            'field_type': 'boolean',
            'doc': "Mostly Object is useful for dividing comp vs non-comp"
        },
        {
            'name': 'short_description',
            'field_type': 'string',
            'doc': "Short description sometimes given by f196 domain tables.",
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
    additional_fields=[
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

DOMAIN_FUND = make_domain_table('fund', 'Fund')

DOMAIN_SUBFUND = make_domain_table('subfund', 'Sub Fund')

DOMAIN_DUTY_ROOT = make_domain_table(
    'duty_root', 'Duty Root',
    description_col_override="duty_title",
    additional_fields=[
        {
            'name': 'duty_category',
            'field_type': 'string',
            'doc': "The basic classification of the duty"
        },
        {
            'name': 'duty_description',
            'field_type': 'string',
            'doc': "Description of the duty name"
        },
    ])


DOMAIN_DUTY_SUFFIX = make_domain_table(
    'duty_suffix', 'Duty Suffix',
    description_col_override="contract_type",
    additional_fields=[
        {
            'name': 'contract_description',
            'field_type': 'string',
            'doc': "Description of the contract type"
        },
    ])

ALL_SCHEMAS = [
    DOMAIN_PROGRAM,
    DOMAIN_ACTIVITY,
    DOMAIN_OBJECT,
    DOMAIN_NCES,
    DOMAIN_CCDDD,
    DOMAIN_COUNTY,
    DOMAIN_FUND,
    DOMAIN_SUBFUND,
    DOMAIN_DUTY_ROOT,
    DOMAIN_DUTY_SUFFIX,
]
