"""Schema for the `fiscal_apportionment_monthly_estimated` fact table.

Source: OSPI Report 1191 Estimated Funding Report as printed on
**pages 2+** of each `apportionment/YYYY-YYYY/district/{ccddd}_{slug}/
Apportionment for {Month}.pdf`. Page 1 of each such PDF is the 1197
Statement of Apportionment (captured by `fiscal_apportionment_monthly`);
pages 3+ carry the interim monthly snapshot of the same Estimated
Funding Report that appears in year-end final form in
`fiscal_apportionment_final`.

Structurally identical to `fiscal_apportionment_final` except each row
also carries a `month` field (September through August for the school
year). The final-round year-end version drops the "F" suffix from each
sub-report code (1191 vs 1191F, 1191SE vs 1191SEF, etc). Same total-
line patterns match both vintages.

Coverage: ~47K files (~4K districts x 12 months x 12 school years).
Headline-only per section, same as `fiscal_apportionment_final`.
"""

from .common import AUDIT_FIELDS, SCHOOL_YEAR_DISTRICT_FIELDS


FISCAL_APPORTIONMENT_MONTHLY_ESTIMATED = {
    "name": "fiscal_apportionment_monthly_estimated",
    "doc": (
        "Per-district per-month interim estimated apportionment totals "
        "per Account from OSPI Report 1191 Estimated Funding Report "
        "(pp 2+ of each monthly Apportionment PDF). Headline-only. "
        "Ships as the mid-year counterpart to `fiscal_apportionment_final` "
        "so consumers can trace the evolution of estimates from monthly "
        "snapshots to the year-end final."
    ),
    "fields": [
        {
            "name": "fiscal_apportionment_monthly_estimated_id",
            "field_type": "auto_primary_key",
            "is_primary_key": True,
            "doc": "Surrogate key.",
        },
    ] + SCHOOL_YEAR_DISTRICT_FIELDS + [
        {
            "name": "month",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "Month of the snapshot: 'September', 'October', ..., "
                "'August'. Derived from the filename "
                "`Apportionment for {Month}.pdf`."
            ),
        },
        {
            "name": "sub_report",
            "field_type": "string",
            "doc": (
                "Sub-report code as printed near the top of each page "
                "banner: '1191' (main 3100 flow), '1191ED' (district "
                "enrollment), '1191EE' (Elementary), '1191EM' (Middle), "
                "'1191EH' (High), '1191CTE' (CTE), '1191MSCTE' (MS "
                "CTE), '1191SC' (Skill Center), '1191MSOC' (Other "
                "Compensation-adjacent), '1191FS' (Food Service), "
                "'1191SE' (Special Education), '1191SER' (Special Ed "
                "Recovery), '1191SN' (LAP / Special Needs), '1191TRN' "
                "(Transportation), '1191TK' (Transition to Kindergarten, "
                "2024-25+). Monthly variants drop the trailing 'F' vs "
                "the same reports on the year-end Final."
            ),
        },
        {
            "name": "account_code",
            "field_type": "string",
            "is_logical_key": True,
            "doc": (
                "OSPI revenue account, same code space as "
                "`fiscal_apportionment_final.account_code`. Attribution "
                "priority: sub_report -> banner. Joint banners "
                "('Account 4198 & 419801') attribute to the first "
                "code."
            ),
        },
        {
            "name": "item_ordinal",
            "field_type": "int",
            "is_logical_key": True,
            "doc": (
                "Positional order of this total line within its "
                "(source, account_code) group. Zero-indexed."
            ),
        },
        {
            "name": "item_label",
            "field_type": "string",
            "doc": (
                "Label as printed (whitespace normalized). Same pattern "
                "as `fiscal_apportionment_final.item_label`."
            ),
        },
        {
            "name": "value",
            "field_type": "decimal",
            "doc": "Dollar amount printed at the end of the label line.",
        },
        {
            "name": "page_number",
            "field_type": "int",
            "doc": (
                "1-indexed page number in the source PDF where the "
                "line was found."
            ),
        },
    ] + AUDIT_FIELDS,
    "unique": [["school_year", "ccddd", "month", "account_code", "item_ordinal"]],
}


ALL_SCHEMAS = [FISCAL_APPORTIONMENT_MONTHLY_ESTIMATED]
