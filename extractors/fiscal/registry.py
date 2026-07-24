"""Fiscal family registry for the bqload pipeline.

Auto-builds a `TableSpec` for every fiscal schema (one per out_fiscal/*.csv)
and annotates the tables that duplicate SAFS canonical data, transcribed from
DATA_SOURCE_DIVERGENCE.md. Everything not listed is treated as unique (the
printed-PDF-only dimensions: salary/staff detail, balance sheet, mid-year
Final Budget, indirect rate, apportionment, non-district entities, ...).
"""

from ..bqload.spec import Canonical, Family, TableSpec
from ..bqload.registry_build import collect_schemas


_GFE = "safs_f19x.general_fund_expenditures"
_GFR = "safs_f19x.general_fund_revenues"

# Tables whose facts also live in the SAFS canonical avros. Prefer SAFS; these
# PDF copies are kept for cross-validation, printed labels, and (where noted)
# the extra columns SAFS lacks.
CANONICAL = {
    "fiscal_f195_program_activity_object_detail": Canonical(
        "duplicate", _GFE,
        "Budget side of the P×A×O cube. SAFS has more grain (NCES, sub-fund, "
        "per-school). UNIQUE here: row_kind='fte_program_staff' rows carry "
        "budgeted fte_cert/fte_class by program."),
    "fiscal_f196_program_activity_object_detail": Canonical(
        "duplicate", _GFE,
        "Actuals side of the P×A×O cube; SAFS general_fund_expenditures "
        "(data_type='actuals') is canonical and finer-grained."),
    "fiscal_f196_program_activity_object": Canonical(
        "duplicate", _GFE, "GF program/activity/object roll-up; SAFS canonical."),
    "fiscal_f195_program_summary_by_object": Canonical(
        "duplicate", _GFE, "Program×object roll-up; SAFS canonical."),
    "fiscal_f196_revenues": Canonical(
        "duplicate", _GFR, "Per-account revenues; SAFS general_fund_revenues "
        "is canonical and adds the 1191F target program_code."),
    "fiscal_f196_resource_to_program": Canonical(
        "duplicate", _GFR, "Funding-source→program attribution now baked into "
        "SAFS general_fund_revenues.program_code."),
    "fiscal_f196_nces_object": Canonical(
        "duplicate", _GFE, "NCES-category grain is on SAFS "
        "general_fund_expenditures (nces_code)."),
    "fiscal_f196_gf_by_subfund": Canonical(
        "duplicate", _GFE, "Sub-fund grain is on SAFS "
        "general_fund_expenditures (sub_fund_code)."),
}

# Corpus root each table's PDFs are parsed from (provenance for the dictionary).
_APPORTIONMENT = "data/fiscal/apportionment"
_FISCAL = "data/fiscal/fiscal"


def _corpus_for(name: str) -> str:
    return _APPORTIONMENT if "apportionment" in name else _FISCAL


def _build() -> Family:
    tables = []
    for schema in collect_schemas("fiscal"):
        name = schema["name"]
        if name == "d_fiscal_source":
            kind = "source_dim"
        elif name.startswith("d_"):
            kind = "static"
        else:
            kind = "parsed"
        tables.append(TableSpec(
            table=name,
            schema=schema,
            kind=kind,
            canonical=CANONICAL.get(name, Canonical("unique")),
            corpus=_corpus_for(name),
        ))
    tables.sort(key=lambda t: t.table)
    return Family(
        name="fiscal",
        bq_dataset="ospi_fiscal",
        out_dir="out_fiscal",
        source_dim_table="d_fiscal_source",
        tables=tables,
    )


FAMILY = _build()
