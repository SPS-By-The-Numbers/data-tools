import csv
import inflection
import subprocess

from decimal import Decimal


# Quantlizaton for scale of 9 which is bigquery's fixed-point scale.
DEC_SCALE = Decimal('0.000000001')


def _to_decimal(x):
    if not x:
        return None

    return Decimal(x).quantize(DEC_SCALE)


def _identity(x):
    return x


def to_bq_name(name):
    """Returns a column name compatible with BigQuery"""
    snake_case = inflection.underscore(name).lower()
    return snake_case.replace(' ', '_')


def _int_or_null(x):
    if not x or x == 'NULL':
        return None
    return int(x)


def to_type(name, re_str_column, re_int_column, re_decimal_column,
            re_date_column, re_boolean_column):
    name_lower = name.lower()

    if re_str_column.match(name_lower):
        return ['null', 'string'], _identity
    elif re_int_column.match(name_lower):
        return ['null', 'int'], _int_or_null
    elif re_decimal_column.match(name_lower):
        return [
            'null',
            {
                "type": "bytes",
                "logicalType": "decimal",
                "precision": 38,
                "scale": 9,
            }], _to_decimal
    elif re_date_column.match(name_lower):
        return ['null', {
            'type': 'int',
            'logicalType': 'timestamp-millis'
        }], int
    elif re_boolean_column.match(name_lower):
        return ['null', 'boolean'], _identity
    else:
        return ['null', 'string'], _identity


def infer_schema(table_name, col_name, normalize_name, re_str_column,
                 re_int_column, re_decimal_column, re_date_column,
                 re_boolean_column):
    col_name = col_name.replace('\ufeff', '').strip()
    name = normalize_name(table_name, col_name)
    avro_type, convert_func = to_type(name, re_str_column, re_int_column,
                                      re_decimal_column, re_date_column,
                                      re_boolean_column)
    return {
        'name': name,
        'type': avro_type,
        '_convert_func': convert_func
    }


def text_column_schema(name):
    return {
        'name': name,
        'type': 'string',
        '_convert_func': _identity,
    }


def load_table_as_csv(filename, mdb_table):
    """Loads all f196 table rows in csv form"""
    proc = subprocess.Popen(['mdb-export', '-B', filename, mdb_table],
                            stdout=subprocess.PIPE, universal_newlines=True)

    rows = []
    reader = csv.reader(proc.stdout)
    for row in reader:
        rows.append(row)
    return rows
