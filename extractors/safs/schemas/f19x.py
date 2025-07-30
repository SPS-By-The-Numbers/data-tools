import inflection

from .. import avro_schema
from .common import AUDIT_FIELDS


def _make_school_year_district_fields(is_logical_key):
    return [
        {
            "name": "school_year",
            "source": "school_year_code",
            "field_type": "string",
            "is_logical_key": is_logical_key,
            "doc": "school year for data",
        },

        {
            "name": "school_starting_year",
            "source": "school_year_code",
            "field_type": "int",
            "extractor": avro_schema.parse_first_schoolyear,
            "doc": ("[convenience] The starting school year as an integer. "
                    "Makes sorting and comparisons easier.")
        },

        {
            "name": "ccddd",
            "field_type": "int",
            "is_logical_key": is_logical_key,
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


def _make_revenues_schema(fund_name):
    return {
        "name": f"{fund_name}_revenues",
        "doc": ("Budgeted and Actual revenues for the "
                f"{inflection.titleize(fund_name)}"),
        "fields": [
            {
                "name": f"{fund_name}_revenue_id",
                "field_type": "auto_primary_key",
                "doc": ("primary key"),
            },

            *_make_school_year_district_fields(is_logical_key=True),

            {
                "name": "data_type",
                "field_type": "string",
                "is_logical_key": True,
                "doc": "Budget or Actual",
            },

            {
                "name": "fund_code",
                "field_type": "int",
                "is_logical_key": True,
                "doc": ("OSPI fund code. Always the same for one fund. Kept "
                        "so unioning tables is easier"),
            },

            {
                "name": "fund",
                "extractor": None,
                "field_type": "string",
                "doc": ("Same for one fund. Kept for consistency if joining "
                        "data."),
            },

            {
                "name": "revenue_code",
                "field_type": "int",
                "is_logical_key": True,
                "doc": "OSPI Revenue code",
            },

            {
                "name": "revenue",
                "field_type": "string",
                "doc": "Description of revenue_code",
            },

            {
                "name": "category_code",
                "field_type": "int",
                "doc": ("OSPI Revenue Category. The 1000s place of the "
                        "revenue_code"),
            },

            {
                "name": "category",
                "field_type": "string",
                "doc": "OSPI Revenue Category.",
            },


            {
                "name": "program_code",
                "field_type": "int",
                "doc": ("Designated OSPI Program code. Taken from the "
                        "revenue_code's last 2 digits. If 00, funds are "
                        "unrestricted"),
            },

            {
                "name": "program",
                "field_type": "string",
                "doc": "OSPI Program name",
            },

            {
                "name": "amount",
                "field_type": "decimal",
                "doc": "Amount of for this line item",
            },

            {
                "name": f"actuals_{fund_name}_revenues_id",
                "field_type": "string",
                "doc": ("Original Primary key in f196 general fund revenues "
                        "table. Kept here for reference. The ID is a "
                        "structured joining of the school_year_code, ccddd "
                        "(0-padded 5 digits), fund_code (0-padded 2 digits), "
                        "and revenue_code."),
            },

            {
                "name": "accounting_item_id",
                "field_type": "int",
                "doc": ("Listed in the Actuals General Fund Revenues table. "
                        "Unsure what it is used for"),
            },
        ] + AUDIT_FIELDS
    }


GENERAL_FUND_EXPENDITURES = {
    "name": "general_fund_expenditures",
    # TODO: Finish explaining the s275 reconciliation.
    "doc": ("Budgeted and Actual expenditures for the general fund. For years "
            "after 2019, the actuals will have building level breakdowns as "
            "well as nces classifictions which allows for much better "
            "analysis as well as reconcillation with the s275. To reconcile "
            "with the s275, the s275s Total Final Salary on the FINAL report "
            "should roughly match the f196 actual reports for Object Codes "
            "2, 3 and NCES codes 110 and 150"),
    "fields": [
        {
            "name": "general_fund_expenditure_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key"),
        },

        *_make_school_year_district_fields(is_logical_key=True),

        {
            "name": "data_type",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "Budget or Actual",
        },

        {
            "name": "has_school",
            "extractor": None,
            "field_type": "boolean",
            "doc": ("[convenience] If the row has school breakdowns. The same "
                    "as checking for school_code is NULL")
        },

        {
            "name": "school_code",
            "field_type": "int",
            "is_logical_key": True,
            "doc": ("The exact school building. Unique across state. Only "
                    "available in f196 actuals data after 2019. Matches the "
                    "s275 buildilng code"),
        },

        {
            "name": "school",
            "extractor": None,
            "field_type": "string",
            "doc": "Name of school building",
        },

        {
            "name": "is_district_office",
            "extractor": None,
            "field_type": "boolean",
            "doc": ("Convenience for tracking if the building is the district "
                    "office"),
        },

        {
            "name": "program_code",
            "field_type": "int",
            "is_logical_key": True,
            "doc": "OSPI code for the program",
        },

        {
            "name": "program",
            "field_type": "string",
            "doc": "OSPI Program name",
        },

        {
            "name": "activity_code",
            "field_type": "int",
            "is_logical_key": True,
            "doc": "OSPI code for the activity",
        },

        {
            "name": "activity",
            "field_type": "string",
            "doc": "OSPI Activity name",
        },

        {
            "name": "object_code",
            "field_type": "int",
            "is_logical_key": True,
            "doc": "OSPI code for the object",
        },

        {
            "name": "object",
            "field_type": "string",
            "doc": "OSPI Object name",
        },

        {
            "name": "fund_code",
            "field_type": "int",
            "is_logical_key": True,
            "doc": ("OSPI fund code. Always the same for one fund. Kept "
                    "so unioning tables is easier"),
        },

        {
            "name": "fund",
            "extractor": None,
            "field_type": "string",
            "doc": "Same for one fund. Kept for consistency if joining data.",
        },

        {
            "name": "sub_fund_code",
            "extractor": None,
            "field_type": "string",
            "is_logical_key": True,
            "doc": "State or local funds. Only in the f196 actuals data.",
        },

        {
            "name": "sub_fund",
            "extractor": None,
            "field_type": "string",
            "doc": ("State or local funds. Only in the f196 actuals data "
                    "since 2019."),
        },

        {
            "name": "nces_code",
            "field_type": "int",
            "is_logical_key": True,
            "doc": "OSPI code for the object",
        },

        {
            "name": "nces",
            "extractor": None,
            "field_type": "string",
            "doc": "NCES expenditure name.",
        },


        {
            "name": "amount",
            "field_type": "decimal",
            "doc": "Amount of for this line item",
        },

        {
            "name": "accounting_item_id",
            "field_type": "int",
            "doc": ("Listed in the Actuals General Fund Expenditures table. "
                    "Unsure what it is used for"),
        },

        {
            "name": "actuals_general_fund_expenditures_id",
            "field_type": "string",
            "doc": ("Original Primary key in f196 general fund expenditures "
                    "table. Kept here for reference. The ID is a structured "
                    "joining of the school_year_code, fund_code "
                    "(0-padded 2 digits), ccddd, program_code "
                    "(0-padded 2 digits), activity_code, object_code, and "
                    "nces_code"),
        },
        {
            "name": "actuals_child_general_fund_expenditures_id",
            "field_type": "string",
            "doc": ("Original Primary key in f196 child general fund "
                    "expenditures table. Kept here for reference. The ID is a "
                    "structured joining of the school_year_code, "
                    "school_code, fund_code, sub_fund_code, program_code, "
                    "activity_code, object_code, and nces_code"),
        },

        # Calculated data.
        {
            "name": "c_in_school_allocated_staff",
            "extractor": None,
            "field_type": "boolean",
            "doc": ("Similar to c_is_district_office, but appiles some custom "
                    "filtering for activities/objects that seem to be "
                    "assigned the building due to accounting maneuvers rather "
                    "than because the money should be there. If there is a "
                    "big divergence between c_should_be_district_office and "
                    "c_is_district_office, more analysis is required."),
        },

        {
            "name": "c_pct_expenditure",
            "field_type": "decimal",
            "doc": ("Amount as percent of total expenditures for the year. "
                    "1.0 is 100%"),
        },

        {
            "name": "c_pct_revenue",
            "field_type": "decimal",
            "doc": ("Amount as percent of total revneues for the year. "
                    "1.0 is 100%"),
        },

    ] + AUDIT_FIELDS
}


GENERAL_FUND_REVENUES = _make_revenues_schema("general_fund")

DEBT_SERVICE_REVENUES = _make_revenues_schema("debt_service")

CAPITAL_PROJECT_REVENUES = _make_revenues_schema("capital_project")

TRANS_VEHICLE_REVENUES = _make_revenues_schema("trans_vehicle")

BUDGET_ITEMS = {
    "name": "budget_items",
    "doc": ("Accounting calculations and data that OSPI uses to build the "
            "f195 report pdfs. Has begining/ending balances"),
    "fields": [
        {
            "name": "budget_item_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key"),
        },

        *_make_school_year_district_fields(is_logical_key=True),

        {
            "name": "fund_code",
            "field_type": "int",
            "is_logical_key": True,
            "doc": "OSPI fund code.",
        },

        {
            "name": "fund",
            "extractor": None,
            "field_type": "string",
            "doc": "Same for one fund. Kept for consistency if joining data.",
        },

        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "Identifier for this specific dataum or calculation.",
        },

        {
            "name": "item",
            "field_type": "string",
            "doc": "Amount of for this line item",
        },

        {
            "name": "amount",
            "field_type": "decimal",
            "doc": "Amount of for this line item",
        },

    ] + AUDIT_FIELDS
}

ACTUALS_ITEMS = {
    "name": "actuals_items",
    "doc": ("Accounting calculations and data that OSPI uses to build the "
            "f196 report pdfs. /hass begining/ending balances"),
    "fields": [
        {
            "name": "actuals_item_id",
            "field_type": "auto_primary_key",
            "doc": ("primary key"),
        },

        *_make_school_year_district_fields(is_logical_key=True),

        {
            "name": "fund_code",
            "field_type": "int",
            "is_logical_key": True,
            "doc": "OSPI fund code.",
        },

        {
            "name": "fund",
            "extractor": None,
            "field_type": "string",
            "doc": "Same for one fund. Kept for consistency if joining data.",
        },

        {
            "name": "item_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": "Identifier for this specific dataum or calculation.",
        },

        {
            "name": "item",
            "field_type": "string",
            "doc": "Amount of for this line item",
        },

        {
            "name": "general_ledger_code_list",
            "field_type": "string",
            "doc": "List of general leader codes that maybe associated.",
        },

        {
            "name": "amount",
            "field_type": "decimal",
            "doc": "Amount of for this line item",
        },

        {
            "name": "accounting_item_id",
            "field_type": "int",
            "doc": ("Listed in the Actuals General Fund Expenditures table. "
                    "Unsure what it is used for"),
        },

        {
            "name": "actuals_item_numbers_id",
            "field_type": "string",
            "doc": ("Original Primary key in f196 item numbers "
                    "table. Kept here for reference. The ID is a "
                    "structured joining of the school_year_code, ccddd "
                    "(0-padded 5 digits), fund_code (0-padded 2 digits), "
                    "and item_code."),
        },

    ] + AUDIT_FIELDS
}

ALL_SCHEMAS = [
    GENERAL_FUND_EXPENDITURES,

    GENERAL_FUND_REVENUES,
    DEBT_SERVICE_REVENUES,
    CAPITAL_PROJECT_REVENUES,
    TRANS_VEHICLE_REVENUES,

    BUDGET_ITEMS,
    ACTUALS_ITEMS,
]
