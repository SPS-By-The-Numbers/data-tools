def append_text_values(info, key, fields, keep_empty=False):
    """Adds all fields into info[key] createing key if necessary.

    if keep_empty is true, skips empty fields.
    """
    for f in fields:
        append_text_value(info, key, f, keep_empty)


def append_text_value(info, key, field, keep_empty=False):
    """Adds field to info[key] creating if necessary.

    if keep_empty is true, skips empty fields.
    """
    if key not in info:
        info[key] = []

    if keep_empty or len(field):
        info[key].append(field)
