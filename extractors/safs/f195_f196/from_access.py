#!python3

import argparse
import logging
from pathlib import Path

from extractors.safs.mdb_reader import MdbReader
from extractors.safs.f195_f196 import f195

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        prog='f195_f196_access',
        description='Converts and access database to avro format')

    parser.add_argument('--datatype', default="f196",
                        choices=['f195', 'f196'],
                        help='Which data type to be loading')
    parser.add_argument('--infile', required=True, help='inputfile')
    parser.add_argument('--school-year', required=True, help='eg. 2014-2015')
    parser.add_argument('--outdir', required=True,
                        help='output directory for AVRO')
    parser.add_argument('--outprefix', default="[default]",
                        help='Prefix for avro files')

    args = parser.parse_args()

    additional_fields = [
        {
            "name": "_source",
            "doc": "Source file for data",
            "field_type": "string",
            "value": Path(args.infile).name,
        },
        {
            "name": "school_year",
            "doc": "school year for data",
            "field_type": "string",
            "value": args.school_year,
        },
    ]

    if args.datatype == "f195":
        reader = MdbReader(args.infile,
                           f195.tablename_normalizer,
                           header_to_schema=f195.header_to_schema,
                           additional_fields=additional_fields,
                           custom_extract_header=f195.custom_extract_header,
                           row_preprocess=f195.row_preprocess)

    if args.outprefix == '[default]':
        outprefix = f"{args.datatype}-f{args.school_year}-"
    else:
        outprefix = args.outprefix

    outdir = Path(args.outdir)
    outdir.mkdir(exist_ok=True)
    for normalized_table, source_table in reader.tables.items():
        print(f"{normalized_table} <= {source_table}")
        reader.export_avro(outdir, outprefix, normalized_table)


if __name__ == '__main__':
    main()
