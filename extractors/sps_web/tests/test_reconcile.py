"""Synthetic cases for `extractors.sps_web.reconcile` (task H2).

Each test builds a tiny in-memory fixture (no real corpus, no network --
`check_citations` is always called with `no_network=True` here) and calls
the individual `check_*` functions directly, the same way
`tests/test_link.py` exercises `link.py`'s internals.

1. ``test_meeting_coverage_categorizes_reasons`` -- covered / cancelled /
   no_docs / not_fetched / text_failed / fetched_no_agenda_minutes, one
   meeting each.
2. ``test_citations_catch_unresolved_and_page_bounds`` -- a good citation,
   an unresolved doc_id, and a page_end past the document's page count.
3. ``test_money_sanity_flags_bad_rows`` -- negative amount, >$2B amount, an
   amendment with revised_total < amount, amount without amount_kind, and
   a prior+amount != revised_total mismatch, plus one clean row.
4. ``test_vendor_mapping_flags_unmapped_and_unknown_ids`` -- a mapped
   vendor, a not_a_vendor-flagged vendor with no vendor_id, and a
   fallback vendor_id that vendors.jsonl never registered.
5. ``test_pairing_chains_and_key_uniqueness_catch_bugs`` -- a duplicate
   action_id, a non-contiguous chain, an intro dated after its action, and
   a duplicate items key, plus one clean chain.
6. ``test_time_series_flags_multi_year_gap`` -- a 3-year run of zero counts
   between two healthy years. A naive "both *immediate* neighbours > 0"
   test misses every interior year of a multi-year gap (its immediate
   neighbours are also zero); check 6 must walk out to the nearest
   non-zero neighbour on each side to flag it, and separately confirms
   coverage_matrix.md's pending-fetch table explains it.
"""

from __future__ import annotations

from extractors.sps_web import reconcile


def test_meeting_coverage_categorizes_reasons():
    meetings = [
        {"meeting_id": "m-covered", "date": "2020-01-01", "title": "Regular Meeting"},
        {"meeting_id": "m-cancelled", "date": "2020-02-01", "title": "Canceled: Work Session"},
        {"meeting_id": "m-nodocs", "date": "2020-03-01", "title": "Regular Meeting"},
        {"meeting_id": "m-notfetched", "date": "2020-04-01", "title": "Regular Meeting"},
        {"meeting_id": "m-textfailed", "date": "2020-05-01", "title": "Regular Meeting"},
        {"meeting_id": "m-nokind", "date": "2020-06-01", "title": "Regular Meeting"},
    ]
    docs_by_meeting = {
        "m-covered": [{"doc_id": "d1", "kind": "minutes", "has_text": True}],
        "m-notfetched": [{"doc_id": "d2", "kind": None, "has_text": False}],
        "m-textfailed": [{"doc_id": "d3", "kind": "agenda", "has_text": False}],
        "m-nokind": [{"doc_id": "d4", "kind": "warrants", "has_text": True}],
    }
    c = reconcile.check_meeting_coverage(meetings, docs_by_meeting)
    counts = dict(c.counts)
    assert counts["covered (agenda/minutes with text)"] == 1
    assert counts["cancelled"] == 1
    assert counts["no docs in manifest"] == 1
    assert counts["not fetched/classified yet (crawl in progress)"] == 1
    assert counts["fetched but text extraction failed"] == 1
    assert counts["fetched+classified, but no agenda/minutes kind"] == 1
    # a genuine (non-provisional) gap -> WARN or FAIL, never a silent PASS
    assert c.status in ("WARN", "FAIL")
    assert any("m-textfailed" in ex for ex in c.examples)
    assert any("m-nokind" in ex for ex in c.examples)


def test_citations_catch_unresolved_and_page_bounds():
    doc_index = {
        "docA": {"doc_id": "docA", "source_url": "https://example.org/a.pdf",
                 "fetch": {"kind": "direct", "url": "https://example.org/a.pdf"}},
    }
    pages_by_doc = {"docA": 5}
    actions = [
        {"action_id": "good-1", "citations": [{"doc_id": "docA", "page_start": 1, "page_end": 2}]},
        {"action_id": "bad-missing-doc", "citations": [{"doc_id": "doc-nowhere", "page_start": 1, "page_end": 1}]},
        {"action_id": "bad-page-bounds", "citations": [{"doc_id": "docA", "page_start": 4, "page_end": 9}]},
    ]
    c = reconcile.check_citations(actions, doc_index, pages_by_doc, sample_n=0, no_network=True, seed=1)
    assert c.status == "FAIL"
    counts = dict(c.counts)
    assert counts["doc_id not found in manifest"] == 1
    assert counts["page_start/page_end out of [1, pages] (pages known)"] == 1
    assert any("doc-nowhere" in ex for ex in c.examples)
    assert any("bad-page-bounds" in ex for ex in c.examples)


def test_money_sanity_flags_bad_rows():
    actions = [
        {"action_id": "clean", "amount": 100.0, "amount_kind": "not_to_exceed",
         "action_type": "new", "prior_total": None, "revised_total": None},
        {"action_id": "neg", "amount": -5.0, "amount_kind": "not_to_exceed", "action_type": "new"},
        {"action_id": "huge", "amount": 5_000_000_000.0, "amount_kind": "not_to_exceed", "action_type": "new"},
        {"action_id": "revised-lt", "amount": 100.0, "amount_kind": "increase",
         "action_type": "amendment", "revised_total": 50.0},
        {"action_id": "no-kind", "amount": 100.0, "amount_kind": None, "action_type": "new"},
        {"action_id": "sum-mismatch", "amount": 100.0, "amount_kind": "increase", "action_type": "amendment",
         "prior_total": 200.0, "revised_total": 999.0},
    ]
    c = reconcile.check_money(actions)
    assert c.status == "FAIL"
    counts = dict(c.counts)
    assert counts["negative amount"] == 1
    assert counts["amount > $2,000,000,000"] == 1
    assert counts["amendment/change_order with revised_total < amount"] == 1
    assert counts["amount present, amount_kind null"] == 1
    assert counts["rows with prior_total + amount + revised_total all present"] == 1
    assert counts["...of those, prior_total + amount != revised_total"] == 1
    assert any("neg" in ex for ex in c.examples)
    assert any("huge" in ex for ex in c.examples)
    assert any("sum-mismatch" in ex for ex in c.examples)


def test_vendor_mapping_flags_unmapped_and_unknown_ids():
    vendors_rows = [{"vendor_id": "acme-inc", "canonical_name": "Acme Inc."}]
    vendor_map_rows = [
        {"vendor_raw": "Acme, Inc.", "vendor_id": "acme-inc", "vendor_class": "contractor"},
        {"vendor_raw": "Board of Directors", "vendor_id": None, "vendor_class": "not_a_vendor"},
    ]
    actions = [
        {"action_id": "ok", "vendor_raw": "Acme, Inc.", "vendor_id": "acme-inc",
         "vendor_id_source": "vendor_map"},
        {"action_id": "not-a-vendor-ok", "vendor_raw": "Board of Directors", "vendor_id": None,
         "vendor_id_source": "none"},
        {"action_id": "stale-fallback", "vendor_raw": "Some New Vendor LLC", "vendor_id": "some-new-vendor",
         "vendor_id_source": "fallback"},
    ]
    c = reconcile.check_vendors(actions, vendors_rows, vendor_map_rows)
    assert c.status in ("WARN", "FAIL")
    counts = dict(c.counts)
    assert counts["vendor_id set but missing from vendors.jsonl"] == 1
    assert counts["vendor_raw flagged not_a_vendor"] == 1
    assert any("stale-fallback" in ex for ex in c.examples)
    assert not any("not-a-vendor-ok" in ex for ex in c.examples)


def test_pairing_chains_and_key_uniqueness_catch_bugs():
    actions = [
        {"action_id": "dup-1", "chain_id": "CH-1", "sequence": 0,
         "meeting_date": "2020-01-15", "paired": False},
        {"action_id": "dup-1", "chain_id": "CH-2", "sequence": 0,
         "meeting_date": "2020-01-15", "paired": False},
        {"action_id": "gap-a", "chain_id": "CH-3", "sequence": 0, "paired": False},
        {"action_id": "gap-b", "chain_id": "CH-3", "sequence": 2, "paired": False},
        {"action_id": "backwards-intro", "chain_id": "CH-4", "sequence": 0, "paired": True,
         "meeting_date": "2020-01-01", "intro_meeting_date": "2020-06-01"},
        {"action_id": "clean-1", "chain_id": "CH-5", "sequence": 0, "paired": True,
         "meeting_date": "2020-06-01", "intro_meeting_date": "2020-01-01"},
        {"action_id": "clean-2", "chain_id": "CH-5", "sequence": 1, "paired": False},
    ]
    c = reconcile.check_pairing_chains(actions)
    assert c.status == "FAIL"
    counts = dict(c.counts)
    assert counts["duplicate action_id groups"] == 1
    assert counts["chains with non-contiguous sequence"] == 1
    assert counts["paired rows with intro dated after action"] == 1
    assert any("dup-1" in ex for ex in c.examples)
    assert any("CH-3" in ex for ex in c.examples)
    assert any("backwards-intro" in ex for ex in c.examples)

    items = [
        {"meeting_id": "2020-01-15-regular", "item_no": "A.1", "char_start": 100},
        {"meeting_id": "2020-01-15-regular", "item_no": "A.1", "char_start": 100},  # duplicate key
        {"meeting_id": "2020-01-15-regular", "item_no": "A.2", "char_start": 500},
    ]
    ku = reconcile.check_key_uniqueness(actions, items)
    assert ku.status == "FAIL"
    ku_counts = dict(ku.counts)
    assert ku_counts["duplicate action_id values"] == 1
    assert ku_counts["duplicate (meeting_id, item_no, char_start) keys"] == 1


def test_time_series_flags_multi_year_gap():
    # 2010-11 healthy, 2011-12..2013-14 a 3-year all-zero gap, 2014-15 healthy.
    meetings = [{"meeting_id": f"m-{y}", "date": f"{y}-09-01", "title": "Regular Meeting"}
                for y in range(2010, 2015)]
    actions = (
        [{"school_year": "2010-11"}] * 20
        + [{"school_year": "2014-15"}] * 18
    )
    extracted = (
        [{"meeting_date": "2010-09-01"}] * 25
        + [{"meeting_date": "2014-09-01"}] * 22
    )
    # unexplained: no coverage_matrix.md pending-fetch data at all
    c = reconcile.check_time_series(actions, extracted, meetings, pending_by_year={})
    counts = dict(c.counts)
    assert counts["years with a >50% dip vs. both neighbours"] == 3
    assert counts["...NOT explained"] == 3
    assert c.status == "FAIL"
    assert any("2012-13" in ex for ex in c.examples)

    # same gap, but coverage_matrix.md says those years have docs pending fetch
    pending = {"2011-12": 40, "2012-13": 171, "2013-14": 178}
    c2 = reconcile.check_time_series(actions, extracted, meetings, pending_by_year=pending)
    counts2 = dict(c2.counts)
    assert counts2["years with a >50% dip vs. both neighbours"] == 3
    assert counts2["...explained by coverage_matrix.md pending-fetch counts"] == 3
    assert counts2["...NOT explained"] == 0
    assert c2.status == "WARN"
