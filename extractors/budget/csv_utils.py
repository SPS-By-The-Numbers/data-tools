import csv


def _value_for_csv(category, value):
    match category:
        case "staffing":
            return "fte", value, None
        case "funding":
            return "dollars", value, None
        case "enrollment":
            return "aafte", value, None


def _merge_staffing_error_for_year(counters, errors):
    for error in errors:
        match error[0]:
            case "fund_type_fte":
                counters["funding_error_total_fte"] += error[1]
                counters["funding_fte_error_count"] += 1
            case "staff_type_fte":
                counters["staff_error_total_fte"] += error[1]
                counters["staff_fte_error_count"] += 1


def calculate_staffing_errors(parsed_schools):
    all_errors = {}
    for school in parsed_schools:
        for year, errors in school["metadata"]["errors"]["staffing"].items():
            if year not in all_errors:
                all_errors[year] = {
                    "funding_fte_error_count": 0,
                    "funding_error_total_fte": 0,
                    "staff_fte_error_count": 0,
                    "staff_error_total_fte": 0,
                }
            _merge_staffing_error_for_year(all_errors[year], errors)
    return all_errors


def write_school_csv(writer, school):
    name = school['metadata']['name']
    print(school['metadata'])
    school_code = school['metadata']['school_code']

    # Output all the year data.
    for year, year_entries in school['year_data'].items():
        for category, category_entries in year_entries.items():
            for item_name, item_entries in category_entries.items():
                if category == 'staffing':
                    subcategoires = item_entries
                else:
                    # For 1 dimension categories, subcategory is the
                    # same as category
                    subcategoires = {category: item_entries}

                for subcategory, item_value in subcategoires.items():
                    value_type, amount, other_value = _value_for_csv(
                        category, item_value)
                    writer.writerow([
                        name,
                        school_code,
                        year,
                        category,
                        subcategory,
                        item_name,
                        value_type,
                        amount,
                        other_value
                    ])


def write_denormalized_csv(outfile, parsed_schools):
    writer = csv.writer(outfile)
    writer.writerow([
        'school',
        'school_code',
        'school_year_code',
        'category',  # enrollment, staffing, funding
        'subcategory',
        'item_name',
        'value_type',
        'amount',
        'other_value',
    ])
    for school in parsed_schools:
        write_school_csv(writer, school)

    budget_errors = calculate_staffing_errors(parsed_schools)
    for year, error_counts in budget_errors.items():
        for item_name, value in error_counts.items():
            if item_name.endswith("_count"):
                value_type = "count"
            elif item_name.endswith("total_fte"):
                value_type = "fte"
            else:
                raise ValueError(item_name)
            writer.writerow([
                "error_counts",
                "-1",
                year,
                "errors",
                item_name,
                value_type,
                value,
                None
            ])
