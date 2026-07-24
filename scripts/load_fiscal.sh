#!/bin/bash
# Seed the parsed fiscal CSVs (out_fiscal/) into Postgres, export AVRO, and
# load them into BigQuery dataset ospi_fiscal. Assumes the PDF parse already
# ran and produced out_fiscal/*.csv (this does NOT re-parse the ~142GB corpus).
#
# Local-only dry run (no GCS/BigQuery writes):
#   scripts/load_fiscal.sh                       # stages seed,export
# Full production load (writes to GCS + BigQuery):
#   STAGES=seed,export,upload,load scripts/load_fiscal.sh
cd "$(dirname "$0")/.." || exit 1
set -e

STAGES="${STAGES:-seed,export}"
DB_NAME="${DB_NAME:-fiscal_prod}"

python3 -m extractors.bqload.run --family fiscal --stages "$STAGES" \
  --db-name "$DB_NAME" "$@"

python3 -m extractors.bqload.gen_dictionary -o docs/DATA_DICTIONARY.md
