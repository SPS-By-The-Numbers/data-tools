from extractors.safs import avro_schema
from . import DataReaderConfig


def field_from_common_column_name(column_name):
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

        case 'organizationname':
            return avro_schema.make_field(
                name='organization_name',
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

        case 'gradelevel':
            return avro_schema.make_field(
                name='grade_level',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case ('dat' |
              'suppression' |
              'dat_reason' |
              'datreason'
              ):
            return avro_schema.make_field(
                name='dat',
                source=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

        case 'dataasof':
            return avro_schema.make_field(
                name=column_name,
                field_type="timestamp",
                extractor=avro_schema.parse_datetime)

        case '__id':
            # Internal ID used by odata. Not super useful.
            return avro_schema.make_field(
                name=column_name,
                field_type="string",
                extractor=avro_schema.cleaned_string)

    return None


def fields_from_header(tablename, row, field_create_func):
    fields = [field_create_func(tablename, col_name) for col_name in row]
    return [f for f in fields if f is not None]


def common_reader_config(datatype, field_create_func, add_additional_fields,
                         get_additional_values):
    return DataReaderConfig(
        datatype=datatype,
        tablename_normalizer=lambda x: x,
        fields_from_header=(
            lambda x, y: fields_from_header(x, y, field_create_func)),
        add_additional_fields=add_additional_fields,
        get_additional_values=get_additional_values)
