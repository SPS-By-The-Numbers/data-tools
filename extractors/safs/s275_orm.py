#!python3

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Column
from sqlalchemy import create_engine
from sqlalchemy import ForeignKey
from sqlalchemy import Table
from sqlalchemy import types
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase

from .schemas.common import DECIMAL_PRECISION, DECIMAL_SCALE
from .schemas import s275


"""Sentinel number used to represent NULL"""
_NULL_NUMBER = -931415926


def get_null_sentinel(field_type, none_instead_of_raise=False):
    """Returns a constant that should mean null for the type"""
    match field_type:
        case 'decimal':
            # Do not use NaN! Those also don't equal one another. grrr.
            return Decimal("-INF")

        case 'string':
            return 'sqlh8'

        case 'timestamp':
            # Random early leap day is unlikely to be used anywhere.
            return datetime(month=2, day=29, year=1972)

        case 'int':
            return _NULL_NUMBER

        case _:
            if none_instead_of_raise:
                return None
            raise ValueError(f"No sentinel defined for {field_type}")


def to_sqlalchemy_constraints(schema):
    constraints = []
    logical_key = [f["name"] for f in schema["fields"]
                   if f.get("is_logical_key", False)]

    if len(logical_key) > 0:
        constraints.append(UniqueConstraint(*logical_key))

    for unique_entries in schema.get("unique", []):
        constraints.append(UniqueConstraint(*unique_entries))

    return constraints


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


def make_table(schema):
    return Table(
        schema["name"],
        Base.metadata,
        *to_sqlalchemy_columns(schema),
        *to_sqlalchemy_constraints(schema)
    )


###
# ORM Classes below
#

class Base(DeclarativeBase):
    pass


class Report(Base):
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


class DbConnection:
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

    @property
    def insert(self):
        return self._insert

    @property
    def engine(self):
        return self._engine


def add_orm_arguments(parser):
    parser.add_argument('--engine', default="sqlite",
                        choices=['sqlite', 'postgresql'],
                        help='Which database backend to use')


TABLENAME_ORM_CLASS_MAP = {
    table.__table__.name: table for table in Base.__subclasses__()}
