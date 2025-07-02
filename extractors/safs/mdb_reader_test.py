from decimal import Decimal
from . import avro_schema
from . import mdb_reader


def fake_normalizer(source_table):
    match source_table:
        case "table1":
            return "n1"
        case "table2":
            return "n2"
        case _:
            raise ValueError(source_table)


def fake_header_to_schema(tablename, header):
    return {
        'name': 'fakey',
        'fields': [
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
    }


def test_tables(mocker):
    reader = mdb_reader.MdbReader(filename=None,
                                  tablename_normalizer=fake_normalizer,
                                  header_to_schema=None)
    mocker.patch.object(mdb_reader.MdbReader, '_call_mdb_tables',
                        return_value=["table1", "table2"])
    assert reader.tables == {"n1": "table1", "n2": "table2"}


def test_as_avro_records(mocker):
    reader = mdb_reader.MdbReader(filename=None,
                                  tablename_normalizer=fake_normalizer,
                                  header_to_schema=fake_header_to_schema)
    mocker.patch.object(mdb_reader.MdbReader, 'tables',
                        new_callable=mocker.PropertyMock,
                        return_value={"n1": "table1", "n2": "table2"})
    mocker.patch.object(mdb_reader.MdbReader, '_read_raw_rows',
                        return_value=iter([['item', 'cost'],
                                           ['toothbrush  ', ' 123.00'],
                                           ['  car ', '13.01  '],
                                           ]))
    assert list(reader.as_avro_records('n1')) == [
        {'titem': 'toothbrush', 'tcost': Decimal('123.00')},
        {'titem': 'car', 'tcost': Decimal('13.01')},
    ]
