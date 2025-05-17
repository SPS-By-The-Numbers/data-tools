#!python3

import argparse
import fastavro
import logging

from . import s275_extractors

from enum import Enum
from ..common import common_logging_setup, get_args
# from .schemas import s275

logger = logging.getLogger(__name__)


class UpdateType(Enum):
    UPDATE = 1
    NO_CHANGE = 2
    NEW_IS_EMPTY = 3
    ERROR = 4


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


def employee_update(current_tuple, new_tuple):
    if current_tuple == new_tuple:
        return UpdateType.NO_CHANGE

    current = dict(current_tuple)
    new = dict(new_tuple)
    hyear_cmp = cmp_field(current_tuple, new, 'highest_degree_year')

    if hyear_cmp == -1:
        return UpdateType.NO_CHANGE
    elif hyear_cmp == 1:
        return UpdateType.UPDATE

    exp_cmp = cmp_field(current, new, 'experience_years')
    if exp_cmp == -1:
        return UpdateType.NO_CHANGE
    elif exp_cmp == 1:
        return UpdateType.UPDATE

    nb_cert_exp = cmp_field(current, new, 'nbpts_certificate_expiration')
    if nb_cert_exp == -1:
        return UpdateType.NO_CHANGE
    elif nb_cert_exp == 1:
        return UpdateType.UPDATE

    return UpdateType.NO_CHANGE


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
    def __init__(self, pk_name,
                 logical_key_extractors=None,
                 other_fields_extractors=None,
                 inferred_fields_extractors=None):
        self._rows = {}
        self._next_id = 0
        self.pk_name = pk_name
        self.logical_key_extractors = logical_key_extractors
        self.other_fields_extractors = other_fields_extractors
        self.inferred_fields_extractors = inferred_fields_extractors

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

    @property
    def inferred_fields_extractors(self):
        return self._inferred_fields_extractors

    @inferred_fields_extractors.setter
    def inferred_fields_extractors(self, value):
        self._inferred_fields_extractors = value

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
        self._s275_report_table = Table(
            's275_report_id',
            **s275_extractors.make_s275_report_extractors())

        self._employee_table = Table(
            'employee_id',
            **s275_extractors.make_employee_extractors())
        self._contract_table = Table(
            'contract_id',
            **s275_extractors.make_contract_extractors())
        self._assignment_table = Table(
            'assignment_id',
            **s275_extractors.make_assignment_extractors(
                self._s275_report_table,
                self._employee_table,
                self._contract_table))
        self._employee_data_table = Table(
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

    def merge_file(self, f):
        reader = fastavro.reader(f)
        for record in reader:
            self._s275_report_table.upsert(record)
            self._employee_table.upsert(record)
            self._contract_table.upsert(record)
            self._assignment_table.upsert(record)
            self._employee_data_table.upsert(record)
            self._private_employee_data_table.upsert(record)
            self._private_contract_table.upsert(record)
            self._private_assignment_table.upsert(record)

    def infer_data(self):
        """This is basically a beefed up reduce() call."""
        context = {}
        self._s275_report_table.infer_data(self, context)
        self._employee_table.infer_data(self, context)
        self._contract_table.infer_data(self, context)
        self._assignment_table.infer_data(self, context)
        self._employee_data_table.infer_data(self, context)
        self._private_employee_data_table.infer_data(self, context)
        self._private_contract_table.infer_data(self, context)
        self._private_assignment_table.infer_data(self, context)


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
        normalized_s275.merge_file(f)

    normalized_s275.infer_data()


if __name__ == '__main__':
    main()
