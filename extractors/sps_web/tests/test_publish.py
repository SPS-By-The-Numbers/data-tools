"""Tests for the spreadsheet/BigQuery publish step (extractors.sps_web.publish,
task G1).

Builds a tiny 5-row synthetic corpus (contract_actions.jsonl + the vendor/
document/meeting manifests it joins against) in pytest's tmp_path -- the
same pattern extractors/sps_web/tests/test_link.py uses -- and checks the
things the G1 card calls out explicitly: citation URLs pick the primary
source (live seattleschools.org/SharePoint URL, else the Wayback `id_` URL)
with a `#page=N` fragment, the xlsx makes those real hyperlinks, money cells
in the xlsx are numeric (not strings), and the AVRO export round-trips.
"""

import json
import os

import openpyxl
import pytest

from extractors.sps_web import publish as P


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


@pytest.fixture
def corpus(tmp_path):
    """5 action rows exercising: a wayback_raw citation, a direct citation,
    a sharepoint_download citation, a null-vendor/no-citation row, and a
    second action for the same vendor in a different school year (for the
    vendors sheet's per-year + ALL YEARS rollup)."""
    root = tmp_path / "out"

    documents = [
        {
            "doc_id": "doc-wayback", "kind": "agenda", "meeting_id": "2010-03-03-regular",
            "meeting_date": "2010-03-03", "school_year": "2009-10",
            "source_url": "http://www.seattleschools.org/area/board/030310agenda.pdf",
            "fetch": {"kind": "wayback_raw",
                      "url": "http://web.archive.org/web/20100401000000id_/http://www.seattleschools.org/area/board/030310agenda.pdf"},
            "pages": 12,
        },
        {
            "doc_id": "doc-direct", "kind": "minutes", "meeting_id": "2022-05-04-regular",
            "meeting_date": "2022-05-04", "school_year": "2021-22",
            "source_url": "https://www.seattleschools.org/wp-content/uploads/2022/05/minutes.pdf",
            "fetch": {"kind": "direct",
                      "url": "https://www.seattleschools.org/wp-content/uploads/2022/05/minutes.pdf"},
            "pages": 5,
        },
        {
            "doc_id": "doc-sharepoint", "kind": "packet", "meeting_id": "2023-06-07-regular",
            "meeting_date": "2023-06-07", "school_year": "2022-23",
            "source_url": "https://seattleschools.sharepoint.com/:b:/s/SPSBoardOffice-O365/ABC123?e=xyz",
            "fetch": {"kind": "sharepoint_download",
                      "url": "https://seattleschools.sharepoint.com/sites/SPSBoardOffice-O365/_layouts/15/download.aspx?share=ABC123",
                      "token": "ABC123"},
            "pages": 33,
        },
    ]
    write_jsonl(root / "manifest" / "documents_classified.jsonl", documents)

    meetings = [
        {"meeting_id": "2010-03-03-regular", "date": "2010-03-03", "title": "March 3, 2010 -- Regular Board Meeting"},
        {"meeting_id": "2022-05-04-regular", "date": "2022-05-04", "title": "May 4, 2022 -- Regular Board Meeting"},
        {"meeting_id": "2023-06-07-regular", "date": "2023-06-07", "title": "June 7, 2023 -- Regular Board Meeting"},
    ]
    write_jsonl(root / "manifest" / "meetings.jsonl", meetings)

    vendors = [
        {"vendor_id": "acme-construction", "canonical_name": "Acme Construction Inc.",
         "vendor_class": "contractor"},
    ]
    write_jsonl(root / "contracts" / "vendors.jsonl", vendors)

    def action(**kw):
        base = {
            "meeting_id": "2010-03-03-regular", "meeting_date": "2010-03-03",
            "school_year": "2009-10", "item_no": "A.1", "item_code": None,
            "era": "legacy", "section": "consent", "board_action": "approved",
            "vote": "unanimous", "title": "Some contract", "vendor_raw": "Acme Construction",
            "vendor_name": "Acme Construction", "vendor_id": "acme-construction",
            "vendor_id_source": "map", "vendor_canonical": "Acme Construction Inc.",
            "action_type": "new", "amount": 100000.5, "amount_kind": "not_to_exceed",
            "prior_total": None, "revised_total": None, "contract_id": "C-1",
            "po_number": None, "term_start": None, "term_end": None,
            "department": None, "program_or_project": None, "fund": None,
            "funding_source_text": None, "procurement_method": None,
            "immediate_action": False, "citations": [],
            "paired": True, "pair_method": "title_exact", "intro_meeting_id": None,
            "intro_meeting_date": None, "intro_item_no": None, "intro_era": None,
            "intro_extractor": None, "amount_conflict": False, "unpaired_reason": None,
            "extractor": "regex", "llm_confidence": None, "extractor_notes": None,
            "chain_id": "CH-1", "sequence": 0, "chain_method": "contract_id",
            "chain_size": 1, "chain_total_latest": 100000.5, "is_root": True,
            "orphan_amendment": False, "chain_evidence": None,
            "action_id": "action-1",
        }
        base.update(kw)
        return base

    actions = [
        action(action_id="action-1", citations=[
            {"doc_id": "doc-wayback", "page_start": 3, "page_end": 3, "role": "action"}]),
        action(action_id="action-2", meeting_id="2022-05-04-regular",
              meeting_date="2022-05-04", school_year="2021-22", amount=250000,
              chain_id="CH-2", citations=[
                  {"doc_id": "doc-direct", "page_start": 2, "page_end": 2, "role": "action"}]),
        action(action_id="action-3", meeting_id="2023-06-07-regular",
              meeting_date="2023-06-07", school_year="2022-23", amount=75000,
              chain_id="CH-3", citations=[
                  {"doc_id": "doc-sharepoint", "page_start": 5, "page_end": 6, "role": "action"}]),
        action(action_id="action-4", meeting_id="2023-06-07-regular",
              meeting_date="2023-06-07", school_year="2022-23", amount=None,
              amount_kind=None, chain_id="CH-4", vendor_raw=None, vendor_name=None,
              vendor_id=None, vendor_id_source="none", vendor_canonical=None,
              citations=[]),
        action(action_id="action-5", meeting_id="2023-06-07-regular",
              meeting_date="2023-06-07", school_year="2022-23", amount=1000,
              chain_id="CH-3", sequence=1, citations=[
                  {"doc_id": "doc-sharepoint", "page_start": 5, "page_end": 6, "role": "action"},
                  {"doc_id": "doc-direct", "page_start": 1, "page_end": 1, "role": "introduction"}]),
    ]
    write_jsonl(root / "contracts" / "contract_actions.jsonl", actions)

    return root


def test_citation_urls_pick_primary_source_with_page_fragment(corpus):
    result = P.run(str(corpus), str(corpus / "publish"))
    assert result == {"actions": 5, "vendors": 4, "documents": 3}

    rows = {r["action_id"]: r for r in P.read_jsonl(str(corpus / "publish" / "contracts.jsonl"))}

    # wayback_raw: primary URL is fetch.url (the id_ raw-bytes URL), not source_url
    r1 = rows["action-1"]
    assert r1["citation_1_url"] == (
        "http://web.archive.org/web/20100401000000id_/"
        "http://www.seattleschools.org/area/board/030310agenda.pdf#page=3")
    assert r1["citation_1_page"] == 3

    # direct: primary URL is source_url (the live page)
    r2 = rows["action-2"]
    assert r2["citation_1_url"] == (
        "https://www.seattleschools.org/wp-content/uploads/2022/05/minutes.pdf#page=2")

    # sharepoint_download: primary URL is source_url (the anonymous share link),
    # not the download.aspx endpoint fetch.py actually requested
    r3 = rows["action-3"]
    assert r3["citation_1_url"] == (
        "https://seattleschools.sharepoint.com/:b:/s/SPSBoardOffice-O365/ABC123?e=xyz#page=5")

    # no citations -> both citation columns are null, not KeyErrors/empty strings
    r4 = rows["action-4"]
    assert r4["citation_1_url"] is None and r4["citation_1_page"] is None

    # second citation is also resolved
    r5 = rows["action-5"]
    assert r5["citation_2_url"] == (
        "https://www.seattleschools.org/wp-content/uploads/2022/05/minutes.pdf#page=1")


def test_xlsx_hyperlinks_and_money_types(corpus):
    P.run(str(corpus), str(corpus / "publish"))
    wb = openpyxl.load_workbook(corpus / "publish" / "contracts.xlsx")
    assert wb.sheetnames == ["actions", "vendors", "documents"]

    ws = wb["actions"]
    headers = [c.value for c in ws[1]]
    col = {h: i + 1 for i, h in enumerate(headers)}

    amounts_seen = 0
    for row in ws.iter_rows(min_row=2):
        action_id = row[col["action_id"] - 1].value
        amount_cell = row[col["amount"] - 1]
        if amount_cell.value is not None:
            assert isinstance(amount_cell.value, (int, float)), (
                f"{action_id}: amount cell holds {type(amount_cell.value)}, not a number")
            amounts_seen += 1

        cite_cell = row[col["citation_1_url"] - 1]
        if cite_cell.value:
            assert cite_cell.hyperlink is not None, f"{action_id}: citation_1_url has no hyperlink"
            assert cite_cell.hyperlink.target == cite_cell.value
    assert amounts_seen == 4  # every action but action-4

    # documents sheet: url column is also a real hyperlink
    ws_docs = wb["documents"]
    doc_headers = [c.value for c in ws_docs[1]]
    url_col = doc_headers.index("url") + 1
    seen_doc_hyperlink = False
    for row in ws_docs.iter_rows(min_row=2):
        cell = row[url_col - 1]
        if cell.value:
            assert cell.hyperlink is not None
            seen_doc_hyperlink = True
    assert seen_doc_hyperlink

    # vendors sheet: amount_sum is numeric, and the ALL YEARS row sums the per-year rows
    ws_v = wb["vendors"]
    v_headers = [c.value for c in ws_v[1]]
    v_col = {h: i for i, h in enumerate(v_headers)}
    per_year_total = 0.0
    all_years_total = None
    for row in ws_v.iter_rows(min_row=2, values_only=True):
        if row[v_col["vendor_id"]] != "acme-construction":
            continue
        assert isinstance(row[v_col["amount_sum"]], (int, float))
        if row[v_col["school_year"]] == "ALL YEARS":
            all_years_total = row[v_col["amount_sum"]]
        else:
            per_year_total += row[v_col["amount_sum"]]
    assert all_years_total == pytest.approx(per_year_total)
    assert all_years_total == pytest.approx(100000.5 + 250000 + 75000 + 1000)


def test_avro_export_round_trips(corpus):
    P.run(str(corpus), str(corpus / "publish"))
    avro_dir = corpus / "publish" / "avro"
    for name, expected in (("contract_actions", 5), ("vendors", 4), ("documents", 3)):
        path = avro_dir / f"{name}.avro"
        assert path.exists()
        records = P.validate_avro_roundtrip(str(path), expected)
        assert len(records) == expected


def test_publish_is_rerunnable(corpus):
    """Every output is rewritten from scratch -- running twice must not
    duplicate or accumulate rows."""
    P.run(str(corpus), str(corpus / "publish"))
    result = P.run(str(corpus), str(corpus / "publish"))
    assert result == {"actions": 5, "vendors": 4, "documents": 3}
    rows = P.read_jsonl(str(corpus / "publish" / "contracts.jsonl"))
    assert len(rows) == 5
