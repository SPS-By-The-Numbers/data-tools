"""Gold-set tests for `extractors.sps_web.extract` (task E1).

``fixtures/gold/gold.jsonl`` holds 60 hand-labelled items -- the labels were
read off the item text (and, where the item was terse, the cited page of the
`out_sps_web/text/...` file).  Each row carries the item key
``(meeting_id, item_no)`` -- ``char_start`` is stored but advisory, see
``extract.resolve_gold_item`` -- plus the truth for the fields a human can
check without leaving the item: ``admitted`` (does the contract pre-filter let
it through?), ``vendor_raw``, ``amount``, ``amount_kind``, ``action_type``,
``revised_total``, ``prior_total``, ``contract_id``.

Coverage of the gold set:

* eras -- legacy 17, wp1620 17, modern 16, blackboard 13, archive 11 (>= 8 each);
  `era` is a reporting label only, nothing in the extractor branches on it, so
  `blackboard` exercises exactly the same patterns as `wp1620`
* every ``action_type``: new, amendment, change_order, renewal,
  final_acceptance, purchase, other
* 10 items the pre-filter **must reject** (warrants, minutes, personnel
  reports, policy amendments, board resolutions, "Amendment to Transportation
  Service Standards")
* items with no dollar amount at all, items with two or more amounts
  (component breakdowns, reimbursable allowances, "$1.2 million" + "$1.9
  million"), items whose vendor is printed only in the title, and items whose
  vendor genuinely is not printed ("various vendors").

The targets from the E1 card are asserted below: **100% precision on `amount`
and `vendor_raw`** (recall may be lower -- a null is always allowed, a wrong
value never is).  Nothing here needs the crawl: the tests skip when
`out_sps_web/items/` is absent.
"""

from __future__ import annotations

import os

import pytest

from extractors.sps_web import extract as E



def _fake_item(title, motion, **kw):
    """A minimal item dict, so the unit tests never touch out_sps_web/."""
    item = {
        "meeting_id": "2020-01-01-regular", "meeting_date": "2020-01-01",
        "source_doc_id": "deadbeef", "source_kind": "minutes",
        "item_no": "A.1", "section": "consent", "title": title,
        "body": title + ". " + motion, "motion_text": motion,
        "result": "approved", "vote": "unanimous",
        "page_start": 1, "page_end": 1, "char_start": 0, "char_end": len(motion),
        "item_code": None, "extractor_notes": [],
    }
    item.update(kw)
    return item


def _load():
    if not os.path.isdir(E.ITEMS_DIR):
        pytest.skip("out_sps_web/items/ not present")
    gold = E.load_gold()
    if not gold:
        pytest.skip("gold fixture missing")
    docs = E.load_docs()
    by_key = {E.item_key(i): (i, era, d) for i, era, d in E.load_items(docs)}
    return gold, by_key, docs


@pytest.fixture(scope="module")
def scored():
    gold, by_key, docs = _load()
    return E.score_gold(docs, by_key), gold, by_key


def test_gold_set_shape():
    gold = E.load_gold()
    if not gold:
        pytest.skip("gold fixture missing")
    assert len(gold) >= 60
    per_era = {}
    for g in gold:
        per_era[g["era"]] = per_era.get(g["era"], 0) + 1
    for era in E.ERAS:
        assert per_era.get(era, 0) >= 8, (era, per_era)
    labelled = {g["action_type"] for g in gold if g["admitted"]}
    assert labelled == set(E.ACTION_TYPES), labelled
    assert sum(1 for g in gold if not g["admitted"]) >= 5
    assert sum(1 for g in gold if g["admitted"] and g["amount"] is None) >= 5


def test_every_gold_item_is_in_the_corpus(scored):
    res, _gold, _ = scored
    assert not res["missing"], res["missing"]


def test_prefilter_matches_gold(scored):
    res, _, _ = scored
    s = res["stats"]["admitted"]
    p, r = E.prf(s)
    assert p >= 0.95, s["errors"]
    assert r >= 0.95, s["errors"]


def test_amount_precision_is_perfect(scored):
    """Target from the E1 card: never a wrong amount, nulls are fine."""
    res, _, _ = scored
    s = res["stats"]["amount"]
    p, _r = E.prf(s)
    assert p == 1.0, s["errors"]


def test_vendor_precision_is_perfect(scored):
    """Target from the E1 card: a vendor string is either right or null."""
    res, _, _ = scored
    s = res["stats"]["vendor_raw"]
    p, _r = E.prf(s)
    assert p == 1.0, s["errors"]


@pytest.mark.parametrize("field,min_p", [
    ("amount_kind", 0.95),
    ("action_type", 0.90),
    ("revised_total", 1.0),
    ("prior_total", 1.0),
    ("contract_id", 0.95),
])
def test_other_field_precision(scored, field, min_p):
    res, _, _ = scored
    s = res["stats"][field]
    p, _r = E.prf(s)
    assert p >= min_p, (field, s["errors"])


def test_extracted_vendors_are_verbatim(scored):
    """`vendor_raw` must be copyable back out of the item text."""
    _res, gold, by_key = scored
    for g in gold:
        got = E.resolve_gold_item(g, by_key)
        assert got, g
        item, era, doc = got
        if not E.is_contract_like(item)[0]:
            continue
        row = E.extract(item, era, doc)
        if row["vendor_raw"]:
            assert row["vendor_raw"] in E._text_of(item), (g["meeting_id"], row["vendor_raw"])


def test_validator_flags_a_bad_row(scored):
    """The validator must reject rows regardless of who produced them."""
    _res, gold, by_key = scored
    g = next(x for x in gold if x["admitted"] and x["vendor_raw"])
    item, era, doc = E.resolve_gold_item(g, by_key)
    row = E.extract(item, era, doc)

    bad = dict(row, vendor_raw="Acme Nonexistent Holdings LLC")
    ok, reasons = E.validate(bad, item)
    assert not ok and "vendor_not_verbatim" in reasons

    bad = dict(row, amount=-5.0, amount_kind="unspecified")
    ok, reasons = E.validate(bad, item)
    assert not ok and "amount_negative" in reasons

    bad = dict(row, action_type="amendment", amount=100.0,
               amount_kind="unspecified", revised_total=1.0)
    ok, reasons = E.validate(bad, item)
    assert not ok and "revised_total_lt_amount" in reasons

    cite = dict(row["citation"])
    cite["page_end"] = cite["page_start"] - 1
    bad = dict(row, citation=cite)
    ok, reasons = E.validate(bad, item)
    assert not ok and "page_end_lt_page_start" in reasons

    ok, reasons = E.validate(dict(row), item, doc_pages=1)
    if row["citation"]["page_end"] > 1:
        assert "page_end_gt_doc_pages" in reasons


def test_per_field_report(scored, capsys):
    """Not an assertion -- prints the per-field precision/recall table."""
    res, _, _ = scored
    lines = ["", f"gold n={res['n']}"]
    for f in E.GOLD_FIELDS:
        s = res["stats"][f]
        p, r = E.prf(s)
        lines.append(f"  {f:14s} tp={s['tp']:3d} fp={s['fp']:3d} fn={s['fn']:3d} "
                     f"P={p:6.1%} R={r:6.1%}")
    with capsys.disabled():
        print("\n".join(lines))


# ---------------------------------------------------------------------------
# Pure unit tests -- no corpus, no fixtures.  Every string below is copied
# verbatim from a real board item; each case is a defect the F1 vendor pass or
# the F2 link pass found in `regex_rows.jsonl`.
# ---------------------------------------------------------------------------

def _vendors(text):
    return [(n, v) for (n, v, _p) in E._find_vendors(text) if E._plausible_vendor(v)]


def _best_vendor(text):
    """What `extract()` would settle on, without needing an item dict."""
    hits = _vendors(text)
    if not hits:
        return None, []
    order = {n: i for i, (n, _) in enumerate(E.VENDOR_ANCHORS)}
    order["v_before_amount"] = order["v_with_amount"] - 0.5
    all_hits = [(n, v, p) for (n, v, p) in E._find_vendors(text) if E._plausible_vendor(v)]
    best = min(all_hits, key=lambda t: (order.get(t[0], 99), t[2]))
    return E.split_joint_vendors(best[1])


# (1) award clause: the vendor starts *after* "to", the id is not part of it
@pytest.mark.parametrize("text,vendor", [
    ("Approval of this item would award contract D-5041 to Regency Northwest "
     "Construction, Inc., as general contractor in the amount of $813,000 plus "
     "Washington State sales tax.", "Regency Northwest Construction, Inc."),
    ("Approval of this item would award contract D-5045 to A-1 Landscaping and "
     "Construction, Inc. as general contractor in the amount of $1,497,286.",
     "A-1 Landscaping and Construction, Inc."),
    ("plus Alternates A-2 and B-1 to Absher Construction Company in the amount "
     "of $8,762,000, plus Washington State Sales Tax", "Absher Construction Company"),
    ("Award Construction Contract D5050 to Western Ventures Construction, Inc. "
     "in the amount of $1,367,000", "Western Ventures Construction, Inc."),
])
def test_award_clause_vendor_starts_after_to(text, vendor):
    primary, _co = _best_vendor(text)
    assert primary == vendor


def test_award_clause_id_lands_in_contract_id():
    item = _fake_item("BTA II, Bid B01705, Arbor Heights Re-Roofing",
                      "Approval of this item would award contract D-5041 to Regency "
                      "Northwest Construction, Inc., as general contractor in the "
                      "amount of $813,000 plus Washington State sales tax.")
    row = E.extract(item, "archive", {})
    assert row["vendor_raw"] == "Regency Northwest Construction, Inc."
    assert row["contract_id"] == "D-5041"
    assert row["bid_number"] == "B01705"


# (2) trailing scope text must not be swallowed
@pytest.mark.parametrize("text,vendor", [
    ("execute a contract with Sylvan Learning Center for Supplemental Education "
     "Services in the amount of $982,002.", "Sylvan Learning Center"),
    ("Final Acceptance of Contract D5050 with Western Ventures Construction, Inc. "
     "to Meany Middle School Phase 1", "Western Ventures Construction, Inc."),
    ("approve the grant agreement with the League of Education Voters Foundation "
     "for South Shore K-8 in the amount of $2,000,000",
     "League of Education Voters Foundation"),
])
def test_trailing_scope_text_is_dropped(text, vendor):
    primary, _co = _best_vendor(text)
    assert primary == vendor


@pytest.mark.parametrize("text,vendor", [
    ("award three contracts to the Center for Educational Leadership, University "
     "of Washington, for a total amount of $322,392.", "Center for Educational Leadership"),
    ("execute a contract with the New England Center for Children in the amount "
     "of $173,000", "New England Center for Children"),
    ("enter into an agreement with Teach For America for the 2010-11 school year",
     "Teach For America"),
])
def test_for_inside_a_name_is_kept(text, vendor):
    """"for" survives after a head noun (<=2 more tokens) or when capitalised."""
    primary, _co = _best_vendor(text)
    assert primary == vendor


# (3) single-word truncations
@pytest.mark.parametrize("tok", ["Teach", "Sylvan", "Thornburg", "Lincoln",
                                 "Machinists", "Local", "Directors", "Seattle",
                                 "City", "Math", "White", "Project", "Proposal"])
def test_single_title_case_word_is_not_a_vendor(tok):
    assert not E._plausible_vendor(tok)


@pytest.mark.parametrize("tok", ["KCDA", "CDW-G", "SEA", "EPI-USE",
                                 "SchoolFusion", "BNBuilders",
                                 "Arcadis", "Apple", "Genesis", "Sysco"])
def test_real_one_word_vendors_survive_the_guard(tok):
    """Acronyms, CamelCase, and one-word names that are not stopwords."""
    assert E._plausible_vendor(tok)


def test_one_word_guard_does_not_swap_in_a_wrong_vendor():
    """Rejecting "Arcadis" used to hand the row to the *second* vendor."""
    item = _fake_item(
        "Award Architectural & Engineering Contract P2076 to Arcadis",
        "Approval of this item would ratify the emergency contracts executed by "
        "the Superintendent with Arcadis (formerly IBI Group Architects) in the "
        "amount of $169,230; LineScape of Washington in the amount of $800,000, "
        "plus WSST, and Valley Electric in the amount of $2,200,000, plus WSST.")
    row = E.extract(item, "modern", {})
    assert row["vendor_raw"] == "Arcadis"
    assert row["amount"] == 169_230


@pytest.mark.parametrize("tok", ["XXX", "Bid No", "Alternates", "Vendor", "RFP"])
def test_placeholder_tokens_are_rejected(tok):
    assert not E._plausible_vendor(tok)


def test_truncated_union_name_yields_no_vendor():
    """"ratify the ... agreement ... Local 174 employees" has no vendor to take."""
    assert not [v for _n, v in _vendors(
        "Approval of this item will ratify the collective bargaining agreement "
        "that has been accepted by the district's Local 174 employees.")
        if v in ("Local", "Machinists", "Teamsters")]


# (4) joint vendors
@pytest.mark.parametrize("raw,primary,co", [
    ("First Student, Inc. and Zūm Services, Inc.",
     "First Student, Inc.", ["Zūm Services, Inc."]),
    ("US Foods and Sysco Seattle, Inc", "US Foods", ["Sysco Seattle, Inc"]),
    ("King County Directors Association and Musco Sports Lighting, LLC",
     "King County Directors Association", ["Musco Sports Lighting, LLC"]),
    ("Lydig Construction, Inc. and Elcon Corporation",
     "Lydig Construction, Inc.", ["Elcon Corporation"]),
])
def test_joint_vendors_split(raw, primary, co):
    assert E.split_joint_vendors(raw) == (primary, co)


@pytest.mark.parametrize("raw", [
    "A-1 Landscaping and Construction, Inc.",
    "International Association of Machinists and Aerospace Workers",
    "Children’s Hospital and Regional Medical Center",
    "Boys and Girls Clubs",
])
def test_single_names_containing_and_are_not_split(raw):
    assert E.split_joint_vendors(raw) == (raw, [])


def test_co_vendors_are_verbatim_and_validated():
    text = ("execute contracts for Student Transportation Services with First "
            "Student, Inc. and Zūm Services, Inc., in amounts not to exceed "
            "$39,542,000,000")
    item = _fake_item("Approval of Contracts RFP022242A, Student Transportation", text)
    row = E.extract(item, "modern", {})
    assert row["vendor_raw"] == "First Student, Inc."
    assert row["co_vendors_raw"] == ["Zūm Services, Inc."]
    for v in [row["vendor_raw"]] + row["co_vendors_raw"]:
        assert v in E._text_of(item)
    row["co_vendors_raw"] = ["Acme Nonexistent Holdings LLC"]
    _ok, reasons = E.validate(row, item)
    assert "co_vendor_not_verbatim" in reasons


# (5) vendor_name is a real cleanup
@pytest.mark.parametrize("raw,name", [
    ("Wayne’s Roofing, Inc.", "Wayne’s Roofing"),
    ("Bayley Construction, LP", "Bayley Construction"),
    ("Shiels Obletz Johnsen, Inc.", "Shiels Obletz Johnsen"),
    ("Regency Northwest Construction, Inc.", "Regency Northwest Construction"),
    ("KCDA", "KCDA"),
    ("City of Seattle", "City of Seattle"),
])
def test_vendor_name_strips_the_legal_suffix(raw, name):
    assert E.clean_vendor(raw) == name


def test_vendor_name_never_empties_a_name():
    assert E.clean_vendor("Inc.") == "Inc"


# (6) amounts: scaling guard + implausibility bound
def test_million_suffix_only_scales_a_small_mantissa():
    assert E._find_amounts("a change order of $1.2 million for repairs")[0]["value"] == 1_200_000
    # source typo: "$4,352,000 million" means $4.352M, and scaling it produced
    # a $4.3 trillion row
    assert E._find_amounts("the transfer of $4,352,000 million from the fund"
                           )[0]["value"] == 4_352_000


def test_implausible_amount_is_a_validator_failure():
    item = _fake_item("Student Transportation Services",
                      "in amounts not to exceed $39,542,000,000 for the contracts")
    row = E.extract(item, "modern", {})
    assert row["amount"] == 39_542_000_000
    ok, reasons = E.validate(row, item)
    assert not ok and "amount_implausible" in reasons
    row["amount"] = 39_542_000
    ok2, reasons2 = E.validate(row, item)
    assert "amount_implausible" not in reasons2


# (7) policy / bylaw / plan amendments are not contract amendments
@pytest.mark.parametrize("title,motion", [
    ("Proposed Amendments to the Student Assignment Plan",
     "Approval of this item will amend the Student Assignment Plan for 2010-11."),
    ("Amendments to Policy D12.00",
     "Approval of this motion will modify policy D12.00 as noted."),
    ("Annual Review of Board Bylaws",
     "Approval of this item would adopt the reviewed Board bylaws."),
])
def test_policy_amendments_are_rejected_by_the_prefilter(title, motion):
    admitted, reason = E.is_contract_like(_fake_item(title, motion))
    assert not admitted, reason


def test_amendment_needs_a_contract_object():
    at, _f = E.classify_action(
        "Approval of this item will amend the Transportation Service Standards "
        "to adjust bus arrival times.", "Amendment to Service Standards")
    assert at != "amendment"
    at2, _f2 = E.classify_action(
        "approve the contract amendment with Emerald Learning Center in the "
        "amount of $414,407", "Emerald Learning Center Contract Amendment")
    assert at2 == "amendment"


# (8) identifiers must be printed in this item, and nothing carries between items
def test_identifier_must_appear_in_the_item_text():
    item = _fake_item("Yellow Wood Academy Contract Amendment",
                      "approve the contract amendment with Yellow Wood Academy in "
                      "the amount of $649,500.")
    row = E.extract(item, "modern", {})
    assert row["contract_id"] is None
    row["contract_id"] = "K5111"          # the leak F2 found
    ok, reasons = E.validate(row, item)
    assert not ok and "contract_id_not_in_item_text" in reasons


def test_identifier_spacing_is_tolerated():
    item = _fake_item("Sign Language Interpreter Vendors, RFQ 11641",
                      "execute contracts with agencies approved through RFQ 11641")
    row = E.extract(item, "wp1620", {})
    assert row["rfp_number"] == "RFQ11641"
    _ok, reasons = E.validate(row, item)
    assert "rfp_number_not_in_item_text" not in reasons


def test_no_state_carries_between_items():
    a = _fake_item("BEX V: Award Construction Contract K5111 to Wayne's Roofing, Inc.",
                   "execute construction contract K5111 with Wayne's Roofing, Inc. "
                   "in the amount of $1,000,000.")
    b = _fake_item("Yellow Wood Academy Contract Amendment",
                   "approve the contract amendment with Yellow Wood Academy in the "
                   "amount of $649,500.")
    ra1 = E.extract(a, "modern", {})
    rb = E.extract(b, "modern", {})
    ra2 = E.extract(a, "modern", {})
    assert ra1["contract_id"] == "K5111" and ra2["contract_id"] == "K5111"
    assert rb["contract_id"] is None
    assert rb["vendor_raw"] == "Yellow Wood Academy"
    assert ra1["patterns_fired"] == ra2["patterns_fired"]
    assert ra1["extractor_notes"] is not ra2["extractor_notes"]
    assert rb["co_vendors_raw"] == []


# every regex row carries its source text and residual category
def test_rows_carry_item_text_and_residual_category():
    item = _fake_item("Approval of Emerald Learning Center Contract Amendment",
                      "approve the contract amendment with Emerald Learning Center "
                      "in the amount of $414,407, for a total contract amount of "
                      "$1,329,287.")
    row = E.extract(item, "modern", {})
    assert row["item_text"] == item["motion_text"]
    assert row["residual_category"] is None
    assert row["missing_required"] == []
    assert row["revised_total"] == 1_329_287


def test_item_text_falls_back_to_body():
    item = _fake_item("BEX II, Cleveland High School Final Acceptance", "")
    item["body"] = "Approval of this item will accept the work of Absher "\
                   "Construction Company as complete."
    row = E.extract(item, "archive", {})
    assert row["item_text"] == item["body"]
    assert row["vendor_raw"] == "Absher Construction Company"
    assert row["action_type"] == "final_acceptance"


# ---------------------------------------------------------------------------
# H1 audit defects (30 rows checked against their cited pages)
# ---------------------------------------------------------------------------

# (a) "from $A to $B"
def test_from_to_with_explicit_increase():
    item = _fake_item(
        "BEX V: Guaranteed Maximum Price amendment, Rainier Beach High School",
        "Approval of this item would authorize the comprehensive Guaranteed Maximum "
        "Price amendment for the Rainier Beach High School Replacement project "
        "revising the contract P5160 with Lydig Construction, Inc., from "
        "$206,556,237.08 to $221,063,335.16 increasing the contract budget by "
        "$14,507,098.08, plus Washington State sales tax.")
    row = E.extract(item, "modern", {})
    assert row["amount"] == 14_507_098.08
    assert row["amount_kind"] == "increase"
    assert row["prior_total"] == 206_556_237.08
    assert row["revised_total"] == 221_063_335.16
    assert row["vendor_raw"] == "Lydig Construction, Inc."
    assert row["contract_id"] == "P5160"


def test_from_to_without_an_explicit_increase_uses_the_delta():
    item = _fake_item("Resolution 2010/11-16, Extension of Debt Service Fund Budget",
                      "Approval of this resolution will increase the 2010-2011 Debt "
                      "Service Fund appropriation amount from $85,056,019 to "
                      "$85,315,093.")
    row = E.extract(item, "archive", {})
    assert row["prior_total"] == 85_056_019 and row["revised_total"] == 85_315_093
    assert row["amount"] == 259_074.0 and row["amount_kind"] == "increase"


def test_from_figure_never_becomes_the_amount():
    """A *project budget* range is barred from the amount but is not the
    contract's own prior/revised total (that would fabricate contract history
    from a levy-programme figure)."""
    item = _fake_item("Van Asselt School Addition budget increase",
                      "Approval of this item would approve a one-time budget increase "
                      "of $6,050,000 for the Van Asselt School Addition project "
                      "revising the overall project budget from $44,247,436 to "
                      "$50,297,436.")
    row = E.extract(item, "modern", {})
    assert row["amount"] == 6_050_000
    assert row["prior_total"] is None and row["revised_total"] is None
    assert any(n.startswith("from_to_not_contract:") for n in row["extractor_notes"])


# (b) malformed printed money
@pytest.mark.parametrize("run,ok", [
    ("$1,100,000", True), ("$250,000", True), ("$1,213,256.18", True),
    ("$5775744.00", True), ("$7.5", True),
    ("$1,100,00", False), ("$5,6000,000", False), ("$1,213,256,18", False),
    ("$96,534,89", False), ("$1,1,048,251", False),
])
def test_well_formed_money(run, ok):
    assert E.well_formed_money(run) is ok


def test_malformed_amount_is_nulled_and_noted():
    item = _fake_item(
        "Library collections for Decatur Elementary and Licton Springs K-8",
        "Approval of this item would authorize the Superintendent to execute a "
        "contract with Follett School Solutions in the amount not to exceed "
        "$1,100,00 for new library collections.")
    row = E.extract(item, "wp1620", {})
    assert row["amount"] is None and row["amount_kind"] is None
    assert "malformed_amount:$1,100,00" in row["extractor_notes"]
    assert row["vendor_raw"] == "Follett School Solutions"


# (c) the district is never the vendor
@pytest.mark.parametrize("tok", [
    "Seattle Public Schools", "SPS", "the District", "Seattle School District",
    "Seattle School District No. 1", "the successful firm", "the successful bidder",
    "the successful proposer", "Community Advisory Committee",
])
def test_district_and_placeholder_are_not_vendors(tok):
    assert not E._plausible_vendor(tok)


def test_district_only_candidate_yields_no_vendor():
    item = _fake_item(
        "School Consolidation Consultant Contract Award - RFP01627 (Exec)",
        "Approval of this item will award a contract in an amount not to exceed "
        "$250,000 to the successful firm to work with Seattle Public Schools and "
        "the Community Advisory Committee on Consolidation and School Closure.")
    row = E.extract(item, "legacy", {})
    assert row["vendor_raw"] is None and row["co_vendors_raw"] == []
    assert row["amount"] == 250_000 and row["amount_kind"] == "not_to_exceed"
    assert row["rfp_number"] == "RFP01627"


# (d) revenue acceptances are not contract actions
@pytest.mark.parametrize("title,motion", [
    ("Acceptance of Seattle Public Schools Seattle Preschool Program Plus Tuition "
     "Reimbursement from the City of Seattle for the 2022-23 school year",
     "Approval of this item would authorize the Superintendent to Accept SPP Plus "
     "tuition reimbursements received from the City of Seattle."),
    ("Acceptance of the League of Education Voters Foundation grant",
     "Approval of this item would authorize the Superintendent to accept the LEVF "
     "grant of up to $2,000,000 for the 2023-24 and 2024-25 school years."),
    ("Acceptance of a donation from the Alliance for Education",
     "Approval of this item would accept the donation of $50,000."),
])
def test_revenue_acceptances_are_rejected(title, motion):
    admitted, reason = E.is_contract_like(_fake_item(title, motion))
    assert not admitted and reason == "excluded:revenue_acceptance"


@pytest.mark.parametrize("title,motion", [
    ("Approval of Grant Agreement with the Alliance for Education",
     "Approval of this item would approve the grant agreement with the Alliance "
     "for Education in the amount of $100,000."),
    ("Children’s Hospital Contract (Student Learning)",
     "The Student Learning Committee recommends approval of this action which "
     "would authorize the district to enter into an agreement for a flow-through "
     "grant estimated at $339,000 for 2006/07."),
])
def test_grant_agreements_stay_admitted(title, motion):
    admitted, _reason = E.is_contract_like(_fake_item(title, motion))
    assert admitted


# ---------------------------------------------------------------------------
# Final H1 citation audit (40 rows): vendor 38/38, amount 37/38, action 36/38
# ---------------------------------------------------------------------------

def test_narrated_three_figure_amount_is_ignored():
    """2013-06-19 D.8: "$250K threshold" is discussion, not the action's value."""
    item = _fake_item(
        "Families and Education Levy (FEL) Community-Based Organizations Contract",
        "Approval of this item would authorize the Superintendent to execute "
        "contracts with The YMCA of Seattle, City of Seattle Parks & Recreation "
        "Department, and University Tutors for school year 2013-14. Directors "
        "asked about other contracts that were less than the $250K threshold "
        "required for Board action.")
    row = E.extract(item, "blackboard", {})
    assert row["amount"] is None and row["amount_kind"] is None
    assert any(n.startswith("low_amount_ignored:") for n in row["extractor_notes"])
    assert row["vendor_raw"] == "YMCA of Seattle"
    assert row["action_type"] == "new"


def test_unit_rate_under_the_floor_is_noted_not_taken():
    item = _fake_item("Sign Language Interpreter Vendors",
                      "execute contracts based on an average Interpreter hourly "
                      "rate of $73.50 per hour for all agencies.")
    row = E.extract(item, "wp1620", {})
    assert row["amount"] is None
    assert any(n.startswith("unit_rate:") for n in row["extractor_notes"])


@pytest.mark.parametrize("amount,expect", [(999.0, None), (1000.0, 1000.0)])
def test_amount_floor_boundary(amount, expect):
    item = _fake_item("Contract award",
                      f"execute a contract with Acme Widgets Inc. in the amount "
                      f"of ${amount:,.0f}.")
    assert E.extract(item, "modern", {})["amount"] == expect


def test_award_outranks_the_amendment_clause():
    """2020-10-07 A.17 -- GC/CM items always award *and* amend; award wins."""
    item = _fake_item(
        "BEX V: Award Contract P5152 for General Contractor/Construction Manager "
        "(GC/CM) to Cornerstone General Contractors Inc. for the Van Asselt project",
        "Approval of this item would authorize the Superintendent to utilize the "
        "GC/CM alternative construction delivery method, authorize the GC/CM to "
        "immediately provide pre-construction services for an amount not to "
        "exceed $360,000. This approval also authorizes the Superintendent to "
        "negotiate and execute a contract amendment for the Guaranteed Maximum "
        "Price (GMP).")
    row = E.extract(item, "wp1620", {})
    assert row["action_type"] == "new"
    assert row["amount"] == 360_000 and row["amount_kind"] == "not_to_exceed"
    assert row["contract_id"] == "P5152"


def test_amendment_without_an_award_stays_an_amendment():
    item = _fake_item("Approval of Emerald Learning Center Contract Amendment",
                      "approve the contract amendment with Emerald Learning Center "
                      "in the amount of $414,407.")
    assert E.extract(item, "modern", {})["action_type"] == "amendment"


def test_execute_modified_contracts_with_several_vendors_is_new():
    """2026-06-03 A.9 -- modifiers between "execute" and "contracts"."""
    item = _fake_item(
        "BEX VI: Approval of Staff Augmentation Vendor Contracts for SAP",
        "Approval of this item would authorize the Superintendent to execute "
        "three-year SAP Staff Augmentation contracts with EPI-USE, Genesis, and "
        "Vigna, from September 1, 2026, to August 31, 2029 for a total "
        "not-to-exceed amount of $7,000,000.")
    row = E.extract(item, "modern", {})
    assert row["action_type"] == "new"
    assert row["amount"] == 7_000_000 and row["amount_kind"] == "not_to_exceed"
    assert row["vendor_raw"] == "EPI-USE"


@pytest.mark.parametrize("motion,amount,kind", [
    ("authorize the Superintendent to amend the contract with Yellow Wood Academy "
     "to a total amount of $1,045,360 for special education programming.",
     1_045_360.0, "revised_total"),
    ("authorize the Superintendent to execute a contract with InterVision up to "
     "an amount of $1,354,206, not including sales tax, for wireless installation.",
     1_354_206.0, "not_to_exceed"),
])
def test_amount_kind_formulas(motion, amount, kind):
    row = E.extract(_fake_item("Contract action", motion), "modern", {})
    assert row["amount"] == amount and row["amount_kind"] == kind


def test_to_a_total_amount_also_fills_revised_total():
    row = E.extract(_fake_item(
        "Amend Yellow Wood Academy Contract",
        "amend the contract with Yellow Wood Academy to a total amount of "
        "$1,045,360."), "modern", {})
    assert row["revised_total"] == 1_045_360.0
    assert row["action_type"] == "amendment"


# ---------------------------------------------------------------------------
# Instructional-materials adoptions: the counterparty is the publisher/product
# named after "purchase" / "the adoption of" (owner feedback)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("motion,vendor", [
    ("authorize the Superintendent to purchase AmplifyScience as the core "
     "instructional materials for all grade 6-8 classrooms for an amount not to "
     "exceed $2,069,686.", "AmplifyScience"),
    ("authorize the Superintendent to purchase Carbon TIME as the core "
     "instructional materials for high school Biology A science classrooms.",
     "Carbon TIME"),
    ("adopt and authorize the superintendent to purchase the Center for the "
     "Collaborative Classroom as instructional materials for all K-5 classrooms.",
     "Center for the Collaborative Classroom"),
    ("authorize the Superintendent to purchase enVision as the core instructional "
     "materials for all K-5 mathematics classrooms.", "enVision"),
    ("authorize the Superintendent to purchase Inquiry By Design as the core "
     "instructional material for all 6-8 English Language Arts classrooms.",
     "Inquiry By Design"),
])
def test_adoption_names_the_product_as_vendor(motion, vendor):
    row = E.extract(_fake_item("Instructional Materials Adoption", motion), "modern", {})
    assert row["vendor_raw"] == vendor
    assert row["action_type"] == "purchase"
    assert "vendor_class:publisher" in row["extractor_notes"]


def test_publisher_wins_and_product_becomes_the_programme():
    item = _fake_item(
        "Adoption of Algebra 1, Geometry, and Algebra 2 Instructional Materials",
        "Approval of this item would approve the adoption of Illustrative "
        "Mathematics, published by Imagine Learning LLC, for instructional "
        "materials for Algebra 1 classrooms. Approval of this item would also "
        "authorize the Superintendent to purchase Illustrative Mathematics as the "
        "core instructional material for an amount not to exceed $3,547,754.")
    row = E.extract(item, "modern", {})
    assert row["vendor_raw"] == "Imagine Learning LLC"
    assert row["program_or_project"] == "Illustrative Mathematics"
    assert row["amount"] == 3_547_754


def test_generic_adoption_tail_is_trimmed():
    """The title's "<grade band> Instructional Materials" is not a vendor."""
    item = _fake_item(
        "Adoption of K-5 English Language Arts Instructional Materials",
        "Approval of this item would approve the adoption of McGraw Hill, Emerge! "
        "Elementary School Curriculum, for core instructional materials, and "
        "authorize the Superintendent to purchase McGraw Hill, Emerge! as the core "
        "instructional material for an amount not to exceed $9,000,000.00.")
    row = E.extract(item, "modern", {})
    assert row["vendor_raw"] == "McGraw Hill"


@pytest.mark.parametrize("tok", [
    "District-Developed Curriculum", "the District-Developed Curriculum",
    "K-5 English Language Arts Instructional Materials",
    "6-8 English Language Arts Instructional Materials", "Instructional Materials",
])
def test_curriculum_descriptions_are_not_vendors(tok):
    assert not E._plausible_vendor(tok)


def test_district_developed_curriculum_never_wins():
    item = _fake_item(
        "High School Science Instructional Materials Adoption",
        "authorize the Superintendent to purchase Carbon TIME as the core "
        "instructional materials for Biology A classrooms, to approve the "
        "District-Developed Curriculum for BIO B as the core instructional "
        "materials for high school classrooms, for an amount not to exceed "
        "$1,034,132.")
    row = E.extract(item, "wp1620", {})
    assert row["vendor_raw"] == "Carbon TIME"
    assert "District-Developed Curriculum" not in (row["co_vendors_raw"] or [])


def test_plain_purchase_is_not_treated_as_an_adoption():
    """The adoption anchor is gated on the "instructional material" formula."""
    item = _fake_item(
        "Purchase of Student and Staff Computers for new BEX IV Schools",
        "Approval of this item would approve the purchase of Student and Staff "
        "computers for a total amount not-to-exceed $1,200,000 for levy projects.")
    row = E.extract(item, "wp1620", {})
    assert row["vendor_raw"] is None
    assert "vendor_class:publisher" not in row["extractor_notes"]


def test_professional_development_figure_stays_an_extra():
    item = _fake_item(
        "Middle School Science Instructional Materials Adoption",
        "authorize the Superintendent to purchase AmplifyScience as the core "
        "instructional materials for an amount not to exceed $2,069,686, covering "
        "licensing from school year 2019-20 to 2027-28, and an amount not to "
        "exceed $565,857 for in-house professional development.")
    row = E.extract(item, "wp1620", {})
    assert row["amount"] == 2_069_686 and row["amount_kind"] == "not_to_exceed"
    assert any("565,857" in n for n in row["extractor_notes"])


# ---------------------------------------------------------------------------
# Course names are not vendors (F1 proposed merging "CHEM B" with
# "District-Developed CHEM B")
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tok", [
    "CHEM B", "CHEM A", "BIO A", "BIO B", "PHYS B", "ALG 1", "GEOM",
    "Chemistry A", "Biology A", "Biology B", "Physics B", "Algebra 1",
    "Algebra 2", "Geometry", "9th grade Chemistry A",
    "District-Developed CHEM B", "District-Developed Curriculum",
    "core instructional materials", "curriculum", "instructional materials",
    "In-house Curriculum",
])
def test_course_and_curriculum_names_are_not_vendors(tok):
    assert not E._plausible_vendor(tok)


@pytest.mark.parametrize("tok", ["Carbon TIME", "PEER", "AmplifyScience",
                                 "enVision", "Inquiry By Design",
                                 "Imagine Learning LLC"])
def test_purchasable_products_still_survive(tok):
    assert E._plausible_vendor(tok)


def test_multi_product_adoption_keeps_every_purchasable_product():
    """2019-05-29 C.1: two products bought, two courses district-developed."""
    item = _fake_item(
        "High School Science Instructional Materials Adoption",
        "Approval of this item would accept the recommendation of the High School "
        "Instructional Materials Adoption Committee for all students taking 9th "
        "grade Chemistry A (CHEM A), 10th grade Biology A (BIO A), and 11th grade "
        "Physics B (PHYS B), and authorize the Superintendent to purchase Carbon "
        "TIME as the core instructional materials for high school Biology A (BIO "
        "A) science classrooms, to approve the District-Developed Curriculum for "
        "BIO B as the core instructional materials for high school Biology B (BIO "
        "B) science classrooms, to approve the District-Developed Curriculum for "
        "CHEM A as the core instructional materials for high school Chemistry A "
        "(CHEM A) science classrooms, and to purchase PEER as the core "
        "instructional materials for high school Physics A and B (PHYS A and B) "
        "science classrooms, for an amount not to exceed $1,034,132.")
    row = E.extract(item, "wp1620", {})
    assert row["vendor_raw"] == "Carbon TIME"
    assert row["co_vendors_raw"] == ["PEER"]
    assert row["amount"] == 1_034_132 and row["action_type"] == "purchase"
    text = E._text_of(item)
    for v in [row["vendor_raw"]] + row["co_vendors_raw"]:
        assert v in text
    for bad in ("CHEM", "BIO", "PHYS", "District-Developed"):
        assert bad not in row["vendor_raw"]
        assert not any(bad in c for c in row["co_vendors_raw"])


def test_district_developed_adoption_has_no_vendor_at_all():
    item = _fake_item(
        "High School Chemistry B Instructional Materials Adoption",
        "Approval of this item would approve the recommendation of the "
        "Instructional Materials Committee to adopt the District-Developed CHEM B "
        "high school instructional materials and authorize the Superintendent to "
        "enter into agreements and incur costs to implement the CHEM B "
        "instructional materials for all high school Chemistry B (CHEM B) science "
        "classrooms for an amount not to exceed $367,845.")
    row = E.extract(item, "wp1620", {})
    assert row["vendor_raw"] is None and row["co_vendors_raw"] == []
    assert row["amount"] == 367_845 and row["amount_kind"] == "not_to_exceed"


# ---------------------------------------------------------------------------
# E3 BAR-conflict triage: amounts that were a component, not the contract
# ---------------------------------------------------------------------------

def test_gccm_takes_the_gmp_not_the_preconstruction_allowance():
    item = _fake_item(
        "Multiple Capital Levy Funds: Award Contract K5086 for GC/CM",
        "Approval of this item would authorize the GC/CM to immediately provide "
        "pre-construction services for an amount not to exceed $250,000, and "
        "authorizes the Superintendent to negotiate and execute a contract "
        "amendment for the Guaranteed Maximum Price (GMP) amount not to exceed "
        "$25,972,700.")
    row = E.extract(item, "wp1620", {})
    assert row["amount"] == 25_972_700 and row["amount_kind"] == "not_to_exceed"
    assert any(n.startswith("component_amount:") for n in row["extractor_notes"])


def test_gmp_regex_crosses_an_rcw_citation():
    """"...(GMP) as defined by the RCW 39.10.370 for an amount not to exceed $X"."""
    item = _fake_item(
        "BEX V: Award Contract P5152 for GC/CM to Cornerstone General Contractors",
        "authorize the GC/CM to immediately provide pre-construction services for "
        "an amount not to exceed $360,000, and negotiate and execute a contract "
        "amendment for the Guaranteed Maximum Price (GMP) as defined by the RCW "
        "39.10.370 for an amount not to exceed $27,000,000.")
    assert E.extract(item, "wp1620", {})["amount"] == 27_000_000


def test_gmp_phrased_as_authorized_total():
    item = _fake_item(
        "BEX VI: GC/CM for the John Marshall School Modernization",
        "The maximum, total Guaranteed Maximum Price authorized for the project is "
        "$90,000,000 plus Washington State sales tax. The Emerson Elementary School "
        "Water Line Remediation in the amount of $153,386.50 is unrelated.")
    assert E.extract(item, "modern", {})["amount"] == 90_000_000


def test_two_contract_actions_in_one_item_are_flagged():
    """2018-03-21 D.15 -- a modification with TCF Architecture *and* a GMP
    amendment with BNBuilders.  One row cannot hold both, and the vendor ends up
    beside the other clause's figure, so the row is flagged rather than silently
    trusted.  The GMP here reads "to increase ... to $X", deliberately NOT a
    `GMP_RE` connector: overriding on it would staple BNBuilders' money to
    whichever vendor won the anchor race."""
    item = _fake_item(
        "BTA IV: Webster School Modernization -- contract amendment with "
        "BNBuilders and contract modification with TCF Architecture",
        "authorize the Superintendent to execute a contract modification for "
        "$643,567 with TCF Architecture for additional design and construction "
        "administration fees, and a contract amendment with BNBuilders to "
        "increase the Guaranteed Maximum Price (GMP) to $23,900,000.")
    row = E.extract(item, "wp1620", {})
    assert row["vendor_raw"] == "BNBuilders"
    assert row["amount"] == 643_567
    assert any(n.startswith("multi_action_item:") for n in row["extractor_notes"])


def test_single_action_item_is_not_flagged():
    item = _fake_item("Approval of Emerald Learning Center Contract Amendment",
                      "approve the contract amendment with Emerald Learning Center "
                      "in the amount of $414,407, for a total contract amount of "
                      "$1,329,287.")
    row = E.extract(item, "modern", {})
    assert not any(n.startswith("multi_action_item:") for n in row["extractor_notes"])


@pytest.mark.parametrize("motion,amount", [
    ("execute a contract with Recology CleanScapes covering the period from "
     "August 1, 2017 to July 31, 2020, in the amount of $803,994.66 annually, or "
     "$2,411,983.90 over the three-year term of the contract.", 2_411_983.90),
    ("execute a one-year contract extension with Herff Jones in an amount not to "
     "exceed $400,000 and may execute two optional annual extensions each in an "
     "amount not to exceed $400,000, each for a total amount not to exceed $1.2 "
     "million over three years.", 1_200_000.0),
])
def test_whole_term_total_beats_the_per_year_figure(motion, amount):
    row = E.extract(_fake_item("Contract award", motion), "modern", {})
    assert row["amount"] == amount


def test_monthly_rate_is_labelled_monthly():
    item = _fake_item(
        "First Amendment to Facilities Capital Projects Warehouse Agreement",
        "execute a first amendment to the lease for the Capital Ellis Street "
        "Warehouse with P&P Georgetown LLC, covering the period of July 1, 2020 "
        "through June 30, 2027 for a total of $24,767 a month.")
    row = E.extract(item, "wp1620", {})
    assert row["amount"] == 24_767 and row["amount_kind"] == "monthly"
    assert "monthly" in E.AMOUNT_KINDS
    ok, reasons = E.validate(row, item)
    assert "amount_kind_invalid" not in reasons


def test_gmp_does_not_hijack_a_from_to_amendment():
    """2025-07-02 A.13 -- "GMP Amendment ... from $A to $B" keeps the delta."""
    item = _fake_item(
        "Authorization to execute the comprehensive Guaranteed Maximum Price "
        "Amendment for Rainier Beach High School",
        "revising the contract P5160 with Lydig Construction, Inc., from "
        "$206,556,237.08 to $221,063,335.16 increasing the contract budget by "
        "$14,507,098.08.")
    row = E.extract(item, "modern", {})
    assert row["amount"] == 14_507_098.08 and row["amount_kind"] == "increase"


# ---------------------------------------------------------------------------
# Structured co_vendors: one item, several vendors (link.py explodes these)
# ---------------------------------------------------------------------------

def test_vendor_amount_list_with_group_total():
    """2019-06-12 A.13 -- envelope NTE, then one pair per agency."""
    item = _fake_item(
        "Approval of contracts for Therapeutic Treatment Day Services, RFQ 05790",
        "Approval of this item would authorize the Superintendent to execute "
        "contracts with agencies approved through RFQ 05790 Therapeutic Treatment "
        "Day Services, for a not-to-exceed total amount of $1,890,000 as follows: "
        "Overlake Hospital Specialty School in the amount of $283,000.00 (3,564 "
        "hours); Fairfax Hospital/NWSOIL in the amount of $646,000.00 (6,705 "
        "hours); and Seneca Family of Agencies in the amount of $961,000.00 "
        "(14,508 hours) for private placement of students.")
    row = E.extract(item, "wp1620", {})
    assert row["vendor_raw"] == "Overlake Hospital Specialty School"
    assert row["amount"] == 283_000.0
    assert row["group_total"] == 1_890_000.0
    assert row["group_total_kind"] == "not_to_exceed"
    assert [(c["vendor_raw"], c["amount"]) for c in row["co_vendors"]] == [
        ("Fairfax Hospital/NWSOIL", 646_000.0),
        ("Seneca Family of Agencies", 961_000.0)]
    assert row["co_vendors_raw"] == ["Fairfax Hospital/NWSOIL",
                                     "Seneca Family of Agencies"]
    ok, reasons = E.validate(row, item)
    assert ok, reasons


def test_vendor_amount_list_nulls_a_mistyped_co_vendor_amount():
    """2020-06-10 C.4 -- Brock's "$250.000" is a typo, so that amount is null."""
    item = _fake_item(
        "Approval of contracts for Specially Designed Instruction",
        "Approval of this item would authorize the Superintendent to execute "
        "contracts with the following agencies under RFQ02758, Specially Designed "
        "Instruction: Yellow Wood Academy in the amount of $649,500; Maxim "
        "Healthcare Services in the amount of $950,000; Brightmont Academy in the "
        "amount of $265,000; and Brock's Academy in the amount of $250.000, and to "
        "take any necessary actions to implement these contracts.")
    row = E.extract(item, "wp1620", {})
    assert row["vendor_raw"] == "Yellow Wood Academy" and row["amount"] == 649_500
    got = [(c["vendor_raw"], c["amount"]) for c in row["co_vendors"]]
    assert got == [("Maxim Healthcare Services", 950_000.0),
                   ("Brightmont Academy", 265_000.0),
                   ("Brock's Academy", None)]
    assert row["group_total"] is None
    ok, reasons = E.validate(row, item)
    assert ok, reasons


def test_joint_award_with_one_shared_amount():
    """2022-07-06 C.4 -- amounts are not split per vendor, so co-vendor is null."""
    item = _fake_item(
        "Approval of Contracts RFP022242A and RFP022242B, Student Transportation",
        "authorize the Superintendent to execute contracts for Student "
        "Transportation Services with First Student, Inc. and Zum Services, Inc., "
        "in amounts not to exceed $39,542,000,000.")
    row = E.extract(item, "modern", {})
    assert row["vendor_raw"] == "First Student, Inc."
    assert row["co_vendors"] == [{"vendor_raw": "Zum Services, Inc.",
                                  "amount": None, "amount_kind": None,
                                  "amount_raw": None}]


def test_component_breakdown_is_not_a_vendor_list():
    """"...delivered by the EEU in the amount of $943,089" is one contract."""
    item = _fake_item(
        "University of Washington Experimental Education Unit Interagency Agreement",
        "execute an interagency agreement with the University of Washington Haring "
        "Center in the amount of $1,513,864 for the following services: Educational "
        "services for up to 42 preschool students delivered by the EEU in the "
        "amount of $943,089; Educational services for up to 16 kindergarten "
        "students delivered by the EEU in the amount of $486,416.")
    row = E.extract(item, "wp1620", {})
    assert row["vendor_raw"] == "University of Washington Haring Center"
    assert row["co_vendors"] == []


def test_parenthetical_alias_is_not_a_co_vendor():
    """"Arcadis (formerly IBI Group Architects) in the amount of $169,230"."""
    item = _fake_item(
        "Insurance Reimbursement and BEX IV Program Contingency: Award "
        "Architectural & Engineering Contract P2076 to Arcadis and Award "
        "Emergency Public Works Contracts P5145 to LineScape of Washington and "
        "Contract P5144 to Valley Electric",
        "ratify the emergency contracts executed by the Superintendent with "
        "Arcadis (formerly IBI Group Architects) in the amount of $169,230; "
        "LineScape of Washington in the amount of $800,000, plus WSST, and Valley "
        "Electric in the amount of $2,200,000, plus WSST.")
    row = E.extract(item, "modern", {})
    assert row["vendor_raw"] == "Arcadis"
    assert [c["vendor_raw"] for c in row["co_vendors"]] == [
        "LineScape of Washington", "Valley Electric"]
    assert [c["amount"] for c in row["co_vendors"]] == [800_000.0, 2_200_000.0]


def test_co_vendor_amount_must_be_printed():
    item = _fake_item("Approval of contracts",
                      "execute contracts as follows: Acme Widgets Inc. in the "
                      "amount of $500,000; Beta Systems LLC in the amount of "
                      "$750,000.")
    row = E.extract(item, "modern", {})
    assert len(row["co_vendors"]) == 1
    row["co_vendors"][0]["amount"] = 12_345.0
    row["co_vendors"][0]["amount_raw"] = "$12,345"
    ok, reasons = E.validate(row, item)
    assert not ok and "co_vendor_amount_not_printed" in reasons
    row["co_vendors"][0]["vendor_raw"] = "Nonexistent Holdings LLC"
    ok, reasons = E.validate(row, item)
    assert not ok and "co_vendor_not_verbatim" in reasons


def test_adoption_multi_product_lands_in_co_vendors():
    item = _fake_item(
        "High School Science Instructional Materials Adoption",
        "authorize the Superintendent to purchase Carbon TIME as the core "
        "instructional materials for Biology A classrooms, and to purchase PEER as "
        "the core instructional materials for Physics classrooms, for an amount "
        "not to exceed $1,034,132.")
    row = E.extract(item, "wp1620", {})
    assert row["vendor_raw"] == "Carbon TIME"
    assert [c["vendor_raw"] for c in row["co_vendors"]] == ["PEER"]
    assert row["co_vendors"][0]["amount"] is None


# ---------------------------------------------------------------------------
# Co-vendor capture defects from the vendor review
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,primary,co", [
    ("Lydig Construction, Inc. and Elcon Corporation, Inc.",
     "Lydig Construction, Inc.", ["Elcon Corporation, Inc."]),
    ("First Student, Inc. and Zum Services, Inc.",
     "First Student, Inc.", ["Zum Services, Inc."]),
    ("Ednetics / MicroK12", "Ednetics", ["MicroK12"]),
    ("The YMCA of Seattle and the City of Seattle Parks & Recreation Department",
     "YMCA of Seattle", ["City of Seattle Parks & Recreation Department"]),
])
def test_joint_splits_to_keep(raw, primary, co):
    assert E.split_joint_vendors(raw) == (primary, co)


@pytest.mark.parametrize("raw", [
    "Listen and Talk",
    "City of Seattle Department of Parks and Recreation",
    "City of Seattle Parks & Recreation Department",
    "U.S. Department of Health and Human Services",
    "Building and Construction Trades Council",
    "City of Seattle Department of Education and Early Learning",
    "A-1 Landscaping and Construction, Inc.",
    "Children's Hospital and Regional Medical Center",
    "Boys and Girls Clubs",
    "Garland/DBS, Inc.",
    "CBRE | Heery",
])
def test_names_that_must_never_split(raw):
    assert E.split_joint_vendors(raw) == (E.strip_leading_article(raw), [])


@pytest.mark.parametrize("raw,want", [
    ("the City of Seattle Parks", "City of Seattle Parks"),
    ("The YMCA of Seattle", "YMCA of Seattle"),
    ("a Regency NW Construction Inc.", "Regency NW Construction Inc."),
    ("Absher Construction Company", "Absher Construction Company"),
])
def test_leading_article_is_stripped(raw, want):
    assert E.strip_leading_article(raw) == want


@pytest.mark.parametrize("tok", [
    "Roosevelt High School Science Modernization",
    "Roosevelt High Schools' Science Modernization Project",
    "Rainier Beach High School Athletic Field Improvements",
    "Waterline Replacement", "Interior Renovations", "Upgrades Phase II",
    "Sand Point Modernization", "Lafayette Elementary School Window Replacement",
    "Queen Anne Elementary School Modernization", "Condensing Boiler Replacement",
])
def test_project_descriptions_are_not_vendors(tok):
    assert not E._plausible_vendor(tok)


@pytest.mark.parametrize("tok", [
    "Reading & Writing Project Network, LLC",     # a real vendor, has a suffix
    "Premier Field Developments",
    "Regency NW Construction Inc.",
])
def test_real_vendors_survive_the_project_filter(tok):
    assert E._plausible_vendor(tok)


def test_award_prefix_is_trimmed_from_the_vendor():
    """2008-10-15 C.6 -- "with Alternates A-2 and B-1 to Absher..."."""
    item = _fake_item(
        "BEX III, Bid B05836: Nathan Hale High School Project 1b Construction",
        "Approval of this item will award a contract with Alternates A-2 and B-1 "
        "to Absher Construction Company in the amount of $8,762,000, plus "
        "Washington State Sales Tax.")
    row = E.extract(item, "archive", {})
    assert row["vendor_raw"] == "Absher Construction Company"
    assert row["co_vendors"] == [] and row["amount"] == 8_762_000


def test_project_name_is_not_a_co_vendor():
    """2013-09-04 D.4 -- and the walk stops at the legal suffix."""
    item = _fake_item(
        "Final Acceptance: Rainier Beach and Roosevelt High School Science "
        "Modernization Project, BTA III Contract No. K5018",
        "Approval of this item demonstrates Final Acceptance of the work "
        "performed under BTA III Public Works Contract K5018, Rainier Beach and "
        "Roosevelt High School Science Modernization with Regency NW Construction "
        "Inc. Mike Skutack spoke about the specifics of the contract.")
    row = E.extract(item, "blackboard", {})
    assert row["vendor_raw"] == "Regency NW Construction Inc."
    assert row["co_vendors"] == []
    assert row["contract_id"] == "K5018"


def test_department_is_not_split_at_ampersand():
    """2021-05-19 D.5 -- no "Recreation Department" co-vendor."""
    item = _fake_item(
        "BEX V: West Seattle Elementary School/Walt Hundley Playfield Property "
        "Exchange with City of Seattle Parks and Recreation Department",
        "authorize the Superintendent to execute an agreement with the City of "
        "Seattle to exchange 35,495 square feet of property in return for 35,495 "
        "square feet of City of Seattle Parks and Recreation Department property.")
    row = E.extract(item, "wp1620", {})
    assert row["vendor_raw"] == "City of Seattle"
    assert row["co_vendors"] == []


def test_unsplit_compound_headed_by_the_district_is_rejected():
    item = _fake_item(
        "School Consolidation Consultant Contract Award - RFP01627",
        "award a contract in an amount not to exceed $250,000 to the successful "
        "firm to work with Seattle Public Schools and the Community Advisory "
        "Committee on Consolidation and School Closure.")
    row = E.extract(item, "legacy", {})
    assert row["vendor_raw"] is None and row["co_vendors"] == []


# ---------------------------------------------------------------------------
# Truncated capture: "Construction Group" (vendor review)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,vendor", [
    ("accept the work performed under Contract P5175 with Construction Group "
     "International for the Viewlands Elementary School Demolition project as "
     "final.", "Construction Group International"),
    ("award a contract to Landon Construction Group, LLC in the amount of "
     "$944,952.", "Landon Construction Group, LLC"),
    ("execute a contract with Unimark Construction Group, LLC in the amount of "
     "$1,177,857.", "Unimark Construction Group, LLC"),
    ("award the A/E contract to DLR Group for the design.", "DLR Group"),
    ("execute a contract with Kassel & Associates, Inc. for the project.",
     "Kassel & Associates, Inc."),
])
def test_mid_name_group_does_not_end_the_walk(text, vendor):
    """"Group"/"Associates"/"Partners" sit mid-name; only a terminal legal form
    (Inc/LLC/Ltd/Corp/Co/LP/PLLC...) ends the name."""
    row = E.extract(_fake_item("Contract action", text), "modern", {})
    assert row["vendor_raw"] == vendor


def test_terminal_suffix_still_ends_the_walk():
    """The 2013-09-04 fix must survive the narrower suffix set."""
    row = E.extract(_fake_item(
        "Final Acceptance",
        "under Contract K5018 with Regency NW Construction Inc. Mike Skutack "
        "spoke about the specifics of the contract."), "blackboard", {})
    assert row["vendor_raw"] == "Regency NW Construction Inc."


@pytest.mark.parametrize("tok", [
    "Construction Group", "Services Company", "Engineering Services",
    "Associates", "Contractors Inc.", "Construction", "Group",
    "Consulting Partners LLC", "Architects and Engineers",
])
def test_generic_only_names_are_rejected(tok):
    """No proper-noun token survived, so there is no vendor identity left."""
    assert not E._plausible_vendor(tok)


@pytest.mark.parametrize("tok", [
    "Construction Group International", "Landon Construction Group, LLC",
    "DLR Group", "NAC Architecture", "Premier Field Developments",
    "Bayley Construction, LP", "Western Ventures Construction, Inc.",
])
def test_names_with_a_proper_noun_survive(tok):
    assert E._plausible_vendor(tok)


def test_generic_only_co_vendor_is_dropped():
    item = _fake_item(
        "Approval of contracts",
        "execute contracts as follows: Acme Widgets Inc. in the amount of "
        "$500,000; Construction Group in the amount of $750,000.")
    row = E.extract(item, "modern", {})
    assert [c["vendor_raw"] for c in row["co_vendors"]] == []
