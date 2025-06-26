#!python3

import argparse
import fastavro
import logging
import time

from functools import cache
from sqlalchemy import bindparam
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import and_

from extractors.common import common_logging_setup, get_args
from extractors.safs import avro_schema

from .orm import add_orm_arguments
from .orm import Assignment
from .orm import AssignmentFte
from .orm import Base
from .orm import DbConnection
from .orm import Employee
from .orm import PrivateAssignment
from .orm import PrivateAssignmentCompBase
from .orm import PrivateEmployee
from .orm import PrivateReportEmployee
from .orm import ReportEmployee
from .orm import Report
from .orm import TABLENAME_ORM_CLASS_MAP
from . import schemas

logger = logging.getLogger(__name__)


def is_primary_key(field):
    return (field['field_type'] == 'auto_primary_key' or
            field.get('is_primary_key', False))


@cache
def get_lk_select(session, fk_tablename):
    fk_schema = schemas.TABLENAME_SCHEMA_MAP[fk_tablename]
    fk_orm_class = TABLENAME_ORM_CLASS_MAP[fk_tablename]

    pk_columns = [f['name']
                  for f in fk_schema['fields']
                  if (f.get('is_primary_key', False) or
                      f['field_type'] == 'auto_primary_key')]
    if len(pk_columns) != 1:
        raise RuntimeError(f"Multiple pk columns unsupported: {pk_columns}")
    where_clause = [getattr(fk_orm_class, f['name']) == bindparam(f['name'])
                    for f in fk_schema['fields']
                    if f.get('is_logical_key', False)]
    return select(getattr(fk_orm_class, pk_columns[0])).where(*where_clause)


@cache
def get_upsert_statement(session, insert, tablename):
    schema = schemas.TABLENAME_SCHEMA_MAP[tablename]
    orm_class = TABLENAME_ORM_CLASS_MAP[tablename]

    statement = insert(orm_class).execution_options(render_nulls=True)

    # Configure behavior on overwrite in columns.
    logical_key_columns = []
    overwrite_columns = {}
    update_where = []
    for f in schema["fields"]:
        field_name = f["name"]

        # This allows for conflict resolution.
        if field_name == 's275_recno':
            update_where.append(getattr(orm_class, field_name) <
                                getattr(statement.excluded, field_name))
            # TODO: Find a way to count collisions.

        # Make sure to allow s275_recno to be updated too.
        if f.get("is_logical_key", False):
            logical_key_columns.append(field_name)
        elif not is_primary_key(f):
            # Don't overwrite the primary key since we're updating.
            overwrite_columns[field_name] = getattr(statement.excluded,
                                                    field_name)
            update_where.append(getattr(orm_class, field_name) !=
                                getattr(statement.excluded, field_name))

    return statement.on_conflict_do_update(
        index_elements=logical_key_columns,
        set_=overwrite_columns,
        where=and_(*update_where))


def get_fk_id(session, record, fk_tablename, fk_name):
    fk_schema = schemas.TABLENAME_SCHEMA_MAP[fk_tablename]

    # Generate the foreign key select statement.
    fk_logical_key = dict(_record_to_upsert(session, record,
                                            fk_schema)["logical_key"])
    statement = get_lk_select(session, fk_tablename)

    return session.execute(statement, fk_logical_key).scalar()


def _record_to_upsert(session, record, schema):
    """Extracts values from records into logical key and other values.

    Combining the two dictionaries will produce bind variables for the upsert.
    The "logical_key" entry can be used to dedupe the insert before it gets
    to the RDMBS which is important since some RDMBS implementations like
    postgresql will reject upserts that touch the same logical key twice
    within one set of values.
    """
    logical_key_fields = {}
    other_fields = {}

    # Extract every field that can be gotten from the record.
    for f in schema['fields']:
        # Skip automatic primary keys Those do not come from the record.
        if f['field_type'] == 'auto_primary_key':
            continue

        if 'foreign_key' in f:
            splits = f['foreign_key'].split('.')
            fk_table = splits[0]
            fk_name = splits[1]
            value = get_fk_id(session, record, fk_table, fk_name)
            if value is None:
                raise RuntimeError(f"{f['name']} is foreign key but NULL for "
                                   f"{record}")
        else:
            source = f.get('source', None)
            extractor = f.get('extractor', None)

            # Extract the value now
            if extractor is None:
                if source is None:
                    # No source or extractor? Must not come from the record.
                    value = None
                else:
                    # Default to the passthru extrator.
                    value = avro_schema.passthru(record, source)
            else:
                value = extractor(record, source)

            if (f['field_type'] == 'decimal' and value is not None and
                    value.is_nan()):
                logger.warning(f"Unexpected NaN for {source} in {record}")

            # Value to use if null found.
            if (f.get('is_logical_key', False) and
                    value is None and
                    not f.get('preserve_null', False)):
                value = avro_schema.get_null_sentinel(f['field_type'])

        # Add to correct key set.
        if f.get('is_logical_key', False):
            logical_key_fields[f['name']] = value
        else:
            other_fields[f['name']] = value

    return {"logical_key": logical_key_fields,
            "other_fields": other_fields}


def _get_lk_bind_values(session, tablename, record):
    """Returns all tuple with logical key tuple and dict of all fields.

    The logical key tuple is sorted and can be used as a deduping key.
    """
    schema = schemas.TABLENAME_SCHEMA_MAP[tablename]
    fields = _record_to_upsert(session, record, schema)

    lk = tuple(sorted(fields["logical_key"].items()))
    bind_values = fields["logical_key"] | fields["other_fields"]
    return lk, bind_values


class NormalizedS275Loader(DbConnection):
    def __init__(self, args):
        super().__init__(args)
        self._report_type = args.report_type
        self._log_batch_size = args.log_batch_size
        self._commit_batch_size = args.commit_batch_size
        self._flush_batch_size = args.flush_batch_size
        self._max_records_per_file = args.max_records_per_file

    def create_tables(self, drop_first):
        if drop_first:
            logger.info("Dropping all tables")
            Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)

    def _merge_impl(self, session, f, accumulate, flush):
        last = time.perf_counter()
        count = 1
        f.seek(0)
        commit_count = 1
        for record in fastavro.reader(f):
            count += 1
            commit_count += 1
            if count % self._log_batch_size == 0:
                now = time.perf_counter()
                print(f"Finished {count} {now - last:.2f}")
                last = now

            # Early bail for testing.
            if (self._max_records_per_file != -1 and
                    count > self._max_records_per_file):
                break

            # Add extra items to the record for extraction.
            record["_report_type"] = self._report_type

            accumulate(record)
            if commit_count > self._commit_batch_size:
                session.commit()
                commit_count = 1

        # Clean out final entries.
        flush()
        session.commit()

    def _merge_tables(self, session, f, orm_classes):
        all_entries = {orm_class.__table__.name: {}
                       for orm_class in orm_classes}

        def flush():
            for tablename, lk_bind_values_map in all_entries.items():
                self.upsert(session, tablename, lk_bind_values_map)
                lk_bind_values_map.clear()

        def accumulate(record):
            # Add entires for each table
            for tablename, lk_bind_values_map in all_entries.items():
                lk, bind_values = _get_lk_bind_values(session, tablename,
                                                      record)
                lk_bind_values_map[lk] = bind_values

            # Flush if it needs to be.
            for entries in all_entries.values():
                if len(entries) > self._flush_batch_size:
                    flush()
                    break

        self._merge_impl(session, f, accumulate, flush)

    def merge(self, f):
        with Session(self.engine) as session:
            # Merge in waves based on dependency. This could be done with a
            # top-sort of all foreign keys but it's easier to write it out
            # manually.
            self._merge_tables(session, f,
                               [Report, Employee, AssignmentFte,
                                PrivateAssignmentCompBase])
            self._merge_tables(session, f, [ReportEmployee, PrivateEmployee])
            self._merge_tables(session, f, [PrivateReportEmployee, Assignment])
            self._merge_tables(session, f, [PrivateAssignment])
            session.commit()

    def upsert(self, session, tablename, lk_bind_values_map):
        """Inserts entries into the orm_class for the given schema.

        This is the heart of the record merging.  Entries set of values
        """
        if len(lk_bind_values_map) == 0:
            return

        TABLENAME_ORM_CLASS_MAP[tablename],
        schemas.TABLENAME_SCHEMA_MAP[tablename],

        statement = get_upsert_statement(session, self.insert, tablename)
        return session.execute(statement, lk_bind_values_map.values())


def main():
    parser = argparse.ArgumentParser(
        description='Loads raw s275 avro files into normalized tables')
    parser.add_argument('--report-type', required=True,
                        choices=['final', 'preliminary'],
                        help=("Whether the s275 database is preliminary from "
                              "oct 1st snapshot, or the final update end of "
                              "year with the tfinsal + contract updates"))
    parser.add_argument('--log-batch-size', default=10000, type=int,
                        help='record per logging message')
    parser.add_argument('--commit-batch-size', default=100000, type=int,
                        help='new records before committing')
    parser.add_argument('--flush-batch-size', default=10000, type=int,
                        help='new records before committing')
    parser.add_argument('--drop-first', default=False, action='store_true',
                        help='Drop all tables before starting')
    parser.add_argument('--max-records-per-file', default=-1, type=int,
                        help=('Max records per avro file to process. '
                              'Useful for tesitng'))
    parser.add_argument('infiles', nargs="+",
                        type=argparse.FileType('rb'),
                        help='raw s275 avro files to combine')
    add_orm_arguments(parser)
    common_logging_setup(parser)

    args = get_args(parser)

    normalized_s275 = NormalizedS275Loader(args=args)

    normalized_s275.create_tables(args.drop_first)
    for f in args.infiles:
        normalized_s275.merge(f)


if __name__ == '__main__':
    main()
