def make_field(name, field_type, doc=None, default=None, primary_key=False):
    """Given a name and field_type, produces the right AVRO field definition"""
    if field_type == 'decimal':
        schema_type = [
            "null",
            {
                "logicalType": "decimal",
                "precision": 38,
                "scale": 9,
                "type": "bytes"
            }
        ]
    elif field_type == 'timestamp':
        schema_type = [
            "null",
            {
                "logicalType": "timestamp-millis",
                "type": "int"
            }
        ]
    else:
        schema_type = [
            "null",
            field_type,
        ]

    return {
        "default": None,
        "name": name,
        "type": schema_type,
        "doc": doc,
        "_orig_type": field_type
    }
