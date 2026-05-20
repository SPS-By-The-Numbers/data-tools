"""STARS-specific domain (lookup) tables.

These mirror the convention used by `extractors.safs.schemas.domains`:
each domain table is named `d_<thing>`, has a string-or-int primary key
matching the code as it appears on the corresponding fact table, plus
descriptive columns that turn opaque codes into self-documenting joins.

Unlike the safs domains, STARS domain values are tiny and stable across
years, so the canonical row data is defined inline in this module
(see `<TABLE_NAME>_ROWS` constants below). Use `extract_domains.py` to
materialize them as CSV files.
"""

from .common import AUDIT_FIELDS


# ============================================================
# d_stars_kpi_metric -- 6 rows
# ============================================================

D_STARS_KPI_METRIC = {
    "name": "d_stars_kpi_metric",
    "doc": "Domain table for stars_kpi.metric_code.",
    "fields": [
        {
            "name": "metric_code",
            "field_type": "string",
            "is_primary_key": True,
            "is_logical_key": True,
            "doc": "Identifier; joins to stars_kpi.metric_code.",
        },
        {
            "name": "base_metric",
            "field_type": "string",
            "doc": ("Underlying metric ignoring the _change_pct suffix. One of "
                    "basic_rider_kpi, sped_rider_kpi, cost_per_rider."),
        },
        {
            "name": "is_change_pct",
            "field_type": "boolean",
            "doc": "True for the YoY change-percentage variants of each base metric.",
        },
        {
            "name": "unit",
            "field_type": "string",
            "doc": "Display unit: 'riders/bus', '$/rider', or '%'.",
        },
        {
            "name": "description",
            "field_type": "string",
            "doc": "Human-readable description of what the metric measures.",
        },
    ] + AUDIT_FIELDS,
}

D_STARS_KPI_METRIC_ROWS = [
    {
        "metric_code": "basic_rider_kpi",
        "base_metric": "basic_rider_kpi",
        "is_change_pct": False,
        "unit": "riders/bus",
        "description": ("Basic-program riders per basic-program bus. Total "
                        "basic ridership (AM+PM count divided by two) over "
                        "basic bus count."),
    },
    {
        "metric_code": "sped_rider_kpi",
        "base_metric": "sped_rider_kpi",
        "is_change_pct": False,
        "unit": "riders/bus",
        "description": ("Special-education riders per special-education bus. "
                        "Same calculation as basic_rider_kpi but for "
                        "special-program routes."),
    },
    {
        "metric_code": "cost_per_rider",
        "base_metric": "cost_per_rider",
        "is_change_pct": False,
        "unit": "$/rider",
        "description": ("Average operating cost per transported rider, in "
                        "dollars per student per year."),
    },
    {
        "metric_code": "basic_rider_kpi_change_pct",
        "base_metric": "basic_rider_kpi",
        "is_change_pct": True,
        "unit": "%",
        "description": ("Year-over-year change in basic_rider_kpi. Positive "
                        "= more efficient."),
    },
    {
        "metric_code": "sped_rider_kpi_change_pct",
        "base_metric": "sped_rider_kpi",
        "is_change_pct": True,
        "unit": "%",
        "description": ("Year-over-year change in sped_rider_kpi. Positive "
                        "= more efficient."),
    },
    {
        "metric_code": "cost_per_rider_change_pct",
        "base_metric": "cost_per_rider",
        "is_change_pct": True,
        "unit": "%",
        "description": ("Year-over-year change in cost_per_rider. Negative "
                        "= more efficient (cost dropped)."),
    },
]


# ============================================================
# d_stars_quarterly_metric -- 28 rows
# ============================================================

D_STARS_QUARTERLY_METRIC = {
    "name": "d_stars_quarterly_metric",
    "doc": "Domain table for stars_quarterly_district.metric_code.",
    "fields": [
        {
            "name": "metric_code",
            "field_type": "string",
            "is_primary_key": True,
            "is_logical_key": True,
            "doc": "Identifier; joins to stars_quarterly_district.metric_code.",
        },
        {
            "name": "section",
            "field_type": "string",
            "doc": ("Which PDF section the metric is in: 'student_detail', "
                    "'route_summary', or 'bus_summary'."),
        },
        {
            "name": "program",
            "field_type": "string",
            "doc": ("Program subdivision the metric applies to: 'basic', "
                    "'special_ed', 'bilingual', 'gifted', 'homeless', "
                    "'early_ed'. NULL for cross-program aggregates "
                    "(totals, destinations, average_distance)."),
        },
        {
            "name": "unit",
            "field_type": "string",
            "doc": ("Display unit: 'riders', 'routes', 'buses', "
                    "'destinations', or 'miles'."),
        },
        {
            "name": "description",
            "field_type": "string",
            "doc": "Human-readable description.",
        },
    ] + AUDIT_FIELDS,
}


def _qrow(code, section, program, unit, description):
    return {
        "metric_code": code,
        "section": section,
        "program": program,
        "unit": unit,
        "description": description,
    }


D_STARS_QUARTERLY_METRIC_ROWS = [
    # STUDENT DETAIL -- basic program subdivision (4)
    _qrow("basic_students_on_buses", "student_detail", "basic", "riders",
          "Basic-program students transported on district buses."),
    _qrow("basic_students_in_walk_areas", "student_detail", "basic", "riders",
          "Basic-program students living in designated walk areas (not "
          "bused but counted)."),
    _qrow("basic_students_transit_buses", "student_detail", "basic", "riders",
          "Basic-program students transported via public transit."),
    _qrow("basic_students_total", "student_detail", "basic", "riders",
          "Total basic-program ridership count."),
    # STUDENT DETAIL -- special program subdivision (6)
    _qrow("special_students_special_ed", "student_detail", "special_ed", "riders",
          "Special-education students transported."),
    _qrow("special_students_bilingual", "student_detail", "bilingual", "riders",
          "Bilingual-program students transported."),
    _qrow("special_students_gifted", "student_detail", "gifted", "riders",
          "Gifted-program students transported."),
    _qrow("special_students_homeless", "student_detail", "homeless", "riders",
          "Homeless students transported."),
    _qrow("special_students_early_ed", "student_detail", "early_ed", "riders",
          "Early-education-program students transported."),
    _qrow("special_students_total", "student_detail", None, "riders",
          "Total special-program ridership count across all subprograms."),
    # ROUTE SUMMARY -- routes by program (6) + aggregates (4)
    _qrow("routes_basic", "route_summary", "basic", "routes",
          "Number of basic-program (A) routes operated."),
    _qrow("routes_special", "route_summary", "special_ed", "routes",
          "Number of special-education (S) routes operated."),
    _qrow("routes_bilingual", "route_summary", "bilingual", "routes",
          "Number of bilingual (B) routes operated."),
    _qrow("routes_gifted", "route_summary", "gifted", "routes",
          "Number of gifted (G) routes operated."),
    _qrow("routes_homeless", "route_summary", "homeless", "routes",
          "Number of homeless (H) routes operated."),
    _qrow("routes_early_ed", "route_summary", "early_ed", "routes",
          "Number of early-ed (E) routes operated."),
    _qrow("routes_total", "route_summary", None, "routes",
          "Total route count across all programs."),
    _qrow("route_summary_destinations", "route_summary", None, "destinations",
          "Distinct destinations served (from ROUTE SUMMARY rollup)."),
    _qrow("route_summary_total_buses", "route_summary", None, "buses",
          "Total buses used across all routes (route-summary rollup)."),
    _qrow("route_summary_average_distance", "route_summary", None, "miles",
          "Average route distance, miles."),
    # BUS SUMMARY -- buses by program (6) + aggregates (2)
    _qrow("buses_basic", "bus_summary", "basic", "buses",
          "Basic-program (A) buses operated."),
    _qrow("buses_special", "bus_summary", "special_ed", "buses",
          "Special-education (S) buses operated."),
    _qrow("buses_bilingual", "bus_summary", "bilingual", "buses",
          "Bilingual (B) buses operated."),
    _qrow("buses_gifted", "bus_summary", "gifted", "buses",
          "Gifted (G) buses operated."),
    _qrow("buses_homeless", "bus_summary", "homeless", "buses",
          "Homeless (H) buses operated."),
    _qrow("buses_early_ed", "bus_summary", "early_ed", "buses",
          "Early-ed (E) buses operated."),
    _qrow("bus_summary_destinations", "bus_summary", None, "destinations",
          "Distinct destinations served (from BUS SUMMARY rollup)."),
    _qrow("bus_summary_total_buses", "bus_summary", None, "buses",
          "Total buses across all programs (bus-summary rollup)."),
]


# ============================================================
# d_stars_route_program -- 6 rows
# ============================================================

D_STARS_ROUTE_PROGRAM = {
    "name": "d_stars_route_program",
    "doc": "Domain table for stars_quarterly_district_route.program.",
    "fields": [
        {
            "name": "program",
            "field_type": "string",
            "is_primary_key": True,
            "is_logical_key": True,
            "doc": "Canonical program identifier.",
        },
        {
            "name": "program_letter",
            "field_type": "string",
            "doc": "Single-letter abbreviation OSPI uses in route detail labels.",
        },
        {
            "name": "full_label",
            "field_type": "string",
            "doc": "Full label as printed in PDF/DOCX (e.g. 'Basic Program (A)').",
        },
        {
            "name": "description",
            "field_type": "string",
            "doc": "Plain-language description.",
        },
    ] + AUDIT_FIELDS,
}


D_STARS_ROUTE_PROGRAM_ROWS = [
    {"program": "basic",      "program_letter": "A", "full_label": "Basic Program (A)",
     "description": "General-education home-to-school transportation."},
    {"program": "special_ed", "program_letter": "S", "full_label": "Special Ed Program (S)",
     "description": "Special-education routes (IEP-mandated transportation)."},
    {"program": "bilingual",  "program_letter": "B", "full_label": "Bilingual Program (B)",
     "description": "Bilingual / Transitional Bilingual Instructional Program routes."},
    {"program": "gifted",     "program_letter": "G", "full_label": "Gifted Program (G)",
     "description": "Gifted / Highly Capable program routes."},
    {"program": "homeless",   "program_letter": "H", "full_label": "Homeless Program (H)",
     "description": "Homeless-student transportation under McKinney-Vento."},
    {"program": "early_ed",   "program_letter": "E", "full_label": "Early Ed Program (E)",
     "description": "Early-childhood / preschool program routes."},
]


# ============================================================
# d_stars_quarter -- 3 rows
# ============================================================

D_STARS_QUARTER = {
    "name": "d_stars_quarter",
    "doc": "Domain table for the quarter field used by quarterly_district tables.",
    "fields": [
        {
            "name": "quarter",
            "field_type": "string",
            "is_primary_key": True,
            "is_logical_key": True,
            "doc": "FALL, WINTER, or SPRING.",
        },
        {
            "name": "sort_order",
            "field_type": "int",
            "doc": "1, 2, 3 for chronological sort within a school year.",
        },
        {
            "name": "description",
            "field_type": "string",
            "doc": "Plain-language description of the reporting window.",
        },
    ] + AUDIT_FIELDS,
}


D_STARS_QUARTER_ROWS = [
    {"quarter": "FALL",   "sort_order": 1,
     "description": "Fall quarter (typically September-November of the school year)."},
    {"quarter": "WINTER", "sort_order": 2,
     "description": "Winter quarter (typically December-February)."},
    {"quarter": "SPRING", "sort_order": 3,
     "description": "Spring quarter (typically March-May)."},
]


# ============================================================
# d_stars_ops_allocation_section -- 4 rows
# ============================================================

D_STARS_OPS_ALLOCATION_SECTION = {
    "name": "d_stars_ops_allocation_section",
    "doc": "Domain table for stars_operations_allocation.section_code.",
    "fields": [
        {
            "name": "section_code",
            "field_type": "string",
            "is_primary_key": True,
            "is_logical_key": True,
            "doc": "Section letter A/B/C/D.",
        },
        {
            "name": "section_title",
            "field_type": "string",
            "doc": "Section title as printed on the 1026A form.",
        },
        {
            "name": "description",
            "field_type": "string",
            "doc": "Plain-language description of what the section computes.",
        },
    ] + AUDIT_FIELDS,
}


D_STARS_OPS_ALLOCATION_SECTION_ROWS = [
    {"section_code": "A", "section_title": "Calculation of Expected Allocation",
     "description": ("Formula inputs (Land Area, Average Distance, "
                     "Destinations, Basic Program, Special Program, "
                     "Non-High flags) plus summary lines A.1-A.6 ending "
                     "in the calculated expected allocation.")},
    {"section_code": "B", "section_title": "Alternate Funding System Adjustments",
     "description": ("Five line items that may pull the allocation off the "
                     "formula value (Non-High, Low Ridership, "
                     "Transportation Co-op, ESD, Other) plus a B.6 subtotal.")},
    {"section_code": "C", "section_title": "Other Adjustments",
     "description": ("Alt-calendar modifier (C.1), car-mileage reimbursement "
                     "(C.2), and a C.3 subtotal.")},
    {"section_code": "D", "section_title": "Determination of Final STARS Allocation",
     "description": ("Adjusted allocation, prior-year expenditures, "
                     "legislative add-ons, and the bottom-line "
                     "ACTUAL ALLOCATION AMOUNT (D.8).")},
]


# ============================================================
# d_stars_ops_allocation_item -- 30 rows
# ============================================================

D_STARS_OPS_ALLOCATION_ITEM = {
    "name": "d_stars_ops_allocation_item",
    "doc": "Domain table for stars_operations_allocation.item_code.",
    "fields": [
        {
            "name": "item_code",
            "field_type": "string",
            "is_primary_key": True,
            "is_logical_key": True,
            "doc": "Canonical item identifier; joins to stars_operations_allocation.item_code.",
        },
        {
            "name": "section_code",
            "field_type": "string",
            "doc": "A/B/C/D; foreign key to d_stars_ops_allocation_section.",
        },
        {
            "name": "label",
            "field_type": "string",
            "doc": "Canonical label as printed on the 1026A form.",
        },
        {
            "name": "value_kind",
            "field_type": "string",
            "doc": ("How to interpret this row's numeric columns. One of: "
                    "'detail' (Section A formula input: value+coefficient+calculated_value), "
                    "'non_high' (Yes/No flag plus coefficient + calculated_value), "
                    "'calc' (unitless decimal summary), "
                    "'amount' (single dollar amount), "
                    "'amount_rt' (dollar amount + running_total), "
                    "'coef_rt' (modifier + running_total)."),
        },
        {
            "name": "description",
            "field_type": "string",
            "doc": "Plain-language description of the line item.",
        },
    ] + AUDIT_FIELDS,
}


def _orow(code, section, label, kind, description):
    return {
        "item_code": code,
        "section_code": section,
        "label": label,
        "value_kind": kind,
        "description": description,
    }


D_STARS_OPS_ALLOCATION_ITEM_ROWS = [
    # Section A detail (7)
    _orow("land_area", "A", "Land Area (Ln)", "detail",
          "Natural log of district land area, weighted into the allocation formula."),
    _orow("average_distance", "A", "Average Distance", "detail",
          "Average route distance (miles)."),
    _orow("destinations", "A", "Destinations", "detail",
          "Distinct delivery destinations served."),
    _orow("basic_program", "A", "Basic Program (Ln)", "detail",
          "Natural log of basic-program enrollment."),
    _orow("special_program", "A", "Special Program (Ln)", "detail",
          "Natural log of special-program enrollment."),
    _orow("non_high_yes", "A", "Non-High Yes", "non_high",
          "Indicator + coefficient for districts classified as 'Non-High Yes'."),
    _orow("non_high_no", "A", "Non-High No", "non_high",
          "Indicator + coefficient for districts classified as 'Non-High No'."),
    # Section A summary (6)
    _orow("a1_sum_calculated_values", "A", "A.1. Sum of Calculated Values", "calc",
          "Sum of the 7 Section A detail calculated values."),
    _orow("a2_expected_allocation_constant", "A", "A.2. Expected Allocation Constant Value", "calc",
          "OSPI-published per-year constant added to the sum."),
    _orow("a3_expected_allocation_value", "A", "A.3. Expected Allocation Value", "calc",
          "A.1 + A.2; intermediate calculation."),
    _orow("a4_initial_allocation", "A", "A.4. Initial Allocation", "amount",
          "Exp(A.3) scaled to dollars -- the formula-driven initial allocation."),
    _orow("a5_local_characteristics_factor", "A", "A.5. Local Characteristics Factor", "calc",
          "Multiplier accounting for local factors. Usually 1.00000."),
    _orow("a6_calculated_expected_allocation", "A", "A.6. CALCULATED EXPECTED ALLOCATION", "amount",
          "A.4 * A.5 -- the formula's final answer before adjustments."),
    # Section B (6)
    _orow("b1_non_high", "B", "B.1. Non-High", "amount",
          "Non-high adjustment."),
    _orow("b2_low_ridership", "B", "B.2. Low Ridership", "amount",
          "Low-ridership adjustment."),
    _orow("b3_transportation_coop", "B", "B.3. Transportation Co-op", "amount",
          "Transportation co-op adjustment."),
    _orow("b4_esd", "B", "B.4. ESD", "amount",
          "ESD-related adjustment."),
    _orow("b5_other", "B", "B.5. Other", "amount",
          "Other alternate-system adjustments."),
    _orow("b6_alternate_system_total", "B", "B.6. Alternate System Total", "amount_rt",
          "B.1-B.5 sum, plus running-total post-Section-B."),
    # Section C (3)
    _orow("c1_alt_calendar_modifier", "C", "C.1. Alt Calendar Modifier", "coef_rt",
          "Alt-calendar modifier (decimal multiplier) plus running total."),
    _orow("c2_car_mileage_reimbursement", "C", "C.2. Car Mileage Reimbursement", "amount",
          "Car-mileage reimbursement amount."),
    _orow("c3_other_adjustments_total", "C", "C.3. Other Adjustments Total", "amount_rt",
          "Sum of C.1 + C.2, plus running total post-Section-C."),
    # Section D (8)
    _orow("d1_adjusted_allocation", "D", "D.1. Adjusted Allocation", "amount",
          "Allocation after all B and C adjustments."),
    _orow("d2_prior_year_expenditures", "D", "D.2. Prior Year Expenditures", "amount",
          "District's transportation expenditures from the prior school year."),
    _orow("d3_federal_restricted_rate_indirects", "D", "D.3. Federal Restricted Rate Indirects", "amount",
          "Federal restricted-rate indirect costs added to prior-year expenditures."),
    _orow("d4_adjusted_prior_year_expenditures", "D", "D.4. Adjusted Prior Year Expenditures", "amount",
          "D.2 + D.3."),
    _orow("d5_lesser_of_adjusted_or_prior_year", "D",
          "D.5. Lesser of Adjusted Allocation or Adjusted Prior Year Expenditures",
          "amount",
          "Min(D.1, D.4) -- the cap that prevents over-allocation."),
    _orow("d6_legislative_salary", "D", "D.6. Legislative Salary", "amount",
          "Legislative salary add-on."),
    _orow("d7_legislative_benefit", "D", "D.7. Legislative Benefit", "amount",
          "Legislative benefit add-on."),
    _orow("d8_actual_allocation_amount", "D", "D.8. ACTUAL ALLOCATION AMOUNT", "amount",
          "Bottom-line transportation allocation paid to the district."),
]


# Public API: list of all schemas, and a mapping from schema name to its rows.

ALL_SCHEMAS = [
    D_STARS_KPI_METRIC,
    D_STARS_QUARTERLY_METRIC,
    D_STARS_ROUTE_PROGRAM,
    D_STARS_QUARTER,
    D_STARS_OPS_ALLOCATION_SECTION,
    D_STARS_OPS_ALLOCATION_ITEM,
]


ROWS_BY_TABLE = {
    D_STARS_KPI_METRIC["name"]:              D_STARS_KPI_METRIC_ROWS,
    D_STARS_QUARTERLY_METRIC["name"]:        D_STARS_QUARTERLY_METRIC_ROWS,
    D_STARS_ROUTE_PROGRAM["name"]:           D_STARS_ROUTE_PROGRAM_ROWS,
    D_STARS_QUARTER["name"]:                 D_STARS_QUARTER_ROWS,
    D_STARS_OPS_ALLOCATION_SECTION["name"]:  D_STARS_OPS_ALLOCATION_SECTION_ROWS,
    D_STARS_OPS_ALLOCATION_ITEM["name"]:     D_STARS_OPS_ALLOCATION_ITEM_ROWS,
}
