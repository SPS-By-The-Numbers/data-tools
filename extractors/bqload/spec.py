"""Dataclasses describing what the bqload pipeline loads.

A `Family` (fiscal or stars) owns a BigQuery dataset and a list of
`TableSpec`s. Each TableSpec pairs a table name with its schema dict (the
same custom schema shape used across `extractors/safs/schemas` and
`extractors/{fiscal,stars}/schemas`) plus provenance and canonical-source
metadata for the data dictionary.

The pipeline is *seed-first*: staging is populated from the already-parsed
`out_<family>/<table>.csv` files, not by re-parsing PDFs. The post-
`build_sources` CSVs already carry `_source_id`, so a staging table mirrors
its export schema directly. The per-file incremental parse path (parser_version,
walker) is described here for the future but is not exercised by the seed path.
"""

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass(frozen=True)
class Canonical:
    """Whether this table is the source of truth for its facts.

    status:
      'unique'    -- these facts appear nowhere else (load and cite here).
      'duplicate' -- also in SAFS (prefer points at the canonical table).
      'canonical' -- this is the preferred copy of facts also parsed elsewhere.
    """
    status: str
    prefer: Optional[str] = None      # e.g. "safs_f19x.general_fund_expenditures"
    note: Optional[str] = None


@dataclass
class TableSpec:
    table: str                        # BigQuery table id == schema["name"]
    schema: dict                      # the custom schema dict
    kind: str = "parsed"              # 'parsed' | 'source_dim' | 'static'
    csv_name: Optional[str] = None    # basename in out_<family>/ (default: table + ".csv")
    canonical: Optional[Canonical] = None
    corpus: Optional[str] = None      # e.g. "data/fiscal/fiscal" (provenance)
    driver: Optional[str] = None      # e.g. "extractors.fiscal.extract_f196_all_pages"
    parser_version: int = 1           # bump to force reparse (incremental path)
    # Incremental-parse path only (unused by the seed path):
    parse_fn: Optional[tuple] = None  # ("module.path", "func_name")
    walker: Optional[Callable] = None
    adapter: Optional[Callable] = None

    def csv_basename(self) -> str:
        return self.csv_name or f"{self.table}.csv"


@dataclass
class Family:
    name: str                         # 'fiscal' | 'stars'
    bq_dataset: str                   # 'ospi_fiscal' | 'ospi_stars'
    out_dir: str                      # 'out_fiscal' | 'out_stars'
    source_dim_table: str             # 'd_fiscal_source' | 'd_stars_source'
    tables: list = field(default_factory=list)

    def by_name(self, name: str) -> Optional[TableSpec]:
        for t in self.tables:
            if t.table == name:
                return t
        return None


def schema_fieldnames(schema: dict) -> list:
    """Column names a parser/CSV emits: schema fields minus the auto-PK.

    The post-build_sources CSVs contain exactly these columns (including the
    integer `_source_id`); the auto_primary_key surrogate is assigned at load
    time by Postgres, not present in the CSV.
    """
    return [f["name"] for f in schema["fields"]
            if f["field_type"] != "auto_primary_key"]


def auto_pk_field(schema: dict) -> Optional[str]:
    for f in schema["fields"]:
        if f["field_type"] == "auto_primary_key":
            return f["name"]
    return None


def staging_schema(schema: dict) -> dict:
    """A permissive copy of `schema` for the Postgres staging table.

    Staging is seeded from already-deduped CSVs and re-loaded table-at-a-time,
    so it drops the logical-key UNIQUE constraints and their implied NOT NULL
    (via `is_logical_key`) to tolerate the occasional blank key cell. The
    auto_primary_key surrogate is kept as a Postgres SERIAL so export can carry
    a stable row id into BigQuery.
    """
    fields = []
    for f in schema["fields"]:
        g = dict(f)
        g.pop("is_logical_key", None)
        fields.append(g)
    out = dict(schema)
    out["fields"] = fields
    out.pop("unique", None)
    return out
