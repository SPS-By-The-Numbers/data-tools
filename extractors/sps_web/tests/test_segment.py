"""Fixture tests for `extractors.sps_web.segment` (task D1).

Each fixture in ``fixtures/items/<meeting_id>.expected.jsonl`` is the
hand-checked item list for one real meeting, one JSON object per item with the
fields a human can verify from the PDF: ``item_no, section, result, vote,
page_start, title``.  The test re-runs the segmenter over that meeting's source
document and compares.

Fixtures cover four of the five format families described in
``segment.py``'s docstring:

    (a) modern minutes 2021+          2024-10-09, 2022-08-31, 2025-03-25
    (b) WP-era minutes 2016-2021      2019-09-18, 2018-08-29, 2020-04-29
    (d) archive edited agendas        2009-08-19, 2011-08-17, 2007-08-01
    (c) Blackboard 2011-12 -> 2015-16 2013-01-23, 2014-03-19, 2015-09-23
    (e) legacy minutes and agendas    2005-09-21, 2006-05-17, 2008-01-09

The tests skip (rather than fail) when `out_sps_web/` is not present or the
source document has not been fetched/extracted yet, so the suite stays green on
a checkout without the generated corpus.
"""

from __future__ import annotations

import json
import os

import pytest

from extractors.sps_web import segment

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "items")
COMPARED = ("item_no", "section", "result", "vote", "page_start", "title",
            "source_kind")


def fixture_ids() -> list[str]:
    if not os.path.isdir(FIXTURE_DIR):
        return []
    return sorted(f[: -len(".expected.jsonl")] for f in os.listdir(FIXTURE_DIR)
                  if f.endswith(".expected.jsonl"))


def load_expected(meeting_id: str) -> list[dict]:
    path = os.path.join(FIXTURE_DIR, f"{meeting_id}.expected.jsonl")
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    """Segment every fixture meeting once; returns meeting_id -> rows."""
    if not os.path.isdir(segment.TEXT_DIR):
        pytest.skip("out_sps_web/text is not present in this checkout")
    scratch = tmp_path_factory.mktemp("segment_items")
    out = {}
    for meeting_id in fixture_ids():
        stats = segment.segment_corpus(
            era=None, meeting_filter=meeting_id, limit=None,
            out_dir=str(scratch))
        out[meeting_id] = [r for r in stats["items"] if r["meeting_id"] == meeting_id]
    return out


@pytest.mark.parametrize("meeting_id", fixture_ids())
def test_items_match_fixture(corpus, meeting_id):
    expected = load_expected(meeting_id)
    got = corpus.get(meeting_id) or []
    if not got:
        pytest.skip(f"{meeting_id}: source document not fetched/extracted yet")

    got_slim = [{k: r[k] for k in COMPARED} for r in got]
    assert [r["item_no"] for r in got_slim] == [r["item_no"] for r in expected], (
        f"{meeting_id}: item numbers differ")
    for exp, act in zip(expected, got_slim):
        assert act == exp, f"{meeting_id}: item {exp['item_no']} differs"


@pytest.mark.parametrize("meeting_id", fixture_ids())
def test_offsets_are_exact(corpus, meeting_id):
    """page_start/page_end must equal 1 + form-feeds before the offset, and the
    char range must actually contain the item's title words."""
    got = corpus.get(meeting_id) or []
    if not got:
        pytest.skip(f"{meeting_id}: source document not fetched/extracted yet")
    index = segment.build_text_index()
    for row in got:
        path = index[row["source_doc_id"]]
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        assert 0 <= row["char_start"] < row["char_end"] <= len(text)
        assert row["page_start"] == 1 + text.count("\f", 0, row["char_start"])
        assert row["page_end"] == 1 + text.count("\f", 0, row["char_end"] - 1)
        assert row["page_end"] >= row["page_start"]
        slice_words = segment.norm_ws(text[row["char_start"]:row["char_end"]]).lower()
        first_words = " ".join(row["title"].split()[:3]).lower()
        assert first_words[:20] in slice_words, (
            f"{meeting_id} {row['item_no']}: title not inside its char range")


@pytest.mark.parametrize("meeting_id", fixture_ids())
def test_row_schema(corpus, meeting_id):
    got = corpus.get(meeting_id) or []
    if not got:
        pytest.skip(f"{meeting_id}: source document not fetched/extracted yet")
    for row in got:
        assert row["section"] in segment.SECTIONS
        assert row["result"] in segment.RESULTS
        assert row["source_kind"] in ("minutes", "agenda")
        assert row["meeting_id"] == meeting_id
        assert row["meeting_date"] == meeting_id[:10]
        assert row["title"]
        # motion_text is what E1's regexes run on; it must be part of the body
        assert row["motion_text"] in row["body"]


def test_no_fixture_directory_regression():
    assert fixture_ids(), "fixtures/items is empty -- fixtures were lost"


# --- unit tests for the pieces that are easy to get wrong ------------------

@pytest.mark.parametrize("stem,expected", [
    # the leading date is the meeting where the minutes were approved
    ("C01_20191002_Minutes_20190918", "2019-09-18"),
    ("Approved_C01_20200826_Minutes_20200805_REVISED20200825_Clean", "2020-08-05"),
    ("20200527_Minutes_OFFICIAL_ADA-for-Posting", "2020-05-27"),
    ("20191106_Minutes_OFFICIAL_Updated20191120", "2019-11-06"),
    ("20251119_RBM_Minutes_rev20251205", "2025-11-19"),
    # legacy / archive MMDDYY stems
    ("010908agenda", "2008-01-09"),
    ("edited-081909agenda", "2009-08-19"),
    ("092105minutes", "2005-09-21"),
    ("edited-20110817-Agenda", "2011-08-17"),
    ("", None),
])
def test_filename_subject_date(stem, expected):
    assert segment.filename_subject_date(stem) == expected


@pytest.mark.parametrize("stem,posting,expected", [
    # an item-coded stem with ONE date that IS the posting meeting cannot name
    # the subject meeting -- the caller must fall back to the page header
    ("C01_20221012_Minutes", "2022-10-12", None),
    # ... but the same shape with a date that is NOT the posting meeting does
    ("C02_20160824_Minutes_FINAL", "2016-09-07", "2016-08-24"),
    # MMDDYYYY tail (2016-17 habit)
    ("C01_20170517_Minutes_04202017", "2017-05-17", "2017-04-20"),
    ("C01_20191002_Minutes_20190918", "2019-10-02", "2019-09-18"),
])
def test_filename_subject_date_with_posting(stem, posting, expected):
    assert segment.filename_subject_date(stem, posting) == expected


@pytest.mark.parametrize("stem,draft", [
    ("20180829_Unofficial_Minutes", True),
    ("20190918_Minutes_UNOFFICIAL", True),
    ("20160601_Minutes_Draft_v2", True),
    ("C01_20180905_Minutes_20180829", False),
    ("20150923_Minutes", False),
])
def test_is_draft(stem, draft):
    assert segment.is_draft({"resolved_filename": stem + ".pdf"}, "") is draft


def test_official_wp_copy_beats_longer_unofficial_blackboard_copy():
    official = {"resolved_filename": "C01_20180905_Minutes_20180829.pdf", "era": "wp"}
    unofficial = {"resolved_filename": "20180829_Unofficial_Minutes.pdf",
                  "era": "blackboard"}
    assert (segment.source_rank(official, "x" * 100)
            > segment.source_rank(unofficial, "x" * 100000))


def test_agenda_supplement_is_marked_and_ordered():
    """2007-08-01: the minutes omit action item C.4, which only the archive
    agenda records; it must appear once, from the agenda, in printed order."""
    rows = load_expected("2007-08-01-regular")
    c4 = [r for r in rows if r["item_no"] == "C.4"]
    assert len(c4) == 1 and c4[0]["source_kind"] == "agenda"
    assert [r["item_no"] for r in rows[6:11]] == ["C.1", "C.2", "C.3", "C.4", "D.1"]
    assert all(r["source_kind"] == "minutes"
               for r in rows if r["item_no"] != "C.4")


@pytest.mark.parametrize("block,result,vote", [
    ("This motion passed with a vote of 5-0-1 (Directors ... voted yes).",
     "approved", "5-0-1"),
    ("This item was approved with a vote of 6-1 (...).", "approved", "6-1"),
    ("The motion to approve the Consent Agenda as amended was approved "
     "unanimously (Directors ... voted yes).", "approved", "unanimous"),
    ("This item passed unanimously.", "approved", "unanimous"),
    ("This motion did not pass.", "failed", None),
    ("The motion to postpone consideration was approved.", "postponed", None),
    # an amendment sub-motion must never decide the item
    ("The motion to approve Amendment 1 did not pass.", "unknown", None),
    ("Directors and staff discussed the item.", "unknown", None),
])
def test_decide_result(block, result, vote):
    got_result, got_vote = segment.decide_result(block)
    assert got_result == result
    if result != "unknown":
        assert got_vote == vote


def test_amendment_then_item_result():
    """The last item-level sentence wins; the amendment vote does not."""
    block = ("Director Sarju moved to approve this item. Director Briggs seconded. "
             "The motion to amend the item was approved unanimously (Directors "
             "Briggs, Clark voted yes). "
             "This item was approved as amended with a vote of 6-1 (...).")
    assert segment.decide_result(block) == ("approved", "6-1")
