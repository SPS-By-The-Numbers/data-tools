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

from sqlalchemy import bindparam
from sqlalchemy import Column
from sqlalchemy import create_engine
from sqlalchemy import ForeignKey
from sqlalchemy import select
from sqlalchemy import Table
from sqlalchemy import text
from sqlalchemy import types
from sqlalchemy import UniqueConstraint
from sqlalchemy.sql.expression import and_
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

class ScriptConfig:
    __slots__ = ["commit_batch_size", "log_batch_size", "max_records_per_file"]

g_config = ScriptConfig()


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


def is_primary_key(field):
    return (field['field_type'] == 'auto_primary_key' or
            field.get('is_primary_key', False))


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
    __table__ = make_table(s275.REPORT_SCHEMA)


class Employee(Base):
    __table__ = make_table(s275.EMPLOYEE_SCHEMA)


class PrivateEmployee(Base):
    __table__ = make_table(s275.PRIVATE_EMPLOYEE_SCHEMA,)


class ReportEmployee(Base):
    __table__ = make_table(s275.REPORT_EMPLOYEE_SCHEMA)


class PrivateReportEmployee(Base):
    __table__ = make_table(s275.PRIVATE_REPORT_EMPLOYEE_SCHEMA)


class Assignment(Base):
    __table__ = make_table(s275.ASSIGNMENT_SCHEMA)


class AssignmentFte(Base):
    __table__ = make_table(s275.ASSIGNMENT_FTE_SCHEMA)


class PrivateAssignmentCompBase(Base):
    __table__ = make_table(s275.PRIVATE_ASSIGNMENT_COMP_BASE_SCHEMA)


class PrivateAssignment(Base):
    __table__ = make_table(s275.PRIVATE_ASSIGNMENT_SCHEMA)


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
    update_where = []
    for f in schema["fields"]:
        field_name = f["name"]

        # This allows for conflict resolution.
        if field_name == 's275_recno':
            has_s275_recno = True
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

    def create_tables(self):
        Base.metadata.drop_all(self._engine)
        Base.metadata.create_all(self._engine)

    def _merge_impl(self, session, f, accumulate, flush):
        last = time.perf_counter()
        count = 1
        f.seek(0)
        for record in fastavro.reader(f):
            count += 1
            if count % g_config.log_batch_size == 0:
                now = time.perf_counter()
                print(f"Finished {count} {now - last:.2f}")
                last = now

            # Early bail for testing.
            if (g_config.max_records_per_file != -1 and
                    count > g_config.max_records_per_file):
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
                if len(entries) > g_config.commit_batch_size:
                    flush()
                    break

        self._merge_impl(session, f, accumulate, flush)


    def merge(self, f):
        with Session(self._engine) as session:
            # Merge in waves based on dependency. This could be done with a
            # top-sort of all foreign keys but it's easier to write it out
            # manually.
            self._merge_tables(session, f,
                               [Reports, Employee, AssignmentFte,
                                PrivateAssignmentCompBase])
            self._merge_tables(session, f, [ReportEmployee, PrivateEmployee])
            self._merge_tables(session, f, [PrivateReportEmployee, Assignment])
            self._merge_tables(session, f, [PrivateAssignment])
            session.commit()

    def fill_employee_rollup_info(self, session):
        """Fill in latest employee data in Employee table.

        Pick the largest record number for the most recent school year.
        """
        raw_sql = """
            UPDATE
                s275_employee e
            SET
                c_highest_degree = t.highest_degree,
                c_highest_degree_year = t.highest_degree_year,
                c_experience_years = t.experience_years,
                c_nbpts_certificate_expiration =
                    t.nbpts_certificate_expiration,
                c_hire_state = t.hire_state,
                c_record_ccddd = t.ccddd,
                c_record_county_code = t.county_code,
                c_record_s275_recno = t.s275_recno
            FROM (
                SELECT
                    re.employee_id,
                    re.highest_degree,
                    re.highest_degree_year,
                    re.experience_years,
                    re.nbpts_certificate_expiration,
                    re.hire_state,
                    r.ccddd,
                    r.county_code,
                    re.s275_recno,
                    ROW_NUMBER() OVER (
                        PARTITION BY re.employee_id
                        ORDER BY r.school_starting_year DESC,
                                    re.s275_recno DESC
                    ) as rn
                FROM s275_report_employee re
                LEFT JOIN s275_report r ON (re.report_id = r.report_id)
            ) t
            WHERE e.employee_id = t.employee_id
            AND t.rn = 1
            """
        session.execute(text(raw_sql))

    def fill_private_assignments_values(self, session):
        """ Calculate the assignment total_final_salary and benefits in the
            PrivateAssignment table.

            This is very confusing. There are 3 kinds of values that are
            updated at different times. They are as follows:

            == Actual Gross Salary ==
            This is one column: total_final_salary.
            The value here comes from _payroll_ at end of the fiscal year and
            is supposed to be the gross compensation for the fiscal year.
            This is will reflect things like mid-year terminations, leaves, and
            supplemental contracts. It is a per-employee, not a per-assignment
            attribute.

            This is supposed to be an entry for every employee on the payroll
            at the end of year.

            == Assignment Salary ==
            These are the numbers for all employees on Oct 1st. These numbers
            do not get updated on terminations, leaves, hires, and fires and
            represent what the employee would have earned had they finished
            their terms.

            assignemnt_salary -- is a per-assigment attribute that determines
            the money allocated to the position. Seems to be 0 at times which
            probably indicates a reassignment after Oct 1st.

            other_salary -- is a per-employee attribute that includes extra
            time-driven (eg extra hours) or not time-driven (extra
            responsibilities) salaries. These are not broken down into
            assignments and do not get updated.

            == Insurance and benefits ==
            These are updated due to contract negotiations for everyone.
            The are updated to represent the amount paid fo the employee
            UNLESS the employee is terminated early. In the case of early
            termination, these numbers, confusingly, are not prorated down
            and similar to assignemnt_salary represent what they would have
            been paid had they finished their term.

            insurance, benefits -- both of these are per-employee values that
            specify the insurance and benefits for the employee for the whole
            year. These are not broken down into assignments and do not change
            if a person is terminated early. They are updated as a result of
            contract neogiations though.

            == Interpretation ==
            The s275 is a strange beast. First, it is just a snapshot of
            staffing on October 1st. All hires/fires after are ignored keeping
            the entry-set static.

            Next, other than total_final_salary, there is no concept of
            what is actually paid to an employee. It is not possible to
            calculate the actual benefits and insurance.

            Similarly, asside from the assignment_salary, there is no solid
            indication on how an employee's time is allocated between different
            positions. There is the fte_in_assignment and
            pct100_fte_in_assignment but these numbers do not seem to be self
            consistent (sometimes one is zero and the other isn't).

            This makes it only possible to know informionat for employees that
            were in the district on Oct 1st. Folks hired afterwards do not
            show up.

            For the folks listed, the following is knowable:

               * the actual total gross salary
               * the oct 1st assignments and expected salaries

            Weird things that can be calculated:
               * A guess at total insurance and benfits of oct 1st employees.
                 but the number is odd since it reflects mid-year contract
                 negotiations without proration.
               * A guess at the FTE assignment per position.

            Thing that can be inferred
               * If total_final_salary is way lower than sum of all
                 assignment_salary, there was an early termination.

            Thing that can be estimated
               * amount of budgeted insurance/benefits/other_sal per assignment
               * amount of total_final_salary per assignment

            These estimated amounts will have error because new assignments
            can be added for a person with a total_final_salary which will
            be given assignment_salary of 0 so that assignment will be
            missed. Also, the insurance/benefit/other_sal numbers will be
            updated to reflect contract negotiations.

            TODO: Do we have folks with only a asssal=0 assignment and
            non-zero total_final_salary?
        """
        pct_of_assignments = """(COALESCE(pa.assignment_salary /
                                NULLIF(t.all_assignment_salary, 0), 0))"""

        update_private_assignment_sql = f"""
            UPDATE
                s275_private_assignment pa
            SET
              c_pct_of_assignments = { pct_of_assignments },

              c_assignment_other_salary = { pct_of_assignments }
                    * pre.other_salary,

              c_assignment_insurance = { pct_of_assignments }
                    * pre.insurance,

              c_assignment_benefits = { pct_of_assignments }
                    * pre.benefits,

              c_assignment_total_final_salary = { pct_of_assignments }
                    * pre.total_final_salary,

              c_assignment_total_compensation =
                    pa.assignment_salary +
                    { pct_of_assignments } * pre.other_salary +
                    { pct_of_assignments } * pre.insurance +
                    { pct_of_assignments } * pre.benefits
            FROM (
                SELECT
                    pa.s275_report_employee_id,
                    sum(pa.assignment_salary) all_assignment_salary
                FROM s275_private_assignment pa
                GROUP BY
                    pa.s275_report_employee_id
                ) t
            LEFT JOIN s275_private_report_employee pre on (
                pre.s275_report_employee_id = t.s275_report_employee_id)

            WHERE pa.s275_report_employee_id = t.s275_report_employee_id
            """
        session.execute(text(update_private_assignment_sql))

    def fill_calculated_fields(self):
        with Session(self._engine) as session:
            self.fill_employee_rollup_info(session)
            self.fill_private_assignments_values(session)
            session.commit()

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
            schema=s275.EMPLOYEE_SCHEMA,
            table=self._employee_table,
            additional_tables=[self._employee_calculated_table])

        self.write_table(
            outdir=outdir,
            schema=s275.FTE_DATA_SCHEMA,
            table=self._fte_data_table)

        self.write_table(
            outdir=outdir,
            schema=s275.ASSIGNMENT_SCHEMA,
            table=self._assignments_table)

        self.write_table(
            outdir=outdir,
            schema=s275.S275_REPORTS_EMPLOYEE_SCHEMA,
            table=self._s275_report_employee_table)

        self.write_table(
            outdir=outdir,
            schema=s275.PRIVATE_EMPLOYEE_SCHEMA,
            table=self._private_employee_data_table)

        self.write_table(
            outdir=outdir,
            schema=s275.PRIVATE_CONTRACTS_SCHEMA,
            table=self._private_fte_data_table)

        self.write_table(
            outdir=outdir,
            schema=s275.PRIVATE_ASSIGNMENT_SCHEMA,
            table=self._private_assignments_table)

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

    global g_config
    g_config.log_batch_size = args.log_batch_size
    g_config.commit_batch_size = args.commit_batch_size
    g_config.max_records_per_file = args.max_records_per_file

    normalized_s275 = NormalizedS275(args.engine)

    r = inspect(normalized_s275._engine)

    normalized_s275.create_tables()
    for f in args.infiles:
        normalized_s275.merge(f)

    normalized_s275.fill_calculated_fields()

    normalized_s275.write_all_tables(args.outdir)


if __name__ == '__main__':
    main()
