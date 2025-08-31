# Order matters. Go backwards in time to be most resilient to schema changes.

DATASETS="enrollment f19x"

python3 -m extractors.safs.from_raw_file  --write-db --db-name=safs_prod data/safs/f196/2023-2024-f196-*.csv data/safs/f196/2022-2023-f196-*.csv data/safs/f196/2021-2022-f196-*.csv data/safs/f196/*.accdb data/safs/f196/*.mdb data/safs/f195/*.accdb data/safs/f196/*-codes.xlsx  data/safs/spsbtn/9998-9999-spsbtn.xlsx data/safs/s275/20*Final*
python3 -m extractors.safs.generate_final_tables --db-name safs_prod --f19x --db-drop-first $DATASETS
python3 -m extractors.safs.dump_tables --db-name safs_prod --outdir safs_prod  $DATASETS
python3 -m extractors.safs.gcloud_load_tables --upload-to-gcs --load-bq-from-gcs --outdir safs_prod $DATASETS
