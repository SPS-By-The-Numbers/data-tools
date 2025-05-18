#!python3

import argparse
import fastavro
import logging

from . import s275_extractors

from enum import Enum
from decimal import Decimal
from pathlib import Path
from ..common import common_logging_setup, get_args
from .schemas import s275

logger = logging.getLogger(__name__)


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


def verify_same(current, new):
    if current == new:
        return UpdateType.NO_CHANGE

    return UpdateType.ERROR


def verify_same_ignore_empty(current, new):
    if current == new:
        return UpdateType.NO_CHANGE

    if has_value(current):
        if has_value(new):
            return UpdateType.ERROR
        else:
            return UpdateType.NEW_IS_EMPTY

    return UpdateType.UPDATE


class Table:
    __slots__ = ('_rows', '_next_id', '_pk_name', '_logical_key_extractors',
                 '_other_fields_extractors')

    def __init__(self, pk_name,
                 logical_key_extractors=None,
                 other_fields_extractors=None):
        self._rows = {}
        self._next_id = 0
        self.pk_name = pk_name
        self.logical_key_extractors = logical_key_extractors
        self.other_fields_extractors = other_fields_extractors

    def __iter__(self):
        for row in self._rows.items():
            yield row

    @property
    def rows(self):
        return self._rows

    @property
    def pk_name(self):
        return self._pk_name

    @pk_name.setter
    def pk_name(self, value):
        self._pk_name = value

    @property
    def logical_key_extractors(self):
        return self._logical_key_extractors

    @logical_key_extractors.setter
    def logical_key_extractors(self, value):
        self._logical_key_extractors = value

    @property
    def other_fields_extractors(self):
        return self._other_fields_extractors

    @other_fields_extractors.setter
    def other_fields_extractors(self, value):
        self._other_fields_extractors = value

    def find(self, record):
        """Returns the row in that matches fields in `record`.

        Returns None if row does not exist.
        """
        logical_key_tuple, _ = self._extract_row_from_record(record)
        if logical_key_tuple in self._rows:
            return self._rows[logical_key_tuple]

        return None

    def find_id(self, record, _):
        """Returns the primary key for the row that matches fields in `record`.

        Returns None if row does not exist.
        """
        logical_key_tuple, _ = self._extract_row_from_record(record)
        if logical_key_tuple in self._rows:
            return self._rows[logical_key_tuple]['id']

        return None

    def upsert(self, record, update_disposition=verify_same):
        logical_key_tuple, other_fields_tuple = self._extract_row_from_record(
            record)

        if logical_key_tuple in self._rows:
            # Update
            current = self._rows[logical_key_tuple]
            update_type = update_disposition(current['fields'],
                                             other_fields_tuple)
            match update_type:
                case UpdateType.ERROR:
                    logger.warning(f"Update failed for {logical_key_tuple}\n"
                                   f"\tfrom\n\t{current} to\n"
                                   f"\t{record}.\n\n"
                                   f"Specifically from \n"
                                   f"\t{current['fields']} to\n"
                                   f"\t{other_fields_tuple}")

                case UpdateType.UPDATE:
                    current['fields'] = other_fields_tuple

                case UpdateType.NO_CHANGE:
                    pass

                case UpdateType.NEW_IS_EMPTY:
                    pass

            return current['id']

        # New item
        new_id = self._next_id
        self._next_id = self._next_id + 1

        self._rows[logical_key_tuple] = {
            'id': new_id,
            'fields': other_fields_tuple
        }
        return new_id

    def _extract_row_from_record(self, record):
        """Take a record and extracts a row from the fields"""
        logical_key_builder = []
        other_fields_builder = []

        for extractor in self.logical_key_extractors:
            logical_key_builder.append(extractor.extract(record))

        if self.other_fields_extractors:
            for extractor in self.other_fields_extractors:
                other_fields_builder.append(extractor.extract(record))

        return tuple(logical_key_builder), tuple(other_fields_builder)


class NormalizedS275:
    def __init__(self):
        # Key is _assignment_table id. Is a 1:1 mapping.
        self._calculated_assignment_compensation = {}

        # Tables for holding data read from the avro files.
        self._s275_report_table = Table(
            's275_report_id',
            **s275_extractors.make_s275_report_extractors())
        self._employee_table = Table(
            'employee_id',
            **s275_extractors.make_employee_extractors())
        self._employee_calculated_table = Table(
            'employee_calculated_id',
            **s275_extractors.make_employee_calculated_extractors(
                self._employee_table))
        self._contract_table = Table(
            'contract_id',
            **s275_extractors.make_contract_extractors())
        self._assignment_table = Table(
            'assignment_id',
            **s275_extractors.make_assignment_extractors(
                self._s275_report_table,
                self._employee_table,
                self._contract_table))
        self._s275_report_employee_table = Table(
            's275_report_employee_id',
            **s275_extractors.make_s275_report_employee_extractors(
                self._s275_report_table,
                self._employee_table))

        self._private_employee_data_table = Table(
            'private_employee_data_id',
            **s275_extractors.make_private_employee_data_extractors(
                self._s275_report_table,
                self._employee_table))
        self._private_contract_table = Table(
            'private_contract_id',
            **s275_extractors.make_private_contract_extractors(
                self._contract_table))
        self._private_assignment_table = Table(
            'private_assignment_id',
            **s275_extractors.make_private_assignment_extractors(
                self._assignment_table,
                self._private_contract_table))

    def merge(self, f):
        reader = fastavro.reader(f)
        assignment_accumulators = {}
        for record in reader:
            self._s275_report_table.upsert(record)
            self._employee_table.upsert(record)
            self._employee_calculated_table.upsert(
                record,
                update_disposition=employee_update)
            self._contract_table.upsert(record)
            self._assignment_table.upsert(record)
            s275_employee_id = self._s275_report_employee_table.upsert(record)
            self._private_employee_data_table.upsert(record)
            self._private_contract_table.upsert(record)
            assignment_id = self._private_assignment_table.upsert(record)

            # Find accumulator for assignments
            if s275_employee_id in assignment_accumulators:
                accumulator = assignment_accumulators[s275_employee_id]
            else:
                accumulator = assignment_accumulators[s275_employee_id] = {
                    'total_assignment_salary': Decimal('0'),
                    'assignment_entries': []
                }

            # Accumulate the total assignment salary for a record.
            assignment_salary = get_decimal(record, 'asssal')
            accumulator['assignment_entries'].append({
                'assignment_id': assignment_id,
                'assignment_salary': assignment_salary,
                'benefits': get_decimal(record, 'cman'),
                'insurance': get_decimal(record, 'cins'),
                'other_salary': get_decimal(record, 'othersal'),
                'total_final_salary': get_decimal(record, 'tfinsal'),
            })
            accumulator['total_assignment_salary'] += assignment_salary

        # Fill in the assignment salary table.
        for _, accumulator in assignment_accumulators.items():
            total_assignment_salary = accumulator['total_assignment_salary']
            for entry in accumulator['assignment_entries']:
                assignment_percent = safe_div(entry['assignment_salary'],
                                              total_assignment_salary)
                assignment_other_salary = (entry['other_salary'] *
                                           assignment_percent)
                assignment_insurance = (entry['insurance'] *
                                        assignment_percent)
                assignment_benefits = (entry['benefits'] * assignment_percent)
                value = {
                    "c_assignment_salary_percentage": assignment_percent,
                    "c_assignment_other_salary": assignment_other_salary,
                    "c_assignment_insurance": assignment_insurance,
                    "c_assignment_benefits": assignment_benefits,
                    "c_assignment_total_compensation": (
                        assignment_salary +
                        assignment_other_salary +
                        assignment_insurance +
                        assignment_benefits
                    ),
                }

                self._calculated_assignment_compensation[
                    entry['assignment_id']] = value

    def write_table(self, outdir, schema, table, calculated_fields):
        with open(outdir / f"{schema['name']}.avro", "wb") as outfile:
            fastavro.writer(outfile,
                            fastavro.parse_schema(schema),
                            table)

    def write_all_tables(self, outdir_str):
        outdir = Path(outdir_str)
        self.write_all_tables(
            path=(outdir / 'employee'),
            table=self._employee_table,
            schema=s275.EMPLOYEE_SCHEMA,
            calculated_fields=[self._employee_calculated_table])


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
    for f in args.infiles:
        normalized_s275.merge(f)

    normalized_s275.write_all_tables(args.outdir)


if __name__ == '__main__':
    main()
