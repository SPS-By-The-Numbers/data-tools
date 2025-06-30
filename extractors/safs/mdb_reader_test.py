from decimal import Decimal
from . import mdb_reader


def fake_value_converter(column_name, value):
    if column_name == 'item':
        return value.strip()
    if column_name == 'cost':
        return Decimal(value)


def fake_normalizer(source_table):
    match source_table:
        case "table1":
            return "n1"
        case "table2":
            return "n2"
        case _:
            raise ValueError(source_table)


def test_tables(mocker):
    reader = mdb_reader.MdbReader(None, fake_normalizer, None)
    mocker.patch.object(mdb_reader.MdbReader, '_call_mdb_tables',
                        return_value=["table1", "table2"])
    assert reader.tables == {"n1": "table1", "n2": "table2"}


def test_as_avro_records(mocker):
    reader = mdb_reader.MdbReader(None, None, fake_value_converter)
    mocker.patch.object(mdb_reader.MdbReader, 'tables',
                        new_callable=mocker.PropertyMock,
                        return_value={"n1": "table1", "n2": "table2"})
    mocker.patch.object(mdb_reader.MdbReader, '_read_raw_rows',
                        return_value=iter([['item', 'cost'],
                                           ['toothbrush  ', ' 123.00'],
                                           ['  car ', '13.01  '],
                                           ]))
    assert list(reader.as_avro_records('n1')) == [
        {'item': 'toothbrush', 'cost': Decimal('123.00')},
        {'item': 'car', 'cost': Decimal('13.01')},
    ]
