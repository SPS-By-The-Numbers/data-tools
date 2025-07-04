import logging
import re

from .common import to_bigquery_colname
from extractors.safs.inferred_schema_config import InferredMdbReaderBuilder


logger = logging.getLogger(__name__)


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


def custom_extract_header(tablename, row_iterator):
    header = next(row_iterator)

    if tablename == 'revenue' and header[0] == 'Field1':
        logger.warning("Skipping first two rows in revenue table")
        next(row_iterator)
        return ['revenue_code', 'title', 'category']
    return header


def pivot_all_districts(orig_rows):
    """All districts has 3 years of amount data as columns. Move into rows.

    The input is something like:
      ['CCDDD', 'FUND', 'ITEM', '22-23 CURRENT', '23-24 FORECAST',
       '24-25 FORECAST', '25-26 FORECAST']

    The output structure should be.
    ['ccddd', 'fund', 'item', 'year', 'forecast', 'amount']
    """
    header = [h.lower() for h in next(orig_rows)]
    ccddd_index = header.index('ccddd')
    fund_index = header.index('fund')
    item_index = header.index('item')

    amount_indicies = [i for i in range(len(header))
                       if i not in [ccddd_index, fund_index, item_index]]
    pivot_info = {}
    first_col_found = False
    for i in amount_indicies:
        if ' ' in header[i]:
            year, raw_forecast = header[i].split(' ')
            is_forecast = raw_forecast.lower() == 'forecast'
        else:
            year = header[i]
            if first_col_found:
                # No words like forecast anymore. Consider the first one real
                # and the others to be forecasts.
                is_forecast = False
            else:
                first_col_found = True
                is_forecast = True

        if len(year) == 5:
            parts = year.split('-')
            year = f"20{parts[0]}-20{parts[1]}"
        pivot_info[i] = [year, is_forecast]

    # Produce the new header.
    yield ['ccddd', 'fund', 'item', 'projection_year', 'is_forecast', 'amount']

    # Produce all the rest of the pivoted rows.
    for r in orig_rows:
        data_start = [r[ccddd_index], r[fund_index], r[item_index]]
        for i in amount_indicies:
            yield data_start + pivot_info[i] + [r[i]]


def row_preprocess(tablename, row_iterator):
    if tablename == 'all_districts':
        return pivot_all_districts(row_iterator)

    return row_iterator


def get_mdb_reader_config(additional_fields):
    config = InferredMdbReaderBuilder(
        datatype="f195",
        tablename_normalizer=tablename_normalizer,
        normalize_column_name=normalize_column_name,
        re_str_column=RE_STR_COLUMN,
        re_int_column=RE_INT_COLUMN,
        re_decimal_column=RE_DECIMAL_COLUMN,
        re_date_column=RE_DATE_COLUMN,
        re_boolean_column=RE_BOOLEAN_COLUMN,
        additional_fields=additional_fields,
        custom_extract_header=custom_extract_header,
        row_preprocess=row_preprocess)
    return config.mdb_reader_config
