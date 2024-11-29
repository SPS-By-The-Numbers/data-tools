#!/bin/bash

set -x

bq --location=us-west1 load \
  --source_format=AVRO \
  sps-btn-data:raw_ospi.${1} \
  gs://sps-btn-data-all-data/raw/ospi/odata/${1}.avro
