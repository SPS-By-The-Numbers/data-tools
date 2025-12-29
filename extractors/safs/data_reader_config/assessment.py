import logging

from extractors.safs import avro_schema

from . import DataReaderConfig

logger = logging.getLogger(__name__)


def _field_from_column_name(_, column_name):
    match column_name:
        case 'schoolorganizationid':
            return avro_schema.make_field(source=column_name,
                                          name="school_organization_id",
                                          field_type="int",
                                          extractor=avro_schema.to_int_or_null)

        case 'districtorganizationid':
            return avro_schema.make_field(source=column_name,
                                          name="district_organization_id",
                                          field_type="int",
                                          extractor=avro_schema.to_int_or_null)

        case 'esdorganizationid':
            return avro_schema.make_field(source=column_name,
                                          name="esd_organization_id",
                                          field_type="int",
                                          extractor=avro_schema.to_int_or_null)

        case 'esdname':
            return avro_schema.make_field(
                name='esd',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'districtcode':
            return avro_schema.make_field(source=column_name,
                                          name="district_code",
                                          field_type="int",
                                          extractor=avro_schema.to_int_or_null)

        case 'districtname':
            return avro_schema.make_field(
                name='district_name',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'organizationlevel':
            return avro_schema.make_field(
                name='organization_level',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'currentschooltype':
            return avro_schema.make_field(
                name='current_school_type',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'county':
            return avro_schema.make_field(
                name=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'schoolname':
            return avro_schema.make_field(
                name='school_name',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'schoolcode':
            return avro_schema.make_field(
                name='school_code',
                source=column_name,
                field_type="int",
                extractor=avro_schema.to_int_or_null)

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

        case 'gradelevel':
            return avro_schema.make_field(
                name='grade_level',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'studentgroup':
            return avro_schema.make_field(
                name='student_group',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'studentgrouptype':
            return avro_schema.make_field(
                name='student_group_type',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'schoolyear':
            return avro_schema.make_field(
                name='school_year',
                source=column_name,
                field_type="string",
                extractor=avro_schema.expand_school_year)

        case ('dat' |
              'suppression'
              ):
            return avro_schema.make_field(
                name='dat',
                source=column_name,
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

        case '__id':
            return avro_schema.make_field(
                name=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'dataasof':
            return avro_schema.make_field(
                name=column_name,
                field_type="timestamp",
                extractor=avro_schema.parse_datetime)

        case _:
            raise Exception("Unexpected field %s" % column_name)


def _fields_from_header(tablename, row):
    fields = [_field_from_column_name(tablename, col_name) for col_name in row]
    return [f for f in fields if f is not None]


def get_reader_config(add_additional_fields, get_additional_values):
    return DataReaderConfig(
        datatype="assessment",
        tablename_normalizer=lambda x: x,
        fields_from_header=_fields_from_header,
        add_additional_fields=add_additional_fields,
        get_additional_values=get_additional_values)
