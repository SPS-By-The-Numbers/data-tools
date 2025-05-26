#!python3

import argparse
import fastavro
import logging

from ..common import common_logging_setup, get_args
from .schemas import s275
from decimal import Decimal
from enum import Enum
from pathlib import Path
from sqlalchemy import Column
from sqlalchemy import create_engine
from sqlalchemy import ForeignKey
from sqlalchemy import select
from sqlalchemy import Table
from sqlalchemy import types
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def to_sqlalchemy_type(field_type):
    match field_type:
        case 'auto_primary_key':
            return types.Integer

        case 'decimal':
            return types.DECIMAL(38, 9)

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
        if field_type == "auto_primary_key":
            autoincrement = True
            is_primary = True

        if f.get('is_primary_key', False):
            # Always let someone specify a column is part of the primary key.
            is_primary = True

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
                                  nullable=True,
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


class Report(Base):
    __table__ = make_table(s275.REPORT_SCHEMA)


class ReportEmployee(Base):
    __table__ = make_table(s275.REPORT_EMPLOYEE_SCHEMA)


class Employee(Base):
    __table__ = make_table(s275.EMPLOYEE_SCHEMA)


class Contract(Base):
    __table__ = make_table(s275.CONTRACT_SCHEMA)


class Assignment(Base):
    __table__ = make_table(s275.ASSIGNMENT_SCHEMA)


class PrivateEmployee(Base):
    __table__ = make_table(s275.PRIVATE_EMPLOYEE_SCHEMA)


class PrivateContract(Base):
    __table__ = make_table(s275.PRIVATE_CONTRACT_SCHEMA)


class PrivateAssignment(Base):
    __table__ = make_table(s275.PRIVATE_ASSIGNMENT_SCHEMA)


class UpdateType(Enum):
    UPDATE = 1
    NO_CHANGE = 2
    NEW_IS_EMPTY = 3
    ERROR = 4


def safe_div(a, b):
    """returns a/b. If b is 0, returns 0."""
    if b.is_zero():
        return Decimal(0)

    return a / b


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


def _record_to_fields(record, schema):
    logical_key_fields = {}
    other_fields = {}

    # Extract every field that can be gotten from the record.
    for f in schema['fields']:
        # Skip automatic primary keys and foreign keys. Those do not come
        # from the record.
        if f['field_type'] == 'auto_primary_key' or 'foreign_key' in f:
            continue

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

        if f.get('is_logical_key', False):
            logical_key_fields[f['name']] = value
        else:
            other_fields[f['name']] = value

    return {"logical_key": logical_key_fields, "other_fields": other_fields}


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
    def __init__(self):
        self._engine = create_engine(
            "postgresql+psycopg2://albert:@localhost/albert",
            echo=False).execution_options(autocommit=False)
#        self._engine = create_engine(
#            "sqlite://", echo=False).execution_options(autocommit=False)

        # Key is _assignment_table id. Is a 1:1 mapping.
        self._calculated_assignment_compensation = {}

    def create_tables(self):
        Base.metadata.create_all(self._engine)

    def merge(self, f):
        reader = fastavro.reader(f)
        with Session(self._engine) as session:
            new_objects = []
            for depth in range(0, 2):
                print(f"depth: {depth}")
                for record in reader:
                    self._merge_one_record(session, record, depth, new_objects)

                    # Commit in batches.
                    if len(new_objects) > 10000:
                        session.add_all(new_objects)
                        session.commit()
                        new_objects = []
                session.commit()

    def _merge_one_record(self, session, record, depth, new_objects):
        report = self.upsert(record, session, Report,
                             _record_to_fields(record, s275.REPORT_SCHEMA),
                             new_objects)
        employee = self.upsert(record, session, Employee,
                               _record_to_fields(record, s275.EMPLOYEE_SCHEMA),
                               new_objects)
        contract = self.upsert(record, session, Contract,
                               _record_to_fields(record, s275.CONTRACT_SCHEMA),
                               new_objects)

        if depth < 1:
            return

        self.upsert(record, session, ReportEmployee,
                    _record_to_fields(record, s275.REPORT_EMPLOYEE_SCHEMA),
                    new_objects,
                    foreign_keys={"report_id": report.report_id,
                                  "employee_id": employee.employee_id})

        assignment = self.upsert(
            record, session, Assignment,
            _record_to_fields(record, s275.ASSIGNMENT_SCHEMA),
            new_objects,
            foreign_keys={"report_id": report.report_id,
                          "employee_id": employee.employee_id,
                          "contract_id": contract.contract_id})

        self.upsert(record, session, PrivateEmployee,
                    _record_to_fields(record, s275.PRIVATE_EMPLOYEE_SCHEMA),
                    new_objects,
                    foreign_keys={"employee_id": employee.employee_id})

        self.upsert(
            record, session, PrivateContract,
            _record_to_fields(record, s275.PRIVATE_CONTRACT_SCHEMA),
            new_objects,
            foreign_keys={"contract_id": contract.contract_id})

        if depth < 2:
            return

        self.upsert(record, session, PrivateAssignment,
                    _record_to_fields(record, s275.PRIVATE_ASSIGNMENT_SCHEMA),
                    foreign_keys={"assignment_id": assignment.assignment_id})

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
            schema=s275.EMPLOYEE_SCHEMA,
            table=self._employee_table,
            additional_tables=[self._employee_calculated_table])

        self.write_table(
            outdir=outdir,
            schema=s275.CONTRACT_SCHEMA,
            table=self._contract_table)

        self.write_table(
            outdir=outdir,
            schema=s275.ASSIGNMENT_SCHEMA,
            table=self._assignment_table)

        self.write_table(
            outdir=outdir,
            schema=s275.S275_REPORT_EMPLOYEE_SCHEMA,
            table=self._s275_report_employee_table)

        self.write_table(
            outdir=outdir,
            schema=s275.PRIVATE_EMPLOYEE_SCHEMA,
            table=self._private_employee_data_table)

        self.write_table(
            outdir=outdir,
            schema=s275.PRIVATE_CONTRACT_SCHEMA,
            table=self._private_contract_table)

        self.write_table(
            outdir=outdir,
            schema=s275.PRIVATE_ASSIGNMENT_SCHEMA,
            table=self._private_assignment_table)

    def upsert(self, record, session, orm_class, fields_dict,
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
    parser.add_argument('infiles', nargs="+",
                        type=argparse.FileType('rb'),
                        help='raw s275 avro files to combine"')
    common_logging_setup(parser)

    args = get_args(parser)

    normalized_s275 = NormalizedS275()
    normalized_s275.create_tables()
    for f in args.infiles:
        normalized_s275.merge(f)

    normalized_s275.write_all_tables(args.outdir)


if __name__ == '__main__':
    main()
