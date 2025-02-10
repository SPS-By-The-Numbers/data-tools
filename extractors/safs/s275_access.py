#!python3

"""
This script turns a s275 access database into an avro file with fields
stripped.

Convert the accdb to csv first by running mdb-export from mdbtools with a
command like

$ mdb-export 2022-2023_Final_S-275_Personnel_Database.accdb \
    2022-2023S-275FinalForPublic

Do NOT attempt to use python only tools for this. They are slow and not
complete. The mdbtools binaries are the best way to convert to a csv.
"""

import argparse
import csv
import fastavro
from decimal import Decimal


def clean_string(x):
    return x.strip()


def title_case(x):
    return clean_string(x).title()


def int_or_null(x):
    x = clean_string(x)
    if x:
        return int(x)

    return None


def decimal_or_null(x):
    x = clean_string(x)
    if x:
        return Decimal(x).quantize(Decimal('0.000000001'))
    return None


def prog_act_or_null(x):
    """Normalize Program and Activity codes.

    s275 has SB and CP for ASB and Capital Projects fund. These are not
    standard. Make up 1 codes way outside the range for them so the type
    can be int.
    """
    x = clean_string(x)
    if x == 'SB':
        return -100
    if x == 'CP':
        return -200
    return int(x)


def make_field_type(field_name):
    match field_name:
        case ("cou" | "dis" | "codist" | "parea" |
              "darea" | "droot" | "dsufx" | "bldgn"):
            return ({"name": field_name,
                     "type": ["null", "int"],
                     "default": None,
                     },
                    int_or_null)

        case ("prog" | "act"):
            return ({"name": field_name,
                     "type": ["null", "int"],
                     "default": None,
                     },
                    prog_act_or_null)

        case ("asssal" | "cins" | "cman" | "certbase" | "clasbase" |
              "othersal" | "tfinsal" |
              "ftehrs" | "ftedays" | "certfte" | "clasfte" | "exp" |
              "camix1" | "asspct" | "assfte" | "asshpy" |
              "acred" | "icred" | "bcred" | "vcred"):
            return ({"name": field_name,
                     "type": [
                         "null",
                         {
                             "type": "bytes",
                             "logicalType": "decimal",
                             "precision": 38,
                             "scale": 9,
                         }],
                     "default": None
                     },
                    decimal_or_null)

        case "SchoolYear":
            return ({"name": field_name,
                     "type": ["null", "string"],
                     "default": None
                     },
                    clean_string)

        case ("FirstName" | "MiddleName" | "LastName"):
            return ({"name": field_name,
                     "type": ["null", "string"],
                     "default": None
                     },
                    title_case)

        case _:
            return ({"name": field_name,
                     "type": ["null", "string"],
                     "default": None
                     },
                    clean_string)


def make_schema(header):
    return {
        "type": "record",
        "namespace": "spsbythenumbers",
        "name": "S275Data",
        "fields": [make_field_type(h)[0] for h in header]
    }


def convert(field_name, value):
    try:
        return make_field_type(field_name)[1](value)
    except Exception as e:
        print(f"Failed on '{field_name}' for '{value}'", e)


def main():
    parser = argparse.ArgumentParser(
        prog='s275_access',
        description='Converts and access database to avro format')

    parser.add_argument('--infile', required=True, help='csv inputfile')
    parser.add_argument('--outfile', required=True, help='output file avro')

    args = parser.parse_args()

    rows = []
    with open(args.infile, newline='') as infile:
        reader = csv.reader(infile)
        schema = None
        headers = None

        for row in reader:
            if schema is None:
                headers = row
                schema = make_schema(row)
            else:
                fields = zip(headers, row)
                rows.append(dict([(h, convert(h, v)) for h, v in fields]))

    with open(args.outfile, "wb") as outfile:
        fastavro.writer(outfile,
                        fastavro.parse_schema(schema),
                        rows,
                        codec="zstandard")


if __name__ == '__main__':
    main()
