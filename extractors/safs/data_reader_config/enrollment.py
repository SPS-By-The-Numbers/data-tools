import logging
import math
import re

from extractors.safs import avro_schema

from . import DataReaderConfig

logger = logging.getLogger(__name__)


def parse_school_year(school_year_str):
    start_year = int(school_year_str.split('-')[0])
    end_year = start_year + 1
    return f"{start_year}-{end_year}"


def tablename_normalizer(source_tablename):
    # Unused in this since all "tables" are merged and names discarded.
    return f"enrollment_summary_{source_tablename}"


def parse_header(row_iterator):
    # Discard first row. It's just a 1-indexed column number.
    _ = next(row_iterator)

    enrollment_domain_row = next(row_iterator)
    grade_category_row = next(row_iterator)

    # Rows here look like
    # FINAL 2021-22, nan, K-12 FTE - Includes ALE,nan,nan,nan,ALE,...
    #
    # It's effectifely a a flattened table dump. The first column defines the
    # name of the table and a floating point nan (empty string in csv) denotes
    # a column in the table named by the same index in the row below.
    #
    # We call each of these "tables" a enrollment_domain and then the thing
    # below a "grade_category" since it's mostly grades like K, 1st, etc.,
    # and then some things like HS Voc for high-school vocational.
    column_map = {}
    current_grade_categories = None
    school_year = None
    for i in range(len(enrollment_domain_row)):
        enrollment_value = enrollment_domain_row[i]

        # Start populating a new enrollment_domain when it's a string.
        if isinstance(enrollment_value, str):
            if enrollment_value.startswith('FINAL'):
                # This first set of rows which has the school year and other
                # values that should be in each row.
                m = re.match(r"(.*) (\d{4}-\d{2})", enrollment_value)
                school_year = parse_school_year(m[2])
                report_type = m[1].lower()
                enrollment_value = '*'
            column_map[enrollment_value] = {}
            current_grade_categories = column_map[enrollment_value]

        # Add the grade_category into the current enrollment_domain.
        grade_category = grade_category_row[i]
        if not (isinstance(grade_category, float) and
                math.isnan(grade_category)):
            current_grade_categories[grade_category] = i

    if school_year is None:
        raise ValueError("Could not parse school year")

    return {'column_map': column_map,
            'school_year': school_year,
            'report_type': report_type}


def denormalize_row(header_config, row):
    column_map = header_config['column_map']
    for enrollment_domain, grade_categories in column_map.items():

        # Don't emit a row for just special the '*' type that's included
        # in every row.
        if enrollment_domain == '*':
            continue

        row_prefix = [header_config['school_year'],
                      header_config['report_type']]

        # Add in all the "every row" columns.
        for grade_category, idx in column_map['*'].items():
            row_prefix.append(row[idx])

        # Finally compose the row to yield.
        for grade_category, idx in grade_categories.items():
            yield row_prefix + [enrollment_domain, grade_category, row[idx]]


def row_preprocess(tablename, row_iterator):
    # Header is actually the first 3 rows which defines multiple tables
    # side-by-size. Example is
    #
    # 0, 1, 2,
    # FINAL 2003-04, nan, K-12 FTE,
    # CCDDD, District, 1/2 K, FDK,
    #
    # The first row is just the index number.
    # The second row's is table in the year's dataset.
    # The first row is a column in that year's dataset.
    #
    # We want to denormalize the entire thing into
    #
    #  ccddd, data_name, column, value
    #
    # An example is
    #
    #  00000, K-12 FTE, K, 79436
    header_config = parse_header(row_iterator)

    # Output the denormalization of each table.
    yield (['school_year', 'report_type'] +
           [k.lower().strip() for k
            in header_config['column_map']['*'].keys()] +
           ['enrollment_domain', 'grade_category', 'amount'])
    for raw_row in row_iterator:
        for row in denormalize_row(header_config, raw_row):
            yield row


def _field_from_column_name(_, column_name):
    match column_name:
        case 'ccddd':
            return avro_schema.make_field(name=column_name,
                                          field_type="int",
                                          extractor=avro_schema.to_int_or_null)

        case 'amount':
            return avro_schema.make_field(
                name=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case _:
            return avro_schema.make_field(
                name=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)


def _fields_from_header(tablename, row):
    return [_field_from_column_name(tablename, col_name) for col_name in row]


def get_reader_config(add_additional_fields, get_additional_values):
    return DataReaderConfig(
        datatype="p223",
        tablename_normalizer=tablename_normalizer,
        fields_from_header=_fields_from_header,
        add_additional_fields=add_additional_fields,
        get_additional_values=get_additional_values,
        row_preprocess=row_preprocess)
