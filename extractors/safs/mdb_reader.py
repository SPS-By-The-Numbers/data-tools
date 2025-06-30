#!python3

import csv
import fastavro
import logging
import subprocess

import functools

logger = logging.getLogger(__name__)


class MdbReader:
    """Reads tables from accdb and mdb files and outputs an AVRO.

    This class normalizes column names and parses out mdb value weirdnesses
    into stronger AVRO types. Other than that, the output should reflect what
    is in original table.  Further semantic combining is done in later stages.
    """
    def __init__(self, filename, tablename_normalizer, value_coverter):
        self._firename = filename
        self._tablename_normalizer = tablename_normalizer
        self._value_coverter = value_coverter

    @functools.cached_property
    def tables(self):
        """Returns a dict mapping normalized table name to table in mdb"""
        return {
            self._tablename_normalizer(line): line
            for line in self._call_mdb_tables()
        }

    def as_avro_records(self, tablename, skip_rows=0):
        raw_rows = self._read_raw_rows()

        # Skip rows if told to since some tables have weird headers.
        [raw_rows.next() for x in range(skip_rows)]

        # Parse the header.
        header = next(raw_rows)

        for row in raw_rows:
            yield self._row_to_record(zip(header, row))

    def export_avro(self, path_prefix, tablename):
        with open(f"{path_prefix}{tablename}.avro", 'wb') as outfile:
            fastavro.writer(outfile,
                            schema=fastavro.parse_schema(self._schema),
                            records=self.as_avro_records(),
                            codec='zstandard')


    def _row_to_record(self, header_row_zip):
        """Converts a dict of raw row values into an AVRO record

        row_dict maps the column name to the raw value.
        """
        return {k : self._value_coverter(k, v) for k, v in header_row_zip}

    def _call_mdb_tables(self):
        """Executes mdb-tables and returns iterable over table names."""
        proc = subprocess.Popen(['mdb-tables', '-1', self._filename],
                                stdout=subprocess.PIPE)

        while True:
            yield  proc.stdout.readline().decode("utf-8").strip()
            if not line:
                break

    def _read_raw_rows(self, tablename):
        """Loads each row from the mdb list of values.

        The header is not distinguished here. It is literally reading all rows.
        Calling code has to interpret what the header is.
        """
        source_table = self.tables[tablename]
        proc = subprocess.Popen(
            ['mdb-export', '-B', self._filename, source_table],
            stdout=subprocess.PIPE, universal_newlines=True)

        for row in csv.reader(proc.stdout):
            yield row



def f195_tablename_normalizer(source_tablename):  # noqa: C901
    if 'ITEMDIC' in source_tablename:
        return "item_dict"
    elif 'ACTIVITY' in source_tablename:
        return "activity"
    elif 'CCDDD' in source_tablename:
        return "ccddd"
    elif 'COUNTY' in source_tablename:
        return "county"
    elif 'FUND' in source_tablename:
        return "fund"
    elif 'OBJECT' in source_tablename:
        return "object"
    elif 'PROGRAM' in source_tablename:
        return "program"
    elif 'REVENUE' in source_tablename:
        return "revenue"
    elif ('CapitalProjectRevenues' in source_tablename
          or 'CapitalRevenues' in source_tablename):
        return "capital_project_revenues"
    elif 'DebtServiceRevenues' in source_tablename:
        return "debt_service_revenues"
    elif 'GeneralFundExpenditures' in source_tablename:
        return "general_fund_expenditures"
    elif 'GeneralFundRevenues' in source_tablename:
        return "general_fund_revenues"
    elif 'TransVehicleRevenues' in source_tablename:
        return "trans_vehicle_revenues"
    elif 'ItemNumbers' in source_tablename:
        return "item_numbers"
    elif 'All Districts' in source_tablename:
        return "all_districts"
    else:
        logger.error(f"!!! Unexpected Table {source_tablename}")
        return None
