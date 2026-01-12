import logging

from extractors.safs import avro_schema

from . import ospi

logger = logging.getLogger(__name__)


def _field_from_column_name(_, column_name):
    retval = ospi.field_from_common_column_name(column_name)
    if retval is not None:
        return retval

    match column_name:
        case 'testsubject':
            return avro_schema.make_field(
                name='test_subject',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'testadministration':
            return avro_schema.make_field(
                name='test_administration',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'test_administration_group':
            return avro_schema.make_field(
                name=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'count_foundational_grade':
            return avro_schema.make_field(
                name=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        # Skipping
        # TODO: Fix this. It'sin later scheumas 2022-2023
        case ('percent_consistent_tested' |
              'percent_consistent_tested_only'
              ):
            return None

        case ('percent_participation' |
              'percentparticipation'
              ):
            return avro_schema.make_field(
                name='percent_participation',
                source=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case ('percent_no_score' |
              'percentnoscore'
              ):
            return avro_schema.make_field(
                name='percent_no_score',
                source=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case ('count_consistent_grade_level' |
              'count_consistent_grade_level_knowledge_and_above' |
              'countmetstandard'
              ):
            return avro_schema.make_field(
                name='count_consistent_grade',
                source=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        case ('percentmetstandard' |
              'percent_consistent_grade_level_knowledge_and_above' |
              'percent_consistent_grade'
              ):
            return avro_schema.make_field(
                name='percent_consistent_grade',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case ('percent_met_tested_only' |
              'percentmettestedonly'
              ):
            return None

        case ('percent_taking_alternative' |
              'percent_taking_alternative_assessment'
              ):
            return avro_schema.make_field(
                source='percent_taking_alternative',
                name=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case 'percent_foundational_grade':
            return avro_schema.make_field(
                name=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'count_of_students_expected':
            return avro_schema.make_field(
                name='count_of_students_expected_excl_prior',
                source=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        case ('count_of_students_expected_1' |
              ('count_of_students_expected_to_test_'
               'including_previously_passed')
              ):
            return avro_schema.make_field(
                name='count_of_students_expected_incl_prior',
                source=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

        case ('percentlevel1' |
              'percentlevel2' |
              'percentlevel3' |
              'percentlevel4'
              ):
            return avro_schema.make_field(
                name=('percent_level_%s' % column_name[-1]),
                source=column_name,
                field_type="decimal",
                extractor=avro_schema.to_decimal_from_floatstr_or_null)

        case _:
            raise Exception("Unexpected field %s" % column_name)


def get_reader_config(add_additional_fields, get_additional_values):
    return ospi.common_reader_config("assessment",
                                     _field_from_column_name,
                                     add_additional_fields,
                                     get_additional_values)
