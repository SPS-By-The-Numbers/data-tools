"""
extract.py -- Task E1 (see extractors/sps_web/PLAN.md, Section 3): the contract
pre-filter, the deterministic regex extractor, the row validator, and the
gold-set harness.

Usage (from the repo root)::

    venv/bin/python3 -m extractors.sps_web.extract                     # whole corpus
    venv/bin/python3 -m extractors.sps_web.extract --era modern --limit 50
    venv/bin/python3 -m extractors.sps_web.extract --gold              # score the gold set
    venv/bin/python3 -m extractors.sps_web.extract --sample-prefilter 60

Inputs (read-only; the crawl and the segmenter are still filling these in):

* ``out_sps_web/items/<meeting_id>.jsonl`` -- one row per business item, from
  ``segment.py``.  Read its docstring for the item schema.
* ``out_sps_web/manifest/documents_classified.jsonl`` -- ``doc_id -> era,
  school_year, pages, source_url``.  ``pages`` is null for roughly half the
  corpus (text extraction still running), so the page-count validation is
  skipped, not failed, when it is missing.

Outputs (all rewritten from scratch on every run -- the module is rerunnable
and owns only these three paths):

* ``out_sps_web/contracts/regex_rows.jsonl`` -- every admitted item with its
  extraction, whether or not it validated (``valid``, ``reasons``).
* ``out_sps_web/contracts/residual.jsonl`` -- the subset that E2 must re-do
  with an LLM: a required field is null or the validator rejected the row.
* ``out_sps_web/contracts/residual_new.jsonl`` -- the part of that residual not
  already present in ``contracts/llm_rows.jsonl`` (same
  ``(meeting_id, item_no, char_start)`` key), so a rerun only batches the delta.
  Written only when ``llm_rows.jsonl`` exists.
* ``out_sps_web/qa/extract_report.md`` -- counts, coverage, gold scores.

-----------------------------------------------------------------------------
Eras
-----------------------------------------------------------------------------

The five reporting eras are ``legacy`` (2005-2011 ``/area/board/`` PDFs),
``archive`` (2006-2012 spsarchivepublic "edited agendas"), ``blackboard``
(2011-12 -> 2015-16 ``YYYYMMDD_Minutes.pdf``), ``wp1620`` (2016-17 -> 2020-21
minutes) and ``modern`` (2021-22 -> present SharePoint minutes).  ``era_of()``
assigns the last three by **meeting date**, not by which host the file survived
on, so a 2018 meeting whose only minutes are a Blackboard copy is still
``wp1620``.  Nothing in the extractor branches on the era -- the patterns are
era-agnostic and ``blackboard`` inherits the same set -- it is a reporting
dimension only.  The first two are *agendas*: they describe what a vote
*will* do and, per the segmenter's report, only ~28% carry any dollar amount
at all -- the vendor and the money live in the minutes or the Board Action
Report.  Nothing here guesses at what the agenda does not print.

-----------------------------------------------------------------------------
Named patterns
-----------------------------------------------------------------------------

Every pattern that fires is recorded by name in ``patterns_fired`` so the QA
report can attribute coverage.  Vendor anchors (the regex locates an anchor;
``_walk_vendor`` then walks forward token by token while the tokens still look
like a proper name -- see its docstring for the stop rules):

===========================  =============================================================
name                         example (verbatim from the corpus)
===========================  =============================================================
``v_change_order_with``      "execute Construction Change Order No. 25 with Absher Construction Company"
``v_final_acceptance_with``  "Final Acceptance of Contract P5099 ... with CDK Construction Services, Inc."
``v_final_acceptance_contr`` "Final Acceptance of Contract P5045, Lydig Construction, Inc."
``v_accept_work_of``         "accept the work of JV Constructors, Inc. as complete"
``v_amendment_with``         "approve the contract amendment with Emerald Learning Center in the amount of $414,407"
``v_lease_with``             "lease agreement with Sound Transit"
``v_agreement_with``         "execute an interagency agreement with the University of Washington Haring Center"
``v_contract_with``          "execute a contract with Dairy Fresh Farms, Inc., in the amount of $1,146,623"
``v_submitted_by``           "authorize the bid as submitted by Rabanco Ltd. in the amount of $147,233"
``v_general_contractor``     "Cope Construction Company, as general contractor, in the amount of $1,196,400"
``v_purchase_from``          "purchase of equipment from Black Box"
``v_purchase_through``       "execution of purchase orders through Apple"
``v_contract_to``            "Award Construction Contract P5121, Bid No. B11823, to Jody Miller Construction"
``v_award_to``               "award a contract to Mahlum Architect"
``v_between_district_and``   "Interlocal Agreement between Seattle School District and the City of Seattle"
``v_funding_from``           "accept federal funding from the U.S. Department of Health and Human Services"
``v_reimburse``              "reimburse the Washington State Auditor's Office for its services"
``v_accept_proposed``        "accept the proposed Washington Schools Risk Management Pool coverage agreement"
``v_before_amount``          "as follows: Mobile Beacon in the amount of $273,113" (walks *backwards*)
``v_with_amount``            "with Lydig Construction, Inc., in the amount of $4,073,000" (loose fallback)
``v_to_vendor_for``          "awarded to First Student" (legacy; narrow on purpose)
===========================  =============================================================

The list is ordered: when several anchors hit, the most specific one wins, ties
break on position, and a candidate that is a strict extension of the winner
("Durham School Services" vs "Durham School Services, Inc.") replaces it.

Amount patterns (``amount_kind`` in parentheses):

============================  ============================================================
name                          example
============================  ============================================================
``a_not_to_exceed``           "for an amount not to exceed $1,368,678"  (not_to_exceed)
``a_nte_total``               "for a total Not-To-Exceed (NTE) amount of $500,000"  (not_to_exceed)
``a_in_the_amount_of``        "in the amount of $31,496,750"  (unspecified)
``a_in_the_total_amount_of``  "in the total amount of $173,000"  (unspecified)
``a_revised_total``           "for a revised total contract amount of $1,595,252"  (revised_total)
``a_total_contract_amount``   "for a total contract amount of $1,329,287"  (revised_total)
``a_new_total``               "for a new contract total of $2,100,000"  (revised_total)
``a_prior_total``             "the current contract amount of $914,880"  (-> prior_total)
``a_increase``                "an increase of $250,000"  (increase)
``a_final_amount``            "final contract amount of $12,411,244"  (final)
``a_annual``                  "$85,000 per year"  (annual)
``a_up_to``                   "payment of up to $500,000"  (not_to_exceed)
``a_for_amount``              "for $147,233"  (unspecified)
``a_bare``                    any other "$X" in the item  (unspecified)
============================  ============================================================

Amounts written "$7.5 million" / "$1.2 billion" are scaled.  ``prior_total``
and ``revised_total`` are pulled out of the pool before the primary amount is
chosen, so "in the amount of $414,407, for a total contract amount of
$1,329,287" yields ``amount=414407`` and ``revised_total=1329287``.

Identifier / term / action patterns:

``i_contract_id``     "Contract P5121", "contract K5120", "Contract No. P1460"
``i_po_number``       "PO7800002212", "Purchase Order No. 78000123"
``i_bid_number``      "Bid No. B11823", "bid number B11722", "Bid B08575"
``i_rfp_number``      "RFP04725", "RFQ02758", "RFP No. 12345"
``t_term_range``      "from July 1, 2019 through June 30, 2020", "for the term 9/1/21 - 8/31/22"
``t_school_year``     "for the 2018-19 school year"  (-> term_start/term_end unset; note only)
``x_immediate``       "Immediate action is in the best interest of the district."
``x_action_type``     the keyword table in ``classify_action``

Row fields added after the F1/F2 review: ``co_vendors_raw`` (a list -- joint
awards such as "First Student, Inc. and Zum Services, Inc." keep the primary in
``vendor_raw`` and the rest here, each verbatim), ``vendor_name`` (the display
form: ``vendor_raw`` minus its legal suffix and punctuation -- F1 canonicalises
from ``vendor_raw``, not from this), ``item_text`` (the text the extractor ran
on, so the linking stage never has to reopen ``items/``), ``missing_required``
and ``residual_category`` (``null`` on a complete row).

``validate()`` additionally rejects: an amount above ``AMOUNT_CEILING`` ($2B --
the source really does print "$39,542,000,000"), a ``co_vendors_raw`` entry that
is not verbatim, and a ``contract_id``/``po_number``/``bid_number``/
``rfp_number`` that is not printed in *this* item (identifiers were leaking
between items in the LLM pass).

Never guess: a field the text does not literally print stays ``null``.  When an
item names more than one vendor or more than one amount, the primary (the one
attached to the first vendor anchor) is emitted and the rest go into
``extractor_notes`` as ``extra_vendor:`` / ``extra_amount:`` entries.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections import Counter

ROOT = os.path.join(os.getcwd(), "out_sps_web")
ITEMS_DIR = os.path.join(ROOT, "items")
MANIFEST = os.path.join(ROOT, "manifest", "documents_classified.jsonl")
CONTRACTS_DIR = os.path.join(ROOT, "contracts")
QA_DIR = os.path.join(ROOT, "qa")
GOLD_PATH = os.path.join(os.path.dirname(__file__), "tests", "fixtures", "gold", "gold.jsonl")

ERAS = ("legacy", "archive", "blackboard", "wp1620", "modern")
ACTION_TYPES = ("new", "amendment", "change_order", "renewal",
                "final_acceptance", "purchase", "other")
AMOUNT_KINDS = ("not_to_exceed", "revised_total", "increase", "final",
                "annual", "monthly", "unspecified")


# ---------------------------------------------------------------------------
# 1. pre-filter
# ---------------------------------------------------------------------------

INCLUDE_RE = re.compile(
    r"\bcontract(s|ed|ing|ual)?\b|\bagreement(s)?\b|\bamendment(s)?\b|"
    r"\bamend(ed|ing)?\b|\bchange\s+order\b|\bpurchas(e|es|ed|ing)\b|"
    r"\bPO\s?\d|\bpurchase\s+order\b|\baward(s|ed|ing)?\b|\bRFP\b|\bRFQ\b|"
    r"\bRFI\b|\bIFB\b|\bbid(s|ding)?\b|\blease(s|d)?\b|\bMOU\b|\bMOA\b|"
    r"\bmemorand(um|a)\s+of\s+(understanding|agreement)\b|\binterlocal\b|"
    r"\bfinal\s+acceptance\b|\brenew(al|als|ed)?\b|\bvendor(s)?\b|"
    r"\blicens(e|es|ing)\b|\bsubscription(s)?\b|\bservices\b|"
    r"\bgeneral\s+contractor\b|\bprocurement\b|\bsole\s+source\b|"
    r"\bnot[- ]to[- ]exceed\b|\bconsultant\b",
    re.I)

# Hard exclusions -- these never carry a board contract action even though the
# words above appear in them ("Vendor" in a warrant table, "amendment" to a
# meeting calendar, "services" in a policy title, ...).
EXCLUDE_RES = [
    ("warrants", re.compile(
        r"^\s*(approval\s+of\s+)?warrants?\b|warrant\s+register|warrants?\s+report", re.I)),
    ("minutes", re.compile(r"^\s*(approval\s+of\s+)?minutes\b|^\s*minutes\s+of\b", re.I)),
    ("personnel", re.compile(r"^\s*personnel\s+report\b|^\s*(approval\s+of\s+the\s+)?"
                             r"personnel\s+(report|action)", re.I)),
    ("calendar", re.compile(r"\b(board\s+meeting|regular\s+board\s+meeting|school\s+year|"
                            r"academic|instructional)\s+(calendar|schedule)\b", re.I)),
    ("floor_amendment", re.compile(r"^\s*amendments?\s+(no\.?\s*)?\d+\b", re.I)),
    # F2 found these typed as contract amendments: "Proposed Amendments to
    # the Student Assignment Plan", "Amendments to Policy D12.00", "Annual
    # Review of Board Bylaws".  Not anchored at ^ any more -- "Proposed" /
    # "Approval of" prefixes are common.
    ("non_contract_amendment", re.compile(
        r"\bamendments?\s+to\s+(?:the\s+)?[^,]{0,60}?\b(motion|standards?|plans?|"
        r"polic(y|ies)|procedures?|calendar|schedule|budget|resolution|bylaws?|"
        r"goals?|guidelines?|handbook|manual|assignment\s+plan)\b|"
        r"\bboard\s+bylaws?\b|\bbylaws?\s+(?:review|amendments?|revisions?)\b|"
        r"\b(?:annual\s+)?review\s+of\s+(?:the\s+)?board\s+(?:bylaws?|polic)", re.I)),
    ("resolution", re.compile(
        r"^\s*(approval\s+of\s+)?(board\s+)?resolutions?\s+(no\.?\s*)?[\d/]|"
        r"^\s*(approval\s+of\s+)?resolution\b", re.I)),
    ("policy", re.compile(r"^\s*(approval\s+of\s+)?(revisions?\s+to\s+)?(new\s+|revised\s+)?"
                          r"(board\s+)?polic(y|ies)\b|\bpolic(y|ies)\s+(nos?\.?\s*)?\d{3,4}\b|"
                          r"\bsuperintendent\s+procedure\b", re.I)),
    ("board_governance", re.compile(
        r"\bboard\s+(self[- ]?)?evaluation\b|\bboard\s+retreat\b|\bschool\s+board\s+"
        r"directors?'?\s+(district|compensation)\b|\bexcused\s+absence\b|"
        r"\boath\s+of\s+office\b|\bboard\s+committee\s+assignments?\b", re.I)),
    ("bargaining", re.compile(
        r"\bcollective\s+bargaining\s+agreement\b|\bcba\b|\btentative\s+agreement\b",
        re.I)),
]

# Signals strong enough to override a hard exclusion (a genuine contract action
# whose title happens to trip one of the patterns above).
OVERRIDE_RE = re.compile(
    r"in\s+the\s+(total\s+)?amount\s+of\s*\$|not\s+to\s+exceed\s*\$|"
    r"\bcontract\s+with\b|\bcontract\s+amendment\b|\bchange\s+order\s+no\b|"
    r"\bfinal\s+acceptance\s+of\b|award\s+(a|the|construction|contract)", re.I)


def _text_of(item: dict) -> str:
    """The item's full text: everything the segmenter captured."""
    return " ".join(x for x in (item.get("title") or "",
                                item.get("body") or "",
                                item.get("motion_text") or "") if x)


# Accepting money the district *receives* is not a contract action.  A grant
# **agreement**, or a pass-/flow-through grant naming the counterparty, still is.
REVENUE_ACCEPTANCE_RE = re.compile(
    r"\bacceptance\s+of\s+[^.]{0,80}?\b(reimbursements?|donations?|gifts?|"
    r"grants?|funds?|funding|revenues?|contributions?|awards?)\b|"
    r"\baccept(?:s|ed|ing)?\s+(?:the\s+|a\s+|an\s+)?[^.]{0,60}?\b"
    r"(grant\s+funds?|donations?|gifts?|reimbursements?|contributions?|"
    r"federal\s+funding|state\s+funding|funding\s+from|funds\s+from)\b",
    re.I)
REVENUE_OVERRIDE_RE = re.compile(
    r"\bgrant\s+agreements?\b|\b(?:pass|flow)[- ]through\b|"
    r"\binterlocal\s+agreement\b|\bcontract\s+with\b|\bMOU\b|\bMOA\b",
    re.I)


# Floor amendments to a motion are minuted inside the item they amend; the
# word "amendment" there is about parliamentary procedure, not a contract.
FLOOR_NOISE_RE = re.compile(
    r"\d*[a-z]?\.?\s*amendments?\s+to\s+(?:the\s+)?motion[^.]{0,80}|"
    r"(?:Director|Dr\.)\s+\w+\s+(?:presented|moved|offered|proposed)\s+the\s+"
    r"following\s+amendment[^.]{0,40}|this\s+amendment\s+(?:failed|passed)[^.]{0,60}",
    re.I)


def is_contract_like(item: dict) -> tuple[bool, str]:
    """Return ``(admitted, reason)``.  ``reason`` names the deciding rule."""
    title = item.get("title") or ""
    motion = item.get("motion_text") or ""
    hay = FLOOR_NOISE_RE.sub(" ", f"{title}\n{motion}")
    for name, rx in EXCLUDE_RES:
        if rx.search(title) and not OVERRIDE_RE.search(hay):
            return False, f"excluded:{name}"
    if REVENUE_ACCEPTANCE_RE.search(hay) and not REVENUE_OVERRIDE_RE.search(hay):
        return False, "excluded:revenue_acceptance"
    m = INCLUDE_RE.search(hay)
    if not m:
        return False, "no_contract_keyword"
    return True, f"keyword:{m.group(0).strip().lower()}"


# ---------------------------------------------------------------------------
# 2. regex extractor
# ---------------------------------------------------------------------------

MONEY_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")
# The whole printed run, so a figure the PDF got wrong can be recognised and
# *rejected* instead of silently truncated: MONEY_RE alone reads "$1,100,00"
# (Follett, 2017-05-03) as 1,100 and "$1,213,256,18" as 1,213.
MONEY_RUN_RE = re.compile(r"\$\s?\d(?:[\d,]*\d)?(?:\.\d+)?")


def well_formed_money(run: str) -> bool:
    """True when every comma group is 3 digits (the first may be 1-3)."""
    body = run.replace("$", "").replace(" ", "")
    body = body.split(".")[0]
    groups = body.split(",")
    if len(groups) == 1:
        return bool(groups[0])
    if not (1 <= len(groups[0]) <= 3):
        return False
    return all(len(g) == 3 for g in groups[1:])

# Tokens that end a vendor name.
_STOP_WORDS = {
    "in", "for", "to", "with", "on", "at", "as", "by", "from", "of", "and",
    "which", "that", "who", "is", "was", "will", "would", "shall", "under",
    "per", "not", "effective", "beginning", "through", "thru", "dated",
    "covering", "during", "over", "up", "an", "a", "the", "or", "but",
    "including", "plus", "pursuant", "using", "via", "so", "if", "when",
    "commencing", "starting", "beginning", "expiring", "amount", "amounts",
    "totaling", "totalling", "valued", "worth", "approximately", "about",
    "this", "these", "those", "it", "its", "their", "his", "her", "such",
    "authorize", "authorizing", "authorized", "approve", "approval",
}
# Lowercase tokens allowed *inside* a vendor name when a capitalised token
# follows ("University of Washington", "Boys and Girls Clubs", "Coast to Coast
# Turf", "d/b/a").  Deliberately excludes "for"/"at"/"on", which start a
# trailing prepositional phrase far more often than they sit inside a name.
_INNER_WORDS = {"of", "and", "the", "to", "de", "la", "le", "du", "des",
                "d/b/a", "dba", "&", "|"}
# "to" is a legitimate infix ("Coast to Coast Turf") but far more often opens
# an infinitive clause ("… with Shoreline School District to Provide …").
_TO_VERBS = {"provide", "support", "manage", "implement", "replace", "develop",
             "deliver", "serve", "operate", "design", "construct", "perform",
             "furnish", "install", "complete", "purchase", "increase",
             "address", "cover", "supply", "host", "conduct", "administer",
             "expand", "continue", "resolve", "reflect", "allow", "assist",
             "begin", "extend", "renew", "fund", "build", "repair", "upgrade"}
# Articles skipped *before* the name so `vendor_raw` stays a clean substring
# ("with the King County Directors' Association" -> "King County ...").
_LEAD_ARTICLES = ("the ", "The ", "a ", "an ", "An ", "A ")
# Skipped before the name so `vendor_raw` is the company itself: "with
# reseller CDW-G", "to the firm Mahlum".
_LEAD_QUALIFIERS = ("reseller ", "vendor ", "contractor ", "firm ",
                    "consultant ", "provider ", "agency ", "supplier ")
# A capitalised word after "and" that clearly opens a new clause, not a second
# half of a company name ("Arcadis and Award Emergency Public Works ...").
_AND_STOP = {"award", "awards", "contract", "contracts", "approval", "approve",
             "authorization", "authorize", "resolution", "amendment", "bid",
             "rfp", "rfq", "purchase", "change", "final", "item", "board",
             "further", "that", "this", "budget", "transfer", "acceptance"}
# "for" continues a name only after one of these head nouns ("Academy for
# Precision Learning", "Center for Children and Youth Justice"); everywhere
# else it starts the trailing purpose clause ("... for the 2018-19 school year").
_FOR_HEADS = {"academy", "center", "centre", "institute", "foundation",
              "council", "coalition", "partnership", "society", "alliance",
              "association", "committee", "organization", "agency", "fund",
              "network", "initiative", "program", "programs", "school",
              "schools", "group", "consortium", "office", "college"}
_ABBREVS = {"inc.", "inc.,", "llc.", "l.l.c.", "ltd.", "ltd.,", "co.", "co.,",
            "corp.", "corp.,", "assoc.", "assn.", "bros.", "st.", "u.s.",
            "p.s.", "p.c.", "pllc.", "no.", "dept.", "jr.", "sr.", "mt.",
            "intl.", "int'l.", "s.", "n.", "e.", "w."}
# A short lowercase prefix followed by a capital is a brand, not a stray word.
_CAMEL_BRAND_RE = re.compile(r"^[a-z]{1,3}[A-Z]\w*")
# The subset that genuinely ends a company name.  `_SUFFIX_RE` is broader (it
# also covers Group/Associates/Partners for the comma-crossing rule), but those
# words appear mid-name -- stopping on them truncated "Construction Group
# International" to "Construction Group".
_TERMINAL_SUFFIX_RE = re.compile(
    r"^(inc|llc|l\.l\.c|ltd|corp|corporation|company|co|lp|llp|pllc|"
    r"p\.?s|p\.?c|plc)\.?,?[;:]?$", re.I)
_SUFFIX_RE = re.compile(r"^(inc|llc|ltd|co|corp|company|corporation|lp|llp|pllc|"
                        r"p\.?s|plc|pc|group|associates|assoc|partners)\.?,?[;:]?$", re.I)
# Read right to left, a preposition means the name *started* after it:
# "award contract D-5041 to Regency Northwest Construction, Inc., as general
# contractor" must yield the contractor, not "D-5041 to Regency ...".
_BACK_INNER = {"of", "and", "the", "de", "la", "le", "du", "des",
               "d/b/a", "dba", "&", "|"}
# Industry words that continue a single name across "and" rather than starting
# a second vendor ("A-1 Landscaping and Construction, Inc.").
_JOINT_GENERIC = {
    "construction", "landscaping", "associates", "aerospace", "regional",
    "sons", "company", "companies", "services", "service", "workers",
    "engineering", "contracting", "contractors", "supply", "medical",
    "girls", "boys", "development", "consulting", "architects", "architecture",
    "partners", "electric", "mechanical", "plumbing", "roofing", "sheet",
    "technologies", "systems", "solutions", "industries", "products",
}


def _walk_vendor(text: str, pos: int, max_tokens: int = 10) -> str | None:
    """Walk forward from ``pos`` while the tokens still look like a name.

    Accepts a token when it starts with an uppercase letter or a digit, or is
    a connector in ``_INNER_WORDS`` followed by another accepted token.  Stops
    before a ``_STOP_WORDS`` token, before anything containing ``$``, and
    *after* a token that ends in a sentence period (an abbreviation such as
    "Inc." or a single initial does not count as a sentence end).  Returns the
    exact substring of ``text``, so ``vendor_raw`` is always verbatim.
    """
    start = pos
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text):
        return None
    for _ in range(2):
        for art in _LEAD_ARTICLES + _LEAD_QUALIFIERS:
            if text[start:start + len(art)].lower() == art:
                start += len(art)
                while start < len(text) and text[start].isspace():
                    start += 1
                break
        else:
            break
    end = start
    n = 0
    i = start
    _last_head = ""                  # last accepted token, lowercased
    _prev_comma = False              # previous accepted token ended in ","
    _saw_suffix = False              # an Inc./LLC/Company token was accepted
    n_conn = 0                       # connectors, budgeted apart from names
    end_before_for = None            # offset of `end` when "for" was crossed
    n_after_for = 0
    pending: list[int] = []          # connector tokens not yet confirmed
    while i < len(text) and n < max_tokens:
        while i < len(text) and text[i] in " \t":
            i += 1
        j = i
        while j < len(text) and not text[j].isspace():
            j += 1
        if j == i:
            break
        tok = text[i:j]
        low = tok.lower().strip(",;:")
        if "$" in tok or "\n" in tok:
            break
        # A *capitalised* connector is part of the printed name ("Teach For
        # America", "Boys And Girls Clubs"); a lowercase "for" is a scope
        # clause unless it follows a head noun ("Center for Children").
        cap_connector = low in ("for", "of", "and", "the", "by") and tok[:1].isupper()
        if (low in _INNER_WORDS or cap_connector
                or (low == "for" and _last_head in _FOR_HEADS)) and n > 0:
            nxt = text[j:].lstrip(" \t").split(" ", 1)[0].lower().strip(",.;:")
            if low == "to" and nxt in _TO_VERBS:
                break
            if low == "and" and nxt in _AND_STOP:
                break
            # Once the legal suffix has been printed the name is finished, so
            # any connector after it opens a scope clause -- "Western Ventures
            # Construction, Inc. to Meany Middle School Phase".  "and" is the
            # one exception: it may introduce a *co-vendor*, split out later.
            if _saw_suffix and low not in ("and", "&"):
                break
            if low in ("and", "&"):
                _saw_suffix = False        # the next name gets its own suffix
            if low == "for":
                end_before_for, n_after_for = end, 0
            pending.append(j)
            i = j
            n_conn += 1
            if n_conn > 6:
                break
            continue
        # "Dairy Fresh Farms, Inc." keeps going past the comma; "Brookwood
        # Farms Inc., ES Foods" is a *list*, so a comma is only crossed when a
        # corporate suffix follows it.
        if _prev_comma and not _SUFFIX_RE.match(low) and low not in _INNER_WORDS:
            break
        if low.rstrip(".") in _STOP_WORDS and not _SUFFIX_RE.match(low):
            break
        if not (tok[0].isupper()
                or (tok[0].isdigit() and re.search(r"[A-Za-z]", tok))
                # camelCase brand names: enVision, iReady, eSchoolPlus
                or _CAMEL_BRAND_RE.match(tok)):
            break
        # A legal suffix ends the name: "Regency NW Construction Inc. Mike
        # Skutack spoke about..." must not swallow the next sentence.
        if _saw_suffix and not _TERMINAL_SUFFIX_RE.match(low):
            break
        pending = []
        end = j
        n += 1
        _last_head = low
        _prev_comma = tok.endswith(",")
        if _TERMINAL_SUFFIX_RE.match(low):
            _saw_suffix = True
        if end_before_for is not None:
            n_after_for += 1
            # "Center for Educational Leadership" and "Alliance for Education"
            # are names; "Sylvan Learning Center for Supplemental Education
            # Services" is a name plus a scope clause.  Two tokens is the line.
            if n_after_for > 2:
                end = end_before_for
                break
        # A period that is not an abbreviation ends the name.
        if tok.endswith(".") and low not in _ABBREVS and len(low.rstrip(".")) > 1 \
                and not _SUFFIX_RE.match(low):
            break
        if tok.endswith((";", ":")):
            break
        if tok.endswith(",") and j < len(text):
            # "Vendor, Inc." keeps going; "Vendor, in the amount" does not --
            # handled naturally on the next iteration by the stop-word test.
            pass
        i = j
    if end <= start:
        return None
    raw = text[start:end].rstrip(";: ")
    raw = raw.rstrip(".,;: ") if not _SUFFIX_RE.match(raw.split()[-1].lower()) else raw.rstrip(",; ")
    raw = raw.strip()
    if len(raw) < 2 or raw.lower() in {"the", "no", "and"}:
        return None
    return raw


def _walk_vendor_back(text: str, pos: int, max_tokens: int = 8) -> str | None:
    """Walk *backwards* from ``pos`` to pick up "<Vendor> in the amount of $X".

    Used for the list formula ("... as follows: Mobile Beacon in the amount of
    $273,113 and Verizon in the amount of $294,900"), where no "with"/"to"
    anchor precedes the name.  Same accept/stop vocabulary as ``_walk_vendor``,
    read right to left; stops on any token ending in ``:`` or ``;``.
    """
    end = pos
    while end > 0 and text[end - 1].isspace():
        end -= 1
    if end <= 0:
        return None
    start = end
    n = 0
    i = end
    while i > 0 and n < max_tokens:
        j = i
        while j > 0 and text[j - 1] in " \t":
            j -= 1
        k = j
        while k > 0 and not text[k - 1].isspace():
            k -= 1
        if k == j:
            break
        tok = text[k:j]
        low = tok.lower().strip(",;:")
        if "$" in tok or "\n" in tok or tok.endswith((":", ";")):
            break
        if low in _BACK_INNER and n > 0:
            i = k
            n += 1
            continue
        if low.rstrip(".") in _STOP_WORDS and not _SUFFIX_RE.match(low):
            break
        if not (tok[0].isupper() or (tok[0].isdigit() and re.search(r"[A-Za-z]", tok))):
            break
        start = k
        n += 1
        i = k
    if start >= end:
        return None
    raw = text[start:end].strip(" ,;:")
    if len(raw) < 3:
        return None
    return raw


def _find_vendor_amount_pairs(text: str, bad_spans=()) -> list[dict]:
    """Every "<Vendor> in the amount of $A" pair, in text order.

    This is the shape multi-agency awards are always minuted in:
    "...under RFQ02758: Yellow Wood Academy in the amount of $649,500; Maxim
    Healthcare Services in the amount of $950,000; ...".  Each vendor is walked
    backwards from its own money phrase, so every string stays verbatim.
    """
    pairs = []
    for m in _BEFORE_AMOUNT_RE.finditer(text):
        v = _walk_vendor_back(text, m.start())
        if not v:
            continue
        v = strip_leading_article(trim_award_prefix(_trim_list_item(v)))
        if not v or not _plausible_vendor(v):
            continue
        # A list member is introduced by a separator (":", ";", ",", "and"), not
        # by a preposition: "...delivered by the EEU in the amount of $943,089"
        # is a component of one contract, not a second vendor.
        before = text[:m.start() - len(v)].rstrip()
        if not _LIST_SEPARATOR_RE.search(before):
            continue
        dollar = m.end() - 1
        mm = MONEY_RE.match(text, dollar)
        if not mm:
            continue
        if any(lo <= dollar < hi for lo, hi in bad_spans):
            continue
        val = parse_money(mm.group(1))
        if val is None:
            continue
        val = _scaled(text, mm.end(), val)
        kind = ("not_to_exceed" if re.search(r"not\s+to\s+exceed", m.group(0), re.I)
                else "unspecified")
        if val < AMOUNT_FLOOR or val > AMOUNT_CEILING:
            val, kind = None, None      # "$250.000" -- a typo, not $250
        pairs.append({"vendor_raw": v, "amount": val, "amount_kind": kind,
                      "amount_raw": None if val is None else mm.group(0),
                      "pos": m.start() - len(v)})
    return pairs


_LIST_SEPARATOR_RE = re.compile(r"(?:[:;,]|\band\b|\bfollows\b|\bfollowing\b)$", re.I)
# Leading noise the backward walk can pick up inside a list
# ("..., plus WSST, and Valley Electric in the amount of ...").
_LIST_ITEM_LEAD_RE = re.compile(
    r"^(?:WSST|plus|tax|sales|Washington|State|and|formerly|approximately)\b[\s,]*",
    re.I)


def _trim_list_item(v: str) -> str:
    """Strip list noise and reject a span with unbalanced parentheses."""
    prev = None
    while prev != v:
        prev = v
        v = _LIST_ITEM_LEAD_RE.sub("", v).strip(" ,;:")
    if v.count(")") != v.count("("):
        return ""
    return v


# "for a not-to-exceed total amount of $1,890,000 as follows: ..." -- the
# envelope for the per-vendor list that follows it.
GROUP_TOTAL_RE = re.compile(
    r"(?:for\s+a\s+)?(?P<nte>not[- ]?to[- ]?exceed\s+)?total\s+(?:amount|cost)\s+"
    r"(?:of\s+)?(?P<money>" + MONEY_RE.pattern + r")"
    r"(?P<tail>[^.$]{0,60}?as\s+follows)?", re.I)


_BEFORE_AMOUNT_RE = re.compile(
    r",?\s+in\s+(?:the|an)\s+(?:total\s+)?amount\s+(?:of\s+)?(?:not\s+to\s+exceed\s+)?\$", re.I)


# A "gap" between the contract noun and "with"/"to" that refuses to cross a
# clause boundary: "…Agreement to provide Special Education services to
# students with Individualized Education Programs" must NOT anchor on that
# final "with".
_GAP = r"(?:(?!\s+(?:to|for|between|by|under|from|and)\s)[^.$]){0,60}?"


# Vendor anchors: (name, regex).  The regex must end where the vendor begins.
VENDOR_ANCHORS = [
    ("v_change_order_with", re.compile(
        r"change\s+order(?:\s+no\.?\s*\d+[A-Za-z]?)?" + _GAP + r"\bwith\s+", re.I)),
    ("v_final_acceptance_with", re.compile(
        r"final\s+acceptance[^.$]{0,120}?\bwith\s+", re.I)),
    ("v_final_acceptance_contract", re.compile(
        r"final\s+acceptance\s+of\s+[^.$]{0,60}?"
        r"(?:contract|purchase\s+order|PO)\s*(?:no\.?\s*)?[A-Z]{0,3}\d{3,8}[A-Z]?\s*,\s*", re.I)),
    ("v_accept_work_of", re.compile(
        r"accept\s+the\s+work\s+(?:of|performed\s+by)\s+", re.I)),
    ("v_amendment_with", re.compile(
        r"(?:contract\s+)?amendments?(?:\s+no\.?\s*\d+)?(?:\s+to\s+(?:the\s+)?"
        r"[A-Za-z0-9 ,\u2019\'\-]{0,60}?)?\s+with\s+", re.I)),
    ("v_lease_with", re.compile(
        r"leas(?:e|ing)(?:\s+agreement)?" + _GAP + r"\bwith\s+", re.I)),
    ("v_agreement_with", re.compile(
        r"\b(?:inter[- ]?agency|interlocal|memorand\w+\s+of\s+\w+|MOU|MOA|"
        r"partnership|services?|sole\s+source|professional\s+services|"
        r"data\s+sharing|use)?\s*agreements?\b" + _GAP + r"\bwith\s+", re.I)),
    ("v_contract_with", re.compile(
        r"\bcontracts?\b(?:\s+(?:no\.?\s*)?[A-Z]{1,3}\d{3,6})?" + _GAP
        + r"\bwith\s+", re.I)),
    ("v_submitted_by", re.compile(
        r"(?:bid|proposal)\s+(?:as\s+)?submitted\s+by\s+", re.I)),
    ("v_general_contractor", None),   # handled specially (vendor precedes)
    # Instructional-materials adoptions name the publisher after "published
    # by"; that outranks the product name the adoption anchor would pick up.
    ("v_published_by", re.compile(r"\bpublished\s+by\s+", re.I)),
    # "purchase AmplifyScience as the core instructional materials", "adopt and
    # authorize the superintendent to purchase the Center for the Collaborative
    # Classroom as instructional materials", "the adoption of Illustrative
    # Mathematics ... for instructional materials".  Gated on the formula so a
    # plain "purchase Student and Staff computers" never matches.
    ("v_adoption_purchase", re.compile(
        r"\b(?:purchase|adoptions?\s+of|adopt)\s+"
        r"(?=[A-Z][^.$]{0,140}?\binstructional\s+material)", re.I)),
    ("v_purchase_from", re.compile(
        r"purchas\w+[^.$]{0,80}?\bfrom\s+", re.I)),
    ("v_purchase_through", re.compile(
        r"purchase\s+orders?[^.$]{0,40}?\bthrough\s+", re.I)),
    ("v_contract_to", re.compile(
        r"\bcontracts?\b(?:\s+(?:no\.?\s*)?[A-Z]{1,3}\d{3,6})?"
        r"(?:\s*,\s*(?:bid|rfp|rfq)[^.$]{0,30})?\s*,?\s+to\s+", re.I)),
    ("v_award_to", re.compile(
        r"award(?:s|ed|ing)?\b[^.$]{0,80}?\bto\s+", re.I)),
    ("v_between_district_and", re.compile(
        r"between\s+(?:the\s+)?Seattle\s+(?:Public\s+)?Schools?"
        r"(?:\s+District(?:\s+No\.?\s*1)?)?[^.$]{0,40}?\band\s+", re.I)),
    ("v_funding_from", re.compile(
        r"(?:accept|receive|ratify)\w*\s+[^.$]{0,40}?"
        r"(?:funding|funds|grant|payment|reimbursement)s?\s+(?:from|through)\s+", re.I)),
    ("v_reimburse", re.compile(r"\breimburse\s+", re.I)),
    ("v_accept_proposed", re.compile(r"accept\s+the\s+proposed\s+", re.I)),
    ("v_with_amount", re.compile(
        r"\bwith\s+(?=(?:the\s+)?(?:reseller|vendor|contractor|firm|consultant|"
        r"provider|agency|supplier)?\s*[A-Z0-9])", re.I)),
    # Legacy "…issued to <Vendor>" / "…awarded to <Vendor>".  Deliberately
    # narrow: a bare "to <Capitalised>" matches half the corpus.
    ("v_to_vendor_for", re.compile(
        r"\b(?:issued?|awarded|granted|let|paid)\s+to\s+(?=(?:the\s+)?[A-Z0-9])", re.I)),
]

_GENERAL_CONTRACTOR_RE = re.compile(r",?\s+as\s+(?:the\s+)?general\s+contractor", re.I)
PUBLISHED_BY_RE = re.compile(r",?\s*published\s+by\s+", re.I)
# Anchors whose vendor is a curriculum publisher rather than a contractor;
# recorded as a hint so F1's alias table can class them without re-reading.
PUBLISHER_ANCHORS = ("v_published_by", "v_adoption_purchase")
# "Inquiry By Design Middle School Curriculum" -> "Inquiry By Design";
# "K-5 English Language Arts Instructional Materials" -> nothing usable.
_ADOPTION_TAIL_RE = re.compile(
    r"(?:\s*,)?\s+(?:(?:Elementary|Middle|High|K-?\d+)\s+School\s+)?"
    r"(?:Curriculum|Instructional\s+Materials?|Materials?|Program)\s*$", re.I)


def trim_adoption_tail(v: str) -> str:
    prev = None
    while prev != v:
        prev = v
        v = _ADOPTION_TAIL_RE.sub("", v).strip(" ,")
    return v


def _find_vendors(text: str) -> list[tuple[str, str, int]]:
    """All (pattern_name, vendor_raw, position) hits, in text order per pattern."""
    out = []
    for m in _GENERAL_CONTRACTOR_RE.finditer(text):
        v = _walk_vendor_back(text, m.start())
        if v:
            out.append(("v_general_contractor", v, m.start() - len(v)))
    for name, rx in VENDOR_ANCHORS:
        if rx is None:
            continue
        for m in rx.finditer(text):
            v = _walk_vendor(text, m.end())
            if not v:
                continue
            if name == "v_final_acceptance_contract" and len(v.split()) < 2 \
                    and not _SUFFIX_RE.match(v.split()[-1].lower()):
                continue      # "Final Acceptance of Contract P1234, Renovations"
            if name == "v_adoption_purchase":
                v = trim_adoption_tail(v)
                if not v:
                    continue
            out.append((name, v, m.end()))
    for m in _BEFORE_AMOUNT_RE.finditer(text):
        v = _walk_vendor_back(text, m.start())
        if v:
            out.append(("v_before_amount", v, m.start() - len(v)))
    return out


def find_vendor_candidates(text: str) -> list[tuple[str, str, list, int]]:
    """`_find_vendors` plus the joint split, with every piece plausibility-checked.

    The split has to happen before the check, or "Seattle Public Schools and
    the Community Advisory Committee" survives as a candidate and then hands
    back the district as ``vendor_raw`` (2006-03-08, RFP01627).
    """
    out = []
    for name, span, pos in _find_vendors(text):
        span = strip_leading_article(trim_award_prefix(span))
        primary, co = split_joint_vendors(span)
        primary = strip_leading_article(trim_award_prefix(primary))
        if not _plausible_vendor(primary):
            continue
        # An unsplit compound is only as good as its first name: "Seattle Public
        # Schools and the Community Advisory Committee" is still the district.
        head = strip_leading_article(_JOINT_SPLIT_RE.split(primary)[0].strip(" ,;:"))
        if head != primary and not _plausible_vendor(head):
            continue
        co = [c for c in (strip_leading_article(trim_award_prefix(x)) for x in co)
              if c and _plausible_vendor(c)]
        out.append((name, primary, co, pos))
    return out


_BAD_VENDOR_RE = re.compile(
    r"^(the|a|an|this|that|these|approval|superintendent|district|board|"
    r"seattle\s+(public\s+)?schools?(\s+district)?(\s+no\.?\s*1)?|"
    r"seattle\s+school\s+district(\s+no\.?\s*1)?|"
    r"(school\s+)?board\s+(action\s+report|polic\w+|resolution|directors?)(\s+nos?\.?)?|"
    r"board\s+action\s+reports?|school\s+board|"
    r"washington\s+state\s+sales\s+tax|wsst|wa\s+state\s+sales\s+tax|"
    r"rcw|wac|esser|ospi|bex\s*[ivx]*|bta\s*[ivx]*|rf[pqi]\s*(no\.?)?|"
    r"bids?\s*(nos?\.?)?|alternates?|x{2,}|proposals?|projects?|"
    r"general\s+fund|capital\s+(projects?|fund)|"
    r"(a\s+)?general\s+partnership|(a\s+)?joint\s+venture|"
    r"(the\s+)?state\s+of\s+washington|"
    r"sps|the\s+district|(the\s+)?seattle\s+school\s+district(\s+no\.?\s*1)?|"
    r"(the\s+)?successful\s+(firm|bidder|proposer|contractor|vendor|respondent|"
    r"applicant|candidate)s?|(to\s+be\s+)?determined|tbd|"
    r"(the\s+)?community\s+advisory\s+committee|"
    r"(the\s+)?district[- ]developed\s+curriculum|(the\s+)?district\s+curriculum|"
    r"(?:pre-?k|k|grades?)\s*[-\u2013]\s*\d+\b.*|\d+\s*[-\u2013]\s*\d+\b.*|"
    r".*\binstructional\s+materials?|.*\bcore\s+curriculum|"
    # course codes and course names -- "CHEM B", "Biology A", "Algebra 1"
    r"(?:chem|bio|phys|alg|geom)\s?[ab12]?|"
    r"(?:chemistry|biology|physics|algebra|geometry|calculus|statistics)"
    r"(?:\s+[ab12])?|"
    r"(?:core\s+)?(?:instructional\s+)?(?:materials?|curriculum|curricula)|"
    r"(?:\d+(?:th|st|nd|rd)\s+grade\s+)?"
    r"(?:chemistry|biology|physics|algebra|geometry)(?:\s+[ab12])?|"
    r"contract|agreement|amendment|change\s+order|vendor|item|"
    r"[a-z0-9 ]*(elementary|middle|high)\s+school)$", re.I)


# Single-token vendors are the truncation failure mode F1 found.  Two rules:
# a curated stopword list (every entry below is a real bad value from
# `vendors_report.md`'s not-a-vendor list, or a generic noun of the same
# shape), and a company-shape fast-accept for acronyms and CamelCase.  A
# single token that is neither -- "Arcadis", "Apple", "Genesis", "Sysco" --
# is allowed through; those are real one-word vendors.
_SINGLE_TOKEN_STOPWORDS = {
    # observed truncations of real vendor names
    "teach", "sylvan", "thornburg", "lincoln", "lloyd", "machinists",
    "teamsters", "local", "directors", "association",
    # generic nouns and roles the walk can land on
    "project", "projects", "proposal", "proposals", "bid", "bids",
    "alternates", "alternate", "renovations", "upgrades", "construction",
    "services", "service", "company", "district", "hospital", "university",
    "college", "city", "county", "state", "seattle", "school", "schools",
    "board", "committee", "program", "programs", "plan", "policy", "contract",
    "agreement", "vendor", "vendors", "contractor", "superintendent",
    "math", "white", "black", "students", "staff", "department", "office",
    "fund", "levy", "grant", "phase", "campus", "center", "group",
}


def _believable_single_token(tok: str) -> bool:
    t = tok.strip(" ,.;:")
    if len(t) < 2:
        return False
    if t.lower() in _SINGLE_TOKEN_STOPWORDS:
        return False
    letters = re.sub(r"[^A-Za-z]", "", t)
    if letters.isupper() and len(letters) >= 2:
        return True                              # KCDA, SEA, CDW-G, EPI-USE
    if re.search(r"[A-Za-z][A-Z]", t):
        return True                              # SchoolFusion, BNBuilders
    if re.search(r"[0-9&]", t):
        return True
    if _SUFFIX_RE.match(t.lower()):
        return True
    return True                                  # Arcadis, Apple, Genesis


# Never a counterparty regardless of what follows: the district produced it.
_BAD_VENDOR_PREFIX_RE = re.compile(
    r"^(?:the\s+)?(?:district[- ]developed|district[- ]created|"
    r"in[- ]house|self[- ]developed|core\s+instructional|"
    r"(?:chem|bio|phys|alg|geom)\s?[ab12]?\b|"
    r"(?:chemistry|biology|physics|algebra|geometry)\s+[ab12]\b)", re.I)


def _plausible_vendor(v: str) -> bool:
    if _BAD_VENDOR_RE.match(v.strip(" ,.")):
        return False
    if _BAD_VENDOR_PREFIX_RE.match(v.strip(" ,.")):
        return False
    # project/scope descriptions -- "Roosevelt High School Science
    # Modernization", "Waterline Replacement", "Upgrades Phase II"
    if _is_project_description(v):
        return False
    # "Construction Group", "Services Company" -- no proper noun survived
    if _is_generic_only(v):
        return False
    toks = v.split()
    if len(toks) == 1 and not _believable_single_token(toks[0]):
        return False
    if len(v) < 3 or len(v) > 90:
        return False
    if not re.search(r"[A-Za-z]{2}", v):
        return False
    return True


# ---- amounts --------------------------------------------------------------

AMOUNT_PATTERNS = [
    ("a_revised_total", "revised_total", re.compile(
        r"(?:for\s+)?a?\s*revised\s+(?:total\s+)?(?:contract\s+)?"
        r"(?:amount|total|value)(?:\s+of)?\s*(?:to\s+)?" + MONEY_RE.pattern, re.I)),
    ("a_to_total_amount", "revised_total", re.compile(
        r"\bto\s+an?\s+(?:new\s+)?total\s+(?:contract\s+)?amount\s+of\s*"
        + MONEY_RE.pattern, re.I)),
    ("a_total_contract_amount", "revised_total", re.compile(
        r"for\s+a\s+(?:new\s+)?total\s+contract\s+(?:amount|value)\s+of\s*"
        + MONEY_RE.pattern, re.I)),
    ("a_new_total", "revised_total", re.compile(
        r"(?:for\s+)?a\s+new\s+(?:contract\s+)?total(?:\s+of)?\s*" + MONEY_RE.pattern, re.I)),
    ("a_prior_total", "prior_total", re.compile(
        r"(?:current|original|previous|prior|existing)\s+(?:total\s+)?"
        r"(?:contract\s+)?(?:amount|value|total)(?:\s+of)?\s*(?:is\s+)?"
        + MONEY_RE.pattern, re.I)),
    # A GC/CM award authorises a small pre-construction allowance *and* the
    # Guaranteed Maximum Price for the whole job.  The GMP is the contract's
    # value; taking the first NTE understated 14 rows by 76x-587x (E3 BAR pass).
    ("a_gmp", "not_to_exceed", re.compile(
        r"(?:guaranteed\s+maximum\s+price|\bGMP\b)(?:\s*\([^)]{0,20}\))?"
        r"[^.$]{0,140}?(?:not[- ]?to[- ]?exceed|amount\s+of|authorized[^.$]{0,40}?is|"
        r"\bis\b|\bof\b)\s*" + MONEY_RE.pattern, re.I)),
    # "$803,994.66 annually, or $2,411,983.90 over the three-year term";
    # "each for a total amount not to exceed $1.2 million over three years".
    ("a_term_total", "unspecified", re.compile(
        r"(?:annually|per\s+year|each\s+year)\s*,?\s*or\s*" + MONEY_RE.pattern
        + r"|total\s+amount\s+not\s+to\s+exceed\s*" + MONEY_RE.pattern
        + r"\s*(?:million\s*)?over\s+\w+\s+years?", re.I)),
    ("a_monthly", "monthly", re.compile(
        MONEY_RE.pattern + r"\s*(?:a|per|each)\s+month\b", re.I)),
    ("a_nte_total", "not_to_exceed", re.compile(
        r"(?:total\s+)?Not[- ]?To[- ]?Exceed\s*(?:\(NTE\))?\s*"
        r"(?:total\s+)?amount\s+of\s*" + MONEY_RE.pattern, re.I)),
    ("a_not_to_exceed", "not_to_exceed", re.compile(
        r"not[- ]?to[- ]?exceed\s*(?:total\s*)?(?:amount\s*(?:of)?\s*)?"
        r"(?:total\s*(?:amount\s*)?(?:of)?\s*)?" + MONEY_RE.pattern, re.I)),
    ("a_up_to", "not_to_exceed", re.compile(
        r"up\s+to\s+(?:an?\s+|the\s+)?(?:total\s+|maximum\s+)?(?:amount\s+of\s+)?"
        + MONEY_RE.pattern, re.I)),
    ("a_final_amount", "final", re.compile(
        r"final\s+(?:contract\s+)?(?:amount|cost|value)\s+of\s*" + MONEY_RE.pattern, re.I)),
    ("a_increase_by", "increase", re.compile(
        r"increas\w+\s+[^.$]{0,40}?\bby\s*" + MONEY_RE.pattern, re.I)),
    ("a_increase", "increase", re.compile(
        r"(?:an?\s+)?(?:budget\s+)?increase(?:\s+of|\s+in\s+the\s+amount\s+of)\s*"
        + MONEY_RE.pattern, re.I)),
    ("a_in_the_total_amount_of", "unspecified", re.compile(
        r"in\s+the\s+total\s+amount\s+of\s*" + MONEY_RE.pattern, re.I)),
    ("a_in_the_amount_of", "unspecified", re.compile(
        r"in\s+(?:the|an)\s+amount\s+of\s*" + MONEY_RE.pattern, re.I)),
    ("a_annual", "annual", re.compile(
        MONEY_RE.pattern + r"\s*(?:annually|(?:per|a|each)\s+(?:year|annum|school\s+year))",
        re.I)),
    ("a_for_amount", "unspecified", re.compile(
        r"\bfor\s+(?:a\s+(?:total\s+)?(?:amount\s+of\s+)?)?" + MONEY_RE.pattern, re.I)),
]

# amount_kind preference when several fire for the same primary amount
_KIND_RANK = {"not_to_exceed": 0, "final": 1, "increase": 2, "annual": 3,
              "monthly": 3, "unspecified": 4, "revised_total": 5,
              "prior_total": 6}


def parse_money(s: str) -> float | None:
    try:
        return float(s.replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


_MULT_RE = re.compile(r"\s*(million|billion|thousand)\b", re.I)
_MULTS = {"thousand": 1e3, "million": 1e6, "billion": 1e9}


def _scaled(text: str, end: int, val: float) -> float:
    """"$7.5 million" -> 7500000.0.

    Only a *small* mantissa is scaled: the corpus contains source typos like
    "the transfer of $4,352,000 million", where the writer meant $4.352M.
    Scaling those produced a $4.3 trillion row, so anything >= 1000 is taken
    at face value and the stray unit word is ignored.
    """
    m = _MULT_RE.match(text, end)
    if m and val < 1000:
        return val * _MULTS[m.group(1).lower()]
    return val


# "…revising the contract P5160 with Lydig Construction, Inc., from
# $206,556,237.08 to $221,063,335.16 increasing the contract budget by
# $14,507,098.08" -- the "from" figure is the *prior* total and must never
# become the row's amount.
FROM_TO_RE = re.compile(
    r"\bfrom\s+(?P<a>" + MONEY_RE.pattern + r")\s+to\s+(?P<b>" + MONEY_RE.pattern + r")",
    re.I)
# "revising the contract P5160 with Lydig ... from $A to $B" -> the contract's
# own totals.  "revising the overall project budget from $A to $B" -> a project
# budget that happens to sit in a contract item; the endpoints are still barred
# from becoming the amount, but they are not this contract's totals.
# RCW citations ("RCW 39.10.370") sit between the GMP phrase and its figure,
# so the gap must allow periods -- only "$" ends it.
GMP_RE = re.compile(
    r"(?:guaranteed\s+maximum\s+price|\bGMP\b)(?:\s*\([^)]{0,20}\))?"
    r"[^$]{0,160}?(?:not[- ]?to[- ]?exceed|amount\s+of|authorized[^$]{0,40}?is|"
    r"\bis\b|\bof\b)\s*" + MONEY_RE.pattern, re.I)
TERM_TOTAL_RE = re.compile(
    r"(?:annually|per\s+year|each\s+year)\s*,?\s*or\s*" + MONEY_RE.pattern
    + r"|total\s+(?:annual\s+)?(?:amount|cost)\s+not\s+to\s+exceed\s*"
    + MONEY_RE.pattern + r"\s*(?:million\s*)?over\s+[\w-]+\s+years?", re.I)


FROM_TO_CONTRACT_RE = re.compile(
    r"(?:contract|agreement|purchase\s+order|change\s+order|amendment)"
    r"[^$]{0,80}$", re.I)


def _malformed_spans(text: str) -> tuple[list[tuple[int, int]], list[str]]:
    spans, notes = [], []
    for m in MONEY_RUN_RE.finditer(text):
        if not well_formed_money(m.group(0)):
            spans.append((m.start(), m.end()))
            notes.append(m.group(0).strip())
    return spans, notes


def _find_amounts(text: str, skip: tuple = ()) -> list[dict]:
    """All money hits with the best-ranked named pattern for each.

    Positions inside a malformed printed figure, or listed in ``skip``, are
    dropped rather than parsed.
    """
    bad, _notes = _malformed_spans(text)
    skip = tuple(skip) + tuple(bad)

    def blocked(pos):
        return any(lo <= pos < hi for lo, hi in skip)

    hits: dict[int, dict] = {}
    for name, kind, rx in AMOUNT_PATTERNS:
        for m in rx.finditer(text):
            mm = MONEY_RE.search(m.group(0))
            if not mm:
                continue
            val = parse_money(mm.group(1))
            if val is None:
                continue
            val = _scaled(text, m.start() + mm.end(), val)
            pos = m.start() + mm.start()
            if blocked(pos):
                continue
            cur = hits.get(pos)
            if cur is None or _KIND_RANK[kind] < _KIND_RANK[cur["kind"]]:
                hits[pos] = {"pattern": name, "kind": kind, "value": val, "pos": pos,
                             "raw": mm.group(0)}
    for m in MONEY_RE.finditer(text):
        if m.start() not in hits and not blocked(m.start()):
            val = parse_money(m.group(1))
            if val is not None:
                hits[m.start()] = {"pattern": "a_bare", "kind": "unspecified",
                                   "value": _scaled(text, m.end(), val),
                                   "pos": m.start(), "raw": m.group(0)}
    return sorted(hits.values(), key=lambda h: h["pos"])


# ---- identifiers, terms, action type --------------------------------------

CONTRACT_ID_RE = re.compile(
    r"\b(?:contract|agreement)\s*(?:no\.?|number|#)?\s*([A-Z]{1,3}-?\d{3,6}[A-Z]?)\b", re.I)
CONTRACT_ID_BARE_RE = re.compile(r"\b([KP]\d{4,5})\b")
# "BTA II D1022, Contract for Ingraham High School Renovation" -- the id is
# printed *before* the word Contract in the 2005-2012 agenda titles.
CONTRACT_ID_PRE_RE = re.compile(r"\b([A-Z]{1,3}-?\d{3,6})\s*,?\s*contract\b", re.I)
PO_RE = re.compile(
    r"\b(?:P\.?O\.?|purchase\s+order)\s*(?:no\.?|number|#)?\s*(\d{4,12})\b|"
    r"\b(PO\d{6,12})\b", re.I)
BID_RE = re.compile(r"\bbid\s*(?:no\.?|number|#)?\s*(B\d{4,6})\b", re.I)
RFP_RE = re.compile(r"\b(RF[PQI]\s?(?:no\.?\s*)?\d{3,6})\b", re.I)

_MONTHS = ("January|February|March|April|May|June|July|August|September|"
           "October|November|December")
TERM_RE = re.compile(
    rf"\b(?:from|effective|beginning|commencing|for\s+the\s+(?:term|period))\s+"
    rf"(?:of\s+)?(?P<start>(?:{_MONTHS})\s+\d{{1,2}},\s*\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{2,4}})"
    rf"\s*(?:through|thru|to|-|until|and\s+ending)\s*"
    rf"(?P<end>(?:{_MONTHS})\s+\d{{1,2}},\s*\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{2,4}})", re.I)
SCHOOL_YEAR_RE = re.compile(r"\b(20\d{2})\s*[-/]\s*(\d{2}|20\d{2})\s+school\s+year\b", re.I)

_ACTION_KEYWORDS = [
    ("final_acceptance", re.compile(
        r"final\s+acceptance|accept\s+the\s+work[^.]{0,60}?\bas\s+(?:final|complete)|"
        r"\bas\s+complete\b", re.I)),
    ("change_order", re.compile(r"change\s+order", re.I)),
    ("amendment", re.compile(
        r"\bamendments?\b|\baddend(?:um|a)\b|"
        r"\bamend(?:ing|ed)?\s+the\s+(?:contract|agreement|MOU|MOA|lease)\b|"
        r"\bmodif(?:y|ication)s?\s+(?:of|to)\s+(?:the\s+)?contract\b|"
        r"\bcontract\s+modifications?\b", re.I)),
    # Deliberately narrow: "with three renewals possible" / "with the option
    # to renew" describe a *new* award, not a renewal action.
    ("renewal", re.compile(
        r"\brenewals?\s+of\b|^\s*renewal\b|\bannual\s+renewal\b|"
        r"\b\d+\s*-?\s*year\s+renewal\b|\brenew\s+the\s+(?:contract|agreement|lease)s?\b|"
        r"\bcontract\s+(?:extension|renewal)\b|"
        r"\bextend(?:ing)?\s+(?:the\s+)?(?:contract|agreement|lease)s?\b|"
        r"\bextension\s+of\s+(?:the\s+)?(?:contract|agreement|lease)s?\b", re.I)),
    ("new", re.compile(
        r"\baward\b|\benter\s+into\b|"
        # "execute three-year SAP Staff Augmentation contracts with EPI-USE,
        # Genesis, and Vigna" -- modifiers sit between the verb and the noun.
        r"\bexecute\s+(?:[\w/&.-]+\s+){0,5}?(?:contracts?|agreements?)\b|"
        r"\bauthoriz\w+\s+(?:a|an|the)\s+(?:[a-z/&]+\s+){0,2}(?:contract|agreement)s?\b|"
        r"\bnew\s+contract\b|\bcontracts?\s+with\b|\bagreements?\s+(?:with|between)\b|"
        r"\bapprove\s+the\s+(?:contract|agreement|MOU|MOA|lease)\b|"
        r"\binterlocal\b|\bmemorand(?:um|a)\s+of\s+(?:understanding|agreement)\b|"
        r"\bMOU\b|\bMOA\b|\bsole\s+source\b|\blease\s+agreement\b|"
        r"\baccept(?:ance)?\s+of\s+(?:the\s+)?(?:grant|funding|funds)\b|"
        r"\baccept\s+the\s+bid\b|\bauthorize\s+the\s+bid\b|"
        r"\baccept\s+(?:the\s+|a\s+|an\s+)?(?:proposed\s+)?[^.]{0,60}?\bagreements?\b|"
        r"\bapprove\s+(?:the\s+|an?\s+)?[A-Z][\w /&'-]{0,60}?\b(?:contracts?|agreements?)\b",
        re.I)),
    # After "new" on purpose: "execute a contract with King County to purchase
    # ORCA cards" is a contract award; "execute purchase orders through Apple"
    # is a purchase.
    ("purchase", re.compile(
        r"\bpurchase\s+(?:of|from|orders?)\b|\bpurchas(?:e|ing)\b[^.]{0,40}?\bfrom\b|"
        r"\bacquisition\s+of\b|\bto\s+purchase\b|\bpurchase\s+[A-Z]", re.I)),
]

IMMEDIATE_RE = re.compile(
    r"immediate\s+action\s+is\s+in\s+the\s+best\s+interest|"
    r"\(introduction\s*(?:&|and|/)\s*action\)|introduction\s+and\s+action", re.I)

DEPT_RE = re.compile(
    r"\((?:Ops|Operations|A&F|Audit\s*&\s*Finance|Exec|Executive|C&I|"
    r"Curriculum\s*&\s*Instruction|Facilities|Teaching\s*(?:&|and)\s*Learning)\b",
    re.I)
PROGRAM_RE = re.compile(r"\b(BEX\s*[IVX]+|BTA\s*[IVX]+|Capital\s+Levy|Title\s+I|"
                        r"Levy|Bond)\b", re.I)


# An "amendment" is only a *contract* amendment when the item also names a
# contract-ish object.  Without this, legacy agendas full of "Amendments to
# the Student Assignment Plan" were typed `amendment` (F2 link report).
CONTRACT_OBJECT_RE = re.compile(
    r"\bcontracts?\b|\bagreements?\b|\bpurchase\s+orders?\b|\bP\.?O\.?\s*\d|"
    r"\bMOU\b|\bMOA\b|\blease\b|\bvendors?\b|\bchange\s+order\b|"
    r"\bnot[- ]to[- ]exceed\b|in\s+the\s+amount\s+of|\bbid\b|\bRF[PQI]\b|"
    r"\binterlocal\b|\bsole\s+source\b|\bcontractor\b", re.I)


# "Award Contract P5152 for GC/CM to Cornerstone General Contractors Inc." is a
# *new* award even though the motion goes on to authorise a GMP contract
# amendment and a pre-construction NTE.  GC/CM items always read that way, so
# an explicit award formula outranks the amendment/renewal keywords.  It does
# not outrank a final acceptance or a change order, which are later events on
# an already-awarded contract.
AWARD_FORMULA_RE = re.compile(
    r"\baward\s+(?:of\s+)?(?:a|the|an)?\s*(?:[\w/&.-]+\s+){0,4}?"
    r"(?:contracts?|agreements?|bids?)\b|"
    r"\baward\s+(?:contracts?|construction\s+contracts?|gc/cm)\b|"
    r"\baward(?:ed|ing)?\s+(?:the\s+)?(?:bid|contract)s?\s+to\b", re.I)


def classify_action(text: str, title: str) -> tuple[str, list[str]]:
    hay = f"{title} {text}"
    has_contract_object = bool(CONTRACT_OBJECT_RE.search(hay))
    fired = []
    for name, rx in _ACTION_KEYWORDS:
        if rx.search(hay):
            if name in ("amendment", "change_order", "renewal") \
                    and not has_contract_object:
                continue
            fired.append(name)
    if not fired:
        return "other", []
    if fired[0] in ("amendment", "renewal") and AWARD_FORMULA_RE.search(hay):
        return "new", ["x_action_type:new", "x_award_formula"]
    return fired[0], ["x_action_type:" + fired[0]]


# ---- the row --------------------------------------------------------------

def _blank_row(item: dict, era: str, doc: dict) -> dict:
    return {
        "meeting_id": item["meeting_id"],
        "meeting_date": item["meeting_date"],
        "item_no": item["item_no"],
        "item_code": item.get("item_code"),
        "char_start": item["char_start"],
        "era": era,
        "section": item.get("section"),
        "title": item.get("title"),
        "vendor_raw": None,
        "vendor_name": None,
        # Structured co-vendors for multi-vendor items; `co_vendors_raw` is the
        # verbatim-string view of the same list, kept for older consumers.
        # link.py explodes these into one action row per vendor.
        "co_vendors": [],
        "co_vendors_raw": [],
        "group_total": None,
        "group_total_kind": None,
        "action_type": None,
        "amount": None,
        "amount_kind": None,
        "prior_total": None,
        "revised_total": None,
        "contract_id": None,
        "po_number": None,
        "bid_number": None,
        "rfp_number": None,
        "term_start": None,
        "term_end": None,
        "department": None,
        "program_or_project": None,
        "board_action": item.get("result"),
        "vote": item.get("vote"),
        "immediate_action": False,
        "citation": {
            "doc_id": item["source_doc_id"],
            "source_kind": item.get("source_kind"),
            "source_url": doc.get("source_url"),
            "page_start": item["page_start"],
            "page_end": item["page_end"],
        },
        "extractor": "regex",
        "patterns_fired": [],
        "extractor_notes": [],
        # The text the extractor actually ran on, so F2/linking never has to
        # go back to out_sps_web/items/ to see what the row was built from.
        "item_text": "",
        "missing_required": [],
        # null on a complete row; set on residual rows (see residual_category)
        "residual_category": None,
    }


_CLEAN_TRAIL_RE = re.compile(r"[\s,;:.]+$")
_CLEAN_LEAD_RE = re.compile(r"^[\s,;:(]+")
# Stripped from `vendor_name` (never from `vendor_raw`, which stays verbatim).
_LEGAL_SUFFIX_TAIL_RE = re.compile(
    r"[\s,]+(?:inc|incorporated|llc|l\.l\.c|ltd|limited|co|corp|corporation|"
    r"company|lp|l\.p|llp|pllc|p\.?s|p\.?c|plc)\.?$", re.I)


def clean_vendor(raw: str) -> str:
    """A display name: `vendor_raw` minus the legal suffix and punctuation.

    ``vendor_raw`` is the verbatim substring and is what F1 canonicalises;
    ``vendor_name`` is the human-readable short form -- "Wayne's Roofing,
    Inc." -> "Wayne's Roofing", "Bayley Construction, LP" -> "Bayley
    Construction".  Never returns the empty string: a name that is *only* a
    suffix keeps its raw form.
    """
    v = re.sub(r"\s+", " ", _CLEAN_LEAD_RE.sub("", _CLEAN_TRAIL_RE.sub("", raw)))
    for _ in range(2):                    # "Foo, Inc., LLC" -- rare but real
        stripped = _LEGAL_SUFFIX_TAIL_RE.sub("", v).strip(" ,.;:")
        if not stripped:
            break
        v = stripped
    return v or _CLEAN_TRAIL_RE.sub("", raw).strip()


# Split points for a joint award: " and ", " & ", and a *spaced* slash
# ("Ednetics / MicroK12").  An unspaced slash is part of one name
# ("Garland/DBS, Inc."), and "CBRE | Heery" is one vendor too.
_JOINT_SPLIT_RE = re.compile(r"\s+(?:and|&)\s+|\s+/\s+", re.I)

# Tokens that cannot carry a vendor identity on their own.  A side of a split
# whose every non-suffix token is generic is not a second vendor -- it is the
# tail of one name ("Parks and Recreation Department" -> "Recreation
# Department").
_GENERIC_HALF_TOKENS = {
    "recreation", "services", "service", "department", "departments",
    "division", "divisions", "talk", "culture", "learning", "human", "trades",
    "resources", "affairs", "sciences", "arts", "health", "education",
    "planning", "operations", "maintenance", "technology", "transportation",
    "early", "girls", "boys", "writing", "reading", "development", "training",
    "technical", "research", "office", "bureau", "administration", "programs",
    "program", "center", "council", "committee", "district", "school",
    "schools", "college", "university", "institute", "authority",
}
# Compounds whose "and"/"&" is internal to a single organisation's name.
_KNOWN_COMPOUND_RE = re.compile(
    r"\b(?:parks?\s+(?:and|&)\s+recreation|health\s+(?:and|&)\s+human\s+services|"
    r"building\s+(?:and|&)\s+construction\s+trades|listen\s+(?:and|&)\s+talk|"
    r"arts?\s+(?:and|&)\s+culture|education\s+(?:and|&)\s+early\s+learning|"
    r"boys\s+(?:and|&)\s+girls|reading\s+(?:and|&)\s+writing|"
    r"research\s+(?:and|&)\s+development|training\s+(?:and|&)\s+development|"
    r"career\s+(?:and|&)\s+technical|arts?\s+(?:and|&)\s+sciences?|"
    r"aerospace\s+workers|science\s+(?:and|&)\s+technology|"
    r"community\s+(?:and|&)\s+family|food\s+(?:and|&)\s+nutrition)\b", re.I)

_LEADING_ARTICLE_RE = re.compile(r"^(?:the|an?)\s+", re.I)

# Business-form words that describe what a company *is*, never which one it is.
# A span made only of these ("Construction Group") lost its proper noun.
# Deliberately excludes place/adjective words like "International", "Northwest"
# or "Pacific", which do identify a company ("Construction Group International").
_GENERIC_BUSINESS_TOKENS = {
    "construction", "group", "groups", "services", "service", "company",
    "companies", "associates", "assoc", "contractors", "contractor",
    "architects", "architecture", "engineering", "engineers", "consulting",
    "consultants", "solutions", "partners", "partnership", "systems",
    "industries", "enterprises", "holdings", "development", "developments",
    "builders", "building", "supply", "management", "technologies",
    "technology", "corporation", "incorporated", "inc", "llc", "ltd", "corp",
    "co", "lp", "llp", "pllc", "plc", "pc", "and", "of", "the", "&",
}


def _is_generic_only(v: str) -> bool:
    toks = [re.sub(r"[^A-Za-z]", "", t).lower() for t in (v or "").split()]
    toks = [t for t in toks if t]
    return bool(toks) and all(t in _GENERIC_BUSINESS_TOKENS for t in toks)

# A capital-works description is never a counterparty.  Guarded by the corporate
# suffix so genuine names survive ("Reading & Writing Project Network, LLC").
_PROJECT_NOUN_RE = re.compile(
    r"\b(?:modernization|replacements?|renovations?|improvements?|upgrades?|"
    r"remediations?|remedia-?tion|restorations?|reroofing|re-?roofing|seismic|"
    r"projects?|additions?|phase\s+[IVX\d]+|expansions?|demolition)\b", re.I)
_HAS_SUFFIX_RE = re.compile(
    r"\b(?:inc|llc|ltd|co|corp|corporation|company|lp|llp|pllc|p\.?s|plc|pc)\b\.?,?\s*$",
    re.I)
# "…award a contract with Alternates A-2 and B-1 to Absher Construction Company"
_AWARD_PREFIX_RE = re.compile(
    r"^(?:alternates?|bids?|contracts?|change\s+order|amendments?|nos?\.?|"
    r"[A-Z]{0,3}-?\d+[A-Z]?|and|,|&)[\s\w.,\-/&]{0,50}?\bto\s+(?=[A-Z])", re.I)


def trim_award_prefix(v: str) -> str:
    """Drop an award/alternate designation that precedes the real name."""
    m = _AWARD_PREFIX_RE.match(v or "")
    return v[m.end():].strip(" ,;:") if m else v


def _is_project_description(v: str) -> bool:
    return bool(_PROJECT_NOUN_RE.search(v or "")) and not _HAS_SUFFIX_RE.search(v or "")


def strip_leading_article(v: str) -> str:
    """`vendor_raw` stays verbatim -- it just starts after the article."""
    return _LEADING_ARTICLE_RE.sub("", v or "").strip(" ,;:")


def _is_standalone_vendor(part: str) -> bool:
    """Can this side of an "and" stand alone as a vendor name?"""
    part = strip_leading_article(part).strip(" ,;:")
    if not part or not _plausible_vendor(part):
        return False
    toks = [t for t in part.split() if not _SUFFIX_RE.match(t.lower())]
    if not toks:
        return False
    if len(toks) == 1 and not _believable_single_token(toks[0]):
        return False
    # every meaningful token generic -> a name fragment, not a vendor
    if all(re.sub(r"[^A-Za-z]", "", t).lower() in _GENERIC_HALF_TOKENS
           for t in toks):
        return False
    return True


def split_joint_vendors(raw: str) -> tuple[str, list[str]]:
    """Split "A, Inc. and B, Inc." into a primary plus co-vendors.

    A split point is used only when the junction is not part of a known
    compound ("Parks & Recreation", "Health and Human Services", "Listen and
    Talk") **and** both sides stand alone as vendors
    (``_is_standalone_vendor``).  So "The YMCA of Seattle and the City of
    Seattle Parks & Recreation Department" splits once, at the "and", while
    "A-1 Landscaping and Construction, Inc." and "Children's Hospital and
    Regional Medical Center" stay whole.  Every piece is a verbatim substring
    of ``raw`` (leading articles aside).
    """
    raw = strip_leading_article(raw)
    cuts = []
    for m in _JOINT_SPLIT_RE.finditer(raw):
        window = raw[max(0, m.start() - 30):m.end() + 30]
        if _KNOWN_COMPOUND_RE.search(window):
            continue
        cuts.append((m.start(), m.end()))
    if not cuts:
        return raw, []
    parts, prev = [], 0
    for a, b in cuts:
        parts.append(raw[prev:a])
        prev = b
    parts.append(raw[prev:])
    cleaned = [strip_leading_article(p).strip(" ,;:") for p in parts]
    for part in cleaned:
        first = re.sub(r"[^A-Za-z0-9&\'\u2019-]", "", part.split(" ")[0]).lower()
        if first in _JOINT_GENERIC or not _is_standalone_vendor(part):
            return raw, []
    return cleaned[0], cleaned[1:]


def extract(item: dict, era: str, doc: dict) -> dict:
    """Fill the Section 2 row schema from the item's own text.  Never guesses."""
    row = _blank_row(item, era, doc)
    text = (item.get("motion_text") or "").strip() or (item.get("body") or "").strip()
    row["item_text"] = text
    title = item.get("title") or ""
    hay = f"{title}. {text}"
    fired: list[str] = []
    notes: list[str] = []

    # -- vendor
    vendors = find_vendor_candidates(hay)
    seen: dict[str, tuple[str, int]] = {}
    for name, v, _co, pos in vendors:
        key = v.lower().strip(" .,")
        if key not in seen or pos < seen[key][1]:
            seen[key] = (name, pos)
    if vendors:
        # Prefer the earliest hit of the most specific anchor family.
        order = {n: i for i, (n, _) in enumerate(VENDOR_ANCHORS)}
        # the backward "<Vendor> in the amount of $X" walk is more specific
        # than the bare "with <X>" / "to <X>" fallbacks but less specific than
        # every named contract/amendment/award anchor above them.
        order["v_before_amount"] = order["v_with_amount"] - 0.5
        best = min(vendors, key=lambda t: (order.get(t[0], 99), t[3]))
        # "Contract with Durham School Services" (title) and "with Durham
        # School Services, Inc." (motion) name the same vendor; keep the
        # fuller printing.
        for _n, _v, _co, _p in vendors:
            if (_v != best[1] and _v.lower().startswith(best[1].lower())
                    and len(_v) <= len(best[1]) + 25
                    and trim_adoption_tail(_v) == _v):
                best = (best[0], _v, _co, best[3])
        row["vendor_raw"] = best[1]
        row["vendor_name"] = clean_vendor(best[1])
        row["co_vendors"] = [{"vendor_raw": v, "amount": None,
                              "amount_kind": None, "amount_raw": None}
                             for v in best[2]]
        fired.append(best[0])
        if best[2]:
            fired.append("v_joint_split")
        if best[0] in PUBLISHER_ANCHORS:
            notes.append("vendor_class:publisher")
        if best[0] == "v_adoption_purchase":
            # "purchase Carbon TIME ... and to purchase PEER ..." names several
            # purchasable products in one motion; keep them all, verbatim.
            extra = [v for n, v, _c, _p in sorted(vendors, key=lambda t: t[3])
                     if n == "v_adoption_purchase" and v != best[1]
                     and v not in row["co_vendors_raw"]
                     and _plausible_vendor(v)]
            if extra:
                row["co_vendors"] = list(row["co_vendors"]) + [
                    {"vendor_raw": v, "amount": None, "amount_kind": None,
                     "amount_raw": None} for v in extra]
                fired.append("v_adoption_multi_product")
        # "Illustrative Mathematics, published by Imagine Learning LLC" -- the
        # publisher is the counterparty, the product is the programme.
        pb = PUBLISHED_BY_RE.search(hay)
        if pb:
            product = _walk_vendor_back(hay, pb.start())
            if product and _plausible_vendor(product) and product != best[1]:
                row["program_or_project"] = product
                fired.append("x_product_publisher")
        for key, (nm, pos) in sorted(seen.items(), key=lambda kv: kv[1][1]):
            if key != best[1].lower().strip(" .,"):
                notes.append(f"extra_vendor:{nm}:{key}")

    # -- amounts
    bad_spans, bad_notes = _malformed_spans(hay)
    for b in bad_notes:
        notes.append(f"malformed_amount:{b}")
    # "from $A to $B": A and B are the prior and revised totals, never the
    # row's amount, so their positions are withheld from the primary pool.
    ft = FROM_TO_RE.search(hay)
    ft_prior = ft_revised = None
    ft_skip: list = []
    if ft:
        a_val, b_val = parse_money(ft.group("a")), parse_money(ft.group("b"))
        if a_val is not None and b_val is not None and not any(
                lo <= ft.start("a") < hi for lo, hi in bad_spans):
            ft_skip = [(ft.start("a"), ft.end("a")), (ft.start("b"), ft.end("b"))]
            fired.append("a_from_to")
            others = [m for m in MONEY_RE.finditer(hay)
                      if not any(lo <= m.start() < hi for lo, hi in ft_skip)
                      and not any(lo <= m.start() < hi for lo, hi in bad_spans)]
            if FROM_TO_CONTRACT_RE.search(hay[:ft.start()]) or not others:
                ft_prior, ft_revised = a_val, b_val
            else:
                notes.append(f"from_to_not_contract:{ft.group('a')}->{ft.group('b')}")

    amounts = _find_amounts(hay, skip=ft_skip)
    prior = next((a for a in amounts if a["kind"] == "prior_total"), None)
    revised = next((a for a in amounts if a["kind"] == "revised_total"), None)
    primary_pool = [a for a in amounts if a["kind"] not in ("prior_total", "revised_total")]
    primary = None
    if primary_pool:
        vpos = None
        if row["vendor_raw"]:
            vpos = hay.find(row["vendor_raw"])
        after = [a for a in primary_pool if vpos is None or a["pos"] > vpos]
        pool = after or primary_pool
        named = [a for a in pool if a["pattern"] != "a_bare"]
        primary = (named or pool)[0]
    if primary is None and ft_prior is not None and ft_revised is not None:
        # no explicit "increasing by $C": the delta is the action's value, and
        # only when both endpoints parsed.
        primary = {"value": round(ft_revised - ft_prior, 2), "kind": "increase",
                   "pattern": "a_from_to_delta", "pos": ft.start("b"), "raw": ""}
    if primary is None and revised is not None and not primary_pool:
        # "…for a total contract amount of $X" with nothing else: that IS the amount.
        primary = dict(revised)
        primary["kind"] = "revised_total"
    # A Guaranteed Maximum Price, or an explicit whole-term total, outranks a
    # component allowance wherever each sits in the sentence: a GC/CM award
    # prints a small pre-construction figure first and the GMP second.
    for _name, _rx in (("a_gmp", GMP_RE), ("a_term_total", TERM_TOTAL_RE)):
        _best = None
        for _m in _rx.finditer(hay):
            _mm = MONEY_RE.search(_m.group(0))
            if not _mm:
                continue
            _pos = _m.start() + _mm.start()
            if any(lo <= _pos < hi for lo, hi in list(ft_skip) + bad_spans):
                continue
            _v = parse_money(_mm.group(1))
            if _v is None:
                continue
            _v = _scaled(hay, _m.start() + _mm.end(), _v)
            if _best is None or _v > _best[0]:
                _best = (_v, _pos, _mm.group(0))
        if _best and (primary is None or _best[0] > primary["value"]):
            if primary is not None:
                notes.append(f"component_amount:{primary['pattern']}:"
                             f"{(primary.get('raw') or '').strip()}")
            primary = {"value": _best[0], "pos": _best[1], "raw": _best[2],
                       "pattern": _name,
                       "kind": "not_to_exceed" if _name == "a_gmp" else "unspecified"}
            break
    if primary and primary["value"] < AMOUNT_FLOOR:
        tail = hay[primary["pos"] + len(primary.get("raw") or ""):][:24]
        if UNIT_RATE_RE.match(tail):
            notes.append(f"unit_rate:{(primary.get('raw') or '').strip()}{tail.rstrip()}")
        else:
            notes.append(f"low_amount_ignored:{(primary.get('raw') or '').strip()}")
        primary = None
    if primary and primary["pattern"] == "a_bare":
        # a bare figure inside narration is not the action's value
        lo = max(0, primary["pos"] - 60)
        if AMOUNT_NARRATION_RE.search(hay[lo:primary["pos"] + 30]):
            notes.append(f"narrated_amount_ignored:{(primary.get('raw') or '').strip()}")
            primary = None
    if primary:
        row["amount"] = primary["value"]
        row["amount_kind"] = primary["kind"]
        fired.append(primary["pattern"])
    if revised:
        row["revised_total"] = revised["value"]
        if revised["pattern"] not in fired:
            fired.append(revised["pattern"])
    if prior:
        row["prior_total"] = prior["value"]
        if prior["pattern"] not in fired:
            fired.append(prior["pattern"])
    if ft_prior is not None:
        row["prior_total"] = ft_prior
        row["revised_total"] = ft_revised
    for a in amounts:
        if primary and a["pos"] == primary["pos"]:
            continue
        if revised and a["pos"] == revised["pos"]:
            continue
        if prior and a["pos"] == prior["pos"]:
            continue
        notes.append(f"extra_amount:{a['pattern']}:{a['raw'].strip()}")

    # -- multi-vendor lists: "X in the amount of $A; Y in the amount of $B; ..."
    pairs = _find_vendor_amount_pairs(hay, bad_spans)
    if len(pairs) >= 2:
        fired.append("v_vendor_amount_list")
        if not row["vendor_raw"]:
            first = pairs[0]
            row["vendor_raw"] = first["vendor_raw"]
            row["vendor_name"] = clean_vendor(first["vendor_raw"])
            if row["amount"] is None and first["amount"] is not None:
                row["amount"] = first["amount"]
                row["amount_kind"] = first["amount_kind"]
        seen_v = {(row["vendor_raw"] or "").lower()}
        co = []
        for pr in pairs:
            key = pr["vendor_raw"].lower()
            if key in seen_v:
                continue
            seen_v.add(key)
            co.append({"vendor_raw": pr["vendor_raw"], "amount": pr["amount"],
                       "amount_kind": pr["amount_kind"],
                       "amount_raw": pr["amount_raw"]})
        # a joint-award co-vendor may already be recorded without an amount
        for existing in row["co_vendors"]:
            if existing["vendor_raw"].lower() not in seen_v:
                co.append(existing)
        row["co_vendors"] = co
        # the envelope NTE that introduces the list
        for gm in GROUP_TOTAL_RE.finditer(hay):
            gpos = gm.start("money")
            if gpos >= pairs[0]["pos"] or any(lo <= gpos < hi for lo, hi in bad_spans):
                continue
            gval = parse_money(MONEY_RE.match(hay, gpos).group(1))
            if gval is None or gval < AMOUNT_FLOOR:
                continue
            row["group_total"] = _scaled(hay, gm.end("money"), gval)
            row["group_total_kind"] = ("not_to_exceed" if gm.group("nte")
                                       else "unspecified")
            fired.append("a_group_total")
            break
    row["co_vendors_raw"] = [c["vendor_raw"] for c in row["co_vendors"]]

    # Two separate contract actions in one item ("a contract modification for
    # $643,567 with TCF Architecture ... and a contract amendment with
    # BNBuilders to increase the GMP to $23,900,000"): a single row cannot hold
    # both, and the vendor may end up paired with the other action's figure.
    # Flag it rather than guess -- H1/F2 filter on this note.
    if row["vendor_raw"] and row["amount"] is not None:
        _others = [n for n in notes if n.startswith("extra_vendor:")]
        if _others and len([n for n in notes if n.startswith("extra_amount:")]) >= 1:
            _vp = hay.find(row["vendor_raw"])
            _clause = re.split(r";|\.\s|\band\s+a\s+contract\b", hay[_vp:])[0] \
                if _vp >= 0 else ""
            if (primary and primary.get("raw")
                    and primary["raw"].strip() not in _clause):
                notes.append("multi_action_item:amount_and_vendor_from_"
                             "different_clauses")

    # -- action type
    at, at_fired = classify_action(text, title)
    row["action_type"] = at
    fired.extend(at_fired)

    # -- identifiers
    m = (CONTRACT_ID_RE.search(hay) or CONTRACT_ID_PRE_RE.search(hay)
         or CONTRACT_ID_BARE_RE.search(hay))
    if m:
        row["contract_id"] = m.group(1)
        fired.append("i_contract_id")
    m = PO_RE.search(hay)
    if m:
        row["po_number"] = (m.group(1) or m.group(2)).upper()
        fired.append("i_po_number")
    m = BID_RE.search(hay)
    if m:
        row["bid_number"] = m.group(1).upper()
        fired.append("i_bid_number")
    m = RFP_RE.search(hay)
    if m:
        row["rfp_number"] = re.sub(r"\s+", "", m.group(1)).upper()
        fired.append("i_rfp_number")

    # -- term
    m = TERM_RE.search(hay)
    if m:
        row["term_start"] = m.group("start")
        row["term_end"] = m.group("end")
        fired.append("t_term_range")
    else:
        m = SCHOOL_YEAR_RE.search(hay)
        if m:
            notes.append(f"school_year:{m.group(0)}")
            fired.append("t_school_year")

    # -- department / program
    m = DEPT_RE.search(title)
    if m:
        row["department"] = m.group(0).lstrip("(").strip()
    m = PROGRAM_RE.search(hay)
    if m and not row["program_or_project"]:
        row["program_or_project"] = re.sub(r"\s+", " ", m.group(1))

    if IMMEDIATE_RE.search(hay) or "immediate action" in (item.get("extractor_notes") or []) \
            or item.get("section") == "immediate":
        row["immediate_action"] = True
        fired.append("x_immediate")

    row["patterns_fired"] = fired
    row["extractor_notes"] = notes
    return row


# ---------------------------------------------------------------------------
# 3. validator
# ---------------------------------------------------------------------------

_HAS_MONEY_RE = re.compile(r"\$\s?\d")
# No single Seattle School Board action is worth more than this.
AMOUNT_CEILING = 2_000_000_000
# Board approval is only required above a six-figure threshold, so a bare
# three-figure number in a business item is a unit rate, a page number, or --
# as in 2013-06-19 D.8 -- narration ("contracts that were less than the $250K
# threshold").  Kept only when the text prints an explicit per-unit cue.
AMOUNT_FLOOR = 1_000
UNIT_RATE_RE = re.compile(
    r"^\s*(?:per|each|/|a)\s+(?:hour|hr|day|student|unit|item|seat|licen[cs]e|"
    r"user|device|month|meal|copy|page|test|ton|yard|square\s+f(?:oo|ee)t)\b|"
    r"^\s*(?:per|each)\b|^\s*hourly\b", re.I)
# Narration around a bare figure that means it is not the action's value.
AMOUNT_NARRATION_RE = re.compile(
    r"less\s+than|greater\s+than|more\s+than|at\s+least|no\s+more\s+than|"
    r"threshold|per\s+student|hourly\s+rate|approximately|about|"
    r"estimated\s+at\s+about|for\s+reference", re.I)

_ACTION_EVIDENCE = {
    "final_acceptance": re.compile(r"final\s+acceptance|as\s+complete|accept\s+the\s+work", re.I),
    "change_order": re.compile(r"change\s+order", re.I),
    "amendment": re.compile(r"amend|addend|modificat|modify", re.I),
    "renewal": re.compile(r"renew|exten[ds]", re.I),
    "purchase": re.compile(r"purchas|acquisition", re.I),
    "new": re.compile(r"award|contract|agreement|enter\s+into|execute|bid|lease|"
                      r"MOU|MOA|interlocal|grant|fund", re.I),
    "other": re.compile(r".", re.S),
}


def validate(row: dict, item: dict, doc_pages: int | None = None) -> tuple[bool, list[str]]:
    """Applied to every row regardless of which extractor produced it."""
    reasons: list[str] = []
    text = _text_of(item)

    for fld in ("amount", "prior_total", "revised_total"):
        v = row.get(fld)
        if v is None:
            continue
        if isinstance(v, str):
            v = parse_money(v)
            if v is None:
                reasons.append(f"{fld}_unparseable")
                continue
            row[fld] = v
        if not isinstance(v, (int, float)):
            reasons.append(f"{fld}_not_numeric")
        elif v < 0:
            reasons.append(f"{fld}_negative")
        elif v > AMOUNT_CEILING:
            # The district's whole annual budget is ~$1.2B, so a single board
            # action above $2B is always either a source typo ("$39,542,000,000"
            # for student transportation) or a scaling bug.
            reasons.append(f"{fld}_implausible" if fld != "amount"
                           else "amount_implausible")

    at = row.get("action_type")
    if at is not None and at not in ACTION_TYPES:
        reasons.append("action_type_invalid")
    ak = row.get("amount_kind")
    if ak is not None and ak not in AMOUNT_KINDS:
        reasons.append("amount_kind_invalid")
    if row.get("amount") is not None and ak is None:
        reasons.append("amount_without_kind")

    if at in ("amendment", "change_order"):
        a, rt = row.get("amount"), row.get("revised_total")
        if isinstance(a, (int, float)) and isinstance(rt, (int, float)) and rt < a:
            reasons.append("revised_total_lt_amount")

    norm_t = re.sub(r"\s+", " ", text)
    vr = row.get("vendor_raw")
    if vr and re.sub(r"\s+", " ", vr) not in norm_t:
        reasons.append("vendor_not_verbatim")
    for cv in (row.get("co_vendors_raw") or []):
        if re.sub(r"\s+", " ", cv) not in norm_t:
            reasons.append("co_vendor_not_verbatim")
            break
    for cv in (row.get("co_vendors") or []):
        name = cv.get("vendor_raw") or ""
        if not name or re.sub(r"\s+", " ", name) not in norm_t:
            reasons.append("co_vendor_not_verbatim")
            break
        amt, raw = cv.get("amount"), cv.get("amount_raw")
        if amt is None:
            continue
        if not isinstance(amt, (int, float)) or amt < 0 or amt > AMOUNT_CEILING:
            reasons.append("co_vendor_amount_invalid")
            break
        # every co-vendor amount must be *printed*, not derived
        if not raw or re.sub(r"\s+", " ", raw) not in norm_t:
            reasons.append("co_vendor_amount_not_printed")
            break
    gt = row.get("group_total")
    if gt is not None:
        if not isinstance(gt, (int, float)) or gt < 0 or gt > AMOUNT_CEILING:
            reasons.append("group_total_invalid")
        elif row.get("group_total_kind") not in AMOUNT_KINDS:
            reasons.append("group_total_kind_invalid")
    # Identifiers must be printed in *this* item -- F2 found "K5111" stamped on
    # an item belonging to a different vendor.  Compared case-insensitively and
    # ignoring internal spacing ("RFP 11641" vs "RFP11641").
    squash_t = re.sub(r"[\s.]+", "", norm_t).lower()
    for fld in ("contract_id", "po_number", "bid_number", "rfp_number"):
        val = row.get(fld)
        if val and re.sub(r"[\s.]+", "", str(val)).lower() not in squash_t:
            reasons.append(f"{fld}_not_in_item_text")

    cit = row.get("citation") or {}
    ps, pe = cit.get("page_start"), cit.get("page_end")
    if ps is None or pe is None:
        reasons.append("citation_missing_page")
    else:
        if ps < 1:
            reasons.append("page_start_lt_1")
        if pe < ps:
            reasons.append("page_end_lt_page_start")
        if doc_pages and pe > doc_pages:
            reasons.append("page_end_gt_doc_pages")

    if at and at in _ACTION_EVIDENCE and not _ACTION_EVIDENCE[at].search(text):
        reasons.append("action_type_unsupported")

    if row.get("amount") is None and _HAS_MONEY_RE.search(text):
        reasons.append("amount_missing_though_text_has_money")

    return (not reasons), reasons


RESIDUAL_CATEGORY_DOC = {
    "no_facts_in_item": "the item prints neither a vendor nor a dollar figure "
                        "(mostly 2005-2012 agenda one-liners) — the LLM should "
                        "return nulls unless the vendor is in the title",
    "vendor_only_in_title": "a dollar figure but the vendor, if any, is only in "
                            "the title or a project/committee annotation",
    "vendor_unnamed": "the item says 'various vendors' / 'the above-listed "
                      "agencies' — vendor must stay null",
    "multi_amount_no_vendor": "two or more dollar figures and no vendor the "
                              "anchors could name: vendor lists ('X in the "
                              "amount of $A; Y in the amount of $B'), component "
                              "breakdowns, and budget transfers that mention a "
                              "contract — pick the primary vendor/amount pair "
                              "and put the rest in extractor_notes",
    "action_type_unclear": "vendor and amount are fine, the action verb is not "
                           "one of the seven types",
    "validator_failed": "the regex produced something the validator rejected",
}


def residual_category(row: dict, item: dict) -> str:
    text = _text_of(item)
    has_money = bool(_HAS_MONEY_RE.search(text))
    miss = row.get("missing_required") or []
    if not row.get("valid", True):
        return "validator_failed"
    if "vendor_raw" not in miss and "amount" not in miss:
        return "action_type_unclear"
    if re.search(r"various\s+vendors|the\s+above[- ]listed|multiple\s+vendors|"
                 r"agencies\s+approved\s+through|following\s+agencies", text, re.I):
        return "vendor_unnamed"
    if len(MONEY_RE.findall(text)) > 1 and "vendor_raw" in miss:
        return "multi_amount_no_vendor"
    if not has_money and "vendor_raw" in miss:
        return "no_facts_in_item"
    return "vendor_only_in_title"


def missing_required(row: dict, item: dict) -> list[str]:
    miss = []
    text = _text_of(item)
    has_money = bool(_HAS_MONEY_RE.search(text))
    if not row.get("vendor_raw"):
        miss.append("vendor_raw")
    if row.get("amount") is None and has_money:
        miss.append("amount")
    if not row.get("action_type") or row["action_type"] == "other":
        miss.append("action_type")
    return miss


# ---------------------------------------------------------------------------
# corpus plumbing
# ---------------------------------------------------------------------------

def era_of(doc_era: str | None, meeting_date: str) -> str:
    """Map a document to its *format family*, which is what the parsers care about.

    For the two district-website generations (`wp` and `blackboard`) the family
    follows the **meeting date**, not the host the file happened to survive on:
    since the Blackboard crawl landed, many 2016-17 -> 2020-21 meetings take
    their minutes from the Blackboard copy because WP only ever had the agenda,
    and those minutes are WP-era minutes in every respect that matters.
    `legacy` and `archive` (2005-2012) keep their own families.
    """
    if doc_era in ("wp", "blackboard"):
        if meeting_date >= "2021-07-01":
            return "modern"
        if meeting_date >= "2016-08-01":
            return "wp1620"
        return "blackboard"          # 2011-12 -> 2015-16, YYYYMMDD_Minutes.pdf
    if doc_era in ("legacy", "archive"):
        return doc_era
    return "unknown"


def load_docs() -> dict:
    docs = {}
    if not os.path.exists(MANIFEST):
        return docs
    with open(MANIFEST) as fh:
        for line in fh:
            if line.strip():
                d = json.loads(line)
                docs[d["doc_id"]] = d
    return docs


def load_items(docs: dict, era_filter: str | None = None, limit: int | None = None):
    out = []
    if not os.path.isdir(ITEMS_DIR):
        return out
    for fn in sorted(os.listdir(ITEMS_DIR)):
        if not fn.endswith(".jsonl"):
            continue
        with open(os.path.join(ITEMS_DIR, fn)) as fh:
            for line in fh:
                if not line.strip():
                    continue
                it = json.loads(line)
                d = docs.get(it["source_doc_id"], {})
                e = era_of(d.get("era"), it["meeting_date"])
                if era_filter and e != era_filter:
                    continue
                out.append((it, e, d))
                if limit and len(out) >= limit:
                    return out
    return out


def item_key(item: dict) -> tuple:
    return (item["meeting_id"], item["item_no"], item["char_start"])


def resolve_gold_item(g: dict, items_by_key: dict):
    """Find the corpus item a gold row labels.

    Gold rows are identified by ``(meeting_id, item_no)``.  ``char_start`` is
    **advisory**: re-running the segmenter shifts offsets whenever pagination
    or the chosen source document changes, and re-keying the gold set on every
    such run would be busywork that hides real drift.  It is used only to pick
    between the 26 ``(meeting_id, item_no)`` pairs that genuinely occur twice
    in the corpus (an item minuted under two roman blocks), where the nearest
    offset wins.  Returns ``(item, era, doc)`` or ``None``.
    """
    exact = items_by_key.get((g["meeting_id"], g["item_no"], g["char_start"]))
    if exact is not None:
        return exact
    cands = [v for k, v in items_by_key.items()
             if k[0] == g["meeting_id"] and k[1] == g["item_no"]]
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    want = g.get("char_start") or 0
    return min(cands, key=lambda t: abs(t[0]["char_start"] - want))


# ---------------------------------------------------------------------------
# gold set
# ---------------------------------------------------------------------------

GOLD_FIELDS = ("admitted", "vendor_raw", "amount", "amount_kind", "action_type",
               "revised_total", "prior_total", "contract_id",
               "co_vendor_count", "group_total")


def gold_value(row: dict, field: str):
    """Read a gold-comparable value; `co_vendor_count` is derived."""
    if field == "co_vendor_count":
        return len(row.get("co_vendors") or []) or None
    return row.get(field)


def load_gold() -> list[dict]:
    if not os.path.exists(GOLD_PATH):
        return []
    with open(GOLD_PATH) as fh:
        return [json.loads(l) for l in fh if l.strip()]


def score_gold(docs: dict, items_by_key: dict) -> dict:
    gold = load_gold()
    stats = {f: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "errors": []} for f in GOLD_FIELDS}
    missing = []
    for g in gold:
        key = (g["meeting_id"], g["item_no"], g["char_start"])
        got = resolve_gold_item(g, items_by_key)
        if got is None:
            missing.append(key)
            continue
        item, era, doc = got
        admitted, _reason = is_contract_like(item)
        s = stats["admitted"]
        if g["admitted"] and admitted:
            s["tp"] += 1
        elif g["admitted"] and not admitted:
            s["fn"] += 1
            s["errors"].append((key, True, False))
        elif not g["admitted"] and admitted:
            s["fp"] += 1
            s["errors"].append((key, False, True))
        else:
            s["tn"] += 1
        if not g["admitted"]:
            continue
        row = extract(item, era, doc)
        for f in GOLD_FIELDS[1:]:
            exp, act = g.get(f), gold_value(row, f)
            if isinstance(exp, (int, float)) and isinstance(act, (int, float)):
                same = abs(float(exp) - float(act)) < 0.005
            else:
                same = (exp or None) == (act or None)
            s = stats[f]
            if exp is None and act is None:
                s["tn"] += 1
            elif exp is not None and act is not None and same:
                s["tp"] += 1
            elif exp is not None and act is None:
                s["fn"] += 1
                s["errors"].append((key, exp, act))
            elif exp is None and act is not None:
                s["fp"] += 1
                s["errors"].append((key, exp, act))
            else:
                s["fp"] += 1
                s["fn"] += 1
                s["errors"].append((key, exp, act))
    return {"n": len(gold), "missing": missing, "stats": stats}


def prf(s: dict) -> tuple[float, float]:
    p = s["tp"] / (s["tp"] + s["fp"]) if (s["tp"] + s["fp"]) else 1.0
    r = s["tp"] / (s["tp"] + s["fn"]) if (s["tp"] + s["fn"]) else 1.0
    return p, r


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def run(era_filter=None, limit=None, write=True):
    docs = load_docs()
    loaded = load_items(docs, era_filter, limit)
    rows, residual = [], []
    admitted_by_era = Counter()
    rejected_by_era = Counter()
    reject_reason = Counter()
    covered_by_era = Counter()
    fail_reasons = Counter()
    pattern_counter = Counter()
    items_by_key = {}
    for item, era, doc in loaded:
        items_by_key[item_key(item)] = (item, era, doc)
        ok, reason = is_contract_like(item)
        if not ok:
            rejected_by_era[era] += 1
            reject_reason[reason] += 1
            continue
        admitted_by_era[era] += 1
        row = extract(item, era, doc)
        valid, reasons = validate(row, item, doc.get("pages"))
        row["valid"] = valid
        row["reasons"] = reasons
        for p in row["patterns_fired"]:
            pattern_counter[p] += 1
        rows.append(row)
        miss = missing_required(row, item)
        if miss or not valid:
            row["missing_required"] = miss
            row["residual_category"] = residual_category(row, item)
            residual.append(dict(row))
            for x in reasons:
                fail_reasons[x] += 1
            for x in miss:
                fail_reasons["missing:" + x] += 1
        else:
            covered_by_era[era] += 1

    if write:
        os.makedirs(CONTRACTS_DIR, exist_ok=True)
        os.makedirs(QA_DIR, exist_ok=True)
        with open(os.path.join(CONTRACTS_DIR, "regex_rows.jsonl"), "w") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        with open(os.path.join(CONTRACTS_DIR, "residual.jsonl"), "w") as fh:
            for r in residual:
                fh.write(json.dumps(r) + "\n")
        # E2 has already processed part of the residual; emit just the items it
        # has not seen, keyed the same way, so a rerun only batches the delta.
        done = set()
        llm_path = os.path.join(CONTRACTS_DIR, "llm_rows.jsonl")
        if os.path.exists(llm_path):
            with open(llm_path) as fh:
                for line in fh:
                    if line.strip():
                        d = json.loads(line)
                        done.add((d.get("meeting_id"), d.get("item_no"),
                                  d.get("char_start")))
            with open(os.path.join(CONTRACTS_DIR, "residual_new.jsonl"), "w") as fh:
                for r in residual:
                    if (r["meeting_id"], r["item_no"], r["char_start"]) not in done:
                        fh.write(json.dumps(r) + "\n")

    gold = score_gold(docs, items_by_key) if os.path.exists(GOLD_PATH) else None
    if write:
        write_report(admitted_by_era, rejected_by_era, covered_by_era, reject_reason,
                     fail_reasons, pattern_counter, residual, gold, len(loaded))
    return {"rows": rows, "residual": residual, "admitted": admitted_by_era,
            "covered": covered_by_era, "rejected": rejected_by_era, "gold": gold}


# Result of reading all 60 items from
# `--sample-prefilter 60` (seed 3: 30 random admits + 30 random rejects).
PREFILTER_AUDIT = """\
A 60-item random sample (30 admitted + 30 rejected, `--sample-prefilter 60`,
seed 3) was read by hand.

- **admitted: 30/30 correct (100%)** — every one is a contract action or a
  contract-action placeholder (bid awards, A/E and construction contracts,
  final acceptances, interagency agreements, amendments). Two are agenda
  placeholders whose bid had not been opened yet; they are contract items with
  no facts to extract, so they belong in the residual, not in the reject pile.
- **rejected: 30/30 correct (100%)** — warrants (2), minutes (5), personnel
  reports (3), board policies (3), board resolutions (3), meeting-schedule
  amendments (1), and 13 genuinely non-contract items (budget transfers,
  educational specifications, value-engineering reports, program plans,
  conditional teaching certificates, student-representative selection).
- The one debatable call is grant/gift *acceptance* ("accept the LEVF grant of
  up to $2,000,000"), rejected when no contract/agreement word appears. That is
  the pre-filter's known recall gap; grant **agreements** are still admitted.
"""


def write_report(admitted, rejected, covered, reject_reason, fail_reasons,
                 patterns, residual, gold, n_items):
    L = []
    A = L.append
    A("# Contract extraction report (E1)\n")
    A(f"Generated by `extractors/sps_web/extract.py`. {n_items} segmented items considered.\n")
    A("## Pre-filter\n")
    A("| era | items | admitted | rejected | admit rate |")
    A("|---|---|---|---|---|")
    tot_a = tot_r = 0
    for e in ERAS + ("unknown",):
        a, r = admitted.get(e, 0), rejected.get(e, 0)
        if not (a or r):
            continue
        tot_a += a
        tot_r += r
        A(f"| {e} | {a+r} | {a} | {r} | {a/(a+r):.1%} |")
    A(f"| **all** | {tot_a+tot_r} | {tot_a} | {tot_r} | "
      f"{tot_a/(tot_a+tot_r) if tot_a+tot_r else 0:.1%} |")
    A("\n### Top rejection reasons\n")
    for k, v in reject_reason.most_common(12):
        A(f"- `{k}` — {v}")
    A("\n### Hand-audited pre-filter precision\n")
    A(PREFILTER_AUDIT)
    A("\n## Regex coverage\n")
    A("Coverage = admitted items with vendor + amount (or no dollar figure in the "
      "text at all) + a non-`other` action type, and no validator failure.\n")
    A("| era | admitted | covered | coverage |")
    A("|---|---|---|---|")
    for e in ERAS + ("unknown",):
        a = admitted.get(e, 0)
        if not a:
            continue
        c = covered.get(e, 0)
        A(f"| {e} | {a} | {c} | {c/a:.1%} |")
    ta = sum(admitted.values())
    tc = sum(covered.values())
    A(f"| **all** | {ta} | {tc} | {tc/ta if ta else 0:.1%} |")
    post16 = sum(admitted.get(e, 0) for e in ("wp1620", "modern"))
    post16c = sum(covered.get(e, 0) for e in ("wp1620", "modern"))
    A(f"\n**post-2016 (wp1620 + modern): {post16c}/{post16} = "
      f"{post16c/post16 if post16 else 0:.1%}** (target >= 70%)\n")
    A("## Gold set\n")
    if not gold:
        A("_No gold set found._\n")
    else:
        A(f"{gold['n']} hand-labelled items"
          + (f"; {len(gold['missing'])} not found in the current items corpus" if gold["missing"] else "")
          + ".\n")
        A("| field | tp | fp | fn | precision | recall |")
        A("|---|---|---|---|---|---|")
        for f in GOLD_FIELDS:
            s = gold["stats"][f]
            p, r = prf(s)
            A(f"| {f} | {s['tp']} | {s['fp']} | {s['fn']} | {p:.1%} | {r:.1%} |")
        A("")
        for f in GOLD_FIELDS:
            errs = gold["stats"][f]["errors"]
            if errs:
                A(f"**{f} mismatches ({len(errs)})**\n")
                for key, exp, act in errs[:10]:
                    A(f"- `{key[0]} {key[1]}` expected `{exp}` got `{act}`")
                A("")
    A("## Named patterns fired\n")
    for k, v in patterns.most_common(40):
        A(f"- `{k}` — {v}")
    A("\n## Top failure reasons (residual)\n")
    for k, v in fail_reasons.most_common(20):
        A(f"- `{k}` — {v}")
    A("\n## Residual categories (what E2's prompt has to cover)\n")
    cats = Counter(r["residual_category"] for r in residual)
    A("| category | items | what the LLM has to do |")
    A("|---|---|---|")
    for k, v in cats.most_common():
        A(f"| `{k}` | {v} | {RESIDUAL_CATEGORY_DOC.get(k, '')} |")
    A(f"\n## Residual: {len(residual)} items (E2 batch input)\n")
    rnd = random.Random(11)
    for r in rnd.sample(residual, min(15, len(residual))):
        A(f"- **{r['meeting_date']} {r['item_no']}** ({r['era']}) missing="
          f"{r['missing_required']} reasons={r['reasons']}")
        A(f"  - _{(r['title'] or '')[:110]}_")
        A(f"  - `{re.sub(chr(10), ' ', r['item_text'])[:260]}`")
    with open(os.path.join(QA_DIR, "extract_report.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")


def sample_prefilter(n: int, seed: int = 3):
    docs = load_docs()
    loaded = load_items(docs)
    rnd = random.Random(seed)
    admitted, rejected = [], []
    for item, era, doc in loaded:
        ok, reason = is_contract_like(item)
        (admitted if ok else rejected).append((item, era, reason))
    out = []
    for label, pool in (("ADMIT", admitted), ("REJECT", rejected)):
        for item, era, reason in rnd.sample(pool, min(n // 2, len(pool))):
            out.append({"verdict": label, "era": era, "reason": reason,
                        "meeting_id": item["meeting_id"], "item_no": item["item_no"],
                        "char_start": item["char_start"], "title": item["title"],
                        "motion": (item.get("motion_text") or "")[:400]})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--era", choices=ERAS)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--gold", action="store_true", help="score the gold set only")
    ap.add_argument("--sample-prefilter", type=int, metavar="N")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    if args.sample_prefilter:
        for r in sample_prefilter(args.sample_prefilter):
            print(json.dumps(r))
        return 0
    if args.gold:
        docs = load_docs()
        loaded = load_items(docs)
        by_key = {item_key(i): (i, e, d) for i, e, d in loaded}
        g = score_gold(docs, by_key)
        print(f"gold n={g['n']} missing={len(g['missing'])}")
        for f in GOLD_FIELDS:
            s = g["stats"][f]
            p, r = prf(s)
            print(f"  {f:16s} tp={s['tp']:3d} fp={s['fp']:3d} fn={s['fn']:3d} "
                  f"P={p:.1%} R={r:.1%}")
            for key, exp, act in s["errors"][:6]:
                print(f"      {key[0]} {key[1]}: exp={exp!r} got={act!r}")
        return 0
    res = run(args.era, args.limit, write=not args.no_write)
    ta = sum(res["admitted"].values())
    tc = sum(res["covered"].values())
    print(f"admitted={ta} covered={tc} ({tc/ta if ta else 0:.1%}) "
          f"residual={len(res['residual'])}")
    for e in ERAS:
        a, c = res["admitted"].get(e, 0), res["covered"].get(e, 0)
        if a:
            print(f"  {e:8s} admitted={a:5d} covered={c:5d} ({c/a:.1%})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
