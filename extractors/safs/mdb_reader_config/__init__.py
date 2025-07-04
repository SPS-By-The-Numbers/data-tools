class MdbReaderConfig:
    def __init__(self,
                 datatype,
                 tablename_normalizer,
                 fields_from_header,
                 additional_fields=None,
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
