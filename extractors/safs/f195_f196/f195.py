import re

from .common import infer_field, to_bigquery_colname


# Column names for type inferrence.
RE_INT_COLUMN = re.compile(
    r"activity_code|"
    r"county_code|"
    r"fund_code|"
    r"object_code|"
    r"district_code|"
    r"program_code|"
    r"revenue_code|"
    r"codist|"
    r"ccddd")
RE_DECIMAL_COLUMN = re.compile(r'amount| proj| bud')
RE_DATE_COLUMN = re.compile(r'last_updated')
RE_BOOLEAN_COLUMN = re.compile(r'is_forecast')

# Use this to force a string. It's an override that's run before the other
# regexps so make it very specific
RE_STR_COLUMN = re.compile(r"fund_des|fund_name")


def normalize_column_name(tablename, col_name):
    """Column names drift over time. Normalize them here"""
    bq_col_name = to_bigquery_colname(col_name)

    match bq_col_name:
        # Normalize column names that have shifted over time.
        case 'cty':
            return 'county_code'

        case 'dist':
            return 'district_code'

        case 'codist':
            return 'ccddd'

        case 'categories':
            return 'category'

        case 'titles':
            return 'title'

        # Handle weird id column
        case 'id':
            # Sigh. Guess this from the table name
            if tablename == 'county':
                return 'county_code'
            return bq_col_name

        # Suffix numeric values with '_code'
        case 'district':
            return 'district_code'

        case 'county':
            return 'county_code'

        case 'itemcode':
            # The 2024-2025 budget uses itemcode in general_fund_revenues for
            # some reason.
            if tablename == 'general_fund_revenues':
                return 'revenue_code'
            return 'item_code'

        case 'item':
            if tablename == 'trans_vehicle_revenues':
                return 'revenue_code'
            return 'item_code'

        case 'item_number':
            return 'item_code'

        case 'revenue':
            return 'revenue_code'

        case 'program_number':
            if tablename == 'revenue':
                # This is a mislabeled column in AF11952122.
                return 'revenue_code'
            else:
                return 'program_code'

        case 'fund_number':
            return 'fund_code'

        case 'program':
            return 'program_code'

        case 'activity':
            return 'activity_code'

        case 'object':
            return 'object_code'

        case 'fund':
            return 'fund_code'

        case _:
            return bq_col_name


def header_to_schema(tablename, row):
    data_fields = [infer_field(tablename, col_name, normalize_column_name,
                               RE_STR_COLUMN, RE_INT_COLUMN, RE_DECIMAL_COLUMN,
                               RE_DATE_COLUMN, RE_BOOLEAN_COLUMN)
                   for col_name in row]
    return {
        "name": "f195",
        "doc": "Inferred schema",
        "fields": data_fields + [
            # f19x.text_column_schema('_source'),
            # f19x.text_column_schema('_table'),
            # f19x.text_column_schema('school_year'),
        ]
    }


def tablename_normalizer(source_tablename):  # noqa: C901
    if 'ITEMDIC' in source_tablename:
        return "item_dict"
    elif 'ACTIVITY' in source_tablename:
        return "activity"
    elif 'CCDDD' in source_tablename:
        return "ccddd"
    elif 'COUNTY' in source_tablename:
        return "county"
    elif 'FUND' in source_tablename:
        return "fund"
    elif 'OBJECT' in source_tablename:
        return "object"
    elif 'PROGRAM' in source_tablename:
        return "program"
    elif 'REVENUE' in source_tablename:
        return "revenue"
    elif ('CapitalProjectRevenues' in source_tablename
          or 'CapitalRevenues' in source_tablename):
        return "capital_project_revenues"
    elif 'DebtServiceRevenues' in source_tablename:
        return "debt_service_revenues"
    elif 'GeneralFundExpenditures' in source_tablename:
        return "general_fund_expenditures"
    elif 'GeneralFundRevenues' in source_tablename:
        return "general_fund_revenues"
    elif 'TransVehicleRevenues' in source_tablename:
        return "trans_vehicle_revenues"
    elif 'ItemNumbers' in source_tablename:
        return "item_numbers"
    elif 'All Districts' in source_tablename:
        return "all_districts"
    else:
        logger.error(f"!!! Unexpected Table {source_tablename}")
        return None


