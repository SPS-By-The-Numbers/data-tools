#!/bin/bash
cd "$(dirname "$0")/.." || exit 1

gcloud storage rsync gs://sps-btn-data-all-data/raw/safs data/safs  --recursive
gcloud storage rsync gs://sps-btn-data-all-data/raw/sps data/sps  --recursive
