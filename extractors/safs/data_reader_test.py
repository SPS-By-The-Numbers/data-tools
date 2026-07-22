from decimal import Decimal
from . import avro_schema
from . import data_reader
from .data_reader_config import DataReaderConfig


class FakeRawReader:
    """Stands in for MdbRawReader/CsvRawReader/XlsxRawReader/AvroRawReader.

    DataReader only needs filename, read_raw_tables() and read_raw_rows().
    """
    def __init__(self, tables, rows=None, filename='fake.accdb'):
        self._tables = tables
        self._rows = rows or {}
        self.filename = filename

    def read_raw_tables(self):
        return self._tables

    def datatype(self):
        return 'faketype'

    def read_raw_rows(self, raw_tablename):
        return iter(self._rows[raw_tablename])


def fake_normalizer(source_table):
    match source_table:
        case "table1":
            return "n1"
        case "table2":
            return "n2"
        case "ignore_me":
            # None means "skip this table".
            return None
        case _:
            raise ValueError(source_table)


def fake_fields_from_header(tablename, header):
    return [
        {
            'name': 'titem',
            'source': 'item',
            'field_type': 'string'
        },
        {
            'name': 'tcost',
            'source': 'cost',
            'field_type': 'decimal',
            'extractor': avro_schema.to_decimal_or_null
        }
    ]


def make_config():
    return DataReaderConfig(
        datatype='faketype',
        tablename_normalizer=fake_normalizer,
        fields_from_header=fake_fields_from_header)


def test_tables():
    reader = data_reader.DataReader(
        FakeRawReader(tables=["table1", "ignore_me", "table2"]),
        make_config())

    assert reader.tables == {"n1": "table1", "n2": "table2"}
    assert reader.skipped_tables == ["ignore_me"]


def test_to_records():
    reader = data_reader.DataReader(
        FakeRawReader(tables=["table1", "table2"],
                      rows={"table1": [['item', 'cost'],
                                       ['toothbrush  ', ' 123.00'],
                                       ['  car ', '13.01  '],
                                       ]}),
        make_config())

    schema, records = reader.to_records('n1')

    assert schema['name'] == 'faketype_n1'
    assert [f['name'] for f in schema['fields']] == [
        'faketype_n1_id', 'titem', 'tcost', '_source_table', '_source']
    assert list(records) == [
        {'titem': 'toothbrush', 'tcost': Decimal('123.00'),
         '_source_table': 'table1', '_source': 'fake.accdb'},
        {'titem': 'car', 'tcost': Decimal('13.01'),
         '_source_table': 'table1', '_source': 'fake.accdb'},
    ]


def test_to_records_uses_null_sentinel():
    """Missing values become sentinels, not None, for the staging RDBMS."""
    reader = data_reader.DataReader(
        FakeRawReader(tables=["table1"],
                      rows={"table1": [['item', 'cost'],
                                       ['toothbrush', ''],
                                       ]}),
        make_config())

    _, records = reader.to_records('n1')

    assert list(records) == [
        {'titem': 'toothbrush',
         'tcost': avro_schema.get_null_sentinel('decimal'),
         '_source_table': 'table1', '_source': 'fake.accdb'},
    ]


def test_mdb_raw_reader_read_raw_tables(mocker):
    """mdb-tables output is read line-by-line until a blank line."""
    proc = mocker.Mock()
    proc.stdout.readline.side_effect = [b"table1\n", b"table2\n", b""]
    mocker.patch.object(data_reader.subprocess, 'Popen', return_value=proc)

    reader = data_reader.MdbRawReader('/fake/path.accdb')

    assert reader.read_raw_tables() == ["table1", "table2"]
    assert reader.filename == 'path.accdb'
