import logging
import re

from extractors.safs.avro_schema import to_bigquery_colname
from extractors.safs.inferred_schema_config import InferredMdbReaderBuilder


logger = logging.getLogger(__name__)


# Column names for type inferrence.
RE_INT_COLUMN = re.compile(
    r"accounting_item_id$|"
    r"activity_code$|"
    r"county_code$|"
    r"fund_code$|"
    r"object_code$|"
    r"district_code$|"
    r"nces_code$|"
    r"school_code$|"
    r"sub_fund_code$|"
    r"program_code$|"
    r"revenue_code$|"
    r"codist$|"
    r"ccddd$")
RE_DECIMAL_COLUMN = re.compile(r'amount| proj| bud')
RE_DATE_COLUMN = re.compile(r'last_updated')
RE_BOOLEAN_COLUMN = re.compile(r'is_forecast')

# Use this to force a string. It's an override that's run before the other
# regexps so make it very specific
RE_STR_COLUMN = re.compile(r"fund_des|fund_name")


def normalize_column_name(table_name, col_name):
    """Column names drift over time. Normalize them here"""
    bq_col_name = to_bigquery_colname(col_name)

    match bq_col_name:
        case 'codist':
            return 'ccddd'

        # Suffix numeric values with '_code'
        case 'district':
            return 'district_code'

        case 'county':
            return 'county_code'

        case 'item_number':
            return 'item_code'

        # Handle weird id column
        case 'id':
            # Sigh. Guess this from the table name
            if table_name == 'item_dict':
                return 'item_code'
            return bq_col_name

        # truncation long description name
        case str(bq_col_name) if (bq_col_name.endswith('_description___long')
                                  or bq_col_name.startswith('description_')):
            return 'description'

        # Rename things with "#" as code
        case str(bq_col_name) if bq_col_name.endswith('_#'):
            return f"{bq_col_name[:-1]}code"

        case 'school_year_code':
            return 'school_year'

        case 'county_district_code':
            return 'ccddd'

        case str(bq_col_name) if (bq_col_name.endswith('_description___short')
                                  or bq_col_name == 'short_desc'
                                  or bq_col_name == 'short_name'):
            return 'short_description'

        case ('program_number' | 'program'):
            return 'program_code'

        case 'object':
            return 'object_code'

        case 'activity':
            return 'activity_code'

        case 'item':
            return 'item_code'

        case 'fund':
            if table_name == 'item_dict':
                return 'fund_code_list'
            return 'fund_code'

        case 'revenue':
            return 'revenue_code'

        case _:
            return bq_col_name


def tablename_normalizer(source_tablename):  # noqa: C901
    if 'Item Dictionary' in source_tablename:
        return "item_dict"
    elif ('P-A-Os - Activities' in source_tablename
          or 'ACTIVITY' in source_tablename
          or 'Activity #' in source_tablename):
        return "activity"
    elif ('P-A-Os - Objects' in source_tablename
          or 'OBJECT' in source_tablename
          or 'Object #' in source_tablename):
        return "object"
    elif ('P-A-Os - Programs' in source_tablename
          or 'PROGRAM' in source_tablename
          or 'Program' in source_tablename):
        return "program"
    elif 'CCDDD' in source_tablename:
        return "ccddd"
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
    elif 'ChildGenerlFundExpenditures' in source_tablename:
        return "child_general_fund_expenditures"
    elif 'RevenuesAndExpenditures' in source_tablename:
        return "revenues_and_expenditures"
    elif 'TransVehicleRevenues' in source_tablename:
        return "trans_vehicle_revenues"
    elif 'ItemNumbers' in source_tablename:
        return "item_numbers"
    else:
        logger.error(f"!!! Unexpected Tables {source_tablename}")
        return None


def get_mdb_reader_config(additional_fields):
    config = InferredMdbReaderBuilder(
        datatype="f196",
        tablename_normalizer=tablename_normalizer,
        normalize_column_name=normalize_column_name,
        re_str_column=RE_STR_COLUMN,
        re_int_column=RE_INT_COLUMN,
        re_decimal_column=RE_DECIMAL_COLUMN,
        re_date_column=RE_DATE_COLUMN,
        re_boolean_column=RE_BOOLEAN_COLUMN,
        additional_fields=additional_fields)
    return config.mdb_reader_config
