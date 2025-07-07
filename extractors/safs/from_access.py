#!python3

import argparse
import logging
from pathlib import Path

from extractors.common import common_logging_setup, get_args
from extractors.safs.mdb_reader import MdbReader
from extractors.safs.mdb_reader_config import (f195, f196, s275)

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        prog='f195_f196_access',
        description='Converts and access database to avro format')

    parser.add_argument('--datatype', choices=['f195', 'f196', 's275'],
                        help='Which data type to be loading')
    parser.add_argument('--infile', required=True, help='inputfile')
    parser.add_argument('--school-year', required=True, help='eg. 2014-2015')
    parser.add_argument('--outdir', required=True,
                        help='output directory for AVRO')
    parser.add_argument('--outprefix', default="[default]",
                        help='Prefix for avro files')

    common_logging_setup(parser)

    args = get_args(parser)

    additional_fields = [
        {
            "name": "_source",
            "doc": "Source file for data",
            "field_type": "string",
            "value": Path(args.infile).name,
        },
        {
            # TODO: This might overwrite embedded fields incorrectly.
            "name": "school_year",
            "doc": "school year for data",
            "field_type": "string",
            "value": args.school_year,
        },
    ]

    if args.datatype == "f195":
        reader = MdbReader(args.infile,
                           f195.get_mdb_reader_config(additional_fields))
    elif args.datatype == "f196":
        reader = MdbReader(args.infile,
                           f196.get_mdb_reader_config(additional_fields))
    elif args.datatype == "s275":
        reader = MdbReader(args.infile,
                           s275.get_mdb_reader_config(additional_fields))

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
