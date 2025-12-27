#!python3

import csv
import fastavro
import functools
import logging
import pandas as pd
import re
import subprocess

from pathlib import Path
from . import avro_schema

logger = logging.getLogger(__name__)


def _strip_str_only(val):
    if isinstance(val, str):
        return val.strip()
    return val


def _parse_structured_csv_filename(filename):
    """Parses 2021-2022-f196-table_name.csv to (2021-2022, f196, table_name)"""
    m = re.match(r"^(\d{4}-\d{4})-([^-]*)-(.*).csv$", filename)
    if m is None:
        raise ValueError(f"Invalid {filename}")

    return (m[1], m[2], m[3])


class XlsxRawReader:
    def __init__(self, filepath):
        self._filepath = filepath

        m = re.match(r"^(\d{4}-\d{4})-(.*).xlsx$", self.filename)
        if m is None:
            raise ValueError(f"Invalid {filepath}")
        self._school_year = m[1]
        self._datatype = m[2]
        self._filepath = filepath
        self._drop_empty_columns = True

    @property
    def filename(self):
        return Path(self._filepath).name

    def disable_drop_empty_columns(self):
        """By default, reader drops columns with empty value in first row.

        This assumes the first row is a header and is just a convenience for
        many formats. Disable if it doesn't help
        """
        self._drop_empty_columns = False

    def read_raw_tables(self):
        return {v: v for v in pd.ExcelFile(self._filepath).sheet_names}

    def datatype(self):
        return self._datatype

    def read_raw_rows(self, raw_tablename):
        # Don't parse the first row as that is manually processed later.
        df = pd.read_excel(self._filepath, sheet_name=raw_tablename,
                           header=None)

        # Remove all the random blank rows folks put in.
        df = df.dropna(how='all')

        if self._drop_empty_columns:
            # Assume the first row is the header.
            columns_to_drop = []
            for index, header_value in df.iloc[0].items():
                if not isinstance(header_value, str):
                    columns_to_drop.append(index)

            if len(columns_to_drop) > 0:
                df = df.drop(columns=columns_to_drop)
                logger.info(f"Dropping columns: {columns_to_drop}. Left over "
                            "are {df.columns}")

        for row in df.values:
            yield [_strip_str_only(v) for v in row]


class CsvRawReader:
    def __init__(self, filepath):
        self._filepath = filepath
        x = _parse_structured_csv_filename(self.filename)
        self._datatype = x[1]
        self._tablename = x[2]

    @property
    def filename(self):
        return Path(self._filepath).name

    def read_raw_tables(self):
        return [self._tablename]

    def datatype(self):
        return self._datatype

    def read_raw_rows(self, raw_tablename):
        if raw_tablename != self._tablename:
            raise ValueError(raw_tablename)

        with open(self._filepath, newline='') as f:
            for row in csv.reader(f):
                yield row


class MdbRawReader:
    def __init__(self, filepath):
        self._filepath = filepath

    @property
    def filename(self):
        return Path(self._filepath).name

    def read_raw_tables(self):
        """Executes mdb-tables and returns iterable over table names."""
        proc = subprocess.Popen(['mdb-tables', '-1', self._filepath],
                                stdout=subprocess.PIPE)

        lines = []
        while True:
            line = proc.stdout.readline().decode("utf-8").strip()
            if not line:
                break
            lines.append(line)
        return lines

    def datatype(self):
        for source_tablename in self.read_raw_tables():
            if 'BudgetGeneralFund' in source_tablename:
                return 'f195'
            if 'ActualsGeneralFund' in source_tablename:
                return 'f196'
            if 'S275' in source_tablename or 'S-275' in source_tablename:
                return 's275'

        raise ValueError(f"Unable to infer datatype of {self._filepath}")

    def read_raw_rows(self, raw_tablename):
        """Loads each row from the mdb list of values.

        The header is not distinguished here. It is literally reading all rows.
        Calling code has to interpret what the header is.
        """
        proc = subprocess.Popen(
            ['mdb-export', '-B', self._filepath, raw_tablename],
            stdout=subprocess.PIPE, universal_newlines=True)

        for row in csv.reader(proc.stdout):
            yield row


class AvroRawReader:
    def __init__(self, filepath):
        self._filepath = filepath
        m = re.match(r"^(\d{4}-\d{4})-(.*).avro$", self.filename)
        if m is None:
            raise ValueError(f"Invalid {filepath}")
        self._datatype = m[2]

    @property
    def filename(self):
        return Path(self._filepath).name

    def read_raw_tables(self):
        return ['odata']

    def datatype(self):
        return self._datatype

    def read_raw_rows(self, raw_tablename):
        if raw_tablename != 'odata':
            raise ValueError(raw_tablename)

        with open(self._filepath, 'rb') as f:
            avro_reader = fastavro.reader(f)
            # Make this look like a csv.
            header = [f["name"] for f in avro_reader.writer_schema["fields"]]
            yield header
            for record in avro_reader:
                yield [record[column] for column in header]


class DataReader:
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
          'name': 'school_year',
          'doc': 'school year for dataset',
          'field_type': 'string',
          'value': '2013-2014'
        },
    ]
    """
    def __init__(self, reader, config):
        self._config = config
        self._reader = reader

    @property
    def config(self):
        return self._config

    @functools.cached_property
    def tables(self):
        """Returns a dict mapping normalized table name to table in mdb"""
        return {k: v for k, v in self._normlized_and_skipped_tables
                if k is not None}

    @functools.cached_property
    def skipped_tables(self):
        """Returns a dict mapping normalized table name to table in mdb"""
        return [v for k, v in self._normlized_and_skipped_tables
                if k is None]

    @functools.cached_property
    def _normlized_and_skipped_tables(self):
        """Returns a dict mapping normalized table name to table in mdb"""
        return [(self.config.tablename_normalizer(t), t)
                for t in self._reader.read_raw_tables()]

    def to_records(self, tablename):
        source_table = self.tables[tablename]
        raw_rows = self._reader.read_raw_rows(source_table)
        if self.config.row_preprocess is not None:
            raw_rows = self.config.row_preprocess(tablename, raw_rows)

        # Parse the header.
        if self.config.custom_extract_header is None:
            header = next(raw_rows)
        else:
            header = self.config.custom_extract_header(tablename, raw_rows)

        schema = self.config.header_to_schema(tablename, header)
        schema['fields'].extend(
            [
                {
                    'name': '_source_table',
                    'source': '_source_table',
                    'doc': 'Original table name',
                    'field_type': 'string',
                },
                {
                    "name": "_source",
                    "source": "_source",
                    "doc": "Source file for data",
                    "field_type": "string",
                }
            ]
        )

        if self.config.add_additional_fields is not None:
            self.config.add_additional_fields(schema)

        def record_generator():
            for row in raw_rows:
                value_dict = dict(zip(header, row))
                value_dict.update({
                    '_source_table': source_table,
                    '_source': self._reader.filename,
                })
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
                    value = extractor(row, f['source'])
                    if value is None:
                        value = avro_schema.get_null_sentinel(f['field_type'])
                    record[f['name']] = value
                except Exception:
                    logger.error(f"Failed {f['name']} from {f['source']} in "
                                 f"row {row}")
                    raise
        return record
