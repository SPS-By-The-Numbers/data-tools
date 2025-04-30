import argparse
import fastavro
import logging
import os
import re
import subprocess

from common import common_logging_setup, get_args
from decimal import Decimal
import f19x

logger = logging.getLogger(__name__)

# Column names for type inferrence.
RE_INT_COLUMN = re.compile(
    r"activity_code$|"
    r"county_code$|"
    r"fund_code$|"
    r"object_code$|"
    r"district_code$|"
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


def clean_schema_field(info):
    return dict([(k, v) for k, v in info.items()
                 if not k.startswith('_')])


def normalize_name(table_name, col_name):
    """Column names drift over time. Normalize them here"""
    bq_col_name = f19x.to_bq_name(col_name)

    match bq_col_name:
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


def header_to_schema(table_name, row):
    data_fields = [f19x.infer_schema(table_name, col_name, normalize_name,
                                     RE_STR_COLUMN, RE_INT_COLUMN,
                                     RE_DECIMAL_COLUMN, RE_DATE_COLUMN,
                                     RE_BOOLEAN_COLUMN)
                   for col_name in row]
    return data_fields + [
        f19x.text_column_schema('_source'),
        f19x.text_column_schema('_table'),
    ]


def make_schema(name, first_row):
    column_info = header_to_schema(name, first_row)

    clean_fields = []
    has_school_year = False
    for info in column_info:
        clean_fields.append(clean_schema_field(info))
        if info['name'] == 'school_year':
            has_school_year = True

    if not has_school_year:
        info = f19x.text_column_schema('school_year')
        column_info.append(info)
        clean_fields.append(clean_schema_field(info))

    clean_header = {
        'name': 'f196',
        'type': 'record',
        'fields': clean_fields
    }

    return column_info, clean_header, has_school_year


def write_avro(outfile, source_file, name, mdb_table_name, school_year, rows):
    column_info, clean_header, has_school_year = make_schema(name, rows[0])
    clean_fields = clean_header['fields']

    records = []
    for csv_row in rows[1:]:
        if has_school_year:
            row = csv_row + [source_file, mdb_table_name]
        else:
            row = csv_row + [source_file, mdb_table_name, school_year]

        # Matches the schema returned by header_to_schema()
        if len(row) != len(column_info):
            raise RuntimeError(f'Header {column_info} and row {row} have a '
                               'different number of elements')
        one_record = {}
        is_zero = False
        if (row[0].startswith('For complete descriptions of')):
            logger.debug("Skipping notes in domain tables")
            continue
        for i in range(len(column_info)):
            info = column_info[i]
            conv_func = info['_convert_func']

            try:
                val = conv_func(row[i])
            except Exception as e:
                logger.error(f"Error with {info} on {row}")
                raise e

            one_record[info['name']] = val
            if info['name'] == 'amount' and val == Decimal(0):
                is_zero = True
        if not is_zero:
            records.append(one_record)

    # Drop everything with a bare "field" name.
    clean_fields = [info for info in clean_fields
                    if not info['name'].startswith('field')]
    clean_header['fields'] = clean_fields
    logger.info(f"Writing {name} "
                f"{['%s:%s' % (f['name'], f['type']) for f in clean_fields]}")

    fastavro.writer(outfile,
                    schema=fastavro.parse_schema(clean_header),
                    records=records,
                    codec='zstandard')


def get_table_mapping(filename):
    """Loads all f196 table names into canonical identifiers"""
    proc = subprocess.Popen(['mdb-tables', '-1', filename],
                            stdout=subprocess.PIPE)
    mappings = {}

    while True:
        line = proc.stdout.readline().decode("utf-8").strip()
        if not line:
            break

        match line:
            case str(line) if 'Item Dictionary' in line:
                mappings["item_dict"] = line
            case str(line) if ('P-A-Os - Activities' in line or
                               'ACTIVITY' in line or
                               'Activity #' in line):
                mappings["activity"] = line
            case str(line) if ('P-A-Os - Objects' in line or
                               'OBJECT' in line or
                               'Object #' in line):
                mappings["object"] = line
            case str(line) if ('P-A-Os - Programs' in line or
                               'PROGRAM' in line or
                               'Program' in line):
                mappings["program"] = line
            case str(line) if 'CCDDD' in line:
                mappings["ccddd"] = line
            case str(line) if 'REVENUE' in line:
                mappings["revenue"] = line
            case str(line) if ('CapitalProjectRevenues' in line
                               or 'CapitalRevenues' in line):
                mappings["capital_project_revenues"] = line

            case str(line) if 'DebtServiceRevenues' in line:
                mappings["debt_service_revenues"] = line

            case str(line) if 'GeneralFundExpenditures' in line:
                mappings["general_fund_expenditures"] = line

            case str(line) if 'GeneralFundRevenues' in line:
                mappings["general_fund_revenues"] = line

            case str(line) if 'ChildGenerlFundExpenditures' in line:
                mappings["child_general_fund_expenditures"] = line

            case str(line) if 'RevenuesAndExpenditures' in line:
                mappings["revenues_and_expenditures"] = line

            case str(line) if 'TransVehicleRevenues' in line:
                mappings["trans_vehicle_revenues"] = line

            case str(line) if 'ItemNumbers' in line:
                mappings["item_numbers"] = line

            case _:
                logger.error(f"!!! Unexpected Tables {line}")

    return mappings


def main():
    parser = argparse.ArgumentParser(description='Reads a f196 mdb into avro')
    parser.add_argument('--infile', required=True, help='f196 mdb file"')
    parser.add_argument('--school-year', required=True, help='eg. 2014-2015')
    parser.add_argument('--outprefix', default="f196-",
                        help='Prefix for avro files')
    parser.add_argument('--outdir', required=True,
                        help='directory for avro output"')
    common_logging_setup(parser)

    args = get_args(parser)

    mappings = get_table_mapping(args.infile)
    csv_tables = {}
    for name, mdb_table in mappings.items():
        rows = f19x.load_table_as_csv(args.infile, mdb_table)

        if len(rows) > 0:
            logger.info(f'read: {name}: {len(rows)} {rows[0]}')
            csv_tables[name] = rows

    for name, rows in csv_tables.items():
        with open(f"{args.outdir}/{args.outprefix}{args.school_year}-"
                  f"{name}.avro", 'wb') as fp:
            write_avro(fp, os.path.basename(args.infile), name, mappings[name],
                       args.school_year, rows)


if __name__ == '__main__':
    main()
