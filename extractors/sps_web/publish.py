"""publish.py -- task G1 (see ``extractors/sps_web/PLAN.md``, Section 3):
turn the linked board-action rows into an analyst-facing spreadsheet and
(optionally, later, by the repo owner) load them into BigQuery.

Usage (from the repo root)::

    venv/bin/python3 -m extractors.sps_web.publish
    venv/bin/python3 -m extractors.sps_web.publish --outdir out_sps_web/publish
    venv/bin/python3 -m extractors.sps_web.publish --root /tmp/scratch --outdir /tmp/scratch/publish
    venv/bin/python3 -m extractors.sps_web.publish --bq     # ALSO loads BigQuery -- owner-run only

This module is rerunnable: every output path is rewritten from scratch on
each run, and nothing here mutates its inputs.

Inputs (read-only, all under ``--root``, default ``out_sps_web``):

* ``contracts/contract_actions.jsonl`` -- one row per board action (task F2,
  ``link.py``). Field list and semantics: see that module's docstring.
* ``contracts/vendors.jsonl`` -- one row per canonical vendor (task F1,
  ``vendors.py``): ``vendor_id, canonical_name, vendor_class, ...``. Used
  here only to join ``vendor_class`` onto each action (``vendor_canonical``
  is already filled in on the action row by ``link.py``).
* ``manifest/documents_classified.jsonl`` -- one row per document (task C2,
  ``classify.py``): ``doc_id, kind, meeting_id, meeting_date, school_year,
  source_url, fetch{kind,url,...}, pages, ...``.
* ``manifest/meetings.jsonl`` -- one row per meeting: ``meeting_id, date,
  title, ...``. Used only for the ``documents`` sheet's ``meeting_title``.
* ``raw/<era>/<date>/*.prov.json`` -- fetch provenance (task B1, ``fetch.py``),
  read via ``classify.build_fetch_index``/``classify.lookup`` for ``sha256``.

Primary-source citation URL
============================
A citation (``contract_actions.jsonl``'s ``citations[]`` -- the introduction
and action minutes plus, since E3, the item's Board Action Report with
``role="bar"``; see ``link.py``) names a ``doc_id`` and a page range.
``citation_1``/``citation_2`` are positional (introduction, then action);
``citation_3`` is the ``role="bar"`` one, looked up by role rather than by
position because an unpaired introduction has only two citations in total. The URL that
should live in the spreadsheet is the **primary source**, not necessarily
the URL the document was actually fetched from:

* ``fetch.kind in {"direct", "sharepoint_download"}`` -- the document is
  still (or was, anonymously) reachable directly from
  seattleschools.org/SharePoint. ``source_url`` *is* that live/share URL
  (see ``fetch.py``'s docstring on the two recipes), so it is used as-is.
* ``fetch.kind == "wayback_raw"`` -- the live URL is dead (that is why it
  had to be fetched from the Wayback Machine at all); ``source_url`` would
  404 today. ``fetch.url`` -- the ``.../web/<ts>id_/<original>`` URL -- is
  used instead; ``id_`` serves the original bytes, unlike the ``.../web/<ts>/``
  form which serves a Wayback-rewritten replay page.

The cited page is appended as a ``#page=N`` fragment (``N`` = the
citation's ``page_start``), which most browsers' and PDF viewers' built-in
PDF renderers honor by jumping straight to that page.

Outputs (under ``--outdir``, default ``out_sps_web/publish``; all rewritten
from scratch every run)::

    contracts.csv                  actions sheet only (flat, for non-xlsx tools)
    contracts.xlsx                 sheets: actions, vendors, documents
    contracts_vendors.csv          vendors sheet, standalone
    contracts_documents.csv        documents sheet, standalone
    contracts.jsonl                actions rows, machine-readable (nested citations kept)
    avro/contract_actions.avro     \\
    avro/vendors.avro               |- extractors/sps_web/schemas.py + avro_schema.py
    avro/documents.avro            /
    README.md                      row counts, action_type totals, top vendors, column dictionary

``--bq`` additionally loads the three AVRO tables into BigQuery dataset
``sps_board`` (project ``sps-btn-data``), creating the dataset if needed and
WRITE_TRUNCATE-loading each table, then patching table/column descriptions
from the schema ``doc`` strings (see ``extractors/bqload/gcs_bq.py`` for the
pattern this reuses). This needs BigQuery credentials and is the repo
owner's call to run -- CI/agents should not pass ``--bq``.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import openpyxl
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from . import classify  # build_fetch_index/lookup reuse
from ..safs import avro_schema
from .schemas import (
    CONTRACT_ACTIONS_SCHEMA, VENDORS_SCHEMA, DOCUMENTS_SCHEMA, ALL_SCHEMAS,
)

logger = logging.getLogger(__name__)

DEFAULT_ROOT = "out_sps_web"
DEFAULT_OUTDIR = os.path.join(DEFAULT_ROOT, "publish")

BQ_PROJECT = "sps-btn-data"
BQ_DATASET = "sps_board"
BQ_LOCATION = "us-west1"

ACTIONS_HEADERS = [
    "date", "school_year", "vendor_canonical", "vendor_raw", "vendor_class",
    "action_type", "amount", "amount_kind", "prior_total", "revised_total",
    "chain_id", "sequence", "chain_total_latest", "board_action", "vote",
    "immediate_action", "contract_id", "po_number", "term", "department",
    "program_or_project", "fund", "funding_source_text", "procurement_method",
    "extractor", "paired", "title",
    "amount_source", "multi_vendor_group", "multi_vendor_n", "group_total",
    "citation_1_url", "citation_1_page", "citation_2_url", "citation_2_page",
    "citation_3_url", "citation_3_page",
    "action_id",
]

VENDOR_HEADERS = [
    "vendor_id", "vendor_canonical", "vendor_class", "school_year",
    "n_actions", "n_amounts", "amount_sum",
]

DOCUMENT_HEADERS = [
    "doc_id", "kind", "meeting_id", "meeting_date", "meeting_title",
    "school_year", "url", "pages", "sha256", "n_citing_actions",
]

# column -> plain-English note for the README's data dictionary. Pulled from
# schemas.py's field docs where a matching field exists there; the rest
# (sheet-only computed columns) are documented here.
ACTIONS_COLUMN_NOTES = {
    "date": "Meeting date (contract_actions.meeting_date).",
    "vendor_canonical": "Canonical vendor display name.",
    "vendor_raw": "Vendor name exactly as it appeared in the source text.",
    "vendor_class": "Vendor category, joined from contracts/vendors.jsonl by vendor_id.",
    "term": "term_start and term_end combined into one 'START to END' string (or whichever is present).",
    "citation_1_url": "Primary source URL for the first citation, with a #page=N fragment. See module docstring.",
    "citation_1_page": "Cited page number (page_start) of the first citation.",
    "citation_2_url": "Primary source URL for the second citation, when present.",
    "citation_2_page": "Cited page number (page_start) of the second citation, when present.",
    "citation_3_url": ("Primary source URL for the Board Action Report behind this item "
                       "(citations[] role=bar, from bar_fill.py), when present."),
    "citation_3_page": "Cited page number (page_start) of the Board Action Report citation.",
    "amount_source": ("Where `amount` came from: minutes (the motion text) or bar (the "
                      "linked Board Action Report). Empty when amount is empty."),
    "multi_vendor_group": ("One motion can award several vendors; link.py emits one row per "
                           "vendor. This is the primary row's action_id, repeated on every "
                           "member (member action_ids are the primary's plus -v2, -v3, ...). "
                           "Empty on ordinary single-vendor rows."),
    "multi_vendor_n": "How many vendor rows the motion was split into. Empty on ordinary rows.",
    "group_total": ("A joint award's single shared not-to-exceed, repeated on every member row. "
                    "It is not apportioned between members and never appears in `amount` -- "
                    "count it once per multi_vendor_group, never sum it down the column."),
}
for _f in CONTRACT_ACTIONS_SCHEMA["fields"]:
    ACTIONS_COLUMN_NOTES.setdefault(_f["name"], _f.get("doc") or "")
# a few sheet columns are renamed relative to the schema field name
ACTIONS_COLUMN_NOTES.setdefault("program_or_project", ACTIONS_COLUMN_NOTES.get("program_or_project", ""))


# ---------------------------------------------------------------------------
# io helpers
# ---------------------------------------------------------------------------

def read_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# citation URL construction
# ---------------------------------------------------------------------------

def primary_doc_url(doc):
    """The primary-source URL for a documents_classified.jsonl row: the live
    seattleschools.org/SharePoint URL when the document is still reachable
    that way, else the Wayback ``id_`` raw-bytes URL. See module docstring."""
    if not doc:
        return None
    fetch = doc.get("fetch") or {}
    if fetch.get("kind") == "wayback_raw":
        return fetch.get("url") or doc.get("source_url")
    return doc.get("source_url") or fetch.get("url")


def url_with_page(url, page):
    if not url or page is None:
        return url
    return f"{url}#page={page}"


def citation_n(action, n, doc_idx):
    """1-indexed. Returns (doc_id, url_with_page, page) for the nth citation,
    or (None, None, None) if there is no such citation."""
    citations = action.get("citations") or []
    if len(citations) < n:
        return None, None, None
    c = citations[n - 1]
    doc = doc_idx.get(c.get("doc_id"))
    base_url = primary_doc_url(doc)
    page = c.get("page_start")
    return c.get("doc_id"), url_with_page(base_url, page), page


def citation_by_role(action, role, doc_idx):
    """(doc_id, url_with_page, page) for the first citation with this role, or
    (None, None, None)."""
    for c in (action.get("citations") or []):
        if c.get("role") == role:
            doc = doc_idx.get(c.get("doc_id"))
            page = c.get("page_start")
            return c.get("doc_id"), url_with_page(primary_doc_url(doc), page), page
    return None, None, None


def amount_source_of(action):
    """`minutes` | `bar` | None.  link.py sets `amount_source` on every row it
    builds from an E3-filled extract; older `contract_actions.jsonl` files (or
    a corpus that never ran bar_fill.py) have no such key, in which case any
    amount present came from the minutes."""
    if action.get("amount") is None:
        return None
    return action.get("amount_source") or "minutes"


# ---------------------------------------------------------------------------
# actions sheet / contracts.jsonl
# ---------------------------------------------------------------------------

def format_term(start, end):
    if start and end:
        return f"{start} to {end}"
    return start or end or None


def vendor_class_for(action, vendor_idx):
    vid = action.get("vendor_id")
    if vid and vid in vendor_idx:
        return vendor_idx[vid].get("vendor_class")
    return None


def build_action_record(action, vendor_idx, doc_idx):
    """One flat dict per action row, used for the actions sheet, contracts.csv
    and contracts.jsonl (with the original nested `citations` added back in
    for the jsonl output only -- see build_action_records)."""
    c1_doc, c1_url, c1_page = citation_n(action, 1, doc_idx)
    c2_doc, c2_url, c2_page = citation_n(action, 2, doc_idx)
    # The Board Action Report citation is role-addressed, not positional: an
    # unpaired introduction has [intro, bar], a paired action [intro, action,
    # bar], so "the third citation" is not reliably the BAR.
    c3_doc, c3_url, c3_page = citation_by_role(action, "bar", doc_idx)
    vendor_canonical = action.get("vendor_canonical") or action.get("vendor_name")
    return {
        "date": action.get("meeting_date"),
        "school_year": action.get("school_year"),
        "vendor_canonical": vendor_canonical,
        "vendor_raw": action.get("vendor_raw"),
        "vendor_class": vendor_class_for(action, vendor_idx),
        "action_type": action.get("action_type"),
        "amount": action.get("amount"),
        "amount_kind": action.get("amount_kind"),
        "prior_total": action.get("prior_total"),
        "revised_total": action.get("revised_total"),
        "chain_id": action.get("chain_id"),
        "sequence": action.get("sequence"),
        "chain_total_latest": action.get("chain_total_latest"),
        "board_action": action.get("board_action"),
        "vote": action.get("vote"),
        "immediate_action": action.get("immediate_action"),
        "contract_id": action.get("contract_id"),
        "po_number": action.get("po_number"),
        "term": format_term(action.get("term_start"), action.get("term_end")),
        "term_start": action.get("term_start"),
        "term_end": action.get("term_end"),
        "department": action.get("department"),
        "program_or_project": action.get("program_or_project"),
        "fund": action.get("fund"),
        "funding_source_text": action.get("funding_source_text"),
        "procurement_method": action.get("procurement_method"),
        "extractor": action.get("extractor"),
        "paired": action.get("paired"),
        "title": action.get("title"),
        "citation_1_doc_id": c1_doc,
        "citation_1_url": c1_url,
        "citation_1_page": c1_page,
        "citation_2_doc_id": c2_doc,
        "citation_2_url": c2_url,
        "citation_2_page": c2_page,
        "citation_3_doc_id": c3_doc,
        "citation_3_url": c3_url,
        "citation_3_page": c3_page,
        "amount_source": amount_source_of(action),
        "multi_vendor_group": action.get("multi_vendor_group"),
        "multi_vendor_n": action.get("multi_vendor_n"),
        "group_total": action.get("group_total"),
        "action_id": action.get("action_id"),
        # carried through for the AVRO/BigQuery table but not in ACTIONS_HEADERS
        "meeting_id": action.get("meeting_id"),
        "item_no": action.get("item_no"),
        "item_code": action.get("item_code"),
        "section": action.get("section"),
        "era": action.get("era"),
        "vendor_name": action.get("vendor_name"),
        "vendor_id": action.get("vendor_id"),
        "vendor_id_source": action.get("vendor_id_source"),
        "chain_method": action.get("chain_method"),
        "chain_size": action.get("chain_size"),
        "is_root": action.get("is_root"),
        "orphan_amendment": action.get("orphan_amendment"),
        "pair_method": action.get("pair_method"),
        "intro_meeting_id": action.get("intro_meeting_id"),
        "intro_meeting_date": action.get("intro_meeting_date"),
        "intro_item_no": action.get("intro_item_no"),
        "intro_era": action.get("intro_era"),
        "intro_extractor": action.get("intro_extractor"),
        "amount_conflict": action.get("amount_conflict"),
        "unpaired_reason": action.get("unpaired_reason"),
        "llm_confidence": action.get("llm_confidence"),
        "extractor_notes": action.get("extractor_notes"),
        "chain_evidence": (",".join(action["chain_evidence"])
                           if action.get("chain_evidence") else None),
    }


def build_action_records(actions, vendor_idx, doc_idx):
    return [build_action_record(a, vendor_idx, doc_idx) for a in actions]


# ---------------------------------------------------------------------------
# vendors sheet
# ---------------------------------------------------------------------------

def build_vendor_rows(actions, vendor_idx):
    per_year = defaultdict(lambda: {"n_actions": 0, "n_amounts": 0, "amount_sum": 0.0})
    for a in actions:
        vid = a.get("vendor_id")
        if not vid:
            continue
        sy = a.get("school_year") or "unknown"
        g = per_year[(vid, sy)]
        g["n_actions"] += 1
        amt = a.get("amount")
        if amt is not None:
            g["amount_sum"] += float(amt)
            g["n_amounts"] += 1

    totals = defaultdict(lambda: {"n_actions": 0, "n_amounts": 0, "amount_sum": 0.0})
    for (vid, _sy), g in per_year.items():
        t = totals[vid]
        t["n_actions"] += g["n_actions"]
        t["n_amounts"] += g["n_amounts"]
        t["amount_sum"] += g["amount_sum"]

    def meta(vid):
        v = vendor_idx.get(vid, {})
        return v.get("canonical_name"), v.get("vendor_class")

    rows = []
    for (vid, sy), g in per_year.items():
        canonical, klass = meta(vid)
        rows.append({
            "vendor_id": vid, "vendor_canonical": canonical, "vendor_class": klass,
            "school_year": sy, "n_actions": g["n_actions"], "n_amounts": g["n_amounts"],
            "amount_sum": round(g["amount_sum"], 2),
        })
    for vid, t in totals.items():
        canonical, klass = meta(vid)
        rows.append({
            "vendor_id": vid, "vendor_canonical": canonical, "vendor_class": klass,
            "school_year": "ALL YEARS", "n_actions": t["n_actions"], "n_amounts": t["n_amounts"],
            "amount_sum": round(t["amount_sum"], 2),
        })

    rows.sort(key=lambda r: (
        (r["vendor_canonical"] or "").lower(),
        1 if r["school_year"] == "ALL YEARS" else 0,
        r["school_year"],
    ))
    return rows


# ---------------------------------------------------------------------------
# documents sheet
# ---------------------------------------------------------------------------

def build_document_rows(actions, doc_idx, meeting_idx, fetch_idx):
    counts = Counter()
    order = []
    seen = set()
    for a in actions:
        for c in (a.get("citations") or []):
            did = c.get("doc_id")
            if not did:
                continue
            counts[did] += 1
            if did not in seen:
                seen.add(did)
                order.append(did)

    rows = []
    for did in order:
        doc = doc_idx.get(did)
        meeting = meeting_idx.get(doc.get("meeting_id")) if doc else None
        hit = classify.lookup(fetch_idx, did)
        sha256 = hit["prov"].get("sha256") if hit else None
        rows.append({
            "doc_id": did,
            "kind": doc.get("kind") if doc else None,
            "meeting_id": doc.get("meeting_id") if doc else None,
            "meeting_date": doc.get("meeting_date") if doc else None,
            "meeting_title": meeting.get("title") if meeting else None,
            "school_year": doc.get("school_year") if doc else None,
            "url": primary_doc_url(doc),
            "pages": doc.get("pages") if doc else None,
            "sha256": sha256,
            "n_citing_actions": counts[did],
        })
    rows.sort(key=lambda r: ((r["meeting_date"] or ""), r["doc_id"]))
    return rows


# ---------------------------------------------------------------------------
# CSV / XLSX writers
# ---------------------------------------------------------------------------

def write_csv(path, headers, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({h: ("" if row.get(h) is None else row.get(h)) for h in headers})


HYPERLINK_FONT = Font(color="0563C1", underline="single")
HEADER_FONT = Font(bold=True)


def _write_sheet(ws, headers, rows, hyperlink_cols=frozenset()):
    ws.append(headers)
    for cell in ws[1]:
        cell.font = HEADER_FONT
    for row in rows:
        ws.append([row.get(h) for h in headers])
        r = ws.max_row
        for ci, h in enumerate(headers, start=1):
            if h in hyperlink_cols:
                url = row.get(h)
                if url:
                    cell = ws.cell(row=r, column=ci)
                    cell.hyperlink = url
                    cell.font = HYPERLINK_FONT
    for ci, h in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = min(max(12, len(h) + 2), 42)
    ws.freeze_panes = "A2"


def write_xlsx(path, action_rows, vendor_rows, document_rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "actions"
    _write_sheet(ws, ACTIONS_HEADERS, action_rows,
                hyperlink_cols={"citation_1_url", "citation_2_url",
                                "citation_3_url"})
    ws_v = wb.create_sheet("vendors")
    _write_sheet(ws_v, VENDOR_HEADERS, vendor_rows)
    ws_d = wb.create_sheet("documents")
    _write_sheet(ws_d, DOCUMENT_HEADERS, document_rows, hyperlink_cols={"url"})
    wb.save(path)


# ---------------------------------------------------------------------------
# AVRO export (dry-run for --bq; always run so it stays exercised)
# ---------------------------------------------------------------------------

def _to_orm_value(raw, field_type):
    if raw is None or raw == "":
        return None
    if field_type == "decimal":
        try:
            return Decimal(str(raw)).quantize(avro_schema.DECIMAL_QUANT_AMOUNT)
        except (InvalidOperation, ValueError):
            return None
    if field_type == "timestamp":
        if isinstance(raw, datetime):
            return raw
        s = str(raw)[:10]
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return None
    if field_type in ("int", "auto_primary_key"):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    if field_type == "boolean":
        return bool(raw)
    return str(raw)


def rows_to_avro_records(rows, schema):
    for row in rows:
        rec = {}
        for f in schema["fields"]:
            orm_val = _to_orm_value(row.get(f["name"]), f["field_type"])
            rec[f["name"]] = avro_schema.to_avro_value(f, orm_val)
        yield rec


def export_avro(schema, rows, out_path):
    import fastavro

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    parsed = fastavro.parse_schema(avro_schema.to_avro_schema(schema))
    records = list(rows_to_avro_records(rows, schema))
    with open(out_path, "wb") as fh:
        fastavro.writer(fh, parsed, records, codec="zstandard")
    return len(records)


def validate_avro_roundtrip(path, expected_rows):
    import fastavro

    with open(path, "rb") as fh:
        got = list(fastavro.reader(fh))
    if len(got) != expected_rows:
        raise AssertionError(
            f"{path}: wrote {expected_rows} rows but read back {len(got)}")
    return got


# ---------------------------------------------------------------------------
# BigQuery load (never run by this task -- owner-run only, see docstring)
# ---------------------------------------------------------------------------

def bq_load_all(avro_paths_by_table, schemas_by_table, project=BQ_PROJECT,
                dataset=BQ_DATASET, location=BQ_LOCATION):
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    ds_ref = bigquery.Dataset(f"{project}.{dataset}")
    ds_ref.location = location
    client.create_dataset(ds_ref, exists_ok=True)

    results = []
    for table, path in avro_paths_by_table.items():
        table_id = f"{project}.{dataset}.{table}"
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.AVRO,
            write_disposition="WRITE_TRUNCATE")
        with open(path, "rb") as fh:
            job = client.load_table_from_file(fh, table_id, job_config=job_config)
        job.result()
        _set_bq_descriptions(client, project, dataset, table, schemas_by_table[table])
        results.append({"table": table, "rows": job.output_rows})
    return results


def _set_bq_descriptions(client, project, dataset, table, schema):
    from google.cloud import bigquery

    table_id = f"{project}.{dataset}.{table}"
    tbl = client.get_table(table_id)
    tbl.description = schema.get("doc")
    docs = {f["name"]: f.get("doc") for f in schema["fields"]}
    new_cols = []
    for col in tbl.schema:
        d = docs.get(col.name)
        new_cols.append(col if d is None else bigquery.SchemaField(
            col.name, col.field_type, mode=col.mode, description=d, fields=col.fields))
    tbl.schema = new_cols
    client.update_table(tbl, ["description", "schema"])


# ---------------------------------------------------------------------------
# summary / README
# ---------------------------------------------------------------------------

def summarize(action_records, vendor_rows, document_rows):
    lines = []
    lines.append(f"actions: {len(action_records)} rows")
    lines.append(f"vendors: {len(vendor_rows)} rows "
                 f"({len({r['vendor_id'] for r in vendor_rows})} distinct vendors)")
    lines.append(f"documents: {len(document_rows)} rows (cited documents)")

    by_type = Counter()
    for r in action_records:
        by_type[r.get("action_type") or "(none)"] += float(r.get("amount") or 0)
    lines.append("")
    lines.append("total naive amount by action_type:")
    for t, total in sorted(by_type.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {t:<20s} ${total:,.2f}")

    top = [r for r in vendor_rows if r["school_year"] == "ALL YEARS"]
    top.sort(key=lambda r: -(r["amount_sum"] or 0))
    lines.append("")
    lines.append("top 10 vendors by naive all-years amount sum:")
    for r in top[:10]:
        lines.append(f"  {r['vendor_canonical']:<40s} "
                     f"${r['amount_sum']:>14,.2f}  ({r['n_actions']} actions)")

    return "\n".join(lines)


def write_readme(path, summary_text, extra_note=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [
        "# Board contracts -- published spreadsheet + BigQuery tables",
        "",
        "Generated by `extractors/sps_web/publish.py` (task G1). Rerunning "
        "this module regenerates every file here from scratch from "
        "`out_sps_web/contracts/` and `out_sps_web/manifest/`.",
        "",
        "## Summary",
        "",
        "```",
        summary_text,
        "```",
        "",
    ]
    if extra_note:
        lines += [extra_note, ""]
    lines += [
        "## `actions` sheet columns",
        "",
        "| column | meaning |",
        "|---|---|",
    ]
    for h in ACTIONS_HEADERS:
        note = ACTIONS_COLUMN_NOTES.get(h, "").replace("\n", " ")
        lines.append(f"| `{h}` | {note} |")
    lines += [
        "",
        "`amount`/`prior_total`/`revised_total`/`chain_total_latest` are "
        "naive: they mix not-to-exceed, revised-total and increase amounts "
        "and are not a spend figure -- see `contracts/vendors.jsonl`'s "
        "`total_amount_sum_note` and the `amount_sum` column here for the "
        "same caveat rolled up by vendor/year.",
        "",
        "## `vendors` sheet columns",
        "",
        "`vendor_id, vendor_canonical, vendor_class, school_year "
        "(or `ALL YEARS`), n_actions, n_amounts, amount_sum` -- one row per "
        "canonical vendor per school year, plus one `ALL YEARS` total row "
        "per vendor. Multi-vendor motions are counted per member: each vendor "
        "named in a joint award contributes its own action row (see "
        "`multi_vendor_group`), so every awardee shows up here. A joint "
        "award's shared `group_total` is deliberately NOT in `amount_sum` -- "
        "only per-vendor `amount`s are summed.",
        "",
        "## `documents` sheet columns",
        "",
        "`doc_id, kind, meeting_id, meeting_date, meeting_title, "
        "school_year, url, pages, sha256, n_citing_actions` -- one row per "
        "document actually cited by an action row.",
        "",
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def run(root, outdir, do_bq=False):
    contracts_dir = os.path.join(root, "contracts")
    manifest_dir = os.path.join(root, "manifest")

    actions = read_jsonl(os.path.join(contracts_dir, "contract_actions.jsonl"))
    vendors = read_jsonl(os.path.join(contracts_dir, "vendors.jsonl"))
    documents = read_jsonl(os.path.join(manifest_dir, "documents_classified.jsonl"))
    meetings = read_jsonl(os.path.join(manifest_dir, "meetings.jsonl"))

    vendor_idx = {v["vendor_id"]: v for v in vendors if v.get("vendor_id")}
    doc_idx = {d["doc_id"]: d for d in documents if d.get("doc_id")}
    meeting_idx = {m["meeting_id"]: m for m in meetings if m.get("meeting_id")}
    fetch_idx = classify.build_fetch_index(root)

    action_records = build_action_records(actions, vendor_idx, doc_idx)
    vendor_rows = build_vendor_rows(actions, vendor_idx)
    document_rows = build_document_rows(actions, doc_idx, meeting_idx, fetch_idx)

    write_csv(os.path.join(outdir, "contracts.csv"), ACTIONS_HEADERS, action_records)
    write_csv(os.path.join(outdir, "contracts_vendors.csv"), VENDOR_HEADERS, vendor_rows)
    write_csv(os.path.join(outdir, "contracts_documents.csv"), DOCUMENT_HEADERS, document_rows)
    write_xlsx(os.path.join(outdir, "contracts.xlsx"), action_records, vendor_rows, document_rows)

    # contracts.jsonl: the flat record plus the original nested citations,
    # for tools that want full fidelity rather than the 2-citation cap.
    jsonl_rows = []
    for a, rec in zip(actions, action_records):
        row = dict(rec)
        row["citations"] = a.get("citations")
        jsonl_rows.append(row)
    write_jsonl(os.path.join(outdir, "contracts.jsonl"), jsonl_rows)

    avro_dir = os.path.join(outdir, "avro")
    avro_paths = {}
    n_avro = {}
    for schema, rows in (
        (CONTRACT_ACTIONS_SCHEMA, action_records),
        (VENDORS_SCHEMA, vendor_rows),
        (DOCUMENTS_SCHEMA, document_rows),
    ):
        path = os.path.join(avro_dir, f"{schema['name']}.avro")
        n = export_avro(schema, rows, path)
        validate_avro_roundtrip(path, n)
        avro_paths[schema["name"]] = path
        n_avro[schema["name"]] = n

    summary_text = summarize(action_records, vendor_rows, document_rows)
    avro_note = ("## AVRO export (dry-run, validated with fastavro; --bq not run)\n\n" +
                "\n".join(f"- `avro/{t}.avro`: {n} rows" for t, n in n_avro.items()))
    write_readme(os.path.join(outdir, "README.md"), summary_text, avro_note)

    print(summary_text)
    print()
    for t, n in n_avro.items():
        print(f"avro/{t}.avro: {n} rows (round-trip validated)")

    if do_bq:
        schemas_by_table = {s["name"]: s for s in ALL_SCHEMAS}
        results = bq_load_all(avro_paths, schemas_by_table)
        for r in results:
            print(f"bq loaded {r['table']}: {r['rows']} rows")

    return {
        "actions": len(action_records),
        "vendors": len(vendor_rows),
        "documents": len(document_rows),
    }


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Publish board-contracts spreadsheet + BigQuery tables (task G1).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=DEFAULT_ROOT,
                   help=f"input root with contracts/ and manifest/ (default {DEFAULT_ROOT})")
    p.add_argument("--outdir", default=DEFAULT_OUTDIR,
                   help=f"output directory (default {DEFAULT_OUTDIR})")
    p.add_argument("--bq", action="store_true",
                   help="ALSO load the AVRO tables into BigQuery dataset sps_board. "
                        "Needs credentials; owner-run only, never run by CI/agents.")
    return p.parse_args(argv)


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)
    run(args.root, args.outdir, do_bq=args.bq)
    return 0


if __name__ == "__main__":
    sys.exit(main())
