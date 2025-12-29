import logging
import re

from extractors.safs.avro_schema import to_bigquery_colname
from .inferred_mdb_reader_builder import InferredMdbReaderBuilder


logger = logging.getLogger(__name__)


# Column names for type inferrence.
RE_INT_COLUMN = re.compile(r"$^")
RE_DECIMAL_COLUMN = re.compile(r'$^')
RE_DATE_COLUMN = re.compile(r'$^')
RE_BOOLEAN_COLUMN = re.compile(r'$^')

RE_CODED_INT_COLUMN = re.compile(
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
    r"duty_root$|"
    r"duty_suffix$|"
    r"is_regular$|"
    r"ccddd$")

# Use this to force a string. It's an override that's run before the other
# regexps so make it very specific
RE_STR_COLUMN = re.compile(r"$^")


def normalize_column_name(table_name, col_name):
    """Column names drift over time. Normalize them here"""
    return to_bigquery_colname(col_name.strip())


def tablename_normalizer(source_tablename):
    return source_tablename


def get_reader_config(add_additional_fields, get_additional_values):
    config = InferredMdbReaderBuilder(
        datatype="spsbtn",
        tablename_normalizer=tablename_normalizer,
        normalize_column_name=normalize_column_name,
        re_str_column=RE_STR_COLUMN,
        re_int_column=RE_INT_COLUMN,
        re_decimal_column=RE_DECIMAL_COLUMN,
        re_date_column=RE_DATE_COLUMN,
        re_boolean_column=RE_BOOLEAN_COLUMN,
        re_coded_int_column=RE_CODED_INT_COLUMN,
        add_additional_fields=add_additional_fields,
        get_additional_values=get_additional_values)
    return config.mdb_reader_config
