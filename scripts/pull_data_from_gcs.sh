#!/bin/bash
# pull_data_from_gcs.sh — mirror GCS to local data/. Pass subdir names to
# limit, e.g. ./scripts/pull_data_from_gcs.sh safs sps
cd "$(dirname "$0")/.." || exit 1
BUCKET=gs://sps-btn-data-all-data/raw
subdirs=("$@")
[ ${#subdirs[@]} -eq 0 ] && subdirs=($(gcloud storage ls "$BUCKET/" | sed -e "s#$BUCKET/##" -e 's#/$##'))
for d in "${subdirs[@]}"; do
  gcloud storage rsync "$BUCKET/$d" "data/$d" --recursive
done
