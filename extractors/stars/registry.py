"""STARS family registry for the bqload pipeline.

STARS pupil-transportation data has no SAFS equivalent, so every table is
unique. Auto-builds a `TableSpec` per stars schema (one per out_stars/*.csv);
the attic-derived transit-analysis CSVs have no schema and are excluded.
"""

from ..bqload.spec import Canonical, Family, TableSpec
from ..bqload.registry_build import collect_schemas


def _build() -> Family:
    tables = []
    for schema in collect_schemas("stars"):
        name = schema["name"]
        if name == "d_stars_source":
            kind = "source_dim"
        elif name.startswith("d_"):
            kind = "static"
        else:
            kind = "parsed"
        tables.append(TableSpec(
            table=name,
            schema=schema,
            kind=kind,
            canonical=Canonical("unique"),
            corpus="data/stars",
        ))
    tables.sort(key=lambda t: t.table)
    return Family(
        name="stars",
        bq_dataset="ospi_stars",
        out_dir="out_stars",
        source_dim_table="d_stars_source",
        tables=tables,
    )


FAMILY = _build()
