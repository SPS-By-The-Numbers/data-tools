#!/bin/bash

gcloud storage rsync data/safs gs://sps-btn-data-all-data/raw/safs --recursive
gcloud storage rsync data/sps gs://sps-btn-data-all-data/raw/sps --recursive
