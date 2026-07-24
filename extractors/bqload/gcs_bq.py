"""Upload exported AVRO to GCS and load it into BigQuery.

Family-agnostic generalization of `extractors/safs/gcloud_load_tables.py`:
same project, location, buckets, WRITE_TRUNCATE AVRO loads, and private-file
routing, but parameterized by family/dataset so fiscal and stars share it.
After each load it patches the BigQuery table + column descriptions from the
schema dict `doc` strings.

google-cloud-* imports are lazy so unit tests never need credentials.
"""

import logging
from pathlib import Path

from ..safs.avro_schema import to_avro_schema


logger = logging.getLogger(__name__)

PROJECT = "sps-btn-data"
LOCATION = "us-west1"
NORMAL_BUCKET = "gs://sps-btn-data-all-data"
PRIVATE_BUCKET = "gs://sps-btn-data-private"


def _blob_uri(family_name, table, bucket):
    return f"{bucket}/processed/{family_name}/{table}.avro"


def _bucket_for(table):
    return PRIVATE_BUCKET if "private" in table else NORMAL_BUCKET


def upload_and_load(out_dir, family_name, bq_dataset, specs, *,
                    project=PROJECT, location=LOCATION,
                    upload=True, load=True, describe=True):
    """specs: iterable of TableSpec. Uploads out_dir/tables/<t>.avro then loads
    bq_dataset.<t> WRITE_TRUNCATE, then sets table/column descriptions."""
    from google.cloud import bigquery, storage
    from google.cloud.storage.blob import Blob

    tables_dir = Path(out_dir) / "tables"
    storage_client = storage.Client(project) if upload else None
    bq = bigquery.Client(project) if (load or describe) else None

    if load or describe:
        ds = bigquery.Dataset(bq.dataset(bq_dataset))
        ds.location = location
        bq.create_dataset(ds, exists_ok=True)

    results = []
    for spec in specs:
        table = spec.table
        avro_path = tables_dir / f"{table}.avro"
        if not avro_path.exists():
            logger.warning("%s: no AVRO at %s, skipping", table, avro_path)
            continue
        bucket = _bucket_for(table)
        gcs_uri = _blob_uri(family_name, table, bucket)

        if upload:
            logger.info("uploading %s -> %s", avro_path, gcs_uri)
            Blob.from_uri(gcs_uri, client=storage_client).upload_from_filename(
                str(avro_path))

        if load:
            table_id = f"{project}.{bq_dataset}.{table}"
            logger.info("loading %s from %s", table_id, gcs_uri)
            job = bq.load_table_from_uri(
                gcs_uri, table_id,
                job_config=bigquery.LoadJobConfig(
                    source_format=bigquery.SourceFormat.AVRO,
                    write_disposition="WRITE_TRUNCATE"))
            job.result()
            results.append({"table": table, "output_rows": job.output_rows})

        if describe:
            _set_descriptions(bq, project, bq_dataset, spec)

    return results


def _set_descriptions(bq, project, bq_dataset, spec):
    """Patch table + column descriptions from the schema doc strings."""
    from google.cloud import bigquery

    table_id = f"{project}.{bq_dataset}.{spec.table}"
    tbl = bq.get_table(table_id)
    doc = spec.schema.get("doc")
    if spec.canonical and spec.canonical.status == "duplicate":
        note = f" [Prefer {spec.canonical.prefer}: {spec.canonical.note}]"
        doc = (doc or "") + note
    tbl.description = (doc or None)

    docs = {f["name"]: f.get("doc") for f in spec.schema["fields"]}
    new_schema = []
    for col in tbl.schema:
        d = docs.get(col.name)
        if d is None:
            new_schema.append(col)
        else:
            new_schema.append(bigquery.SchemaField(
                col.name, col.field_type, mode=col.mode,
                description=d, fields=col.fields))
    tbl.schema = new_schema
    bq.update_table(tbl, ["description", "schema"])
