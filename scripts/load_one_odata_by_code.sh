#!/bin/bash
cd "$(dirname "$0")/.." || exit 1

#
#  ./scripts/load_one_odata_by_code.sh wagov xxxx-yyyy
#
#  using ospi currently runs into an issue because tables are done with biglake so its all external.

set -x

bq --location=us-west1 load \
  --source_format=AVRO \
  sps-btn-data:raw_${1}_data.${2} \
  gs://sps-btn-data-all-data/raw/ospi/odata/${2}.avro
