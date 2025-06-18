#!python3

import argparse
import fastavro
import logging
import time
from datetime import datetime
from functools import cache

from ..common import common_logging_setup, get_args
from .schemas import s275
from decimal import Decimal, getcontext
from enum import Enum
from pathlib import Path
from sqlalchemy.inspection import inspect

from sqlalchemy import Column
from sqlalchemy import create_engine
from sqlalchemy import ForeignKey
from sqlalchemy import select
from sqlalchemy import bindparam
from sqlalchemy import Table
from sqlalchemy import types
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgres_insert

from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

"""Precision used on the sql DECIMAL type"""
DECIMAL_PRECISION = 38


"""Scale used on the sql DECIMAL type."""
DECIMAL_SCALE = 9


"""quant() parameter for Decimals after math. ALWAYS QUANT TO AVOID ERRORS."""
DECIMAL_QUANT_AMOUNT = Decimal(10**-9)


"""Number of items to hold before a commit"""
COMMIT_BATCH_SIZE = 1000

"""Number of records before a log message"""
LOG_BATCH_SIZE = 10000

"""Number of records before a log message"""
MAX_RECORDS_PER_FILE = -1


"""All objects added to a foreign key, indexed by logical key.

First level is table name. Next is index logic_key to id map

"""

def get_null_sentinel(field_type):
    match field_type:
        case 'decimal':
            return Decimal(-999999999.000000001)

        case 'string':
            return 'sqlh8'

        case 'timestamp':
            return datetime(month=1,day=1,year=1970)

        case 'int':
            return -999999999

        case _:
            raise ValueError(f"No sentinel defined for {field_type}")


def to_sqlalchemy_type(field_type):
    match field_type:
        case 'auto_primary_key':
            return types.Integer

        case 'decimal':
            return types.DECIMAL(DECIMAL_PRECISION, DECIMAL_SCALE)

        case 'timestamp':
            return types.TIMESTAMP

        case 'string':
            return types.TEXT

        case 'boolean':
            return types.BOOLEAN

        case 'int':
            return types.INTEGER


def to_sqlalchemy_columns(schema):
    columns = []

    for f in schema["fields"]:
        name = f["name"]
        field_type = f["field_type"]
        sqlalchemy_type = to_sqlalchemy_type(field_type)
        is_primary = False
        autoincrement = False
        nullable = True
        if field_type == "auto_primary_key":
            is_primary = True
            autoincrement = True
            nullable = False

        if f.get('is_primary_key', False):
            # Always let someone specify a column is part of the primary key.
            is_primary = True
            nullable = False

        if f.get('is_logical_key', False):
            nullable = False

        if "foreign_key" in f:
            columns.append(Column(name,
                                  sqlalchemy_type,
                                  ForeignKey(f["foreign_key"],
                                             ondelete='CASCADE'),
                                  nullable=False,
                                  doc=f["doc"],
                                  primary_key=is_primary,
                                  autoincrement=autoincrement))
        else:
            columns.append(Column(name,
                                  sqlalchemy_type,
                                  nullable=nullable,
                                  doc=f["doc"],
                                  primary_key=is_primary,
                                  autoincrement=autoincrement))

    return columns


def to_sqlalchemy_constraints(schema):
    constraints = []
    logical_key = [f["name"] for f in schema["fields"]
                   if f.get("is_logical_key", False)]

    if len(logical_key) > 0:
        constraints.append(UniqueConstraint(*logical_key))

    for unique_entries in schema.get("unique", []):
        constraints.append(UniqueConstraint(*unique_entries))

    return constraints


def make_table(schema):
    return Table(
        schema["name"],
        Base.metadata,
        *to_sqlalchemy_columns(schema),
        *to_sqlalchemy_constraints(schema)
    )


class Base(DeclarativeBase):
    pass


class Reports(Base):
    __table__ = make_table(s275.REPORTS_SCHEMA)


class ReportEmployees(Base):
    __table__ = make_table(s275.REPORT_EMPLOYEES_SCHEMA)


class Employees(Base):
    __table__ = make_table(s275.EMPLOYEES_SCHEMA)


class Contracts(Base):
    __table__ = make_table(s275.CONTRACTS_SCHEMA)


class Assignments(Base):
    __table__ = make_table(s275.ASSIGNMENTS_SCHEMA)


class PrivateEmployees(Base):
    __table__ = make_table(s275.PRIVATE_EMPLOYEES_SCHEMA)


class PrivateContracts(Base):
    __table__ = make_table(s275.PRIVATE_CONTRACTS_SCHEMA)


class PrivateAssignments(Base):
    __table__ = make_table(s275.PRIVATE_ASSIGNMENTS_SCHEMA)


TABLENAME_ORM_CLASS_MAP = {
    table.__table__.name: table for table in Base.__subclasses__()}


class UpdateType(Enum):
    UPDATE = 1
    NO_CHANGE = 2
    NEW_IS_EMPTY = 3
    ERROR = 4


def safe_div(a, b):
    """returns a/b. If b is 0, returns 0."""
    if b.is_zero():
        return Decimal(0)

    return (a / b).quantize(DECIMAL_QUANT_AMOUNT)


def get_decimal(record, field):
    if field not in record:
        return Decimal(0)

    value = record[field]
    if not value:
        return Decimal(0)

    return value


def has_value(a_tuple):
    for _, v in a_tuple:
        if v:
            return True
    return False


def cmp_field(current, new, field):
    """-1 if current is fresher. 0 if equal. 1 if new is fresher"""
    if field not in new:
        if field not in current:
            return 0
        else:
            return -1

    if field not in current:
        return 1

    c_value = current[field]
    n_value = new[field]

    if c_value == n_value:
        return 0

    if c_value is None:
        return 1

    if n_value is None:
        return -1

    if c_value > n_value:
        return -1
    else:
        return 1


def cmp_field_update_if_greater(current, new, field):
    school_year_cmp = cmp_field(current, new, field)
    if school_year_cmp == -1:
        return UpdateType.NO_CHANGE
    elif school_year_cmp == 1:
        return UpdateType.UPDATE

    return None


def _employee_update_by_value(current, new):
    # Use the latest School Year record.
    result = cmp_field_update_if_greater(current, new, 'SchoolYear')
    if result is not None:
        return result

    # Highest degree year seems strongest signal.
    result = cmp_field_update_if_greater(current, new, 'highest_degree_year')
    if result is not None:
        return result

    # Experience years next strongest signal.
    result = cmp_field_update_if_greater(current, new, 'experience_years')
    if result is not None:
        return result

    # This is weak, but at least it is something.
    result = cmp_field_update_if_greater(current, new,
                                         'nbpts_certificate_expiration')
    if result is not None:
        return result

    # Otherwise pick the ccddd with the largest number so at least this is
    # somewhat consistent on what is chosen.
    result = cmp_field_update_if_greater(current, new, 'codist')
    if result is not None:
        return result

    return UpdateType.NO_CHANGE


def employee_update(current_tuple, new_tuple):
    if current_tuple == new_tuple:
        return UpdateType.NO_CHANGE

    current = dict(current_tuple)
    new = dict(new_tuple)

    return _employee_update_by_value(current, new)


def verify_same(existing_obj, fields_dict):
    """Returns true if ORM object equals the values in fields_dict"""
    # Sanity check the logical key.
    for k, v in fields_dict["logical_key"].items():
        if getattr(existing_obj, k) != v:
            logger.error(
                f"Expected {repr(k)} to have value {repr(v)} not "
                f"{repr(getattr(existing_obj, k))}")
            raise RuntimeError(
                f"Logical Key for {existing_obj} does not match {fields_dict}")

    # Verify the rest of the fields.
    for k, v in fields_dict["other_fields"].items():
        if getattr(existing_obj, k) != v:
            return UpdateType.ERROR

    return UpdateType.NO_CHANGE


def verify_same_ignore_empty(current, new):
    if current == new:
        return UpdateType.NO_CHANGE

    if has_value(current):
        if has_value(new):
            return UpdateType.ERROR
        else:
            return UpdateType.NEW_IS_EMPTY

    return UpdateType.UPDATE


@cache
def get_lk_select(session, fk_tablename):
    fk_schema = s275.TABLENAME_SCHEMA_MAP[fk_tablename]
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
    schema = s275.TABLENAME_SCHEMA_MAP[tablename]
    orm_class = TABLENAME_ORM_CLASS_MAP[tablename]

    statement = insert(orm_class).execution_options(render_nulls=True)

    # Configure behavior on overwrite in columns.
    logical_key_columns = []
    overwrite_columns = {}
    for f in schema["fields"]:
        field_name = f["name"]
        if f.get("is_logical_key", False):
            logical_key_columns.append(field_name)
        else:
            overwrite_columns[field_name] = getattr(statement.excluded,
                                                    field_name)
    return statement.on_conflict_do_update(index_elements=logical_key_columns,
                                           set_=overwrite_columns)


def get_fk_id(session, record, fk_tablename, fk_name):
    fk_schema = s275.TABLENAME_SCHEMA_MAP[fk_tablename]
    fk_orm_class = TABLENAME_ORM_CLASS_MAP[fk_tablename]

    # Generaate the foreign key select statement.
    fk_logical_key =  dict(_record_to_fields(session, record,
                                             fk_schema)["logical_key"])
    statement = get_lk_select(session, fk_tablename)

    return session.execute(statement, fk_logical_key).scalar()


def _record_to_fields(session, record, schema):
    """Extracts values from records into two dicts for fields in the object.

    An avro field is roughly a table column. This converts a row into a two
    dictionaries, logical_key_fields and other_fields, which contain all the
    data from the record for the given schema.

    Concatenate the two dictionaries to get the full set of input column data.
    """
    logical_key_fields = {}
    other_fields = {}

    # Extract every field that can be gotten from the record.
    for f in schema['fields']:
        # Skip automatic primary keys and foreign keys. Those do not come
        # from the record.
        if f['field_type'] == 'auto_primary_key':
            continue

        if 'foreign_key' in f:
            splits = f['foreign_key'].split('.')
            fk_table = splits[0]
            fk_name = splits[1]
            source = None
            extractor = lambda record, _: get_fk_id(session, record, fk_table,
                                                    fk_name)
        else:
            source = f.get('source', None)
            extractor = f.get('extractor', None)

        if extractor is None:
            if source is None:
                # No source or extractor? Must not come from the record.
                value = None
            else:
                # Default to the passthru extrator.
                value = s275.passthru(record, source)
        else:
            value = extractor(record, source)

        if 'foreign_key' in f and value is None:
            raise RuntimeError(f"{f['name']} is foreign key but NULL for "
                               f"{record}")


        # Value to use if null found.
        if (f.get('is_logical_key', False) and
                value is None and
                not f.get('preserve_null', False)):
            value = get_null_sentinel(f['field_type'])

        if f.get('is_logical_key', False):
            logical_key_fields[f['name']] = value
        else:
            other_fields[f['name']] = value

    return {"logical_key": logical_key_fields,
            "other_fields": other_fields}


def _hashable_fields(session, tablename, record):
    """Returns all tuple with logical key tuple and dict of all fields.

    The logical key tuple is sorted and can be used as a deduping key.
    """
    schema = s275.TABLENAME_SCHEMA_MAP[tablename]
    fields = _record_to_fields(session, record, schema)

    lk = tuple(sorted(fields["logical_key"].items()))
    value = fields["logical_key"] | fields["other_fields"]
    return lk, value


def table_to_avro_rows(table, additional_tables):
    """Converts a table entry into a single dict for avro serializaiton.

    This will join fields in additional_tables by the primary key id of the
    table.
    """
    for logical_key, data in table:
        avro_row = dict(logical_key)
        avro_row = avro_row | dict(data['fields'])

        primary_key = data['id']
        avro_row[table.pk_name] = primary_key

        for t in additional_tables:
            avro_row = avro_row | dict(t.find_by_id(primary_key)['fields'])

        yield avro_row


class NormalizedS275:
    def __init__(self, engine_type):
        if engine_type == 'sqlite':
            self._insert = sqlite_insert
            self._engine = create_engine(
                "sqlite://", echo=False).execution_options(autocommit=False)
        else:
            self._insert = postgres_insert
            self._engine = create_engine(
                "postgresql+psycopg2://albert:@localhost/albert",
                echo=False).execution_options(autocommit=False)

        # Key is _assignment_table id. Is a 1:1 mapping.
        self._calculated_assignment_compensation = {}

    def create_tables(self):
        Base.metadata.drop_all(self._engine)
        Base.metadata.create_all(self._engine)

    def _merge_impl(self, session, f, accumulate, flush):
        last = time.perf_counter()
        count = 1
        f.seek(0)
        for record in fastavro.reader(f):
            count += 1
            if count % LOG_BATCH_SIZE == 0:
                now = time.perf_counter()
                print(f"Finished {count} {now - last:.2f}")
                last = now

                # Early bail for testing.
                if MAX_RECORDS_PER_FILE != -1 and count > MAX_RECORDS_PER_FILE:
                    break
            accumulate(record)
        flush()

    def _merge_tables(self, session, f, orm_classes):
        all_entries = {orm_class.__table__.name: {}
                       for orm_class in orm_classes}

        def flush():
            for tablename, lk_value_map in all_entries.items():
                self.upsert(session,
                            tablename,
                            lk_value_map)
                lk_value_map.clear()
            session.commit()

        def accumulate(record):
            # Add entires for each table
            for tablename, lk_value_map in all_entries.items():
                lk, value = _hashable_fields(session, tablename, record)
                lk_value_map[lk] = value

            # Check if it needs to be flushed
            for entries in all_entries.values():
                if len(entries) > COMMIT_BATCH_SIZE:
                    flush()
                    break

        self._merge_impl(session, f, accumulate, flush)


    def merge(self, f):
        with Session(self._engine) as session:
            # Merge in waves based on dependency.
            self._merge_tables(session, f,
                               [Reports, Employees, Contracts])
            self._merge_tables(session, f,
                               [ReportEmployees, Assignments, PrivateEmployees,
                                PrivateContracts])
            self._merge_tables(session, f, [PrivateAssignments])

    def _merge_one_record_old(self, session, record, depth, new_objects):
        """merges one record. depth is how deep in he realted tree to merge."""
        # self._employee_table.upsert(record)
        # self._employee_calculated_table.upsert(
        #     record,
        #     update_disposition=employee_update)
        # self._contract_table.upsert(record)
        # self._assignment_table.upsert(record)
        #  s275_employee_id = self._s275_report_employee_table.upsert(
        #      record)
        # self._private_employee_data_table.upsert(record)
        # self._private_contract_table.upsert(record)
        #  assignment_id = self._private_assignment_table.upsert(record)

        # Find accumulator for assignments
#        if s275_employee_id in assignment_accumulators:
#            accumulator = assignment_accumulators[s275_employee_id]
#        else:
#            accumulator = assignment_accumulators[s275_employee_id] = {
#                'total_assignment_salary': Decimal('0'),
#                'assignment_entries': []
#            }
#
        # Accumulate the total assignment salary for a record.
#        assignment_salary = get_decimal(record, 'asssal')
#        accumulator['assignment_entries'].append({
#            'assignment_id': assignment_id,
#            'assignment_salary': assignment_salary,
#            'benefits': get_decimal(record, 'cman'),
#            'insurance': get_decimal(record, 'cins'),
#            'other_salary': get_decimal(record, 'othersal'),
#            'total_final_salary': get_decimal(record, 'tfinsal'),
#        })
#        accumulator['total_assignment_salary'] += assignment_salary

#    def _FIXME_accumuaate(self):
#        # Fill in the assignment salary table.
#        for _, accumulator in assignment_accumulators.items():
#            total_assignment_salary = accumulator[
#                'total_assignment_salary']
#            for entry in accumulator['assignment_entries']:
#                assignment_percent = safe_div(entry['assignment_salary'],
#                                                total_assignment_salary)
#                assignment_other_salary = (entry['other_salary'] *
#                                            assignment_percent)
#                assignment_insurance = (entry['insurance'] *
#                                        assignment_percent)
#                assignment_benefits = (entry['benefits'] *
#                                        assignment_percent)
#                value = {
#                    "c_assignment_salary_percentage": assignment_percent,
#                    "c_assignment_other_salary": assignment_other_salary,
#                    "c_assignment_insurance": assignment_insurance,
#                    "c_assignment_benefits": assignment_benefits,
#                    "c_assignment_total_compensation": (
#                        assignment_salary +
#                        assignment_other_salary +
#                        assignment_insurance +
#                        assignment_benefits
#                    ),
#                }
#
#                self._calculated_assignment_compensation[
#                    entry['assignment_id']] = value

    def write_table(self, outdir, schema, table, additional_tables=[]):
        with open(outdir / f"{schema['name']}.avro", "wb") as outfile:
            fastavro.writer(outfile,
                            fastavro.parse_schema(schema),
                            table_to_avro_rows(table, additional_tables))

    def write_all_tables(self, outdir_str):
        return
        outdir = Path(outdir_str)
        self.write_table(
            outdir=outdir,
            schema=s275.EMPLOYEES_SCHEMA,
            table=self._employee_table,
            additional_tables=[self._employee_calculated_table])

        self.write_table(
            outdir=outdir,
            schema=s275.CONTRACTS_SCHEMA,
            table=self._contract_table)

        self.write_table(
            outdir=outdir,
            schema=s275.ASSIGNMENTS_SCHEMA,
            table=self._assignment_table)

        self.write_table(
            outdir=outdir,
            schema=s275.S275_REPORTS_EMPLOYEE_SCHEMA,
            table=self._s275_report_employee_table)

        self.write_table(
            outdir=outdir,
            schema=s275.PRIVATES_EMPLOYEE_SCHEMA,
            table=self._private_employee_data_table)

        self.write_table(
            outdir=outdir,
            schema=s275.PRIVATES_CONTRACT_SCHEMA,
            table=self._private_contract_table)

        self.write_table(
            outdir=outdir,
            schema=s275.PRIVATES_ASSIGNMENT_SCHEMA,
            table=self._private_assignment_table)

    def upsert(self, session, tablename, lk_value_map):
        """Inserts entries into the orm_class for the given schema.

        This is the heart of the record merging.  Entries set of values
        """
        if len(lk_value_map) == 0:
            return

        TABLENAME_ORM_CLASS_MAP[tablename],
        s275.TABLENAME_SCHEMA_MAP[tablename],

        statement = get_upsert_statement(session, self._insert, tablename)
        return session.execute(statement, lk_value_map.values())


    def upsert_old(self, record, session, orm_class, fields_dict,
               new_objects,
               foreign_keys={},
               update_disposition=verify_same):

        statement = select(orm_class).filter_by(
            **(fields_dict["logical_key"] | foreign_keys))

        rows = session.execute(statement).all()

        if len(rows) > 1:
            raise RuntimeError(f"{fields_dict} matched multiple rows {rows}")

        if len(rows) > 0:
            current = rows[0][0]
            update_type = update_disposition(current, fields_dict)

            match update_type:
                case UpdateType.ERROR:
                    logger.warning(f"Update failed for {fields_dict}\n"
                                   f"\tfrom\n\t{current}")

                case UpdateType.UPDATE:
                    logger.debug(f"Updating {current} with {fields_dict}")
                    for k, v in fields_dict["other_fields"].items():
                        setattr(current, k, v)

                case UpdateType.NO_CHANGE:
                    logger.debug(f"No change to {current}")
                    pass

                case UpdateType.NEW_IS_EMPTY:
                    pass

            logger.debug(f"Returning {current}")
            return current

        # New item
        new_item = orm_class(
            **(fields_dict["logical_key"] | fields_dict["other_fields"] |
               foreign_keys))
        new_objects.append(new_item)
        logger.debug(f"Adding {new_item}")
        return new_item


def main():
    parser = argparse.ArgumentParser(
        description='Combines raw s275 avro files into normalized tables')
    parser.add_argument('--outprefix', default="s275-",
                        help='Prefix for avro filenamess')
    parser.add_argument('--outdir', required=True,
                        help='directory for set of normalized avro tables"')
    parser.add_argument('--engine', default="sqlite",
                        choices=['sqlite', 'postgresql'],
                        help='Which database backend to use')
    parser.add_argument('--log-batch-size', default=10000, type=int,
                        help='record per logging message')
    parser.add_argument('--commit-batch-size', default=1000, type=int,
                        help='new records before committing')
    parser.add_argument('--max-records-per-file', default=-1, type=int,
                        help=('Max records per avro file to process. '
                              'Useful for tesitng'))
    parser.add_argument('infiles', nargs="+",
                        type=argparse.FileType('rb'),
                        help='raw s275 avro files to combine')
    common_logging_setup(parser)

    args = get_args(parser)

    # GET THIS TO MATCH YOUR DB OR YOU WILL BE SORRY DEBUGGING WHY EQUALITY
    # FAILS RANDOMLY DUE TO ROUNDING/TRUNCATION ERRORS. #@$#$#%#%#
    getcontext().prec = DECIMAL_PRECISION


    global LOG_BATCH_SIZE, COMMIT_BATCH_SIZE, MAX_RECORDS_PER_FILE
    LOG_BATCH_SIZE = args.log_batch_size
    COMMIT_BATCH_SIZE = args.commit_batch_size
    MAX_RECORDS_PER_FILE = args.max_records_per_file

    normalized_s275 = NormalizedS275(args.engine)

    r = inspect(normalized_s275._engine)

    normalized_s275.create_tables()
    for f in args.infiles:
        normalized_s275.merge(f)

    normalized_s275.write_all_tables(args.outdir)


if __name__ == '__main__':
    main()
