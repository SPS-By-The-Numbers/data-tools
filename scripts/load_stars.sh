#!/bin/bash
# Seed the parsed STARS CSVs (out_stars/) into Postgres, export AVRO, and load
# them into BigQuery dataset ospi_stars. Assumes the PDF parse already ran and
# produced out_stars/*.csv (this does NOT re-parse the corpus).
#
# Local-only dry run (no GCS/BigQuery writes):
#   scripts/load_stars.sh                        # stages seed,export
# Full production load (writes to GCS + BigQuery):
#   STAGES=seed,export,upload,load scripts/load_stars.sh
cd "$(dirname "$0")/.." || exit 1
set -e

STAGES="${STAGES:-seed,export}"
DB_NAME="${DB_NAME:-stars_prod}"

python3 -m extractors.bqload.run --family stars --stages "$STAGES" \
  --db-name "$DB_NAME" "$@"

python3 -m extractors.bqload.gen_dictionary -o docs/DATA_DICTIONARY.md
