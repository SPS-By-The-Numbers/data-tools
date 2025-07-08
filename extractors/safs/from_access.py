#!python3

import argparse
import inflection
import logging

from pathlib import Path
from sqlalchemy import insert
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Session

from extractors.common import common_logging_setup, get_args
from extractors.safs.mdb_reader import MdbReader
from extractors.safs.mdb_reader_config import (f195, f196, s275)

from .db_connection import DbConnection, add_db_arguments
from .orm import make_table

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class DbLoader(DbConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orm_classes = {}

    def add_table(self, schema):
        table_name = schema["name"]
        class_name = inflection.camelize(table_name)
        new_class = type(class_name,
                         (Base,),
                         {"__table__": make_table(schema, Base)})
        self._orm_classes[table_name] = new_class
        return new_class

    def load_values(self, schema, rows, drop_first):
        orm_class = self.add_table(schema)
#        if drop_first:
#            orm_class.drop(self.engine)
#        orm_class.create(self.engine)
        Base.metadata.create_all(self.engine)

        with Session(self.engine) as session:
            statement = insert(orm_class)
            current_batch = []
            rows_since_commit = 0
            for r in rows:
                rows_since_commit += 1
                current_batch.append(r)
                if len(current_batch) > 1000:
                    session.execute(statement, current_batch)
                    current_batch.clear()
                if rows_since_commit > 100000:
                    session.commit()
                    rows_since_commit = 0

            if len(current_batch) > 0:
                session.execute(statement, current_batch)
            session.commit()


def main():
    parser = argparse.ArgumentParser(
        prog='f195_f196_access',
        description='Converts and access database to avro format')

    parser.add_argument('--datatype', choices=['f195', 'f196', 's275'],
                        help='Which data type to be loading')
    parser.add_argument('--infile', required=True, help='inputfile')
    parser.add_argument('--school-year', required=True, help='eg. 2014-2015')
    parser.add_argument('--outdir', help='output directory for AVRO')
    parser.add_argument('--outprefix', default="[default]",
                        help='Prefix for avro files')
    parser.add_argument('--write-avro', action="store_true",
                        help='Should write avro files')
    parser.add_argument('--write-db', action="store_true",
                        help='Should write to a database')
    parser.add_argument('--db-drop-first', action="store_true",
                        help='Should drop the table before loading')

    common_logging_setup(parser)
    add_db_arguments(parser)

    args = get_args(parser)

    if args.write_avro and not args.outdir:
        raise ValueError("outdir is empty")

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


    if args.write_db:
        db_loader = DbLoader(args)

        for normalized_table, source_table in reader.tables.items():
            schema, record_generator = reader.to_records(normalized_table)
            db_loader.load_values(schema, record_generator, args.db_drop_first)


    if args.write_avro:
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
