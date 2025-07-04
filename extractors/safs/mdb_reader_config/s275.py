import re
import logging

from . import MdbReaderConfig
from extractors.safs import avro_schema

logger = logging.getLogger(__name__)


def _field_from_column_name(_, column_name):
    match column_name:
        case ("cou" | "dis" | "codist" | "parea" |
              "darea" | "droot" | "dsufx"):
            return avro_schema.make_field(name=column_name,
                                          field_type="int",
                                          extractor=avro_schema.to_int_or_null)

        case ("prog" | "act"):
            return avro_schema.make_field(
                name=column_name,
                field_type="int",
                extractor=avro_schema.program_activity_or_null)

        case "bldgn":
            return avro_schema.make_field(
                name=column_name,
                field_type="int",
                extractor=avro_schema.building_or_null)

        case ("asssal" | "cins" | "cman" | "certbase" | "clasbase" |
              "othersal" | "tfinsal" |
              "ftehrs" | "ftedays" | "certfte" | "clasfte" | "exp" |
              "camix1" | "asspct" | "assfte" | "asshpy" |
              "acred" | "icred" | "bcred" | "vcred"):
            return avro_schema.make_field(
                name=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_or_null)

        case "SchoolYear":
            return avro_schema.make_field(
                name="school_year",
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case ("FirstName" | "MiddleName" | "LastName"):
            return avro_schema.make_field(
                name=avro_schema.to_bigquery_colname(column_name),
                source=column_name,
                field_type="string",
                extractor=avro_schema.to_title_case)

        case _:
            return avro_schema.make_field(
                name=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)


def _fields_from_header(tablename, row):
    return [_field_from_column_name(tablename, col_name) for col_name in row]


def tablename_normalizer(tablename):
    m = re.match(r"(\d{4}-\d{4})s-?275(final|preliminary).*",
                 tablename.lower())
    logger.info(f"Reading S275 {m[2]} for {m[1]}")
    return f"s275_{m[2]}"


def get_mdb_reader_config(additional_fields):
    return MdbReaderConfig(
        datatype="s275",
        tablename_normalizer=tablename_normalizer,
        fields_from_header=_fields_from_header)
