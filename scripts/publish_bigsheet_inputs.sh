#!/usr/bin/env bash
#
# Publish the seven bigsheet static inputs to the public cache bucket as CSVs
# that back BigQuery external tables in sps-btn-data.bigsheet_inputs
# (see marts/bigsheet.py migration -> website functions/src/bigsheet).
#
# Run from the data-tools repo root:  scripts/publish_bigsheet_inputs.sh
#
# NOTE: the export cache does NOT auto-invalidate when these CSV contents change
# (only pivot-combo changes invalidate it). After re-running this script, BUMP
# BIGSHEET_SQL_VERSION in the website (functions/src/bigsheet/assemble.ts).
set -euo pipefail

BUCKET_PREFIX="gs://sps-by-the-numbers-public/static/bigsheet-inputs"
STAGING="reference/scratch/bigsheet-inputs"

echo "== Privacy check =="
echo "All seven inputs are school-level (or building/area-level) AGGREGATES:"
echo "  map_hc/map_nonhc     : per-school average/stddev RIT scores"
echo "  bex/utilization/income: per-building condition/utilization/area income"
echo "  building_transitions : per-(class_of,school) staff counts"
echo "  sqss                 : per-(school,group) percentages/counts"
echo "None contain individual-person rows. If that ever changes, STOP."
echo

echo "== Building staging CSVs in $STAGING =="
rm -rf "$STAGING"
venv/bin/python3 scripts/bigsheet_inputs_lib.py stage "$STAGING"

echo
echo "== Uploading to $BUCKET_PREFIX =="
gsutil -m cp "$STAGING"/*.csv "$BUCKET_PREFIX/"

echo
echo "== Verifying headers =="
for t in map_hc map_nonhc sqss bex utilization_condition income_by_school building_transitions; do
  printf '  %-24s ' "$t.csv:"
  gsutil cat "$BUCKET_PREFIX/$t.csv" | head -1
done
echo
echo "Done. Remember to (re)run scripts/create_bigsheet_input_tables.sh and,"
echo "if contents changed, bump BIGSHEET_SQL_VERSION in the website."
