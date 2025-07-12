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

    additional_fields has additional columns to be added to the output. They
    should usually be prefixed with an underscore to avoid collision. Example
    additional_fields = [
        {
          'name': '_source',
          'doc': 'originating file',
          'field_type': 'string',
          'value': 'abc123'
        },
        {
          'name': '_school_year',
          'doc': 'school year for dataset',
          'field_type': 'string',
          'value': '2013-2014'
        },
    ]
    """
    def __init__(self, filename, config):
        self._filename = filename
        self._config = config

    @property
    def config(self):
        return self._config

    @functools.cached_property
    def tables(self):
        """Returns a dict mapping normalized table name to table in mdb"""
        raw_entries = [(self.config.tablename_normalizer(t), t)
                       for t in MdbReader.call_mdb_tables(self._filename)]
        return {k: v for k, v in raw_entries if k is not None}

    def to_records(self, tablename):
        raw_rows = self._read_raw_rows(tablename)

        if self.config.row_preprocess is not None:
            raw_rows = self.config.row_preprocess(tablename, raw_rows)

        # Parse the header.
        if self.config.custom_extract_header is None:
            header = next(raw_rows)
        else:
            header = self.config.custom_extract_header(tablename, raw_rows)

        schema = self.config.header_to_schema(tablename, header)
        source_tablename = self.tables[tablename]
        schema['fields'].append(
            {
                'name': '_source_table',
                'source': '_source_table',
                'doc': 'Original table name',
                'field_type': 'string',
            }
        )

        if self.config.add_additional_fields is not None:
            self.config.add_additional_fields(schema)

        def record_generator():
            for row in raw_rows:
                value_dict = dict(zip(header, row))
                value_dict.update({'_source_table': source_tablename})
                if self.config.get_additional_values is not None:
                    additional_values = self.config.get_additional_values(
                        schema,
                        tablename,
                        self.tables)
                    value_dict.update(additional_values)
                yield self._row_to_record(schema, value_dict)
        return schema, record_generator()

    def export_avro(self, outdir, outprefix, tablename):
        """Writes the tablename into a file in outdir

        Args:
            outdir is a path
            tablename is a key from self.table
        """
        outpath = outdir / f"{outprefix}{tablename}.avro"

        schema, record_generator = self.to_records(tablename)

        with outpath.open(mode='wb') as outfile:
            fastavro.writer(outfile,
                            schema=fastavro.parse_schema(
                                avro_schema.to_avro_schema(schema)),
                            records=record_generator,
                            codec='zstandard')

    def _row_to_record(self, schema, row):
        """Converts a dict of raw row values into an AVRO record

        row_dict maps the column name to the raw value.
        """
        record = {}
        for f in schema["fields"]:
            source = f.get("source", None)
            if source is None:
                continue
            if source in row:
                extractor = f.get('extractor', avro_schema.cleaned_string)
                try:
                    record[f['name']] = extractor(row, f['source'])
                except Exception:
                    logger.error(f"Failed {f['name']} from {f['source']} in "
                                 f"row {row}")
                    raise
        return record

    @staticmethod
    def call_mdb_tables(filename):
        """Executes mdb-tables and returns iterable over table names."""
        proc = subprocess.Popen(['mdb-tables', '-1', filename],
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
