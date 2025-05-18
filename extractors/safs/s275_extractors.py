import logging

logger = logging.getLogger(__name__)


def passthru(record, source):
    """Just pass through the data value unchanged"""
    return record[source]


def decode_cbrtn(record, source):
    """Just pass through the data value unchanged"""
    src_val = record[source].upper()
    match src_val:
        case 'C':
            return 'Continuing'
        case 'B':
            return 'Beginning'
        case 'R':
            return 'Returning'
        case 'T':
            return 'Transfering'
        case 'N':
            return 'New Classified-Only'
        case '' | '0' | None:
            return 'Unknown'
        case _:
            raise ValueError(src_val)


class ExtractorConfig:
    __slots__ = '_source', '_target', '_extractor'

    def __init__(self, source=None, target=None,
                 extractor=passthru):
        self._source = source
        self._target = target
        self._extractor = extractor

    @property
    def source(self):
        return self._source

    @property
    def target(self):
        return self._source

    def extract(self, record):
        """Extracts the value from the record and returns the target name

        Returns:  "assignment_salary", Decimal(1.23)
        """
        return self._target, self._extractor(record, self._source)


def y_n_to_boolean(record, source):
    """Converts a "Y" and "N" value ot True/False"""
    src_val = record[source]
    if src_val == 'Y':
        return True
    elif src_val == 'N':
        return False
    elif src_val == '' or src_val is None:
        return None
    else:
        logger.error(src_val)
        raise ValueError(src_val)


def area_to_is_esd(record, source):
    """area is "L" if district."""
    src_val = record[source]
    return src_val != 'L'


def parse_datetime(record, source):
    """Takes times of the format 08/20/14 11:37:28 and turns it to millis"""
    return None


def name_typo_correction(name):
    # TODO: Move this to its own file.
    return name


def make_obfuscated_id(record, _):
    """Attempts to create an id for an individual in the s275.

    The s275 does not have a real concept of an employee id so this attempts to
    infer it from the fields.

    First, if there is a teaching certificate, the certificate number is used
    as an employee identifier.

    If there is not one, then the FirstName, MiddleName, LastName are used.

    There will be collisions. Even for the same person two different reporting
    entities will often have mismatches in meta information such as the years
    of experience, highest degree, etc. There is not enough data to do better
    so this is so far a best guess.
    """
    identifier = None
    if 'cert' in record:
        identifier = record['cert']

    if not identifier:
        identifier = name_typo_correction(extract_full_name(record, _))

    return identifier


def extract_full_name(record, source):
    """Constructs a single joined full-name"""
    raw_full_name = ' '.join([record['FirstName'], record['MiddleName'],
                              record['LastName']])
    return name_typo_correction(raw_full_name)


def make_employee_extractors():
    employee_logical_key = [
        ExtractorConfig(target="obfuscated_id", source=None,
                        extractor=make_obfuscated_id),
    ]
    return {'logical_key_extractors': employee_logical_key}


def make_employee_calculated_extractors(employee_table):
    employee_logical_key = [
        ExtractorConfig(target="employee_id", source=None,
                        extractor=employee_table.find_id),
    ]

    employee_other_fields = [
        ExtractorConfig(target="c_record_year", source="SchoolYear"),
        ExtractorConfig(target="c_record_ccddd", source="codist"),
        ExtractorConfig(target="c_highest_degree", source="hdeg"),
        ExtractorConfig(target="c_highest_degree_year", source="hyear"),
        ExtractorConfig(target="c_experience_years", source="exp"),
        ExtractorConfig(target="c_nbpts_certificate_expiration",
                        source="c_NBcertexpdate",
                        extractor=parse_datetime)
    ]

    return {'logical_key_extractors': employee_logical_key,
            'other_fields_extractors': employee_other_fields}


def make_s275_report_extractors():
    s275_report_logical_key = [
        ExtractorConfig(target="school_year_code", source="SchoolYear"),
        ExtractorConfig(target="ccddd", source="codist"),
    ]

    s275_report_other_fields = [
        ExtractorConfig(target="county_code", source="cou"),
        ExtractorConfig(target="district_code", source="dis"),
        ExtractorConfig(target="is_esd", source="area",
                        extractor=area_to_is_esd),
        ExtractorConfig(target="s275_crasdate", source="crasdate",
                        extractor=parse_datetime),
        ExtractorConfig(target="s275_ceridate", source="ceridate",
                        extractor=parse_datetime),
    ]

    return {'logical_key_extractors': s275_report_logical_key,
            'other_fields_extractors': s275_report_other_fields}


def make_contract_extractors():
    contract_logical_key = [
        ExtractorConfig(target="fte_hours", source="ftehrs"),
        ExtractorConfig(target="fte_days", source="ftedays"),
        ExtractorConfig(target="certificated_fte", source="certfte"),
        ExtractorConfig(target="classified_fte", source="clasfte"),
        ExtractorConfig(target="certificated_base_hours", source="certbase"),
        ExtractorConfig(target="classified_base_hours", source="clasbase"),
        ExtractorConfig(target="is_classified", source="clasflag",
                        extractor=y_n_to_boolean),
        ExtractorConfig(target="is_certificated", source="certflag",
                        extractor=y_n_to_boolean),
    ]

    return {'logical_key_extractors': contract_logical_key}


def make_assignment_extractors(s275_report_table, employee_table,
                               contract_table):
    assignment_logical_key = [
        ExtractorConfig(target="s275_report_id",
                        extractor=s275_report_table.find_id),
        ExtractorConfig(target="contract_id",
                        extractor=contract_table.find_id),
        ExtractorConfig(target="employee_id",
                        extractor=employee_table.find_id),
        ExtractorConfig(target="school_code", source="bldgn"),
        ExtractorConfig(target="program_code", source="prog"),
        ExtractorConfig(target="activity_code", source="act"),
        ExtractorConfig(target="duty_root_code", source="droot"),
        ExtractorConfig(target="duty_suffix_code", source="dsufx"),
        ExtractorConfig(target="grade", source="grade"),
        ExtractorConfig(target="s275_recno", source="recno"),
    ]

    assignment_other_fields = [
        ExtractorConfig(target="pct_of_certificated_contract",
                        source="asspct"),
        ExtractorConfig(target="fte_in_assignment",
                        source="assfte"),
        ExtractorConfig(target="percent_fte_in_assignment",
                        source="asspct"),
        ExtractorConfig(target="hours_per_year_in_assignment",
                        source="asshpy"),
        ExtractorConfig(target="is_major", source="major"),
    ]

    return {'logical_key_extractors': assignment_logical_key,
            'other_fields_extractors': assignment_other_fields}


def make_s275_report_employee_extractors(s275_report_table, employee_table):
    employee_data_logical_key = [
        ExtractorConfig(target="s275_report_id",
                        extractor=s275_report_table.find_id),
        ExtractorConfig(target="employee_id",
                        extractor=employee_table.find_id),
    ]

    employee_data_other_fields = [
        ExtractorConfig(target="highest_degree", source="hdeg"),
        ExtractorConfig(target="highest_degree_year", source="hyear"),
        ExtractorConfig(target="experience_years", source="exp"),
        ExtractorConfig(target="nbpts_certificate_expiration",
                        source="NBcertexpdate",
                        extractor=parse_datetime),
        ExtractorConfig(target="hire_state", source="cbrtn",
                        extractor=decode_cbrtn),
    ]

    return {'logical_key_extractors': employee_data_logical_key,
            'other_fields_extractors': employee_data_other_fields}


def make_private_employee_data_extractors(s275_report_table, employee_table):
    private_employee_data_logical_key = [
        ExtractorConfig(target="s275_report_id",
                        extractor=s275_report_table.find_id),
        ExtractorConfig(target="employee_id",
                        extractor=employee_table.find_id),
    ]

    private_employee_data_other_fields = [
        ExtractorConfig(target="full_name", extractor=extract_full_name),
        ExtractorConfig(target="sex", source="sex"),
        ExtractorConfig(target="is_hispanic", source="hispanic",
                        extractor=y_n_to_boolean),
        ExtractorConfig(target="race", source="race"),
        ExtractorConfig(target="certificate_id", source="cert"),
    ]

    return {'logical_key_extractors': private_employee_data_logical_key,
            'other_fields_extractors': private_employee_data_other_fields}


def make_private_contract_extractors(contract_table):
    private_contract_logical_key = [
        ExtractorConfig(target="contract_id",
                        extractor=contract_table.find_id),
        ExtractorConfig(target="total_final_salary", source="tfinsal"),
        ExtractorConfig(target="insurance", source="cins"),
        ExtractorConfig(target="benefits", source="cman"),
        ExtractorConfig(target="other_salary", source="othersal"),
    ]

    return {'logical_key_extractors': private_contract_logical_key}


def make_private_assignment_extractors(assignment_table,
                                       private_contract_table):
    private_assignment_logical_key = [
        ExtractorConfig(target="assignemnt_id",
                        extractor=assignment_table.find_id),
        ExtractorConfig(target="private_contract_id",
                        extractor=private_contract_table.find_id),
    ]

    private_assignment_other_fields = [
        ExtractorConfig(target="assignment_salary", source="asssal"),
    ]

    return {'logical_key_extractors': private_assignment_logical_key,
            'other_fields_extractors': private_assignment_other_fields}
