"""Hand-built cases for `extractors.sps_web.link` (task F2).

Nothing here touches the real corpus: every case is a tiny synthetic
``extracted.jsonl`` written into ``tmp_path``, so the whole file runs in
milliseconds and the expected behaviour is legible next to the assertion.

The eight cases mirror the F2 card:

1. ``test_paired_by_exact_title``      -- the ordinary two-meeting item
2. ``test_unpaired_outside_date_window`` -- 90 days apart: no pair, reason logged
3. ``test_immediate_action_passes_through`` -- ``paired`` is null, not false
4. ``test_removed_item_and_revote``    -- an "Items Removed" re-vote is one
   action row; a genuinely *removed* item is a pass-through
5. ``test_ambiguous_candidates_are_not_paired`` -- two equally-close targets
6. ``test_chain_by_contract_id``       -- new -> amendment -> final acceptance
7. ``test_chain_by_vendor_project``    -- no ids, same vendor + project phrase
8. ``test_orphan_amendment``           -- amendment with no root in its chain

plus two structural checks (merge precedence / both citations, and that
``chain_id`` is unique per chain).
"""

from __future__ import annotations

import json
import os

import pytest

from extractors.sps_web import link


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def row(meeting_date, section, title, **kw):
    """One `extracted.jsonl` row with every field the module reads."""
    r = {
        "meeting_id": "%s-regular" % meeting_date,
        "meeting_date": meeting_date,
        "item_no": kw.pop("item_no", "A.1"),
        "item_code": kw.pop("item_code", None),
        "char_start": kw.pop("char_start", 1000),
        "era": kw.pop("era", "modern"),
        "section": section,
        "title": title,
        "board_action": kw.pop(
            "board_action", "introduced" if section == "introduction" else "approved"),
        "vote": kw.pop("vote", None if section == "introduction" else "unanimous"),
        "vendor_raw": None,
        "vendor_name": None,
        "action_type": "new",
        "amount": None,
        "amount_kind": None,
        "prior_total": None,
        "revised_total": None,
        "contract_id": None,
        "po_number": None,
        "term_start": None,
        "term_end": None,
        "department": None,
        "program_or_project": None,
        "immediate_action": section == "immediate",
        "fund": None,
        "funding_source_text": None,
        "procurement_method": None,
        "llm_confidence": None,
        "citation": {"doc_id": "doc-%s" % meeting_date, "page_start": 2, "page_end": 2},
        "extractor": "regex",
        "extractor_notes": None,
    }
    r.update(kw)
    return r


def run_link(tmp_path, rows):
    """Run the module over `rows` and return (actions, chains-by-id)."""
    out_root = str(tmp_path / "out")
    src = str(tmp_path / "extracted.jsonl")
    os.makedirs(os.path.dirname(src), exist_ok=True)
    with open(src, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    actions, chains = link.run(out_root=out_root, extracted=src)
    assert os.path.exists(os.path.join(out_root, "contracts", "contract_actions.jsonl"))
    assert os.path.exists(os.path.join(out_root, "qa", "link_report.md"))
    return actions, {cid: group for cid, group in chains}


def only(rows, **match):
    hits = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, "expected exactly 1 row matching %r, got %d" % (match, len(hits))
    return hits[0]


# --------------------------------------------------------------------------
# 1. the ordinary paired item
# --------------------------------------------------------------------------
def test_paired_by_exact_title(tmp_path):
    title = "BTA V: Award Construction Contract P5200 to Acme Builders, Inc."
    rows = [
        row("2024-01-10", "introduction", title, item_no="D.3",
            vendor_raw="Acme Builders, Inc.", amount=1000000.0,
            contract_id="P5200", department="Capital Projects"),
        row("2024-01-24", "consent", title, item_no="A.7",
            vendor_raw="Acme Builders, Inc.", amount=1050000.0, vote="7-0"),
    ]
    actions, _ = run_link(tmp_path, rows)
    assert len(actions) == 1
    a = actions[0]
    assert a["paired"] is True
    assert a["pair_method"] == "title_exact"
    # the event comes from the action meeting ...
    assert a["meeting_date"] == "2024-01-24"
    assert a["item_no"] == "A.7"
    assert a["board_action"] == "approved"
    assert a["vote"] == "7-0"
    # ... the detail is the union, action wins on conflict ...
    assert a["amount"] == 1050000.0          # action row's amount, not the intro's
    assert a["amount_conflict"] is True
    assert a["department"] == "Capital Projects"  # only the intro had it
    assert a["contract_id"] == "P5200"
    # ... and both citations are kept, introduction first.
    assert [c["role"] for c in a["citations"]] == ["introduction", "action"]
    assert a["citations"][0]["doc_id"] == "doc-2024-01-10"
    assert a["citations"][1]["doc_id"] == "doc-2024-01-24"
    assert a["intro_meeting_date"] == "2024-01-10"
    assert a["action_id"].startswith("2024-01-24-A7-")
    assert a["school_year"] == "2023-24"


def test_action_id_is_stable_across_runs(tmp_path):
    rows = [
        row("2024-01-10", "introduction", "Approval of a contract with Acme Testing Services"),
        row("2024-01-24", "consent", "Approval of a contract with Acme Testing Services"),
    ]
    first, _ = run_link(tmp_path, rows)
    second, _ = run_link(tmp_path / "again", rows)
    assert first[0]["action_id"] == second[0]["action_id"]


# --------------------------------------------------------------------------
# 2. outside the date window
# --------------------------------------------------------------------------
def test_unpaired_outside_date_window(tmp_path):
    title = "Approval of a services contract with Northwest Learning Partners"
    rows = [
        row("2024-01-10", "introduction", title, item_no="D.1"),
        row("2024-04-10", "consent", title, item_no="A.2"),   # 91 days later
    ]
    actions, _ = run_link(tmp_path, rows)
    assert len(actions) == 2
    intro = only(actions, meeting_date="2024-01-10")
    assert intro["paired"] is False
    assert intro["board_action"] == "introduced"
    assert intro["pair_method"] is None
    assert "60-day window" in intro["unpaired_reason"]
    # the action row survives on its own, with only its own citation
    act = only(actions, meeting_date="2024-04-10")
    assert act["paired"] is False
    assert [c["role"] for c in act["citations"]] == ["action"]


# --------------------------------------------------------------------------
# 3. immediate action
# --------------------------------------------------------------------------
def test_immediate_action_passes_through(tmp_path):
    rows = [
        row("2024-02-14", "immediate",
            "Approval of an emergency roofing contract with Storm Roofing LLC",
            vendor_raw="Storm Roofing LLC", amount=250000.0),
    ]
    actions, _ = run_link(tmp_path, rows)
    assert len(actions) == 1
    a = actions[0]
    assert a["paired"] is None          # null, not False -- nothing to pair
    assert a["board_action"] == "approved"
    assert a["immediate_action"] is True
    assert len(a["citations"]) == 1


# --------------------------------------------------------------------------
# 4. removed from consent, re-voted
# --------------------------------------------------------------------------
def test_removed_item_and_revote(tmp_path):
    title = "Approval of the transportation services contract with Rider Bus Co"
    rows = [
        row("2024-03-06", "introduction", title, item_no="D.2"),
        # pulled from the consent agenda and voted separately: ONE action row
        row("2024-03-20", "action", title, item_no="B.1", board_action="approved",
            vote="5-2"),
        # a different item that was removed from the agenda entirely: no vote
        row("2024-03-20", "consent", "Approval of a lease with Harbor Properties",
            item_no="A.9", board_action="removed", vote=None),
    ]
    actions, _ = run_link(tmp_path, rows)
    assert len(actions) == 2
    revote = only(actions, item_no="B.1")
    assert revote["paired"] is True
    assert revote["vote"] == "5-2"
    assert revote["section"] == "action"
    removed = only(actions, item_no="A.9")
    assert removed["paired"] is None    # not an action: passes through
    assert removed["board_action"] == "removed"


# --------------------------------------------------------------------------
# 5. ambiguity is never broken arbitrarily
# --------------------------------------------------------------------------
def test_ambiguous_candidates_are_not_paired(tmp_path):
    title = "Approval of a contract with Puget Sound Educational Service District"
    rows = [
        row("2024-05-01", "introduction", title, item_no="D.1"),
        row("2024-05-15", "consent", title, item_no="A.1", char_start=100),
        row("2024-05-15", "consent", title, item_no="A.2", char_start=200),
    ]
    actions, _ = run_link(tmp_path, rows)
    assert len(actions) == 3
    intro = only(actions, meeting_date="2024-05-01")
    assert intro["paired"] is False
    assert "ambiguous" in intro["unpaired_reason"]
    assert all(a["paired"] is False for a in actions)


# --------------------------------------------------------------------------
# 6. chain by contract id
# --------------------------------------------------------------------------
def test_chain_by_contract_id(tmp_path):
    rows = [
        row("2020-06-10", "consent", "BEX V: Award Construction Contract P5145 to Fieldworks",
            contract_id="P5145", vendor_raw="Fieldworks Inc.", action_type="new",
            amount=757256.0),
        row("2021-03-10", "consent", "BEX V: Amend Contract P-5145 with Fieldworks",
            contract_id="P-5145", vendor_raw="Fieldworks Inc.", action_type="amendment",
            amount=42000.0, prior_total=757256.0, revised_total=799256.0),
        row("2022-01-12", "consent", "BEX V: Final Acceptance of Contract P5145",
            contract_id="P5145", vendor_raw="Fieldworks Inc.",
            action_type="final_acceptance"),
    ]
    actions, chains = run_link(tmp_path, rows)
    assert len(actions) == 3
    assert len({a["chain_id"] for a in actions}) == 1        # "P-5145" normalizes to "P5145"
    assert all(a["chain_method"] == "id" for a in actions)
    seqs = {a["meeting_date"]: a["sequence"] for a in actions}
    assert seqs == {"2020-06-10": 0, "2021-03-10": 1, "2022-01-12": 2}
    root = only(actions, sequence=0)
    assert root["is_root"] is True
    assert root["action_type"] == "new"
    assert all(a["chain_size"] == 3 for a in actions)
    # last known revised_total wins over the root amount
    assert all(a["chain_total_latest"] == 799256.0 for a in actions)
    assert not any(a["orphan_amendment"] for a in actions)


def test_chain_total_falls_back_to_root_amount(tmp_path):
    rows = [
        row("2020-06-10", "consent", "Award Contract K9000 to Bright Path Services",
            contract_id="K9000", action_type="new", amount=500000.0),
        row("2021-06-10", "consent", "Final Acceptance of Contract K9000",
            contract_id="K9000", action_type="final_acceptance"),
    ]
    actions, _ = run_link(tmp_path, rows)
    assert {a["chain_total_latest"] for a in actions} == {500000.0}


# --------------------------------------------------------------------------
# 7. chain by vendor + project
# --------------------------------------------------------------------------
def test_chain_by_vendor_project(tmp_path):
    rows = [
        row("2019-09-04", "consent",
            "Approval of the Yellow Wood Academy services contract",
            vendor_raw="Yellow Wood Academy", action_type="new", amount=900000.0),
        row("2020-11-04", "consent",
            "Approval of the Yellow Wood Academy services contract amendment",
            vendor_raw="Yellow Wood Academy, Inc.", action_type="amendment",
            amount=100000.0),
        # same project phrase, different vendor -> must NOT join
        row("2021-11-04", "consent",
            "Approval of the Yellow Wood Academy services contract amendment",
            vendor_raw="Gersh Academy", action_type="amendment", amount=50000.0),
    ]
    actions, _ = run_link(tmp_path, rows)
    yw = [a for a in actions if "Yellow Wood" in (a["vendor_raw"] or "")]
    other = only(actions, vendor_raw="Gersh Academy")
    assert len({a["chain_id"] for a in yw}) == 1
    assert yw[0]["chain_method"] == "vendor_project"
    # "Yellow Wood Academy" and "Yellow Wood Academy, Inc." collapse to one key
    assert len({a["vendor_id"] for a in yw}) == 1
    assert other["chain_id"] != yw[0]["chain_id"]
    assert other["chain_method"] == "singleton"


def test_money_continuity_links_a_chain_without_a_shared_project_phrase(tmp_path):
    rows = [
        row("2019-09-04", "consent",
            "Approval of a professional services agreement with Cascade Engineering Group",
            vendor_raw="Cascade Engineering Group", action_type="new", amount=400000.0,
            revised_total=400000.0),
        row("2020-03-04", "consent",
            "Authorization to increase the scope of the Rainier Beach field study",
            vendor_raw="Cascade Engineering Group", action_type="amendment",
            amount=75000.0, prior_total=400000.0, revised_total=475000.0),
    ]
    actions, _ = run_link(tmp_path, rows)
    assert len({a["chain_id"] for a in actions}) == 1
    assert all(a["chain_method"] == "vendor_project" for a in actions)
    assert "money_continuity" in actions[0]["chain_evidence"]
    assert {a["chain_total_latest"] for a in actions} == {475000.0}


def test_id_blocks_are_not_dragged_into_vendor_project_clusters(tmp_path):
    """A bad `contract_id` on one row must not merge two unrelated contracts."""
    rows = [
        row("2019-06-12", "consent", "Award Construction Contract K5111 to Wayne Roofing",
            contract_id="K5111", vendor_raw="Wayne Roofing, Inc.", action_type="new",
            amount=950000.0),
        # upstream mis-stamped K5111 on an unrelated vendor's amendment
        row("2022-05-18", "consent", "Amend the Yellow Wood Academy contract",
            contract_id="K5111", vendor_raw="Yellow Wood Academy", action_type="amendment",
            amount=100000.0),
        row("2023-08-30", "consent", "Amend the Yellow Wood Academy contract",
            vendor_raw="Yellow Wood Academy", action_type="amendment", amount=120000.0),
    ]
    actions, _ = run_link(tmp_path, rows)
    idless = only(actions, meeting_date="2023-08-30")
    wayne = only(actions, meeting_date="2019-06-12")
    assert idless["chain_id"] != wayne["chain_id"]
    assert idless["chain_method"] == "singleton"


# --------------------------------------------------------------------------
# 8. orphan amendment
# --------------------------------------------------------------------------
def test_orphan_amendment(tmp_path):
    rows = [
        row("2018-04-04", "consent",
            "Approval of a contract amendment with Emerald Learning Center",
            vendor_raw="Emerald Learning Center", action_type="amendment",
            amount=414407.0, revised_total=1200000.0),
    ]
    actions, _ = run_link(tmp_path, rows)
    a = actions[0]
    assert a["chain_method"] == "singleton"
    assert a["chain_size"] == 1
    assert a["sequence"] == 0
    assert a["orphan_amendment"] is True
    assert a["is_root"] is True          # nothing better to point at
    assert a["chain_total_latest"] == 1200000.0
    report = (tmp_path / "out" / "qa" / "link_report.md").read_text()
    assert "Orphan amendments (1)" in report


def test_amendment_after_a_root_is_not_an_orphan(tmp_path):
    rows = [
        row("2018-01-04", "consent", "Award Contract P7000 to Emerald Learning Center",
            contract_id="P7000", vendor_raw="Emerald Learning Center",
            action_type="new", amount=800000.0),
        row("2018-04-04", "consent", "Amend Contract P7000 with Emerald Learning Center",
            contract_id="P7000", vendor_raw="Emerald Learning Center",
            action_type="amendment", amount=414407.0),
    ]
    actions, _ = run_link(tmp_path, rows)
    assert not any(a["orphan_amendment"] for a in actions)


# --------------------------------------------------------------------------
# vendor map: F1's output is used when present, fallback when not
# --------------------------------------------------------------------------
def test_vendor_map_is_used_when_present(tmp_path):
    out_root = tmp_path / "out"
    (out_root / "contracts").mkdir(parents=True)
    (out_root / "contracts" / "vendor_map.jsonl").write_text(
        json.dumps({"vendor_raw": "KCDA", "vendor_id": "king-county-directors-association"})
        + "\n"
        + json.dumps({"vendor_raw": "King County Directors' Association",
                      "vendor_id": "king-county-directors-association"}) + "\n")
    (out_root / "contracts" / "vendors.jsonl").write_text(
        json.dumps({"vendor_id": "king-county-directors-association",
                    "vendor_name": "King County Directors' Association"}) + "\n")
    src = tmp_path / "extracted.jsonl"
    rows = [
        row("2019-04-17", "consent", "Award a purchasing agreement to KCDA",
            vendor_raw="KCDA", action_type="new", amount=408714.0),
        row("2020-04-17", "consent", "Amend the purchasing agreement",
            vendor_raw="King County Directors' Association", action_type="amendment",
            amount=1000.0, prior_total=408714.0),
    ]
    src.write_text("".join(json.dumps(r) + "\n" for r in rows))
    actions, _ = link.run(out_root=str(out_root), extracted=str(src))
    assert all(a["vendor_id"] == "king-county-directors-association" for a in actions)
    assert all(a["vendor_id_source"] == "vendor_map" for a in actions)
    assert all(a["vendor_canonical"] == "King County Directors' Association" for a in actions)
    # the two aliases now share a chain via money continuity
    assert len({a["chain_id"] for a in actions}) == 1


def test_fallback_vendor_key_strips_suffixes():
    assert link._fallback_vendor_key("Lydig Construction, Inc.") == \
        link._fallback_vendor_key("LYDIG CONSTRUCTION INC")
    assert link._fallback_vendor_key("Absher Construction Company") == "absher construction"
    assert link._fallback_vendor_key(None) is None


def test_report_is_written_and_has_the_required_sections(tmp_path):
    rows = [
        row("2024-01-10", "introduction", "Approval of a contract with Acme Testing Services"),
        row("2024-01-24", "consent", "Approval of a contract with Acme Testing Services"),
        row("2024-02-14", "immediate", "Emergency purchase of classroom furniture"),
    ]
    run_link(tmp_path, rows)
    report = (tmp_path / "out" / "qa" / "link_report.md").read_text()
    for heading in ("## Pairing rate by era", "## Pairing rate by school year",
                    "## Unpaired introductions", "## Orphan amendments",
                    "## Chains", "## 10 example chains"):
        assert heading in report, heading


def test_school_year_boundary():
    assert link.school_year("2020-08-31") == "2019-20"
    assert link.school_year("2020-09-01") == "2020-21"
