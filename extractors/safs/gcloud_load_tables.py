#!python3

import argparse
import logging

from extractors.common import common_logging_setup, get_args
from google.cloud import bigquery
from pathlib import Path
from google.cloud import storage
from google.cloud.bigquery import Dataset
from google.cloud.storage.blob import Blob


logger = logging.getLogger(__name__)


PRIVATE_BUCKET = 'gs://sps-btn-data-private'
NORMAL_BUCKET = 'gs://sps-btn-data-all-data'
PROJECT_NAME = 'sps-btn-data'


def bq_dataset_name(dataset):
    return f"safs_{dataset}"


def get_bucket_uri(filepath):
    if 'private' in filepath.name:
        return PRIVATE_BUCKET

    return NORMAL_BUCKET


def get_blob_uri(dataset, filepath):
    return (f"{get_bucket_uri(filepath)}/processed/safs/"
            f"{dataset}/{filepath.name}")


def do_load_bq_from_gcs(bigquery_client, dataset, tablename, gcs_uri):
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.AVRO,
        write_disposition="WRITE_TRUNCATE")

    table_id = f"sps-btn-data.{bq_dataset_name(dataset)}.{tablename}"
    logging.info(f"Loading {table_id} from {gcs_uri}")
    load_job = bigquery_client.load_table_from_uri(
        gcs_uri,
        table_id,
        job_config=job_config
    )

    load_job.result()  # Waits for the job to complete.


def ensure_bq_dataset_exists(bigquery_client, dataset):
    # Ensure dataset exists.
    dataset_name = bq_dataset_name(dataset)
    logging.info(f"ensuring bq dataset {dataset_name} exists")
    d = Dataset(bigquery_client.dataset(dataset_name))
    d.location = 'us-west1'
    print(bigquery_client.create_dataset(d, exists_ok=True))


def load_dataset(outdir, dataset, upload_to_gcs, load_bq_from_gcs):
    if upload_to_gcs:
        storage_client = storage.Client(PROJECT_NAME)

    if load_bq_from_gcs:
        bigquery_client = bigquery.Client(PROJECT_NAME)
        ensure_bq_dataset_exists(bigquery_client, dataset)

    for entry in (outdir / dataset).iterdir():
        if entry.is_file() and entry.name.endswith('.avro'):
            blob_uri = get_blob_uri(dataset, entry)

            if upload_to_gcs:
                logging.info(f"Uploading {entry} to {blob_uri}")
                blob = Blob.from_uri(blob_uri, client=storage_client)
                blob.upload_from_filename(entry)

            if load_bq_from_gcs:
                do_load_bq_from_gcs(bigquery_client,
                                    dataset, entry.name.removesuffix('.avro'),
                                    blob_uri)


def main():
    parser = argparse.ArgumentParser(
        description='Loads avro files into Google Cloud')
    parser.add_argument('--outdir', required=True,
                        help='directory for set finalized avro tables"')
    parser.add_argument('datasets', nargs="+",
                        choices=['f19x', 's275', 'domains', 'enrollment'],
                        help='loads files from outdir into the ospi datasets')
    parser.add_argument('--upload-to-gcs', action='store_true',
                        help='Upload file to gcs')
    parser.add_argument('--load-bq-from-gcs', action='store_true',
                        help='Load the AVRO file gcs into bigquery')
    common_logging_setup(parser)

    args = get_args(parser)

    for dataset in args.datasets:
        load_dataset(Path(args.outdir), dataset,
                     args.upload_to_gcs,
                     args.load_bq_from_gcs)


if __name__ == '__main__':
    main()
