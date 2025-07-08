from sqlalchemy.orm import DeclarativeBase

from ..orm import make_table
from . import schemas


###
# ORM Classes below
#

class Base(DeclarativeBase):
    pass


class Report(Base):
    __table__ = make_table(schemas.REPORT_SCHEMA, Base)


class Employee(Base):
    __table__ = make_table(schemas.EMPLOYEE_SCHEMA, Base)


class PrivateEmployee(Base):
    __table__ = make_table(schemas.PRIVATE_EMPLOYEE_SCHEMA, Base)


class ReportEmployee(Base):
    __table__ = make_table(schemas.REPORT_EMPLOYEE_SCHEMA, Base)


class PrivateReportEmployee(Base):
    __table__ = make_table(schemas.PRIVATE_REPORT_EMPLOYEE_SCHEMA, Base)


class Assignment(Base):
    __table__ = make_table(schemas.ASSIGNMENT_SCHEMA, Base)


class AssignmentFte(Base):
    __table__ = make_table(schemas.ASSIGNMENT_FTE_SCHEMA, Base)


class PrivateAssignmentCompBase(Base):
    __table__ = make_table(schemas.PRIVATE_ASSIGNMENT_COMP_BASE_SCHEMA, Base)


class PrivateAssignment(Base):
    __table__ = make_table(schemas.PRIVATE_ASSIGNMENT_SCHEMA, Base)


TABLENAME_ORM_CLASS_MAP = {
    table.__table__.name: table for table in Base.__subclasses__()}
