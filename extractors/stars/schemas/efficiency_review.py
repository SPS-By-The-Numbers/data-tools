"""Schema for the STARS Efficiency Review report.

OSPI's Regional Transportation Coordinators (RTCs) publish a written
review for districts whose STARS Relative Efficiency Rating (RER)
crossed the 90% threshold versus the prior year, or that remained
below 90% for multiple years. The report is a multi-page narrative
document, not a structured data table: this schema captures the
review metadata + the executive summary numerics that are reliably
present in every report.

One row per (school_year, ccddd).

The scraper's filename embeds the subcategory band crossing
("Current above 90% Prior below 90%", etc.) as the 3rd ` - `-separated
segment; the parser maps it to two `current_band` / `prior_band`
fields ('above_90' / 'below_90').
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


STARS_EFFICIENCY_REVIEW = {
    "name": "stars_efficiency_review",
    "doc": ("STARS Efficiency Review metadata + executive-summary "
            "numerics per district per published-review school year."),
    "fields": [
        {
            "name": "stars_efficiency_review_id",
            "field_type": "auto_primary_key",
            "doc": "primary key",
        },
        *SCHOOL_YEAR_DISTRICT_FIELDS,
        {
            "name": "subcategory",
            "field_type": "string",
            "doc": ("Raw subcategory label from the filename, e.g. "
                    "'Current above 90% Prior below 90%'."),
        },
        {
            "name": "current_band",
            "field_type": "string",
            "doc": ("'above_90' or 'below_90'. The RER band at the time of "
                    "this review."),
        },
        {
            "name": "prior_band",
            "field_type": "string",
            "doc": "'above_90' or 'below_90'. The RER band the year before.",
        },
        {
            "name": "review_year_text",
            "field_type": "string",
            "doc": ("School year the review covers, as printed (e.g. "
                    "'2015-16'). Typically one or two years before the "
                    "report's `school_year`."),
        },
        {
            "name": "review_date",
            "field_type": "string",
            "doc": ("Date the review was issued, as printed on the cover "
                    "page (e.g. '10/5/2017'). Free-text, not normalized."),
        },
        {
            "name": "rtc_name",
            "field_type": "string",
            "doc": ("Name of the Regional Transportation Coordinator who "
                    "conducted the review, extracted from the executive "
                    "summary."),
        },
        {
            "name": "rtc_esd",
            "field_type": "string",
            "doc": ("Name of the Educational Service District the RTC is "
                    "from."),
        },
        {
            "name": "fte_enrollment",
            "field_type": "decimal",
            "doc": "District full-time-equivalent enrollment.",
        },
        {
            "name": "basic_riders",
            "field_type": "int",
            "doc": ("Average basic-program riders per day during the "
                    "reviewed school year."),
        },
        {
            "name": "special_riders",
            "field_type": "int",
            "doc": "Average special-program riders per day.",
        },
        {
            "name": "buses",
            "field_type": "int",
            "doc": "Number of school buses operated.",
        },
        {
            "name": "total_cost",
            "field_type": "decimal",
            "doc": "Total transportation cost for the reviewed school year.",
        },
        {
            "name": "current_rer",
            "field_type": "decimal",
            "doc": ("Current Relative Efficiency Rating, in percent. "
                    "Corresponds to the report's `school_year`."),
        },
        {
            "name": "prior_rer",
            "field_type": "decimal",
            "doc": "RER from the year before the current one.",
        },
        {
            "name": "two_years_prior_rer",
            "field_type": "decimal",
            "doc": "RER from two years before the current one.",
        },
    ] + AUDIT_FIELDS,
}


ALL_SCHEMAS = [STARS_EFFICIENCY_REVIEW]
