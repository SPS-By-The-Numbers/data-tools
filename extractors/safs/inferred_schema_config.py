from . import avro_schema


class MdbReaderConfig:
    def __init__(self, datatype, tablename_normalizer,
                 fields_from_header, additional_fields=None,
                 custom_extract_header=None, row_preprocess=None):
        self._datatype = datatype
        self._tablename_normalizer = tablename_normalizer
        self._fields_from_header = fields_from_header
        self._additional_fields = additional_fields
        self._custom_extract_header = custom_extract_header
        self._row_preprocess = row_preprocess

    @property
    def data_type(self):
        return self._datatype

    @property
    def tablename_normalizer(self):
        return self._tablename_normalizer

    @property
    def additional_fields(self):
        return self._additional_fields

    @property
    def custom_extract_header(self):
        return self._custom_extract_header

    @property
    def row_preprocess(self):
        return self._row_preprocess

    def header_to_schema(self, tablename, row):
        data_fields = self._fields_from_header(tablename, row)
        return {
            "name": self._datatype,
            "doc": (f"{self._datatype} schema for {tablename} inferred "
                    f"from {row}"),
            "fields": data_fields
        }


class InferredMdbReaderBuilder:
    """Makes a MdbReader that will infers the avro schema by column name"""
    def __init__(self, datatype, tablename_normalizer, normalize_column_name,
                 re_str_column, re_int_column, re_decimal_column,
                 re_date_column, re_boolean_column, additional_fields=None,
                 custom_extract_header=None, row_preprocess=None):

        self._normalize_column_name = normalize_column_name
        self._re_str_column = re_str_column
        self._re_int_column = re_int_column
        self._re_decimal_column = re_decimal_column
        self._re_date_column = re_date_column
        self._re_boolean_column = re_boolean_column

        self._mdb_reader_config = MdbReaderConfig(
            datatype, tablename_normalizer, normalize_column_name,
            self._fields_from_header, additional_fields, custom_extract_header,
            row_preprocess)

    @property
    def mdb_reader_config(self):
        return self._mdb_reader_config

    def _fields_from_header(self, tablename, row):
        return [self._infer_field(tablename, col_name) for col_name in row]

    def _infer_field(self, table_name, col_name):
        """Given a table and a raw column name, generate a schema field."""
        col_name = col_name.replace('\ufeff', '').strip()
        name = self._normalize_column_name(table_name, col_name)
        type_extractor = self._field_type_and_extractor(name)
        return avro_schema.make_field(
            name=name,
            source=col_name,
            **type_extractor)

    def _field_type_and_extractor(self, name):
        """Given a normalized column name, return schema type and extractor"""
        name_lower = name.lower()

        if self._re_str_column.match(name_lower):
            return {"field_type": "string",
                    "extractor": avro_schema.cleaned_string}
        elif self._re_int_column.match(name_lower):
            return {"field_type": "int",
                    "extractor": avro_schema.to_int_or_null}
        elif self._re_decimal_column.match(name_lower):
            return {"field_type": "decimal",
                    "extractor": avro_schema.to_decimal_or_null}
        elif self._re_date_column.match(name_lower):
            return {"field_type": "timestamp",
                    "extractor": avro_schema.parse_datetime}
        elif self._re_boolean_column.match(name_lower):
            return {"field_type": "boolean",
                    "extractor": avro_schema.to_boolean_or_null}
        else:
            return {"field_type": "string",
                    "extractor": avro_schema.cleaned_string}
