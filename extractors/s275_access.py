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

parser = argparse.ArgumentParser(
    prog='s275_access',
    description='Converts and access database to avro format')

parser.add_argument('--infile', required=True, help='csv inputfile')
parser.add_argument('--outfile', required=True, help='output file avro')

args = parser.parse_args()


def clean_string(x):
    return x.strip()


def int_or_null(x):
    if x:
        return int(x)
    return None


def float_or_null(x):
    if x:
        return float(x)
    return None


def make_field_type(field_name):
    match field_name:
        case ("cou" | "dis" | "codist" | "acred" | "icred" | "bcred" |
              "vcred" |
              "cins" | "cman" | "parea" |
              "darea" | "droot" | "dsufx" | "bldgn"):
            return ({"name": field_name, "type": ["null", "int"]}, int_or_null)

        case ("ftehrs" | "ftedays" | "certfte" | "exp" | "camix1" |
              "clasfte" | "certbase" | "clasbase" | "othersal" | "tfinsal" |
              "asspct" | "assfte" | "asssal" | "asshpy"):
            return ({"name": field_name, "type": ["null", "float"]},
                    float_or_null)

        case "SchoolYear":
            return ({"name": field_name, "type": ["null", "string"]},
                    clean_string)

        case _:
            return ({"name": field_name, "type": "string"},
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
    writer = fastavro.writer(outfile,
                             fastavro.parse_schema(schema),
                             rows,
                             codec="zstandard")
