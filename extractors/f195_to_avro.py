import argparse
import csv
import fastavro
import logging
import os
import re
import subprocess

from common import common_logging_setup, get_args
from decimal import Decimal

logger = logging.getLogger(__name__)

# Quantlizaton for scale of 9 which is bigquery's fixed-point scale.
DEC_SCALE = Decimal('0.000000001')

# Column names for type inferrence.
RE_INT_COLUMN = re.compile(
    r"code|"
    r"activity|"
    r"program|"
    r"object|"
    r"fund|"
    r"revenue|"
    r"codist|"
    r"ccddd")
RE_DECIMAL_COLUMN = re.compile(r'amount| proj| bud')
RE_DATE_COLUMN = re.compile(r'last_updated')
RE_BOOLEAN_COLUMN = re.compile(r'is_forecast')

# Use this to force a string. It's an override that's run before the other
# regexps so make it very specific
RE_STR_COLUMN = re.compile(r"fund_des|fund_name")


def to_decimal(x):
    if not x:
        return None

    return Decimal(x).quantize(DEC_SCALE)


def identity(x):
    return x


def to_bq_name(name):
    """Returns a column name compatible with BigQuery"""
    return name.replace(' ', '_').lower()


def table_id_column(table_name):
    """Returns the normal column name for id value of this table"""
    match table_name:
        case 'county':
            return 'county'

        case _:
            return "id"


def normalize_name(table_name, col_name):
    """Column names drift over time. Normalize them here"""
    bq_col_name = to_bq_name(col_name)

    match bq_col_name:
        case 'cty':
            return 'county'

        case 'dist':
            return 'district'

        case 'codist':
            return 'ccddd'

        case 'item_number':
            return 'item'

        case 'categories':
            return 'category'

        case 'id':
            # Sigh. Guess this from the table name
            return table_id_column(table_name)

        case 'item':
            if table_name == 'trans_vehicle_revenues':
                return 'revenue'
            return bq_col_name

        case 'titles':
            return 'title'

        case 'program_number':
            if table_name == 'revenue':
                # This is a mislabeled column in AF11952122.
                return 'revenue'
            else:
                return 'program'

        case 'fund_number':
            return 'fund'

        case _:
            return bq_col_name


def int_or_null(x):
    if not x:
        return None
    return int(x)


def to_type(name):
    name_lower = name.lower()

    if RE_STR_COLUMN.match(name_lower):
        return ['null', 'string'], identity
    elif RE_INT_COLUMN.match(name_lower):
        return ['null', 'int'], int_or_null
    elif RE_DECIMAL_COLUMN.match(name_lower):
        return [
            'null',
            {
                "type": "bytes",
                "logicalType": "decimal",
                "precision": 38,
                "scale": 9,
            }], lambda d: Decimal(d).quantize(DEC_SCALE)
    elif RE_DATE_COLUMN.match(name_lower):
        return ['null', {
            'type': 'int',
            'logicalType': 'timestamp-millis'
        }], int
    elif RE_BOOLEAN_COLUMN.match(name_lower):
        return ['null', 'boolean'], identity
    else:
        return ['null', 'string'], identity


def infer_schema(table_name, col_name):
    col_name = col_name.replace('\ufeff', '').strip()
    name = normalize_name(table_name, col_name)
    avro_type, convert_func = to_type(name)
    return {
        'name': name,
        'type': avro_type,
        '_convert_func': convert_func
    }


def text_column_schema(name):
    return {
        'name': name,
        'type': 'string',
        '_convert_func': identity,
    }


def header_to_schema(table_name, row):
    data_fields = [infer_schema(table_name, col_name) for col_name in row]
    return data_fields + [
        text_column_schema('_source'),
        text_column_schema('_table'),
        text_column_schema('school_year'),
    ]


def pivot_all_districts(orig_rows):
    """All districts has 3 years of amount data as columns. Move into rows.

    The input is something like:
      ['CCDDD', 'FUND', 'ITEM', '22-23 CURRENT', '23-24 FORECAST',
       '24-25 FORECAST', '25-26 FORECAST']

    The output structure should be.
    ['ccddd', 'fund', 'item', 'year', 'forecast', 'amount']
    """
    header = [h.lower() for h in orig_rows[0]]
    ccddd_index = header.index('ccddd')
    fund_index = header.index('fund')
    item_index = header.index('item')

    rows = [['ccddd', 'fund', 'item', 'year', 'is_forecast', 'amount']]

    amount_indicies = [i for i in range(len(header))
                       if i not in [ccddd_index, fund_index, item_index]]
    pivot_info = {}
    for i in amount_indicies:
        year, raw_forecast = header[i].split(' ')
        if len(year) == 5:
            parts = year.split('-')
            year = f"20{parts[0]}-20{parts[1]}"
        is_forecast = raw_forecast.lower() == 'forecast'
        pivot_info[i] = [year, is_forecast]

    for r in orig_rows[1:]:
        data_start = [r[ccddd_index], r[fund_index], r[item_index]]
        for i in amount_indicies:
            rows.append(data_start + pivot_info[i] + [r[i]])

    return rows


def write_avro(outfile, source_file, name, mdb_table_name, school_year, rows):
    columns = header_to_schema(name, rows[0])

    clean_fields = []
    for c in columns:
        clean_fields.append(dict([(k, v) for k, v in c.items()
                                  if not k.startswith('_')]))

    clean_header = {
        'name': 'f195',
        'type': 'record',
        'fields': clean_fields
    }

    records = []
    for csv_row in rows[1:]:
        # Matches the schema returned by header_to_schema()
        row = csv_row + [source_file, mdb_table_name, school_year]
        if len(row) != len(columns):
            raise RuntimeError(f'Header {columns} and row {row} have a '
                               'different number of elements')
        one_record = {}
        is_zero = False
        for i in range(len(columns)):
            h = columns[i]
            conv_func = h['_convert_func']

            try:
                val = conv_func(row[i])
            except Exception as e:
                logger.error(f"Error with {h} on {row}")
                raise e

            one_record[h['name']] = val
            if h['name'] == 'amount' and val == Decimal(0):
                is_zero = True
        if not is_zero:
            records.append(one_record)

    fastavro.writer(outfile,
                    schema=fastavro.parse_schema(clean_header),
                    records=records,
                    codec='zstandard')


def load_table_as_csv(filename, mdb_table):
    """Loads all f195 table rows in csv form"""
    proc = subprocess.Popen(['mdb-export', '-B', filename, mdb_table],
                            stdout=subprocess.PIPE, universal_newlines=True)

    rows = []
    reader = csv.reader(proc.stdout)
    for row in reader:
        rows.append(row)
    return rows


def get_table_mapping(filename):
    """Loads all f195 table names into canonical identifiers"""
    proc = subprocess.Popen(['mdb-tables', '-1', filename],
                            stdout=subprocess.PIPE)
    mappings = {}

    while True:
        line = proc.stdout.readline().decode("utf-8").strip()
        if not line:
            break

        match line:
            case str(line) if 'ITEMDIC' in line:
                mappings["item_dict"] = line
            case str(line) if 'ACTIVITY' in line:
                mappings["activity"] = line
            case str(line) if 'CCDDD' in line:
                mappings["ccddd"] = line
            case str(line) if 'COUNTY' in line:
                mappings["county"] = line
            case str(line) if 'FUND' in line:
                mappings["fund"] = line
            case str(line) if 'OBJECT' in line:
                mappings["object"] = line
            case str(line) if 'PROGRAM' in line:
                mappings["program"] = line
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
            case str(line) if 'TransVehicleRevenues' in line:
                mappings["trans_vehicle_revenues"] = line
            case str(line) if 'ItemNumbers' in line:
                mappings["item_numbers"] = line
            case str(line) if 'All Districts' in line:
                mappings["all_districts"] = line
            case _:
                logger.error(f"!!! Unexpected Tables {line}")

    return mappings


def main():
    parser = argparse.ArgumentParser(description='Reads a f195 mdb into avro')
    parser.add_argument('--infile', required=True, help='f195 mdb file"')
    parser.add_argument('--school-year', required=True, help='eg. 2014-2015')
    parser.add_argument('--outprefix', default="f195-",
                        help='Prefix for avro files')
    parser.add_argument('--outdir', required=True,
                        help='directory for avro output"')
    common_logging_setup(parser)

    args = get_args(parser)

    mappings = get_table_mapping(args.infile)
    csv_tables = {}
    for name, mdb_table in mappings.items():
        rows = load_table_as_csv(args.infile, mdb_table)
        # Handle weird case in AF11952122.accdb where there is an extra
        # header row and incorrect labels.
        if name == 'revenue' and rows[0][0] == 'Field1':
            logger.warning("Skipping first two rows in revenue table")
            rows = [['revenue', 'title', 'category']] + rows[2:]
        elif name == 'all_districts':
            rows = pivot_all_districts(rows)

        if len(rows) > 0:
            logger.info(f'{name}: {len(rows)} {rows[0]}')
            csv_tables[name] = rows

    for name, rows in csv_tables.items():
        with open(f"{args.outdir}/{args.outprefix}{args.school_year}-"
                  f"{name}.avro", 'wb') as fp:
            write_avro(fp, os.path.basename(args.infile), name, mappings[name],
                       args.school_year, rows)


if __name__ == '__main__':
    main()
