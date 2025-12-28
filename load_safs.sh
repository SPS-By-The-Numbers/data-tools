# Order matters. Go backwards in time to be most resilient to schema changes.

DATASETS="enrollment f19x s275 assessment"

python3 -m extractors.safs.from_raw_file --db-drop-first --db-name=safs_prod \
  data/safs/f196/2024-2025-f196-*.csv \
  data/safs/f196/2023-2024-f196-*.csv \
  data/safs/f196/2022-2023-f196-*.csv \
  data/safs/f196/2021-2022-f196-*.csv \
  data/safs/f196/2020-2021-f196-*.csv \
  data/safs/f196/*.accdb \
  data/safs/f196/*.mdb \
  data/safs/f195/*.accdb \
  data/safs/f196/*-codes.xlsx \
  data/safs/spsbtn/9998-9999-spsbtn.xlsx \
  data/safs/s275/20*Final* \
  data/safs/p223/2001-2025-historical-enrollment-summary.xlsx \
  data/safs/assessment/2024-2025-assessment.avro \
  data/safs/assessment/2023-2024-assessment.avro \
  data/safs/assessment/2022-2023-assessment.avro \
  data/safs/assessment/2015-2022-assessment.avro
python3 -m extractors.safs.generate_final_tables --db-drop-first --db-name safs_prod $DATASETS
python3 -m extractors.safs.dump_tables --db-name safs_prod --outdir safs_prod  $DATASETS
python3 -m extractors.safs.gcloud_load_tables --upload-to-gcs --load-bq-from-gcs --outdir safs_prod $DATASETS
