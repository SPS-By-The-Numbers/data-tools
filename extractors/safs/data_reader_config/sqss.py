import logging

from extractors.safs import avro_schema

from . import ospi

logger = logging.getLogger(__name__)


def _field_from_column_name(_, column_name):
    retval = ospi.field_from_common_column_name(column_name)
    if retval is not None:
        return retval

    match column_name:
        case ('measure' |
              'measures'
              ):
            return avro_schema.make_field(
                name='measure',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'label':
            return avro_schema.make_field(
                name=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'percent':
            return avro_schema.make_field(
                name=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case 'numerator':
            return avro_schema.make_field(
                name=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        case 'denominator':
            return avro_schema.make_field(
                name=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        case ('apcoursenumber' |
              'numbertakingap'
              ):
            return avro_schema.make_field(
                name='num_taking_ap',
                source=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        case ('ibcoursenumber' |
              'numbertakingib'
              ):
            return avro_schema.make_field(
                name='num_taking_ib',
                source=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        case ('cihscoursenumber' |
              'numbertakingcollegeinthe'
              ):
            return avro_schema.make_field(
                name='num_taking_cihs',
                source=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        case ('cambridgecoursenumber' |
              'numbertakingcambridge'
              ):
            return avro_schema.make_field(
                name='num_taking_cambridge',
                source=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        case ('ctecoursenumber' |
              'numbertakingctetechprep'
              ):
            return avro_schema.make_field(
                name='num_taking_cte',
                source=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        case ('runningstartcoursenumber' |
              'numbertakingrunningstart'
              ):
            return avro_schema.make_field(
                name='num_taking_runningstart',
                source=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        case ('apcoursepercent' |
              'percenttakingap'
              ):
            return avro_schema.make_field(
                name='pct_taking_ap',
                source=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case ('ibcoursepercent' |
              'percenttakingib'
              ):
            return avro_schema.make_field(
                name='pct_taking_ib',
                source=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case ('cihscoursepercent' |
              'percenttakingcollegeinth'):
            return avro_schema.make_field(
                name='pct_taking_cihs',
                source=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case ('cambridgecoursepercent' |
              'percenttakingcambridge'
              ):
            return avro_schema.make_field(
                name='pct_taking_cambridge',
                source=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case ('ctecoursepercent' |
              'percenttakingctetechprep'
              ):
            return avro_schema.make_field(
                name='pct_taking_cte',
                source=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case ('runningstartcoursepercent' |
              'percenttakingrunningstart'
              ):
            return avro_schema.make_field(
                name='pct_taking_runningstart',
                source=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case _:
            raise Exception("Unexpected field %s" % column_name)


def get_reader_config(add_additional_fields, get_additional_values):
    return ospi.common_reader_config("sqss",
                                     _field_from_column_name,
                                     add_additional_fields,
                                     get_additional_values)
