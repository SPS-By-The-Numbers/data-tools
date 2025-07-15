class MdbReaderConfig:
    def __init__(self,
                 datatype,
                 tablename_normalizer,
                 fields_from_header,
                 add_additional_fields=None, get_additional_values=None,
                 custom_extract_header=None, row_preprocess=None):
        self._datatype = datatype
        self._tablename_normalizer = tablename_normalizer
        self._fields_from_header = fields_from_header
        self._add_additional_fields = add_additional_fields
        self._get_additional_values = get_additional_values
        self._custom_extract_header = custom_extract_header
        self._row_preprocess = row_preprocess

    @property
    def data_type(self):
        return self._datatype

    @property
    def tablename_normalizer(self):
        return self._tablename_normalizer

    @property
    def add_additional_fields(self):
        return self._add_additional_fields

    @property
    def get_additional_values(self):
        return self._get_additional_values

    @property
    def custom_extract_header(self):
        return self._custom_extract_header

    @property
    def row_preprocess(self):
        return self._row_preprocess

    def header_to_schema(self, tablename, row):
        data_fields = self._fields_from_header(tablename, row)
        sql_table_name = f"{self._datatype}_{tablename}"
        return {
            "name": sql_table_name,
            "doc": (f"{self._datatype} schema for {tablename} inferred "
                    f"from {row}"),
            "fields": [
                {
                    "name": f"{sql_table_name}_id",
                    "field_type": "auto_primary_key",
                    "doc": "(primary key)",
                },
                *data_fields
            ]
        }
