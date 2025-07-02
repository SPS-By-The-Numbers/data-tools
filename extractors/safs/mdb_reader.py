#!python3

import csv
import fastavro
import functools
import logging
import subprocess

from . import avro_schema

logger = logging.getLogger(__name__)


class MdbReader:
    """Reads tables from accdb and mdb files and outputs an AVRO.

    This class normalizes column names and parses out mdb value weirdnesses
    into stronger AVRO types. Other than that, the output should reflect what
    is in original table.  Further semantic combining is done in later stages.
    """
    def __init__(self, filename, tablename_normalizer, header_to_schema):
        self._filename = filename
        self._tablename_normalizer = tablename_normalizer
        self._schemas = {}
        self._header_to_schema = header_to_schema

    @functools.cached_property
    def tables(self):
        """Returns a dict mapping normalized table name to table in mdb"""
        return {
            self._tablename_normalizer(line): line
            for line in self._call_mdb_tables()
        }

    def as_avro_records(self, tablename, skip_rows=0):
        raw_rows = self._read_raw_rows(tablename)

        # Skip rows if told to since some tables have weird headers.
        [raw_rows.next() for x in range(skip_rows)]

        # Parse the header.
        header = next(raw_rows)

        if tablename not in self._schemas:
            self._schemas[tablename] = self._header_to_schema(tablename,
                                                              header)

        for row in raw_rows:
            yield self._row_to_record(self._schemas[tablename],
                                      dict(zip(header, row)))

    def export_avro(self, path_prefix, tablename):
        with open(f"{path_prefix}{tablename}.avro", 'wb') as outfile:
            fastavro.writer(outfile,
                            schema=fastavro.parse_schema(
                                self._schemas[tablename]),
                            records=self.as_avro_records(),
                            codec='zstandard')

    def _row_to_record(self, schema, row):
        """Converts a dict of raw row values into an AVRO record

        row_dict maps the column name to the raw value.
        """
        record = {}
        for f in schema["fields"]:
            if f["source"] in row:
                extractor = f.get('extractor', avro_schema.cleaned_string)
                record[f['name']] = extractor(row, f['source'])
        return record

    def _call_mdb_tables(self):
        """Executes mdb-tables and returns iterable over table names."""
        proc = subprocess.Popen(['mdb-tables', '-1', self._filename],
                                stdout=subprocess.PIPE)

        while True:
            line = proc.stdout.readline().decode("utf-8").strip()
            if not line:
                break
            yield line

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
