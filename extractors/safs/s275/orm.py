from sqlalchemy import Column
from sqlalchemy import ForeignKey
from sqlalchemy import Table
from sqlalchemy import types
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import DeclarativeBase

from ..avro_schema import DECIMAL_PRECISION, DECIMAL_SCALE
from . import schemas


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
    __table__ = make_table(schemas.REPORT_SCHEMA)


class Employee(Base):
    __table__ = make_table(schemas.EMPLOYEE_SCHEMA)


class PrivateEmployee(Base):
    __table__ = make_table(schemas.PRIVATE_EMPLOYEE_SCHEMA,)


class ReportEmployee(Base):
    __table__ = make_table(schemas.REPORT_EMPLOYEE_SCHEMA)


class PrivateReportEmployee(Base):
    __table__ = make_table(schemas.PRIVATE_REPORT_EMPLOYEE_SCHEMA)


class Assignment(Base):
    __table__ = make_table(schemas.ASSIGNMENT_SCHEMA)


class AssignmentFte(Base):
    __table__ = make_table(schemas.ASSIGNMENT_FTE_SCHEMA)


class PrivateAssignmentCompBase(Base):
    __table__ = make_table(schemas.PRIVATE_ASSIGNMENT_COMP_BASE_SCHEMA)


class PrivateAssignment(Base):
    __table__ = make_table(schemas.PRIVATE_ASSIGNMENT_SCHEMA)


TABLENAME_ORM_CLASS_MAP = {
    table.__table__.name: table for table in Base.__subclasses__()}
