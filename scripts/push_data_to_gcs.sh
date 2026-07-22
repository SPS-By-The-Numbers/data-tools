#!/bin/bash
# push_data_to_gcs.sh — mirror local data/ to GCS. Pass subdir names to limit,
# e.g. ./scripts/push_data_to_gcs.sh safs sps
# NOTE: first full push is ~150 GB (data/fiscal alone is ~142 GB) — run deliberately.
cd "$(dirname "$0")/.." || exit 1
BUCKET=gs://sps-btn-data-all-data/raw
subdirs=("$@")
[ ${#subdirs[@]} -eq 0 ] && subdirs=($(cd data && ls -d */ | tr -d /))
for d in "${subdirs[@]}"; do
  gcloud storage rsync "data/$d" "$BUCKET/$d" --recursive
done
