"""Hand-built cases for `extractors.sps_web.bar_fill` (task E3).

Nothing here touches the real corpus: each test writes a tiny synthetic
``out_sps_web`` tree into ``tmp_path`` (an ``extracted.jsonl``, a
``documents_classified.jsonl`` and one or two BAR ``.txt`` + ``.textmeta.json``
pairs), so the file runs in milliseconds and the expected behaviour is legible
next to the assertion.

The cases mirror the E3 card:

* parsing  -- the closeout table, the fiscal-impact sentence, the motion
  fallback, and the figures that must *not* be picked up (levy budget, state
  funding assistance)
* linking  -- item code, title similarity, the two-BAR tie, and the
  contract-id veto
* merging  -- fill only nulls, never overwrite a minutes amount, record the
  conflict, ``*_source`` tags and ``bar_citation``
* outputs  -- ``extracted_filled.jsonl`` row order, the fallback batches and
  the report
"""

from __future__ import annotations

import json
import os

from extractors.sps_web import bar_fill as bf


# --------------------------------------------------------------------------
# fixtures / helpers
# --------------------------------------------------------------------------

CLOSEOUT_BAR = """SCHOOL BOARD ACTION REPORT
DATE:                   February 1, 2019
FROM:                   Denise Juneau, Superintendent
LEAD STAFF:             Fred Podesta, Chief Operations Officer

For Introduction:       March 27, 2019
For Action:             April 17, 2019

1.      TITLE

BTA III/BEX IV: Final Acceptance of Contract K5069 with CDK Construction
Services, Inc., for the Seismic Upgrades at Salmon Bay K-8 project

2.      PURPOSE

The purpose of this action is to approve final acceptance of Contract K5069.

3.      RECOMMENDED MOTION

I move that the School Board accept the work performed under Contract K5069
with CDK Construction Services, Inc., as final.

4.      BACKGROUND INFORMATION

The construction project was publicly bid as Bid No. B11538 on March 30, 2016.

5.      FISCAL IMPACT/REVENUE SOURCE

The revenue source for this project budget is BTA III & BEX IV Capital Levy
funds in the amount of $9,900,000.

All payments have been made to the contractor from the BTA III/BEX IV Capital
levy funds. No outstanding invoices remain.

        Contractor:                       CDK Construction Services, Inc.
        Contract Amount                     $1,353,814
        Change Orders                         $146,151
        WSST                                  $148,546
        Total Contract including WSST       $1,648,510
        Project Retention                      $74,998

Expenditure:      One-time    Annual    Multi-Year    N/A
"""

AWARD_BAR = """SCHOOL BOARD ACTION REPORT
DATE:                 August 25, 2016
LEAD STAFF:           Dr. Lester Herndon, Associate Superintendent of Facilities

For Introduction:     September 7, 2016
For Action:           September 21, 2016

1.      TITLE

BEX IV and BTA IV: Award Contract P1454 for Architectural Services to Integrus
Architecture, for the Classroom Addition at Ingraham High School project

2.      PURPOSE

This action awards the design contract.

3.      RECOMMENDED MOTION

I move that the School Board authorize the Superintendent to execute Contract
P1454 with Integrus Architecture in the amount of $2,900,000, plus
reimbursable expenses.

4.      BACKGROUND INFORMATION

The firm was selected through RFP 04572. The term of this contract is from
September 1, 2016 through August 31, 2019.

5.      FISCAL IMPACT/REVENUE SOURCE

Fiscal impact to this action will be $2,900,000, plus reimbursable expenses.

The revenue source for this motion is the BEX IV capital levy funds.

Expenditure:      One-time    Annual    Multi-Year    N/A
"""

# No figure in the fiscal section at all -- only the motion has the money.
MOTION_ONLY_BAR = AWARD_BAR.replace(
    "Fiscal impact to this action will be $2,900,000, plus reimbursable expenses.",
    "This action helps to secure up to $8,295,900 in state funding assistance.")


def write_corpus(tmp_path, bars, rows):
    """bars: [(doc_id, meeting_date, filename, text, item_code)]."""
    root = str(tmp_path / "out")
    os.makedirs(os.path.join(root, "manifest"), exist_ok=True)
    os.makedirs(os.path.join(root, "contracts"), exist_ok=True)
    docs = []
    for doc_id, meeting_date, filename, text, item_code in bars:
        d = os.path.join(root, "text", "wp", meeting_date)
        os.makedirs(d, exist_ok=True)
        stem = os.path.splitext(filename)[0]
        with open(os.path.join(d, stem + ".txt"), "w", encoding="utf-8") as fh:
            fh.write(text)
        with open(os.path.join(d, stem + ".textmeta.json"), "w", encoding="utf-8") as fh:
            json.dump({"doc_id": doc_id, "pages": text.count("\f") + 1}, fh)
        docs.append({
            "doc_id": doc_id, "era": "wp", "meeting_id": "%s-regular" % meeting_date,
            "meeting_date": meeting_date, "filename": filename,
            "resolved_filename": filename, "filename_date": meeting_date.replace("-", ""),
            "item_code": item_code, "kind": "bar", "pages": text.count("\f") + 1,
        })
    with open(os.path.join(root, "manifest", "documents_classified.jsonl"),
              "w", encoding="utf-8") as fh:
        for d in docs:
            fh.write(json.dumps(d) + "\n")
    src = os.path.join(root, "contracts", "extracted.jsonl")
    with open(src, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return root


def row(meeting_date, title, **kw):
    r = {
        "meeting_id": "%s-regular" % meeting_date,
        "meeting_date": meeting_date,
        "item_no": kw.pop("item_no", "A.1"),
        "item_code": kw.pop("item_code", None),
        "char_start": 100,
        "era": "modern",
        "section": kw.pop("section", "action"),
        "title": title,
        "item_text": kw.pop("item_text", title),
        "board_action": "approved",
        "vote": "unanimous",
        "vendor_raw": None, "vendor_name": None,
        "action_type": kw.pop("action_type", "new"),
        "amount": None, "amount_kind": None,
        "prior_total": None, "revised_total": None,
        "contract_id": None, "po_number": None,
        "term_start": None, "term_end": None,
        "department": None, "program_or_project": None,
        "immediate_action": False,
        "fund": None, "funding_source_text": None, "procurement_method": None,
        "citation": {"doc_id": "min-1", "page_start": 3, "page_end": 3},
        "extractor": "regex", "extractor_notes": None,
    }
    r.update(kw)
    return r


def run(tmp_path, bars, rows, **kw):
    root = write_corpus(tmp_path, bars, rows)
    out, stats, _text = bf.run(out_root=root, since=kw.pop("since", "2016-08-01"), **kw)
    return root, out, stats


def bar_of(text, doc_id="d1", meeting_date="2019-03-27", filename="I09_x.pdf",
           item_code="I09"):
    return (doc_id, meeting_date, filename, text, item_code)


def parse(text):
    doc = {"doc_id": "d1", "meeting_id": "m", "meeting_date": "2019-03-27",
           "filename": "I09_x.pdf", "resolved_filename": "I09_x.pdf",
           "filename_date": "2019-03-27", "item_code": "I09"}
    return bf.Bar(doc, text)


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def test_bar_title_and_header_dates():
    b = parse(CLOSEOUT_BAR)
    assert b.title.startswith("BTA III/BEX IV: Final Acceptance of Contract K5069")
    assert (b.intro_date.isoformat(), b.action_date.isoformat()) == ("2019-03-27", "2019-04-17")


def test_closeout_table_wins_over_the_levy_budget_sentence():
    """The fiscal section opens with a $9.9M levy budget; the contract is
    $1.65M. The closeout table must win."""
    out = bf.parse_bar(parse(CLOSEOUT_BAR), "final_acceptance")
    assert out["amount_bar"] == 1_648_510.0
    assert out["amount_bar_kind"] == "final"
    assert out["bar_prior_total"] == 1_353_814.0
    assert out["bar_change_orders"] == 146_151.0
    assert out["vendor_raw_bar"] == "CDK Construction Services, Inc."


def test_fiscal_impact_sentence_and_detail_fields():
    out = bf.parse_bar(parse(AWARD_BAR), "new")
    assert out["amount_bar"] == 2_900_000.0
    assert out["amount_bar_kind"] == "total"
    assert out["amount_bar_section"] == "fiscal"
    assert out["contract_id"] == "P1454"
    assert out["rfp_number"] == "04572"
    assert out["fund"] == "BEX"
    assert "BEX IV capital levy" in out["funding_source_text"]
    assert out["procurement_method"] == "RFP"
    assert out["term_start"] == "September 1, 2016"
    assert out["term_end"] == "August 31, 2019"
    assert out["bar_lead_staff"].startswith("Dr. Lester Herndon")


def test_state_funding_assistance_is_not_an_amount_but_the_motion_is():
    out = bf.parse_bar(parse(MOTION_ONLY_BAR), "new")
    assert out["amount_bar"] == 2_900_000.0
    assert out["amount_bar_section"] == "motion"


def test_department_is_only_taken_from_an_explicit_line():
    """A LEAD STAFF role is a job title, not the corpus's `department`
    vocabulary ("Ops", "C&I"), so it must not leak into `department`."""
    assert bf.parse_bar(parse(AWARD_BAR), "new")["department"] is None
    out = bf.parse_bar(parse(AWARD_BAR.replace(
        "2.      PURPOSE", "Department: Capital Projects\n\n2.      PURPOSE")), "new")
    assert out["department"] == "Capital Projects"


def test_multiple_in_the_amount_of_figures_are_ambiguous():
    text = AWARD_BAR.replace(
        "Fiscal impact to this action will be $2,900,000, plus reimbursable expenses.",
        "Awards are made to seven vendors: Acme in the amount of $1,500,834.50; "
        "Beta in the amount of $558,462.00.")
    text = text.replace("in the amount of $2,900,000, plus\nreimbursable expenses.",
                        "as attached to this Board Action Report.")
    assert bf.parse_bar(parse(text), "new")["amount_bar"] is None


# --------------------------------------------------------------------------
# linking
# --------------------------------------------------------------------------

def test_links_by_item_code_and_fills_the_closeout_amount(tmp_path):
    r = row("2019-04-17", "BTA III/BEX IV: Final Acceptance of Contract K5069 with CDK "
                          "Construction Services, Inc., for the Seismic Upgrades at "
                          "Salmon Bay K-8 project",
            item_code="I09", action_type="final_acceptance")
    _root, out, stats = run(tmp_path, [bar_of(CLOSEOUT_BAR)], [r])
    got = out[0]
    assert got["bar_doc_id"] == "d1"
    assert got["bar_match_method"] in ("item_code_exact", "item_code_number", "title_jaccard")
    assert got["amount"] == 1_648_510.0
    assert got["amount_kind"] == "final"
    assert got["amount_source"] == "bar"
    assert got["prior_total"] == 1_353_814.0
    assert got["bar_citation"]["doc_id"] == "d1"
    assert stats["n_linked"] == 1


def test_links_across_the_intro_meeting_by_title(tmp_path):
    """The BAR is attached to the March introduction; the row is the April
    action meeting, 21 days later, and carries no item code."""
    r = row("2019-04-17", "BTA III/BEX IV: Final Acceptance of Contract K5069 with CDK "
                          "Construction Services, Inc., for the Seismic Upgrades at "
                          "Salmon Bay K-8 project", action_type="final_acceptance")
    _root, out, _stats = run(tmp_path, [bar_of(CLOSEOUT_BAR)], [r])
    assert out[0]["bar_doc_id"] == "d1"
    assert out[0]["bar_match_method"] == "title_jaccard"


def test_two_matching_bars_link_nothing(tmp_path):
    bars = [bar_of(CLOSEOUT_BAR, doc_id="d1", filename="I09_a.pdf", item_code="I09"),
            bar_of(CLOSEOUT_BAR, doc_id="d2", filename="I10_b.pdf", item_code="I10")]
    r = row("2019-04-17", "BTA III/BEX IV: Final Acceptance of Contract K5069 with CDK "
                          "Construction Services, Inc., for the Seismic Upgrades at "
                          "Salmon Bay K-8 project", action_type="final_acceptance")
    _root, out, stats = run(tmp_path, bars, [r])
    assert out[0].get("bar_doc_id") is None
    assert out[0]["amount"] is None
    assert stats["unlinked"]["ambiguous_title_jaccard"] == 1


def test_contract_id_conflict_vetoes_an_item_code_match(tmp_path):
    """Same meeting, same item code, but the row is about K5070 and the BAR
    about K5069 -- the numbering is off by one and the link would donate the
    wrong final amount."""
    r = row("2019-03-27", "BTA III: Final Acceptance of Contract K5070 with Other "
                          "Builders for the Seismic Upgrades at Whitman project",
            item_code="I09", action_type="final_acceptance")
    _root, out, stats = run(tmp_path, [bar_of(CLOSEOUT_BAR)], [r])
    assert out[0].get("bar_doc_id") is None
    assert stats["unlinked"]["contract_id_conflict"] == 1


# --------------------------------------------------------------------------
# merging
# --------------------------------------------------------------------------

def test_minutes_amount_is_never_overwritten_and_the_conflict_is_noted(tmp_path):
    r = row("2019-04-17", "BEX IV and BTA IV: Award Contract P1454 for Architectural "
                          "Services to Integrus Architecture, for the Classroom "
                          "Addition at Ingraham High School project",
            amount=1_000_000.0, amount_kind="not_to_exceed", fund="general")
    _root, out, stats = run(tmp_path, [bar_of(AWARD_BAR, meeting_date="2019-04-17")], [r])
    got = out[0]
    assert got["amount"] == 1_000_000.0            # untouched
    assert got["amount_kind"] == "not_to_exceed"
    assert got["amount_source"] == "minutes"
    assert got["fund"] == "general"                # not overwritten by BEX
    assert got.get("fund_source") is None
    assert any(n.startswith("bar_amount_conflict") for n in got["extractor_notes"])
    assert len(stats["conflicts"]) == 1
    # the BAR's own reading is still recorded, just not merged
    assert got["amount_bar"] == 2_900_000.0


def test_amounts_within_one_percent_are_not_a_conflict(tmp_path):
    r = row("2019-04-17", "BEX IV and BTA IV: Award Contract P1454 for Architectural "
                          "Services to Integrus Architecture, for the Classroom "
                          "Addition at Ingraham High School project",
            amount=2_900_000.0, amount_kind="unspecified")
    _root, out, stats = run(tmp_path, [bar_of(AWARD_BAR, meeting_date="2019-04-17")], [r])
    assert not stats["conflicts"]
    assert out[0]["extractor_notes"] is None


def test_null_fields_are_filled_and_tagged(tmp_path):
    r = row("2019-04-17", "BEX IV and BTA IV: Award Contract P1454 for Architectural "
                          "Services to Integrus Architecture, for the Classroom "
                          "Addition at Ingraham High School project")
    _root, out, _stats = run(tmp_path, [bar_of(AWARD_BAR, meeting_date="2019-04-17")], [r])
    got = out[0]
    assert got["contract_id"] == "P1454" and got["contract_id_source"] == "bar"
    assert got["fund"] == "BEX" and got["fund_source"] == "bar"
    assert got["procurement_method"] == "RFP"
    assert got["term_start"] == "September 1, 2016"
    assert got["amount_source"] == "bar"
    # vendor_raw IS filled when the minutes left it null (the BAR names the
    # counterparty far more reliably), tagged, and verbatim in the BAR text --
    # note "verbatim in the BAR", not in the item text, which is why
    # vendors.py (F1) has to be rerun after this stage.
    assert got["vendor_raw"] == "Integrus Architecture"
    assert got["vendor_raw_source"] == "bar"
    assert got["vendor_raw_bar"] == "Integrus Architecture"
    assert bf.norm_ws(got["vendor_raw"]) in bf.norm_ws(AWARD_BAR)
    # ...and it is never overwritten when the minutes already had one
    r2 = row("2019-04-17", got["title"], vendor_raw="From The Minutes LLC")
    _root2, out2, _s2 = run(tmp_path / "second",
                            [bar_of(AWARD_BAR, meeting_date="2019-04-17")], [r2])
    assert out2[0]["vendor_raw"] == "From The Minutes LLC"
    assert out2[0].get("vendor_raw_source") is None


def test_rows_outside_the_since_window_are_passed_through_untouched(tmp_path):
    old = row("2015-01-01", "BTA III/BEX IV: Final Acceptance of Contract K5069 with CDK "
                            "Construction Services, Inc.", action_type="final_acceptance")
    new = row("2019-04-17", "BTA III/BEX IV: Final Acceptance of Contract K5069 with CDK "
                            "Construction Services, Inc., for the Seismic Upgrades at "
                            "Salmon Bay K-8 project", action_type="final_acceptance")
    _root, out, stats = run(tmp_path, [bar_of(CLOSEOUT_BAR)], [old, new])
    assert len(out) == 2                       # same rows, same order
    assert out[0]["meeting_date"] == "2015-01-01"
    assert "bar_doc_id" not in out[0]
    assert out[1]["bar_doc_id"] == "d1"
    assert stats["n_scope"] == 1


# --------------------------------------------------------------------------
# outputs
# --------------------------------------------------------------------------

def test_fallback_batches_and_report(tmp_path):
    """A row whose BAR has no figure at all goes to the LLM fallback batch,
    with the fiscal-impact text attached; a filled row does not."""
    no_money = AWARD_BAR.replace(
        "Fiscal impact to this action will be $2,900,000, plus reimbursable expenses.",
        "There is no fiscal impact to this action.").replace(
        "in the amount of $2,900,000, plus\nreimbursable expenses.",
        "as attached to this Board Action Report.")
    r = row("2019-04-17", "BEX IV and BTA IV: Award Contract P1454 for Architectural "
                          "Services to Integrus Architecture, for the Classroom "
                          "Addition at Ingraham High School project")
    root, out, _stats = run(tmp_path, [bar_of(no_money, meeting_date="2019-04-17")], [r])
    assert out[0]["amount"] is None
    batch = os.path.join(root, "contracts", "bar_batches", "000.jsonl")
    assert os.path.exists(batch)
    brows = bf.read_jsonl(batch)
    assert len(brows) == 1
    assert brows[0]["bar_doc_id"] == "d1"
    assert "no fiscal impact" in brows[0]["bar_text"]
    # same key fields as contracts/batches/*.jsonl, so the E2 prompt applies
    for k in ("meeting_id", "item_no", "char_start", "title", "citation", "action_type"):
        assert k in brows[0]
    report = os.path.join(root, "qa", "bar_fill_report.md")
    assert os.path.exists(report)
    with open(report, encoding="utf-8") as fh:
        text = fh.read()
    assert "## Link method" in text and "## By action_type" in text
    assert os.path.exists(os.path.join(root, "contracts", "extracted_filled.jsonl"))


def test_amount_printed_check():
    assert bf.amount_printed("Total Contract including WSST  $1,648,510", 1648510.0)
    assert bf.amount_printed("...$758,433.77...", 758433.77)
    assert not bf.amount_printed("Total Contract including WSST  $1,648,510", 1648511.0)


# --------------------------------------------------------------------------
# conflicts triage file
# --------------------------------------------------------------------------

def test_conflicts_file_has_both_excerpts(tmp_path):
    r = row("2019-04-17", "BEX IV and BTA IV: Award Contract P1454 for Architectural "
                          "Services to Integrus Architecture, for the Classroom "
                          "Addition at Ingraham High School project",
            amount=1_000_000.0, amount_kind="not_to_exceed",
            item_text="Approval of this item would award Contract P1454 in the "
                      "amount of $1,000,000.")
    root, _out, _stats = run(tmp_path, [bar_of(AWARD_BAR, meeting_date="2019-04-17")], [r])
    rows = bf.read_jsonl(os.path.join(root, "qa", "bar_conflicts.jsonl"))
    assert len(rows) == 1
    c = rows[0]
    assert (c["amount_minutes"], c["amount_bar"]) == (1_000_000.0, 2_900_000.0)
    assert c["meeting_id"] == "2019-04-17-regular" and c["item_no"] == "A.1"
    assert "$1,000,000" in c["item_text_excerpt"]
    assert "$2,900,000" in c["bar_excerpt"]
    assert c["bar_doc_id"] == "d1" and c["bar_page_start"]


# --------------------------------------------------------------------------
# --merge-llm
# --------------------------------------------------------------------------

def llm_out(root, rows):
    d = os.path.join(root, "contracts", "bar_batches")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "000.out.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def llm_row(batch_row, **kw):
    r = {"meeting_id": batch_row["meeting_id"], "item_no": batch_row["item_no"],
         "char_start": batch_row["char_start"], "citation": batch_row["citation"],
         "extractor": "llm", "llm_confidence": 0.7, "extractor_notes": None}
    for f in bf.LLM_FILLABLE:
        r.setdefault(f, None)
    r.update(kw)
    return r


def no_money_bar():
    return AWARD_BAR.replace(
        "Fiscal impact to this action will be $2,900,000, plus reimbursable expenses.",
        "The contract value is stated in the attached agreement: $1,234,567 over "
        "the term.").replace(
        "in the amount of $2,900,000, plus\nreimbursable expenses.",
        "as attached to this Board Action Report.")


def setup_fallback(tmp_path):
    """A row the regex could not fill, so it lands in bar_batches/000.jsonl."""
    r = row("2019-04-17", "BEX IV and BTA IV: Award Contract P1454 for Architectural "
                          "Services to Integrus Architecture, for the Classroom "
                          "Addition at Ingraham High School project")
    root, out, _stats = run(tmp_path, [bar_of(no_money_bar(), meeting_date="2019-04-17")], [r])
    assert out[0]["amount"] is None
    batch = bf.read_jsonl(os.path.join(root, "contracts", "bar_batches", "000.jsonl"))
    assert len(batch) == 1
    return root, batch[0]


def test_merge_llm_fills_only_null_fields_and_tags_them(tmp_path):
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, amount="$1,234,567", amount_kind="not_to_exceed",
                           contract_id="P1454", department="Capital Projects")])
    rows, stats, _ = bf.merge_llm(out_root=root)
    got = rows[0]
    assert got["amount"] == 1234567.0
    assert got["amount_kind"] == "not_to_exceed"
    assert got["amount_source"] == "bar_llm"
    assert got["amount_kind_source"] == "bar_llm"
    assert got["department"] == "Capital Projects"
    assert got["department_source"] == "bar_llm"
    # the regex pass already filled contract_id -- the LLM must not restate it
    assert got["contract_id"] == "P1454"
    assert got["contract_id_source"] == "bar"   # regex got there first
    assert got["bar_llm_confidence"] == 0.7
    assert stats["n_merged"] == 1 and stats["n_rejected"] == 0


def test_merge_llm_scaled_money_is_accepted_when_the_bar_prints_the_digits(tmp_path):
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, amount=1234567, amount_kind="total")])
    rows, _stats, _ = bf.merge_llm(out_root=root)
    assert rows[0]["amount"] == 1234567.0
    # "total" is not in E1's vocabulary; it maps to unspecified
    assert rows[0]["amount_kind"] == "unspecified"


def test_merge_llm_rejects_a_figure_that_is_not_in_the_bar(tmp_path):
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, amount="$9,999,999", amount_kind="total", fund="BEX")])
    rows, stats, _ = bf.merge_llm(out_root=root)
    assert rows[0]["amount"] is None
    assert rows[0].get("fund_source") != "bar_llm"    # whole row rejected
    assert stats["n_rejected"] == 1
    rej = [r for r in bf.read_jsonl(os.path.join(root, "qa", "bar_llm_rejects.jsonl"))
           if not r.get("persistent")]   # the curated list is mirrored in too
    assert len(rej) == 1
    assert any("amount_not_printed_in_bar" in r for r in rej[0]["reasons"])
    assert rej[0]["bar_text_excerpt"]


def test_merge_llm_rejects_invented_identifiers_and_vendors(tmp_path):
    """Checked against everything the model was shown (bar_text + the batch
    row's title/item_text), so an echoed field passes and an invented one
    does not."""
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, po_number="7800009999"),
                   llm_row(b, vendor_raw="Nonexistent Vendor LLC")])
    _rows, stats, _ = bf.merge_llm(out_root=root)
    assert stats["n_rejected"] >= 1
    assert stats["hard"]["po_number_not_in_bar"] + stats["hard"]["vendor_raw_not_verbatim"] >= 1


def test_merge_llm_soft_drops_a_bad_fund_and_keeps_the_row(tmp_path):
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, amount="1,234,567", amount_kind="total",
                           fund="Levy Money", term_start="not a date")])
    rows, stats, _ = bf.merge_llm(out_root=root)
    assert rows[0]["amount"] == 1234567.0        # row kept
    assert rows[0]["fund_source"] != "bar_llm"   # regex value (or null) stands
    assert stats["n_rejected"] == 0
    assert stats["soft"]["fund_not_in_vocabulary"] == 1
    assert stats["soft"]["term_start_unparseable"] == 1
    assert any(n.startswith("bar_llm_dropped:") for n in rows[0]["extractor_notes"])


def test_merge_llm_is_idempotent(tmp_path):
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, amount="1,234,567", amount_kind="total",
                           fund="Levy Money")])
    bf.merge_llm(out_root=root)
    path = os.path.join(root, "contracts", "extracted_filled.jsonl")
    with open(path, encoding="utf-8") as fh:
        first = fh.read()
    rows, stats, _ = bf.merge_llm(out_root=root)
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == first, "a second --merge-llm changed the file"
    assert stats["n_merged"] == 0 and stats["n_nothing_left"] == 1


def test_merge_llm_survives_a_regex_rerun(tmp_path):
    """The documented order: bar_fill rebuilds the file (dropping LLM fills),
    then --merge-llm puts them back."""
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, amount="1,234,567", amount_kind="total")])
    bf.merge_llm(out_root=root)
    rows, _stats, _ = bf.run(out_root=root, since="2016-08-01")
    assert rows[0]["amount"] is None              # regex pass wiped it
    rows, _stats, _ = bf.merge_llm(out_root=root)
    assert rows[0]["amount"] == 1234567.0         # and --merge-llm restores it


def test_merge_llm_tolerates_malformed_lines_and_unknown_keys(tmp_path):
    root, b = setup_fallback(tmp_path)
    d = os.path.join(root, "contracts", "bar_batches")
    with open(os.path.join(d, "000.out.jsonl"), "w", encoding="utf-8") as fh:
        fh.write("{not json\n")
        fh.write(json.dumps(llm_row(b, amount="1,234,567", amount_kind="total")) + "\n")
        fh.write(json.dumps({"meeting_id": "nope", "item_no": "Z.9",
                             "char_start": 1, "amount": 5000}) + "\n")
    rows, stats, _ = bf.merge_llm(out_root=root)
    assert stats["n_bad_lines"] == 1
    assert stats["hard"]["unknown_key"] == 1
    assert rows[0]["amount"] == 1234567.0


def test_llm_money_parsing():
    assert bf.llm_money("$1,234,567.00") == 1234567.0
    assert bf.llm_money("1.75 million") == 1750000.0
    assert bf.llm_money("1.75M") == 1750000.0
    assert bf.llm_money(42000) == 42000.0
    assert bf.llm_money("about a million") is None
    # a mantissa already >= 1000 is a source typo, not a trillion
    assert bf.llm_money("4,352,000 million") == 4352000.0


def test_figure_in_text_accepts_the_scaled_printed_form():
    assert bf.figure_in_text("proceeds of approximately $1.75 million over four years",
                             1750000.0)
    assert bf.figure_in_text("Total Contract including WSST $1,648,510", 1648510.0)
    assert not bf.figure_in_text("Total Contract including WSST $1,648,510", 999999.0)


# --------------------------------------------------------------------------
# malformed figures and implausible ratios
# --------------------------------------------------------------------------

def test_money_at_rejects_malformed_comma_runs():
    """The two source typos in the corpus. A MONEY match consumes only the
    well-grouped prefix, so accepting it silently divides by 1000."""
    assert bf.money_at("5,500250,000", 0) is None      # missing comma
    assert bf.money_at("3,700.000", 0) is None         # period for a comma
    assert bf.money_at("1,213,256,18", 0) is None      # comma for a period
    assert bf.money_at("1,648,510", 0) == 1648510.0
    assert bf.money_at("758,433.77", 0) == 758433.77
    assert bf.money_at("988,000.00", 0) == 988000.0
    assert bf.money_at("42000", 0) == 42000.0


def test_a_malformed_bar_figure_is_not_filled(tmp_path):
    text = AWARD_BAR.replace(
        "Fiscal impact to this action will be $2,900,000, plus reimbursable expenses.",
        "The fiscal impact of this motion will be in the amount of $5,500250,000, "
        "plus Washington State sales tax.").replace(
        "in the amount of $2,900,000, plus\nreimbursable expenses.",
        "as attached to this Board Action Report.")
    r = row("2019-04-17", "BEX IV and BTA IV: Award Contract P1454 for Architectural "
                          "Services to Integrus Architecture, for the Classroom "
                          "Addition at Ingraham High School project")
    _root, out, _stats = run(tmp_path, [bar_of(text, meeting_date="2019-04-17")], [r])
    assert out[0]["amount"] is None            # not 5500.0
    assert out[0].get("amount_bar") is None


def test_implausible_ratio_is_flagged_and_blocks_the_total_fills(tmp_path):
    text = CLOSEOUT_BAR.replace("Total Contract including WSST       $1,648,510",
                                "Total Contract including WSST       $1,648")
    r = row("2019-03-27", "BTA III/BEX IV: Final Acceptance of Contract K5069 with CDK "
                          "Construction Services, Inc., for the Seismic Upgrades at "
                          "Salmon Bay K-8 project",
            item_code="I09", action_type="final_acceptance",
            amount=1_648_510.0, amount_kind="final")
    _root, out, stats = run(tmp_path, [bar_of(text)], [r])
    got = out[0]
    assert got["amount"] == 1_648_510.0
    assert any(n.startswith("bar_amount_implausible_vs_minutes")
               for n in got["extractor_notes"])
    # the same suspect parse must not donate prior_total/revised_total either
    assert got["prior_total"] is None and got["revised_total"] is None
    assert len(stats["conflicts"]) == 1


def test_implausible_ratio_helper():
    assert bf._implausible_ratio(5500, 5_250_000)
    assert bf._implausible_ratio(5_250_000, 5500)
    assert not bf._implausible_ratio(2_900_000, 1_000_000)
    assert not bf._implausible_ratio(None, 100)


def test_monthly_kind_from_extract_is_accepted(tmp_path):
    """E1's AMOUNT_KINDS gained `monthly`; the LLM merge must pass it through
    rather than flattening it to unspecified."""
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, amount="1,234,567", amount_kind="monthly")])
    rows, _stats, _ = bf.merge_llm(out_root=root)
    assert rows[0]["amount_kind"] == "monthly"
    assert "monthly" in bf.AMOUNT_KINDS


def test_merge_llm_rejects_malformed_money_strings(tmp_path):
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, amount="3,700.000", amount_kind="total")])
    rows, stats, _ = bf.merge_llm(out_root=root)
    assert rows[0]["amount"] is None
    assert stats["hard"]["amount_unparseable"] == 1


# --------------------------------------------------------------------------
# hand-checked amount reject list
# --------------------------------------------------------------------------

def write_reject_csv(tmp_path, key, reason="hand_checked_wrong"):
    path = str(tmp_path / "rejects.csv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# curated\nmeeting_id,item_no,char_start,amount,reason,note\n")
        fh.write("%s,%s,%s,1234567.0,%s,because\n" % (key[0], key[1], key[2], reason))
    return path


def test_amount_reject_list_blocks_the_amount_but_keeps_other_fields(tmp_path, monkeypatch):
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, amount="1,234,567", amount_kind="total",
                           fund="BEX", department="Capital Projects")])
    monkeypatch.setattr(bf, "AMOUNT_REJECTS_CSV",
                        write_reject_csv(tmp_path, bf._key(b), "top_of_a_stated_range"))
    rows, stats, _ = bf.merge_llm(out_root=root)
    got = rows[0]
    assert got["amount"] is None and got.get("amount_source") is None
    assert got["department"] == "Capital Projects"      # other fields still merged
    assert got["department_source"] == "bar_llm"
    assert "bar_llm_amount_rejected:top_of_a_stated_range" in got["extractor_notes"]
    assert stats["n_amount_rejected"] == 1


def test_amount_reject_survives_a_regex_rerun_and_a_second_merge(tmp_path, monkeypatch):
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, amount="1,234,567", amount_kind="total")])
    monkeypatch.setattr(bf, "AMOUNT_REJECTS_CSV", write_reject_csv(tmp_path, bf._key(b)))
    bf.merge_llm(out_root=root)
    bf.run(out_root=root, since="2016-08-01")          # rebuilds from extracted.jsonl
    rows, _stats, _ = bf.merge_llm(out_root=root)
    assert rows[0]["amount"] is None, "a rerun must not re-fill a rejected amount"


def test_reject_entries_are_mirrored_into_the_qa_file_and_read_back(tmp_path, monkeypatch):
    root, b = setup_fallback(tmp_path)
    llm_out(root, [llm_row(b, amount="1,234,567", amount_kind="total")])
    monkeypatch.setattr(bf, "AMOUNT_REJECTS_CSV", write_reject_csv(tmp_path, bf._key(b)))
    bf.merge_llm(out_root=root)
    rej = bf.read_jsonl(os.path.join(root, "qa", "bar_llm_rejects.jsonl"))
    persistent = [r for r in rej if r.get("persistent")
                  and tuple(r["key"]) == bf._key(b)]
    assert len(persistent) == 1
    assert persistent[0]["scope"] == "amount"
    # ...and the mirrored row alone is enough to keep blocking it
    monkeypatch.setattr(bf, "AMOUNT_REJECTS_CSV", str(tmp_path / "gone.csv"))
    assert bf._key(b) in bf.load_amount_rejects(root)
    bf.run(out_root=root, since="2016-08-01")
    rows, _stats, _ = bf.merge_llm(out_root=root)
    assert rows[0]["amount"] is None


def test_the_checked_in_reject_list_parses(tmp_path):
    """`tmp_path` is an out_root with no qa/, so only the shipped CSV is read."""
    rejects = bf.load_amount_rejects(out_root=str(tmp_path))
    assert len(rejects) >= 6
    for key, meta in rejects.items():
        assert len(key) == 3 and all(x not in (None, "") for x in key)
        assert isinstance(key[2], int)          # char_start is an int, so keys match
        assert meta["reason"] and meta["note"]  # every entry says why
