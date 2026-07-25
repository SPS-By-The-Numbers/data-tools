# marts

**Migrated (2026-07-25).** The one data mart this directory held — `bigsheet`,
the joined per-school wide sheet — now lives entirely in the website repo as a
BigQuery Cloud Function, which is the single source of truth:

- Generator: `sps-by-the-numbers-website/functions/src/bigsheet/`
- Column naming/structure: `functions/src/bigsheet/NAMING.md` there
- Legacy (Python-era) → current column mapping: `functions/src/bigsheet/COLUMN_MAPPING.csv`
- Migration record: `BIGSHEET_MIGRATION_PLAN.md` there

The Python implementation (`bigsheet.py`, `vitals.sql`, `assessment.sql`, and
the pre-consolidation originals `vitals_org.sql`,
`expenditures_by_school.sql`, `s275_school_summary.sql`) was deleted from the
tree once the migration was proven; recover it from git history if ever
needed (it was last present in the parent of the commit that introduced this
README).

**What this repo still owns for bigsheet:** the seven static input CSVs under
`data/sps/{map,building,s275,sqss}/` and the scripts that publish them as
BigQuery external tables — `scripts/publish_bigsheet_inputs.sh` then
`scripts/create_bigsheet_input_tables.sh` (in that order; external-table
schemas are positional over the CSVs). After republishing changed contents,
bump `BIGSHEET_SQL_VERSION` in the website
(`functions/src/bigsheet/assemble.ts`) — the export cache does not
auto-invalidate on CSV content changes.
