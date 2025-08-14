#!python3

import argparse
import inflection
import logging
import re

from pathlib import Path
from sqlalchemy import insert
from sqlalchemy import delete
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Session

from extractors.common import common_logging_setup, get_args
from extractors.safs.data_reader import (DataReader, CsvRawReader,
                                         MdbRawReader, XslxRawReader)
from extractors.safs.data_reader_config import (f195, f196, s275, spsbtn)

from .db_connection import DbConnection, add_db_arguments
from .orm import make_table

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class DataLoader(DbConnection):
    def __init__(self, args, **kwargs):
        super().__init__(args, **kwargs)
        self._orm_classes = {}
        self.db_drop_first = args.db_drop_first
        self.outprefix = args.outprefix
        self.outdir = args.outdir
        self._has_loaded = set()

    def add_orm_table(self, schema):
        table_name = schema["name"]
        orm_class = self._orm_classes.get(table_name, None)
        if orm_class is None:
            class_name = inflection.camelize(table_name)
            orm_class = type(class_name,
                             (Base,),
                             {"__table__": make_table(schema, Base)})
            self._orm_classes[table_name] = orm_class

        return orm_class

    def load_values(self, schema, rows, drop_first, is_new_table):
        orm_class = self.add_orm_table(schema)
        if drop_first:
            orm_class.__table__.drop(self.engine, checkfirst=True)

        if drop_first or is_new_table:
            orm_class.__table__.create(self.engine, checkfirst=True)

        with Session(self.engine) as session:
            statement = insert(orm_class)
            current_batch = []
            rows_since_commit = 0

            has_cleared_old_data = False

            for r in rows:
                if not has_cleared_old_data:
                    # Delete old entries
                    delete_statement = (
                        delete(orm_class)
                        .where(orm_class._source_table == r['_source_table'])
                        .where(orm_class.school_year == r['school_year']))
                    logger.info(f"Deleting '{r['_source_table']}' and "
                                f"'{r['school_year']}' from {schema['name']}")
                    session.execute(delete_statement)
                    has_cleared_old_data = True

                rows_since_commit += 1
                current_batch.append(r)
                if len(current_batch) > 100000:
                    logger.info(f"Executing batch for {schema['name']}")
                    session.execute(statement, current_batch)
                    current_batch.clear()
                if rows_since_commit > 1000000:
                    logger.info(f"Committing for {schema['name']}")
                    session.commit()
                    rows_since_commit = 0

            if len(current_batch) > 0:
                logger.info(f"Final batch for {schema['name']}")
                session.execute(statement, current_batch)
            logger.info(f"Final commit for {schema['name']}")
            session.commit()

    def process_file(self, filename):
        reader = self._make_reader(filename)

        for normalized_table, source_table in reader.tables.items():
            schema, record_generator = reader.to_records(normalized_table)
            raw_table_name = schema['name']

            is_new_table = raw_table_name not in self._has_loaded
            drop_first = self.db_drop_first and is_new_table

            self.load_values(schema, record_generator, drop_first,
                             is_new_table)
            self._has_loaded.add(raw_table_name)

        for normalized_table, source_table in reader.tables.items():
            print('output: ', normalized_table, source_table)

    def _make_reader(self, filename):
        def get_additional_values(schema, tablename, all_tables):
            source = Path(filename).name
            values = {}

            if 'school_year' not in schema['fields']:
                values.update(_get_additional_school_year(
                    schema, tablename, all_tables, source))
            return values

        if filename.endswith('csv'):
            raw_reader = CsvRawReader(filename)
        elif filename.endswith('xlsx'):
            raw_reader = XslxRawReader(filename)
        else:
            raw_reader = MdbRawReader(filename)

        datatype = raw_reader.datatype()

        match datatype:
            case "f195":
                return DataReader(
                    raw_reader,
                    f195.get_reader_config(add_additional_fields,
                                           get_additional_values))
            case "f196" | "f196-codes":
                return DataReader(
                    raw_reader,
                    f196.get_reader_config(add_additional_fields,
                                           get_additional_values))
            case "s275":
                return DataReader(
                    raw_reader,
                    s275.get_reader_config(add_additional_fields,
                                           get_additional_values))

            case "spsbtn":
                return DataReader(
                    raw_reader,
                    spsbtn.get_reader_config(add_additional_fields,
                                             get_additional_values))

            case _:
                raise ValueError(f"Unknown datatype {datatype}")


def add_additional_fields(schema):
    """Adds school_year field if not already there."""
    if 'school_year' not in schema['fields']:
        schema['fields'].append(
            {
                "name": "school_year",
                "source": "_school_year",
                "doc": "school year for data",
                "field_type": "string",
            })


def _get_additional_school_year(schema, tablename, all_tables, source):
    orig_table_name = all_tables.get('item_numbers', '')
    match orig_table_name[0:5]:
        case '1415A' | '1415B':
            return {"_school_year": "2014-2015"}

        case '1516A' | '1516B':
            return {"_school_year": "2015-2016"}

        case '1617A' | '1617B':
            return {"_school_year": "2016-2017"}

        case '1718A' | '1718B':
            return {"_school_year": "2017-2018"}

        case '1819A' | '1819B':
            return {"_school_year": "2018-2019"}

        case '1920A' | '1920B':
            return {"_school_year": "2019-2020"}

        case '2021A' | '2021B':
            return {"_school_year": "2020-2021"}

        case '2022A' | '2022B':
            # They typoed the table name here.
            return {"_school_year": "2021-2022"}

        case '2022-':
            return {"_school_year": "2022-2023"}

        case '2023-':
            return {"_school_year": "2023-2024"}

        case '2024-':
            return {"_school_year": "2024-2025"}

    source_year_guess = re.match(r'\d\d\d\d-\d\d\d\d', source)
    if source_year_guess is not None:
        return {"_school_year": source_year_guess[0]}

    raise ValueError(f"Cannot infer school year from {orig_table_name}")


def _parse_args():
    parser = argparse.ArgumentParser(
        prog='from_access',
        description='Converts and access database to avro format')

    parser.add_argument('--outdir', help='output directory for AVRO')
    parser.add_argument('--outprefix', default="[default]",
                        help='Prefix for avro files')
    parser.add_argument('--write-avro', action="store_true",
                        help='Should write avro files')
    parser.add_argument('--write-db', action="store_true",
                        help='Should write to a database')
    parser.add_argument('--db-drop-first', action="store_true",
                        help='Should drop the table before loading')
    parser.add_argument('infiles', nargs="+", help='raw f195 files to combine')

    common_logging_setup(parser)
    add_db_arguments(parser)

    return get_args(parser)


def main():
    args = _parse_args()

    loader = DataLoader(args)
    for filename in args.infiles:
        loader.process_file(filename)


if __name__ == '__main__':
    main()
