#!/usr/bin/env bash
#
# Create (or replace) the sps-btn-data.bigsheet_inputs external tables that back
# the migrated bigsheet SQL. Idempotent; safe to re-run after republishing the
# CSVs with scripts/publish_bigsheet_inputs.sh.
#
# External-table schemas are POSITIONAL over the published CSVs: if the schema
# lists in bigsheet_inputs_lib.py changed, re-run publish_bigsheet_inputs.sh
# FIRST so the CSVs and the DDL agree.
#
# The dataset is created in the SAME location as ospi/safs_* (us-west1) so
# cross-dataset joins and EXPORT DATA to the public bucket work.
#
# Run from the data-tools repo root:  scripts/create_bigsheet_input_tables.sh
set -euo pipefail

LOCATION="us-west1"
DDL_FILE="reference/scratch/bigsheet_inputs.ddl.sql"

mkdir -p "$(dirname "$DDL_FILE")"
venv/bin/python3 scripts/bigsheet_inputs_lib.py ddl > "$DDL_FILE"

echo "== DDL =="
cat "$DDL_FILE"
echo
echo "== Running in location $LOCATION =="
bq --project_id=sps-btn-data query --use_legacy_sql=false --location="$LOCATION" < "$DDL_FILE"

echo
echo "== Verifying external tables (row counts) =="
for t in map_hc map_nonhc sqss bex utilization_condition income_by_school building_transitions; do
  n=$(bq --project_id=sps-btn-data query --use_legacy_sql=false --location="$LOCATION" \
        --format=csv "SELECT COUNT(*) FROM \`sps-btn-data.bigsheet_inputs.$t\`" | tail -1)
  printf '  %-24s %s rows\n' "$t" "$n"
done
