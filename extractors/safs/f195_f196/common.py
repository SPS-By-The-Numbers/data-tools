import inflection
from  extractors.safs import avro_schema


def to_bigquery_colname(name):
    """Returns a column name compatible with BigQuery"""
    snake_case = inflection.underscore(name).lower()
    return snake_case.replace(' ', '_')


def to_type_extractor(name, re_str_column, re_int_column, re_decimal_column,
                      re_date_column, re_boolean_column):
    """Given a normalized column name, return schema type and extractor"""
    name_lower = name.lower()

    if re_str_column.match(name_lower):
        return {"field_type": "string", "extractor": avro_schema.passthru}
    elif re_int_column.match(name_lower):
        return {"field_type": "int", "extractor": avro_schema.to_int_or_null}
    elif re_decimal_column.match(name_lower):
        return {"field_type": "decimal",
                "extractor": avro_schema.to_decimal_or_null}
    elif re_date_column.match(name_lower):
        return {"field_type": "timestamp",
                "extractor": avro_schema.parse_datetime}
    elif re_boolean_column.match(name_lower):
        return {"field_type": "boolean", "extractor": avro_schema.passthru}
    else:
        return {"field_type": "string", "extractor": avro_schema.passthru}


def infer_field(table_name, col_name, normalize_name, re_str_column,
                re_int_column, re_decimal_column, re_date_column,
                re_boolean_column):
    """Given a table and a raw column name, generate a schema field."""
    col_name = col_name.replace('\ufeff', '').strip()
    name = normalize_name(table_name, col_name)
    type_extractor = to_type_extractor(name, re_str_column, re_int_column,
                                       re_decimal_column, re_date_column,
                                       re_boolean_column)
    return {
        'name': name,
        'source': col_name,
        'default': None,
    } | type_extractor
