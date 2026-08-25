"""
bar_fill.py -- Task E3, "BAR detail pass" (see ``extractors/sps_web/PLAN.md``,
Section 1 "Where the contract facts live" and Section 3 card E3): link every
extracted contract row to its **Board Action Report** (BAR) and fill the
fields that only the BAR carries -- contract/PO number, term, department,
fund, funding source, procurement method -- plus the ``amount`` for the two
big classes of rows the minutes leave blank:

* **final acceptance closeouts.**  The motion says only "...accept the work
  performed under Contract P5131 with Lincoln Construction, Inc. ... as
  final".  The BAR's fiscal-impact section carries the closeout table
  (``Contract Amount`` / ``Change Orders`` / ``WSST`` / ``Total Contract
  including WSST`` / ``Project Retention``), which is where the real final
  contract value lives.
* **new contracts and amendments whose motion defers to the attachment**
  ("...in the amount as attached to the Board Action Report").  The BAR says
  "Fiscal impact to this action will be $X" / "not to exceed $X" / "The total
  contract amount is $X".

Usage (from the repo root)::

    venv/bin/python3 -m extractors.sps_web.bar_fill                 # since 2016-08-01
    venv/bin/python3 -m extractors.sps_web.bar_fill --since 2005-01-01
    venv/bin/python3 -m extractors.sps_web.bar_fill --limit 200     # smoke test
    venv/bin/python3 -m extractors.sps_web.bar_fill --report /tmp/r.md
    venv/bin/python3 -m extractors.sps_web.bar_fill --merge-llm   # after the batches ran

Runs **after** ``e2_merge.py`` and **before** ``link.py``.  It never touches
``extracted.jsonl``; it writes a parallel file.

Inputs (all read-only)
----------------------
* ``out_sps_web/contracts/extracted.jsonl`` -- one row per admitted item
  (e2_merge output).  Row order and row count are preserved exactly.
* ``out_sps_web/manifest/documents_classified.jsonl`` -- ``kind == "bar"``
  rows give the BAR corpus (``doc_id, meeting_id, meeting_date,
  resolved_filename/filename, item_code, filename_date, pages``).
* ``out_sps_web/text/<era>/<date>/<stem>.txt`` -- the BAR text, located
  through the sibling ``<stem>.textmeta.json`` (which always carries
  ``doc_id``; the ``.txt`` stem does not, because colliding filenames get a
  ``-<doc_id>`` suffix).  Pages are separated by ``\\f``.

Outputs (rewritten from scratch every run)
------------------------------------------
* ``out_sps_web/contracts/extracted_filled.jsonl`` -- same rows, same order,
  with BAR-derived fields merged in (below).
* ``out_sps_web/contracts/bar_batches/NNN.jsonl`` -- optional LLM fallback
  input, 100 rows per file, same schema as ``contracts/batches/*.jsonl`` plus
  ``bar_doc_id`` / ``bar_page_start`` / ``bar_text``.  Written for rows that
  still have a null ``amount`` after the regex pass *and* have a linked BAR.
  This module never calls a model.
* ``out_sps_web/qa/bar_conflicts.jsonl`` -- one row per
  ``bar_amount_conflict`` (row key, the minutes amount and the BAR amount with
  their kinds, an item-text excerpt and the BAR sentence the figure came from,
  doc id + page), for the E1 owner to triage.  Several of these are E1 bugs
  rather than BAR-parsing bugs -- a motion that quotes only the GC/CM
  preconstruction fee, or the $250,000 board-approval threshold.
* ``out_sps_web/qa/bar_fill_report.md``.

``--merge-llm`` (a second, separate invocation) additionally reads
``contracts/bar_batches/NNN.out.jsonl`` and writes
``out_sps_web/qa/bar_llm_rejects.jsonl`` + ``qa/bar_llm_report.md``; see Part
4 below.

=============================================================================
Part 1 -- linking a row to its BAR
=============================================================================

A BAR is attached to the meeting where the item is **introduced** and usually
re-attached at the **action** meeting two to four weeks later, so the
candidate set for a row is every BAR attached to the row's own meeting or to
a meeting 0-60 days earlier (``MAX_BAR_GAP_DAYS``, the same window
``link.py`` uses for intro<->action pairing), plus any BAR whose own header
("For Introduction: <date>" / "For Action: <date>") names the row's meeting
date.

Match tiers, tried in order; the first tier that produces a *unique* winner
wins.  A tie (two BARs equally good at the winning tier) links nothing and is
recorded as ``ambiguous`` -- a wrong link would silently attach another
contract's money to this row.

1. ``item_code_exact``   -- same meeting, identical item code (``I06``).
2. ``item_code_number``  -- same code *number* with a different letter
   (introduction ``I06`` vs. action ``A06``/``C06``), where the BAR is on
   this meeting, or its filename date / header dates name this meeting.
3. ``title_jaccard``     -- token Jaccard of the item title vs. the BAR's
   "1. TITLE" section >= ``MIN_JACCARD`` (0.6) and clear of the runner-up.
4. ``title_containment`` -- the shorter title's tokens are >= 0.8 contained
   in the longer's (minutes titles often carry a trailing "Approval of this
   item would..." blurb that drags Jaccard down), >= 6 shared tokens.
5. ``title_slug``        -- the first 40 characters of the two slugs agree.
6. ``vendor_contract``   -- the row's ``contract_id``/``po_number`` (strong)
   or ``vendor_raw`` (only together with >= 0.3 title overlap) appears on the
   BAR's first page.

``bar_match_confidence`` is 0.97/0.90/0.5+j/2/0.80/0.78/0.70 by tier.

=============================================================================
Part 2 -- parsing the BAR
=============================================================================

Only the first ``MAX_BAR_PAGES`` (6) pages are read: the header, title,
motion and fiscal-impact section are always up front, and the rest of a
"packet" PDF is the draft contract itself, which is full of boilerplate money
that must never be mistaken for the board action's amount.

Every money pattern is named and carries an ``amount_kind``; ``AMOUNT_PATTERNS``
is ordered most-specific-first and the first match wins.  Sentences that
contain a ``_MONEY_NEGATIVE`` phrase ("state funding assistance", "savings",
"project budget", "budgeted at", "forfeit", "does not represent a specific
expenditure", ...) are skipped -- those figures are real but are not the
contract's value.

For a closeout the table gives three numbers, mapped as::

    Contract Amount           -> prior_total
    Change Orders             -> (kept only in bar_change_orders)
    Total Contract incl. WSST -> amount (amount_kind="final"), revised_total

Other fields: ``contract_id`` ("Contract P1454", "Contract No. K5069"),
``po_number``, ``rfp_number``/``bid_number`` (kept as BAR-only fields),
``term_start``/``term_end`` (raw source text, matching E1's convention),
``fund`` (BEX|BTA|general|grant|capital|ASB|other from the levy phrases),
``funding_source_text`` (the whole revenue sentence), ``procurement_method``,
``department`` (only from a literal "Department:" line -- the corpus's
``department`` values are board-committee codes ("Ops", "C&I"), so a BAR's
"LEAD STAFF: ..., Chief Operations Officer" role is *not* merged into it; it
is kept separately as ``bar_lead_staff``), and the counterparty.

The vendor is read from ``VENDOR_SLICES`` in order -- a "Vendor:"/
"Contractor:"/"Consultant:" line (including the closeout table's unlabelled
"Contractor    <name>" column), then the "1. TITLE" line, the "3. RECOMMENDED
MOTION", then the "2. PURPOSE" paragraph.  Each
slice is handed to **E1's** ``find_vendor_candidates``, so the vendor walk,
the legal-suffix and stopword tables, the joint-vendor split and the
plausibility rules live in exactly one place: the district itself, its
departments, board committees, course names, "the successful bidder", "TBD"
and the like are rejected there for the whole pipeline.  (One consequence
worth knowing: E1 also rejects anything starting "State of Washington", so an
interlocal with e.g. the Department of Enterprise Services yields no vendor
here either.)

=============================================================================
Part 3 -- merging (conservative)
=============================================================================

* A field is filled **only when it is null/absent on the row**.  A
  minutes-derived value always wins.
* ``vendor_raw`` is filled only when the minutes left it null (a consent
  motion that says just "approve the contract as attached to the Board Action
  Report"), and only with a string that is verbatim in the BAR text.  It is
  never *overwritten*.  Co-vendors are **not** filled from BARs: E1 now emits
  a structured ``co_vendors`` list (with a per-vendor amount) that this pass
  passes through untouched; the BAR's own reading is kept, unmerged, in
  ``vendor_raw_bar`` / ``co_vendors_raw_bar`` / ``vendor_bar_slice``.
  Note this means a filled ``vendor_raw`` is **not** verbatim in the *item*
  text, which is what E1's own validator checks -- so ``vendors.py`` (F1) must
  be rerun after this stage or ``reconcile`` check 4 will flag the new strings
  as unmapped.
* A filled amount must pass the E1-style checks: parses, >= ``MIN_AMOUNT``
  ($1,000 -- below the board-approval threshold, so a smaller figure is
  almost always a unit price or a page number), <= ``AMOUNT_CEILING`` ($2B),
  and its digits are printed in the BAR text.
* When the BAR amount and a **non-null** row amount disagree by more than
  ``CONFLICT_TOLERANCE`` (1%), the row's amount is left alone and
  ``bar_amount_conflict:<bar>!=<row>`` is appended to ``extractor_notes``.
  When they are ``IMPLAUSIBLE_RATIO`` (100x) or more apart the note becomes
  ``bar_amount_implausible_vs_minutes`` and ``prior_total``/``revised_total``
  are *not* filled from that BAR either -- at that distance one side is a bad
  parse, and those two fields come from the same sentences.
* Amounts are only ever read from a **labelled** position -- the closeout
  table's own rows, "Fiscal impact ... will be", "not to exceed", "total
  contract amount", "in the amount of".  There is deliberately no bare
  ``$X`` pattern: a fiscal section that mentions a figure without saying what
  it is goes to the LLM fallback instead.
* Every filled field ``f`` also gets ``f_source = "bar"``; rows that already
  had an amount get ``amount_source = "minutes"`` so publish.py can emit the
  column without re-deriving it.  The row gets
  ``bar_citation {doc_id, page_start, page_end}``, whose ``page_start`` is the
  page the *amount* was printed on (the field a QA sampler checks first).

=============================================================================
Part 4 -- the LLM fallback merge (``--merge-llm``)
=============================================================================

Rows the regex could not fill are written to ``contracts/bar_batches/`` for
the coordinator's haiku batch run, which drops ``NNN.out.jsonl`` beside each
input.  ``--merge-llm`` validates every LLM row **against that batch row's own
``bar_text``** -- the only text the model saw -- and merges the survivors:

* hard failures reject the whole row (an amount that does not parse, is under
  $1,000, over $2B, or is not printed in ``bar_text``; a ``contract_id``/
  ``po_number``/``vendor_raw`` absent from everything the model was shown --
  ``bar_text`` plus the batch row's own ``title``/``item_text``, since echoing
  a field we handed it is not fabrication).  A model that
  invented one field is not trusted for the others.  Rejects, with reasons and
  a BAR excerpt, go to ``qa/bar_llm_rejects.jsonl``.
* soft failures drop only that field (a ``fund`` outside the vocabulary, an
  unparseable term date, a funding sentence not in the text) and are recorded
  in the row's ``extractor_notes`` as ``bar_llm_dropped:<reason>``.
* survivors fill **only still-null fields**, each tagged
  ``<field>_source = "bar_llm"`` (``amount_source = "bar_llm"``), and the row
  gets a ``bar_citation`` if it did not already have one.
* a **hand-checked amount reject list** (``bar_llm_amount_rejects.csv``, next
  to this module, plus any ``persistent: true`` row in
  ``qa/bar_llm_rejects.jsonl``) blocks ``amount``/``amount_kind`` for
  individual keys whose LLM figure was reviewed against the BAR and judged
  wrong or partial -- the first row of a multi-vendor table, a base salary
  where the contract is total compensation, the top of a stated range, one
  school year of two.  Every other field the model supplied for those rows is
  still merged, and the row gets
  ``extractor_notes: bar_llm_amount_rejected:<reason>``.  The list is keyed by
  ``(meeting_id, item_no, char_start)``, is checked in so it outlives a
  regenerated corpus, and is mirrored into ``qa/bar_llm_rejects.jsonl`` on
  every run.

Order matters and makes the pair idempotent: a plain run always rebuilds
``extracted_filled.jsonl`` from ``extracted.jsonl``, dropping the LLM fills,
so rerun ``--merge-llm`` after it.  ``--merge-llm`` writes only null fields,
so running it twice changes nothing the second time.

``vendor_raw`` is the one field the *regex* pass refuses to fill (E1's
validator requires it verbatim in the item text, which a BAR string need not
be) but the LLM pass does, at the coordinator's request, validated verbatim
against ``bar_text``.  Any new string needs ``vendors.py`` (F1) rerun before
``link``/``publish``, or ``reconcile`` check 4 flags it; ``--merge-llm``
prints a warning when it fills any.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

ROOT = "out_sps_web"

MAX_BAR_GAP_DAYS = 60
MAX_BAR_PAGES = 6
MIN_JACCARD = 0.6
MIN_CONTAINMENT = 0.8
MIN_SHARED_TOKENS = 6
SLUG_PREFIX = 40
MIN_AMOUNT = 1_000.0
AMOUNT_CEILING = 2_000_000_000.0
CONFLICT_TOLERANCE = 0.01
BATCH_SIZE = 100

# Fields bar_fill may write into a row (only where the row is null/absent).
FILLABLE = (
    "amount", "amount_kind", "prior_total", "revised_total",
    "contract_id", "po_number", "term_start", "term_end",
    "department", "fund", "funding_source_text", "procurement_method",
)
# BAR-only diagnostics, always written when parsed (never merged into an
# existing column, so they cannot corrupt a minutes-derived field).
BAR_ONLY = (
    "amount_bar", "amount_bar_kind", "amount_bar_section",
    "bar_prior_total", "bar_revised_total",
    "bar_change_orders", "vendor_raw_bar", "co_vendors_raw_bar",
    "vendor_bar_slice", "bar_lead_staff",
    "rfp_number", "bid_number", "bar_title",
)


# ---------------------------------------------------------------------------
# io
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
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    os.replace(tmp, path)


def build_text_index(out_root=ROOT):
    """doc_id -> text path, from text/<era>/<date>/*.textmeta.json."""
    idx = {}
    root = os.path.join(out_root, "text")
    if not os.path.isdir(root):
        return idx
    for era in sorted(os.listdir(root)):
        era_dir = os.path.join(root, era)
        if not os.path.isdir(era_dir):
            continue
        for d in os.listdir(era_dir):
            date_dir = os.path.join(era_dir, d)
            if not os.path.isdir(date_dir):
                continue
            for name in os.listdir(date_dir):
                if not name.endswith(".textmeta.json"):
                    continue
                stem = name[: -len(".textmeta.json")]
                txt = os.path.join(date_dir, stem + ".txt")
                try:
                    with open(os.path.join(date_dir, name), encoding="utf-8") as fh:
                        meta = json.load(fh)
                except Exception:  # noqa: BLE001
                    continue
                doc_id = meta.get("doc_id")
                if doc_id and os.path.isfile(txt):
                    idx[doc_id] = txt
    return idx


def _d(s):
    """'YYYY-MM-DD' -> date, tolerantly."""
    if not s:
        return None
    try:
        y, m, dd = str(s)[:10].split("-")
        return date(int(y), int(m), int(dd))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# text / money helpers
# ---------------------------------------------------------------------------

# The tabular BAR layouts put a run of spaces between "$" and the figure
# ("Contract Amount        $      2,949,980"), so allow a same-line gap.
MONEY = r"\$[ \t]{0,10}(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
_MULT_RE = re.compile(r"\s*(million|billion|thousand)\b", re.I)
_MULTS = {"thousand": 1e3, "million": 1e6, "billion": 1e9}


def parse_money(s):
    if s is None:
        return None
    try:
        return float(str(s).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


_MONEY_RUN_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def money_at(text, start):
    """Value of the money figure whose digits begin at `start`, or None when
    the printed run is malformed.

    A ``MONEY`` match only consumes a *well-grouped* prefix, so the two source
    typos in the corpus silently truncate by three orders of magnitude:
    ``$5,500250,000`` (a missing comma) matched as 5,500, and ``$3,700.000``
    (a period for the second comma) as 3,700 -- both against contracts in the
    millions. So re-read the whole ``[0-9,.]`` run at that position and run
    E1's ``well_formed_money`` over it, plus a "money has at most two
    decimals" rule that ``well_formed_money`` does not cover because it splits
    the fraction off first. A malformed run is *rejected*, never truncated:
    the figure goes to the LLM fallback instead of poisoning the row."""
    m = _MONEY_RUN_RE.match(text, start)
    if not m:
        return None
    run = m.group(0).rstrip(",.")
    if not run or not well_formed_money(run):
        return None
    if "." in run and len(run.split(".", 1)[1]) > 2:
        return None
    try:
        return float(run.replace(",", ""))
    except ValueError:
        return None


def _scaled(text, end, val):
    """"$7.5 million" -> 7_500_000. Same guard as extract.py: a mantissa that
    is already >= 1000 is taken at face value (source typos like
    "$4,352,000 million")."""
    m = _MULT_RE.match(text, end)
    if m and val is not None and val < 1000:
        return val * _MULTS[m.group(1).lower()]
    return val


def norm_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def page_of(text, pos):
    """1-based page number of a character offset in a form-feed-paged text."""
    return text.count("\f", 0, pos) + 1


def first_pages(text, n=MAX_BAR_PAGES):
    return "\f".join((text or "").split("\f")[:n])


def amount_printed(text, value):
    """E1-style check: the figure really is printed in the source text.
    Accepts the comma-grouped and bare forms, with or without cents."""
    if value is None:
        return False
    iv = int(round(value))
    forms = {f"{iv:,}", str(iv), f"{iv:,}.00", f"{value:,.2f}"}
    if abs(value - iv) > 1e-9:
        forms.add(f"{value:,.2f}")
        forms.add(f"{value:.2f}")
    squash = re.sub(r"\s+", "", text)
    return any(re.sub(r"\s+", "", f) in squash for f in forms)


# ---------------------------------------------------------------------------
# BAR section parsing
# ---------------------------------------------------------------------------

# "1.  TITLE", "I.  TITLE", "   5.   FISCAL IMPACT/REVENUE SOURCE"
_SECTION_RE = re.compile(
    r"^[ \t]*(?:(\d{1,2})|([IVX]{1,5}))[ \t]*[.):][ \t]+([A-Z][A-Z0-9 /&'\-.,()]{3,60})[ \t]*$",
    re.M)
_FOR_DATE_RE = re.compile(
    r"For\s+(Introduction|Action)\s*:?\s*([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}


def parse_us_date(s):
    m = re.match(r"\s*([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", s or "")
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).lower()[:20])
    if mon is None:
        for k, v in _MONTHS.items():
            if k.startswith(m.group(1).lower()[:3]):
                mon = v
                break
    if mon is None:
        return None
    try:
        return date(int(m.group(3)), mon, int(m.group(2)))
    except ValueError:
        return None


def bar_sections(text):
    """[(name, start, end)] over the numbered/roman section headings."""
    heads = [(m.start(), norm_ws(m.group(3)).upper()) for m in _SECTION_RE.finditer(text)]
    out = []
    for i, (pos, name) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        out.append((name, pos, end))
    return out


def section_body(sections, text, *needles):
    for name, start, end in sections:
        if any(n in name for n in needles):
            body_start = text.index("\n", start) + 1 if "\n" in text[start:] else start
            return text[body_start:end], body_start, end
    return None, None, None


class Bar:
    """A parsed Board Action Report (first MAX_BAR_PAGES pages only)."""

    def __init__(self, doc, text):
        self.doc = doc
        self.doc_id = doc.get("doc_id")
        self.meeting_id = doc.get("meeting_id")
        self.meeting_date = _d(doc.get("meeting_date"))
        self.filename = doc.get("resolved_filename") or doc.get("filename") or ""
        self.filename_date = _d(doc.get("filename_date"))
        self.item_code = doc.get("item_code") or _code_from_filename(self.filename)
        self.text = first_pages(text)
        self.sections = bar_sections(self.text)
        self.title = _bar_title(self.text, self.sections)
        self.page1 = self.text.split("\f")[0]
        self.intro_date, self.action_date = _bar_header_dates(self.text)
        self.tokens = title_tokens(self.title)
        self.slug = slug(self.title)


def _code_from_filename(name):
    m = re.match(r"^\s*([A-Z]{1,3}\d{1,2})[_\- ]", name or "")
    return m.group(1) if m else None


def _bar_header_dates(text):
    intro = action = None
    for m in _FOR_DATE_RE.finditer(text[:6000]):
        dt = parse_us_date(m.group(2))
        if dt is None:
            continue
        if m.group(1).lower().startswith("intro") and intro is None:
            intro = dt
        elif m.group(1).lower().startswith("act") and action is None:
            action = dt
    return intro, action


def _bar_title(text, sections):
    body, _, _ = section_body(sections, text, "TITLE")
    if body is None:
        return None
    # pdftotext interleaves the right-hand "For Introduction / For Action"
    # column into the title block in the 2016-17 layout; strip it.
    body = _FOR_DATE_RE.sub(" ", body)
    body = re.sub(r"For\s+(Introduction|Action)\s*:?", " ", body, flags=re.I)
    return norm_ws(body)[:400] or None


# ---------------------------------------------------------------------------
# title similarity
# ---------------------------------------------------------------------------

_STOP = {
    "the", "a", "an", "of", "for", "and", "to", "with", "in", "on", "at", "by",
    "from", "as", "is", "be", "will", "would", "this", "that", "or", "no",
    "approval", "approve", "approved", "authorize", "authorizing", "adoption",
    "adopt", "board", "school", "schools", "district", "seattle", "public",
    "superintendent", "directors", "item", "action", "report", "motion",
    "introduction", "introduces", "recommendation", "resolution", "contract",
    "contracts", "agreement", "agreements", "amendment", "amendments",
    "change", "order", "orders", "renewal", "final", "acceptance", "accept",
    "purchase", "award", "awarding", "execute", "amount", "total", "project",
    "not", "exceed", "revised", "consent", "would", "shall", "per", "new",
}
_WORD_RE = re.compile(r"[a-z0-9]+")


def title_tokens(s):
    if not s:
        return set()
    toks = _WORD_RE.findall(s.lower())
    return {t for t in toks if t not in _STOP and len(t) > 1}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


# ---------------------------------------------------------------------------
# linking
# ---------------------------------------------------------------------------

def _code_num(code):
    m = re.search(r"(\d{1,2})$", code or "")
    return int(m.group(1)) if m else None


# District contract identifiers: P5059, K5069, P1454, B11538. Four or five
# digits, so "K-5" and "P223" cannot match.
_ID_TOKEN_RE = re.compile(r"\b([A-Z]{1,2}\d{4,5})\b")
MIN_LINK_JACCARD = 0.15
MIN_LINK_CONTAINMENT = 0.30


def _ids(text):
    return set(_ID_TOKEN_RE.findall(text or ""))


def _id_conflict(row_ids, bar):
    """True when the row names contract identifiers and the BAR names some
    too, but they share none. Seen in the wild: a meeting's item codes are
    off by one and ``item_code_exact`` links the P5059 closeout to the P5058
    BAR, which then donates the wrong final amount."""
    if not row_ids:
        return False
    bar_ids = _ids(bar.text)
    return bool(bar_ids) and not (row_ids & bar_ids)


def _title_agrees(rtok, bar):
    """Weak floor applied to the identifier-based tiers: a code match with no
    lexical overlap at all is a numbering coincidence, not the same item."""
    if not rtok or not bar.tokens:
        return True
    return (jaccard(rtok, bar.tokens) >= MIN_LINK_JACCARD
            or containment(rtok, bar.tokens) >= MIN_LINK_CONTAINMENT)


def _same_meeting_dates(row_date, bar):
    """Does this BAR's own dating point at the row's meeting?"""
    return row_date in {bar.filename_date, bar.intro_date, bar.action_date,
                        bar.meeting_date}


def link_row(row, bars_by_date, dates_sorted):
    """-> (bar, method, confidence, reason_when_unlinked)."""
    rd = _d(row.get("meeting_date"))
    if rd is None:
        return None, None, None, "row_has_no_date"
    cands = []
    for bd in dates_sorted:
        gap = (rd - bd).days
        if gap < 0:
            break
        if gap <= MAX_BAR_GAP_DAYS:
            cands.extend(bars_by_date[bd])
    # BARs from anywhere whose own header names this meeting date.
    for bd in dates_sorted:
        if abs((rd - bd).days) > MAX_BAR_GAP_DAYS:
            continue
        for b in bars_by_date[bd]:
            if b not in cands and rd in (b.intro_date, b.action_date):
                cands.append(b)
    if not cands:
        return None, None, None, "no_candidate_bars"

    rcode, rnum = row.get("item_code"), _code_num(row.get("item_code"))
    rtok = title_tokens(row.get("title"))
    rslug = slug(row.get("title"))
    rmid = row.get("meeting_id")

    # veto: never link across disagreeing contract identifiers
    row_ids = _ids("%s %s %s" % (row.get("title") or "", row.get("item_text") or "",
                                 row.get("contract_id") or ""))
    kept = [b for b in cands if not _id_conflict(row_ids, b)]
    if not kept:
        return None, None, None, "contract_id_conflict"
    cands = kept

    # tier 1 -- same meeting, same code
    t1 = [b for b in cands
          if rcode and b.item_code == rcode and b.meeting_id == rmid
          and _title_agrees(rtok, b)]
    if len(t1) == 1:
        return t1[0], "item_code_exact", 0.97, None
    if len(t1) > 1:
        t1 = _break_tie_on_title(t1, rtok)
        if len(t1) == 1:
            return t1[0], "item_code_exact", 0.95, None

    # tier 2 -- same code number, different letter, dated at this meeting
    if rnum is not None:
        t2 = [b for b in cands
              if _code_num(b.item_code) == rnum
              and (b.meeting_id == rmid or _same_meeting_dates(rd, b))
              and _title_agrees(rtok, b)]
        if len(t2) == 1:
            return t2[0], "item_code_number", 0.90, None
        if len(t2) > 1:
            t2b = _break_tie_on_title(t2, rtok)
            if len(t2b) == 1:
                return t2b[0], "item_code_number", 0.88, None

    # tiers 3-5 -- title
    scored = sorted(((jaccard(rtok, b.tokens), b) for b in cands),
                    key=lambda x: -x[0])
    if scored and scored[0][0] >= MIN_JACCARD:
        best, second = scored[0], (scored[1] if len(scored) > 1 else (0.0, None))
        if best[0] - second[0] >= 0.02:
            return best[1], "title_jaccard", min(0.95, 0.5 + best[0] / 2), None
        return None, None, None, "ambiguous_title_jaccard"

    cs = sorted(((containment(rtok, b.tokens), b) for b in cands), key=lambda x: -x[0])
    strong = [(c, b) for c, b in cs
              if c >= MIN_CONTAINMENT and len(rtok & b.tokens) >= MIN_SHARED_TOKENS]
    if len(strong) == 1:
        return strong[0][1], "title_containment", 0.80, None
    if len(strong) > 1:
        # keep the one with the most shared tokens if it is a clear winner
        strong.sort(key=lambda x: -len(rtok & x[1].tokens))
        if len(rtok & strong[0][1].tokens) > len(rtok & strong[1][1].tokens):
            return strong[0][1], "title_containment", 0.78, None
        return None, None, None, "ambiguous_title_containment"

    if len(rslug) >= SLUG_PREFIX:
        pref = [b for b in cands if b.slug[:SLUG_PREFIX] == rslug[:SLUG_PREFIX]]
        if len(pref) == 1:
            return pref[0], "title_slug", 0.80, None
        if len(pref) > 1:
            return None, None, None, "ambiguous_title_slug"

    # tier 6 -- identifiers / vendor on the BAR's first page
    ident = [v for v in (row.get("contract_id"), row.get("po_number")) if v]
    if ident:
        hits = [b for b in cands
                if all(re.search(r"\b%s\b" % re.escape(str(v)), b.page1, re.I)
                       for v in ident)]
        if len(hits) == 1:
            return hits[0], "vendor_contract", 0.75, None
        if len(hits) > 1:
            hits2 = _break_tie_on_title(hits, rtok)
            if len(hits2) == 1:
                return hits2[0], "vendor_contract", 0.72, None
            return None, None, None, "ambiguous_contract_id"
    vr = norm_ws(row.get("vendor_raw"))
    if vr and len(vr) >= 5:
        hits = [b for b in cands
                if norm_ws(b.page1).lower().find(vr.lower()) >= 0
                and containment(rtok, b.tokens) >= 0.3]
        if len(hits) == 1:
            return hits[0], "vendor_contract", 0.70, None
        if len(hits) > 1:
            return None, None, None, "ambiguous_vendor"

    return None, None, None, "no_match"


def _break_tie_on_title(bars, rtok):
    scored = sorted(((jaccard(rtok, b.tokens), b) for b in bars), key=lambda x: -x[0])
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.05:
        return bars
    return [scored[0][1]]


# ---------------------------------------------------------------------------
# BAR field extraction
# ---------------------------------------------------------------------------

_MONEY_NEGATIVE = re.compile(
    r"state funding assistance|does not represent a specific expenditure|"
    r"savings|forfeit|project budget|budgeted at|is budgeted|"
    r"total project (?:budget|cost)|program contingency|"
    r"retainage|retention|per (?:student|unit|hour|square foot|sq)|"
    r"threshold|policy no|exceed(?:s|ing)? \$250,000|previously (?:established|approved)|"
    r"revenue source for|budget is funded|is funded from|"
    # hypotheticals and net positions, not contract values: "Scenario 1 ...
    # showing expenditures exceeding revenue by $1.44 million"
    r"\bscenario\b|exceeding revenue|net (?:shortfall|deficit)",
    re.I)

# (name, amount_kind, regex, guarded).  First match in this order wins.
# ``guarded`` = apply _MONEY_NEGATIVE to the surrounding sentence.  The
# closeout-table patterns are deliberately *unguarded*: their label already
# pins the meaning of the number, and the line right below them is always
# "Project Retention ...", which would trip the guard's retainage clause.
# Closeout-table patterns, tried before anything else and only in the
# fiscal-impact section.  Unguarded: their label already pins the meaning
# of the number, and the line right below is always "Project Retention",
# which would trip the guard's retainage clause.
FINAL_PATTERNS = [
    ("final_total_wsst", "final", re.compile(
        r"Total\s+Contract\s+(?:Amount\s+)?(?:includ\w*|incl\.?|with)\s+"
        r"(?:WSST|Washington\s+State\s+Sales\s+Tax|Sales\s+Tax|sales\s+tax|tax)\s*[:.]?\s*" + MONEY,
        re.I), False),
    ("final_contract_amount", "final", re.compile(
        r"Final\s+Contract\s+(?:Amount|Value)\s*[:.]?\s*" + MONEY, re.I), False),
    ("final_total_contract_line", "final", re.compile(
        r"(?:^|\n)[ \t]*Total\s+Contract(?:\s+Amount)?\s*[:.]?[ \t]*" + MONEY, re.I), False),
]

AMOUNT_PATTERNS = [
    ("fiscal_not_exceed", "not_to_exceed", re.compile(
        r"[Ff]iscal\s+impact\s+(?:to|of)\s+this\s+\w+\s+will\s+not\s+exceed\s+" + MONEY), True),
    ("fiscal_impact", "total", re.compile(
        r"[Ff]iscal\s+impact\s+(?:to|of)\s+th(?:is|e)\s+(?:action|BAR|motion|item|contract)\s+"
        r"(?:will|would|is)\s+(?:be\s+)?(?:up\s+to\s+)?(?:an?\s+)?(?:additional\s+)?"
        r"(?:approximately\s+)?" + MONEY), True),
    ("the_fiscal_impact_is", "total", re.compile(
        r"[Tt]he\s+fiscal\s+impact\s+of\s+this\s+\w+\s+(?:will\s+be|is)\s+"
        r"(?:up\s+to\s+)?(?:an?\s+)?(?:additional\s+)?(?:approximately\s+)?" + MONEY), True),
    ("not_to_exceed", "not_to_exceed", re.compile(
        r"(?:will\s+)?not\s+to\s+exceed\s+(?:a\s+total\s+of\s+)?" + MONEY, re.I), True),
    ("total_contract_amount", "revised_total", re.compile(
        r"(?:for\s+a\s+)?total\s+contract\s+(?:amount|value)\s+(?:is|of|will\s+be|would\s+be)?\s*"
        + MONEY, re.I), True),
    ("estimated_total_cost", "total", re.compile(
        r"(?:estimated\s+)?total\s+cost\s+(?:of\s+(?:the|this)\s+\w+\s+)?(?:is|will\s+be)\s+"
        + MONEY, re.I), True),
    ("annual", "annual", re.compile(
        r"annual(?:ly)?\s+(?:cost|amount|fee|payment)\s+of\s+" + MONEY, re.I), True),
    ("in_the_amount_of", "total", re.compile(
        r"in\s+the\s+amount\s+of\s+" + MONEY, re.I), True),
]

# BAR-side kind -> the E1 ``amount_kind`` vocabulary (extract.py:AMOUNT_KINDS,
# which has no "total"; an unqualified contract total is "unspecified" there).
# E1 owns the amount_kind vocabulary and the money well-formedness rule; take
# both from extract.py so this module tracks it (it gained "monthly" in the
# 2026-08-25 rerun). Guarded, because extract.py is another task's file and
# this module must stay importable while it is mid-edit.
try:  # pragma: no cover - exercised only when extract.py is broken
    from .extract import (AMOUNT_KINDS, find_vendor_candidates,
                          split_joint_vendors, well_formed_money,
                          _plausible_vendor)
except Exception:  # noqa: BLE001
    find_vendor_candidates = split_joint_vendors = _plausible_vendor = None
    AMOUNT_KINDS = ("not_to_exceed", "revised_total", "increase", "final",
                    "annual", "monthly", "unspecified")

    def well_formed_money(run):
        """True when every comma group is 3 digits (the first may be 1-3)."""
        body = run.replace("$", "").replace(" ", "").split(".")[0]
        groups = body.split(",")
        if len(groups) == 1:
            return bool(groups[0])
        if not (1 <= len(groups[0]) <= 3):
            return False
        return all(len(g) == 3 for g in groups[1:])
ROW_AMOUNT_KIND = {"final": "final", "not_to_exceed": "not_to_exceed",
                   "annual": "annual", "monthly": "monthly",
                   "revised_total": "revised_total", "total": "unspecified"}

_CLOSEOUT_CONTRACT_AMOUNT = re.compile(
    r"(?:^|\n)[ \t]*Contract\s+Amount\s*[:.]?\s*" + MONEY, re.I)
_CLOSEOUT_ACCEPTED_BID = re.compile(
    r"accepted\s+bid\s+of\s+" + MONEY, re.I)
_CLOSEOUT_CHANGE_ORDERS = re.compile(
    r"(?:^|\n)[ \t]*Change\s+Orders?\s*[:.]?[ \t]*\(?" + MONEY + r"\)?", re.I)
_CHANGE_ORDERS_TOTALED = re.compile(
    r"Change\s+Orders?\s+totale?d?\s+(?:a\s+credit\s+of\s+)?" + MONEY, re.I)
# The 2016-17 closeout layout is a table row:
#   "Total   $568,000   $55,848   $59,889   $683,738   Bonded"
_CLOSEOUT_TABLE_ROW = re.compile(
    r"(?:^|\n)[ \t]*Total[ \t]+" + MONEY + r"[ \t]+" + MONEY + r"[ \t]+" + MONEY +
    r"[ \t]+" + MONEY, re.I)

_CONTRACT_ID_RE = re.compile(
    r"\bContract\s+(?:No\.?\s*|Number\s*|#\s*)?([A-Z]{1,2}\d{3,6})\b")
_PO_RE = re.compile(r"\b(?:P\.?\s?O\.?|Purchase\s+Order)\s*(?:No\.?|#)?\s*(\d{5,12})\b", re.I)
_RFP_RE = re.compile(r"\bRFP\s*(?:No\.?|#)?\s*([A-Z]?\d{3,6})\b", re.I)
_RFQ_RE = re.compile(r"\bRFQ\s*(?:No\.?|#)?\s*([A-Z]?\d{3,6})\b", re.I)
_BID_RE = re.compile(r"\bBid\s*(?:No\.?|#)?\s*([A-Z]?\d{3,6})\b", re.I)

_DATE_TXT = r"([A-Z][a-z]{2,8}\.?\s+\d{1,2},?\s+\d{4})"
TERM_PATTERNS = [
    re.compile(r"term\s+of\s+(?:this|the)\s+(?:contract|agreement|lease|MOU|MOA)\s+"
               r"(?:is\s+)?(?:extended\s+)?(?:from\s+)?" + _DATE_TXT +
               r"\s*(?:to|through|until|-|–)\s*" + _DATE_TXT, re.I),
    re.compile(r"(?:for|covering|during)\s+the\s+period\s+(?:of\s+|from\s+)?" + _DATE_TXT +
               r"\s*,?\s*(?:to|through|until|-|–)\s*" + _DATE_TXT, re.I),
    re.compile(r"effective\s+(?:retroactively\s+)?(?:from\s+)?" + _DATE_TXT +
               r"\s*,?\s*(?:to|through|until|and\s+ending|-|–)\s*" + _DATE_TXT, re.I),
    re.compile(r"commencing\s+(?:on\s+)?" + _DATE_TXT +
               r"\s*,?\s*(?:and\s+ending|to|through|until)\s*" + _DATE_TXT, re.I),
    re.compile(r"beginning\s+(?:on\s+)?" + _DATE_TXT +
               r"\s*,?\s*(?:and\s+)?(?:running\s+)?(?:through|to|until|and\s+ending)\s*"
               + _DATE_TXT, re.I),
]

_REVENUE_SENT = re.compile(
    r"(?:The\s+)?revenue\s+sources?\s+for\s+th(?:is|e)\s+\w+\s+(?:is|are)\s+([^\n]{3,300}?)\.",
    re.I)
_PAYMENTS_SENT = re.compile(
    r"All\s+payments\s+have\s+been\s+made\s+[^.]{0,200}?from\s+(?:the\s+)?([^.]{3,200})\.", re.I)
_REVENUE_SOURCE_IS = re.compile(
    r"(?:The\s+)?revenue\s+source\s+is\s+([^\n]{3,300}?)\.", re.I)
_THIS_ACTION_FUNDED = re.compile(
    r"[Tt]his\s+action\s+(?:is\s+)?funded\s+by\s+(?:the\s+)?([^\n]{3,200}?)\.")

_FUND_RULES = [
    ("BEX", re.compile(r"\bBEX\b|Building\s+Excellence", re.I)),
    ("BTA", re.compile(r"\bBTA\b|Buildings?,?\s+Technology\s+and\s+Academics", re.I)),
    ("grant", re.compile(r"\bgrant\b|Title\s+I\b|federal\s+funds|ESSER|DHHS|"
                         r"OSPI\s+grant|iGrant", re.I)),
    ("capital", re.compile(r"capital\s+(?:levy|projects?|fund)", re.I)),
    ("ASB", re.compile(r"\bASB\b|Associated\s+Student\s+Body", re.I)),
    ("general", re.compile(r"\bGeneral\s+Fund\b|general\s+fund(?:s|ing)?\b", re.I)),
]

_PROC_RULES = [
    ("RFP", re.compile(r"\bRFP\b|[Rr]equest\s+for\s+[Pp]roposals?", re.I)),
    ("RFQ", re.compile(r"\bRFQ\b|[Rr]equest\s+for\s+[Qq]ualifications?", re.I)),
    ("sole source", re.compile(r"\bsole[- ]source\b", re.I)),
    ("bid", re.compile(r"publicly\s+bid|competitive(?:ly)?\s+bid|\bBid\s*(?:No\.?|#)|"
                       r"\blow\s+bid|invitation\s+for\s+bid|\bIFB\b", re.I)),
    ("cooperative purchasing", re.compile(
        r"\bKCDA\b|NASPO|[Ss]tate\s+contract|cooperative\s+purchas|"
        r"purchasing\s+cooperative|\bE&I\b|Omnia", re.I)),
    ("interlocal", re.compile(r"interlocal", re.I)),
]

# "Vendor: X" / "Contractor:  X" only. The unlabelled column form
# ("Contractor            CDK Construction, LLC") was tried and reverted: a
# bare label followed by whitespace also matches a signature block
# ("Contractor   Date  Originator (Principal, Program Manager, etc)"), a
# table header ("VENDOR CONTRACTED VALUE REQUESTED CHANGE NEW TOTAL") and a
# furniture spreadsheet's column row -- 3 of the 5 errors in a 30-row
# hand-check. Closeouts lose nothing: their title names the contractor too.
_VENDOR_LINE = re.compile(
    r"(?:^|\n)[ \t]*(?:Vendor|Contractor|Consultant|Supplier|Provider)"
    r"\s*[:\t]\s*([^\n$]{3,80})", re.I)
# Case-sensitive on the vendor's first letter (it must be a proper noun), so
# the literals spell out both cases rather than using re.I.
_VENDOR_INLINE = re.compile(
    r"[Cc]ontract\s+(?:[A-Z]{1,2}\d{3,6}\s+)?with\s+([A-Z][^,.\n]{2,70}?)"
    r"(?=,\s|\.\s|\s+for\b|\s+in\s+the\b|\n)")
_LEAD_STAFF = re.compile(r"LEAD\s+STAFF\s*:?\s*([^\n]{3,140})", re.I)
_DEPARTMENT_LINE = re.compile(r"(?:^|\n)[ \t]*Department\s*[:\t]\s*([^\n]{3,80})", re.I)


# Where a BAR names its counterparty, most reliable first.  Each slice is fed
# to E1's `find_vendor_candidates`, which owns the vendor walk, the legal
# suffixes, the stopwords, the joint-vendor split and the plausibility rules
# (the district, its departments, committees, course names, "the successful
# bidder" and the like are rejected there, once, for the whole pipeline).
# The fiscal-impact section is deliberately NOT here. It is a money narrative,
# not a naming position, and reading it produced course names ("Physical
# Science" on a chemistry adoption), district acronyms ("DAC"), display
# technologies ("Miracast") and street names. Every position below is one
# where a BAR *names its counterparty*.
VENDOR_SLICES = ("vendor_line", "title", "motion", "purpose")


# Single-token candidates that are document furniture, not counterparties.
# E1's `_believable_single_token` waves almost any capitalised word through
# (rightly -- "Arcadis", "Apple", "BNBuilders" are all real), but a BAR's
# prose sections contain structural nouns the item text does not: "Settlement
# Agreement with Exhibits 1, 2 and 3", "aligned with Chapter 392-400 of the
# WAC", "Case No. 15-2-12565-6 SEA".
_BAR_VENDOR_STOP_1TOK = {
    "chapter", "exhibit", "exhibits", "section", "sections", "attachment",
    "attachments", "appendix", "addendum", "amendment", "amendments",
    "resolution", "policy", "procedure", "settlement", "agreement",
    "plaintiff", "defendant", "respondent", "petitioner", "counsel",
    "staff", "students", "student", "teachers", "families", "parents",
}


# A name ending in a street type is an address, not a counterparty
# ("...the intersection of Henderson Street and Seward Avenue").
_STREET_TAIL_RE = re.compile(
    r"\b(street|st|avenue|ave|road|rd|way|boulevard|blvd|drive|dr|place|pl|"
    r"court|ct|lane|ln|parkway|pkwy|highway|hwy)\.?$", re.I)
# Solicitation numbers, not vendors ("RFP No.06792 with XXXX").
_SOLICITATION_HEAD_RE = re.compile(
    r"^(rf[pqi]|ifb|bid|po|purchase\s+order|contract)\b\s*(no\.?|#)?\s*[\w-]*$", re.I)
# Redaction placeholders left in the source ("with XXXX Dell/Thornburg").
_REDACTION_TOKEN_RE = re.compile(r"^x{2,}$", re.I)
# Fill-in-the-blank tails on a signature-ready motion:
# "with Ray and Associates(_____________) in the amount of $35,500".
_BLANK_TAIL_RE = re.compile(r"\s*\(?_{2,}\)?\s*$")
# A vendor never *starts* with an infinitive: "…Contract to Expand the Fresh
# Fruit and Vegetable Program" is a purpose clause, not a counterparty.
_LEADING_VERBS = {
    "expand", "provide", "support", "purchase", "extend", "continue",
    "establish", "implement", "develop", "deliver", "operate", "conduct",
    "perform", "increase", "reduce", "replace", "install", "construct",
    "renew", "amend", "modify", "fund", "cover", "allow", "enable",
}


def _clean_bar_vendor(v):
    """Drop a leading redaction placeholder and a trailing form blank. Both
    leave a string that is still a verbatim substring of the BAR, so the
    merge-time check still holds."""
    v = _BLANK_TAIL_RE.sub("", v or "")
    toks = v.split()
    while toks and _REDACTION_TOKEN_RE.match(toks[0].strip(" ,.")):
        toks = toks[1:]
    return " ".join(toks)


def _bar_vendor_ok(v, slice_text=None, pos=None):
    """A bar_fill-local gate on top of E1's plausibility, for the shapes only
    a BAR's prose and tables produce."""
    if not v:
        return False
    stripped = v.strip(" ,.;:")
    if _SOLICITATION_HEAD_RE.match(stripped):
        return False
    if _STREET_TAIL_RE.search(stripped):
        return False
    toks = v.split()
    if toks[0].strip(" ,.").lower() in _LEADING_VERBS:
        return False
    if len(toks) == 1:
        bare = toks[0].strip(" ,.;:\u2019'").lower()
        if bare in _BAR_VENDOR_STOP_1TOK:
            return False
        if ")" in toks[0] or "(" in toks[0]:      # "…Case No. …-6 SEA)"
            return False
        # A lone mixed-case token followed by ", Capitalised" is E1's comma
        # rule truncating a longer name ("Hazard, Young, Attea & Associates"
        # -> "Hazard"). Better null than a name that will never match itself
        # elsewhere in the corpus. All-caps acronyms (KCDA, DELL, EPI-USE) are
        # genuinely one token, so they are exempt.
        if slice_text is not None and pos is not None and not toks[0].isupper():
            tail = slice_text[pos + len(v): pos + len(v) + 4]
            if re.match(r",\s+[A-Z][a-z]", tail):
                return False
    return True


def bar_vendor(bar, fiscal):
    """-> (vendor_raw, co_vendors_raw, slice_name) or (None, [], None).

    The minutes leave `vendor_raw` null on ~20% of post-2016 rows -- a consent
    motion often says only "Approval of the contract as attached to the Board
    Action Report".  The BAR always names the counterparty, in one of the
    positions in VENDOR_SLICES.  Returned verbatim (whitespace-normalised, the
    same standard extract.validate uses), so the string can be checked back
    against the BAR text.
    """
    if find_vendor_candidates is None:      # extract.py mid-edit
        return _legacy_bar_vendor(bar, fiscal)

    # Whitespace-normalised: BAR sections are raw wrapped PDF lines, and E1's
    # vendor walk stops at a newline. "...contract P5127 for the project with
    # Slate\nConstruction, Inc." otherwise yields the vendor "Slate" -- 27 of
    # the first 107 fills were single-token truncations of exactly this shape.
    slices = {
        "vendor_line": None,                # handled below, it is not a walk
        "title": norm_ws(bar.title or ""),
        "motion": norm_ws(_motion_text(bar)[0] or ""),
        "purpose": norm_ws(section_body(bar.sections, bar.text, "PURPOSE")[0] or ""),
    }

    for name in VENDOR_SLICES:
        if name == "vendor_line":
            m = _VENDOR_LINE.search(fiscal) or _VENDOR_LINE.search(bar.text)
            if not m:
                continue
            # A labelled line is already just the name: split joint vendors,
            # then apply the same plausibility gate as a walked candidate.
            primary, co = split_joint_vendors(norm_ws(m.group(1)).rstrip(" ,;"))
            if primary and _plausible_vendor(primary) and _bar_vendor_ok(primary):
                return primary, [c for c in co if _plausible_vendor(c)], name
            continue
        text = slices[name]
        for _pat, primary, co, pos in find_vendor_candidates(text):
            cleaned = _clean_bar_vendor(primary)
            if (cleaned and _plausible_vendor(cleaned)
                    and _bar_vendor_ok(cleaned, text, text.find(primary))):
                return cleaned, [c for c in co if _bar_vendor_ok(c)], name
    return None, [], None


def _legacy_bar_vendor(bar, fiscal):
    """Fallback used only when extract.py cannot be imported."""
    m = _VENDOR_LINE.search(fiscal) or _VENDOR_LINE.search(bar.text)
    if m is None:
        for hay in (fiscal, _motion_text(bar)[0] or "", bar.title or ""):
            m = _VENDOR_INLINE.search(hay)
            if m:
                break
    if m:
        return norm_ws(m.group(1)).rstrip(" ,;"), [], "legacy"
    return None, [], None


def _sentence_around(text, pos, width=240):
    """The sentence a match sits in, capped at ``width`` characters either
    side so a table with no full stops in it cannot drag in half a page."""
    floor = max(0, pos - width)
    lo = max(text.rfind(".", floor, pos), text.rfind("\n\n", floor, pos), floor)
    hi = text.find(".", pos, pos + width)
    hi = min(len(text), pos + width) if hi < 0 else hi + 1
    return text[lo:hi]


def _fiscal_text(bar):
    body, start, end = section_body(bar.sections, bar.text, "FISCAL")
    if body is None:
        return bar.text, 0
    return body, start


MOTION_WINDOW = 1500


def _motion_text(bar):
    """The RECOMMENDED MOTION section, trimmed to the motion sentence itself.

    The section body often runs on into background prose ("...was approved by
    the School Board in September 2014 in the amount of $28,340,330..."), so
    anchor on "I move" and keep one paragraph."""
    body, start, end = section_body(bar.sections, bar.text, "RECOMMENDED MOTION", "MOTION")
    if body is None:
        return None, 0
    m = re.search(r"I\s+move\b", body)
    if m:
        body, start = body[m.start():], start + m.start()
    para = re.search(r"\n[ \t]*\n", body[200:])
    if para:
        body = body[: 200 + para.start()]
    return body[:MOTION_WINDOW], start


# Patterns whose phrasing is generic enough that two different figures in one
# region means we cannot tell which one is the board action's amount (a
# seven-vendor furniture motion lists seven "in the amount of $X").
UNIQUE_REQUIRED = {"in_the_amount_of"}


def _closeout_amount(fiscal, out):
    """The final-acceptance closeout total, from the labelled line or from the
    tabular layout ("Total  $2,473,651  $242,810  $260,780.25  $2,977,241.25").
    Tried *before* the prose patterns: several closeout BARs open their fiscal
    section with the project's levy budget ("...funded from BEX IV Capital
    Levy funds in the amount of $11,412,082"), which is four times the
    contract and must never win over the table below it."""
    for _name, kind, rx, _guarded in FINAL_PATTERNS:
        m = rx.search(fiscal)
        if m:
            v = _scaled(fiscal, m.end(), money_at(fiscal, m.start(1)))
            if v is not None and MIN_AMOUNT <= v <= AMOUNT_CEILING:
                return v, kind, m.start()
    m = _CLOSEOUT_TABLE_ROW.search(fiscal)
    if m:
        v = money_at(fiscal, m.start(4))
        if v is not None and MIN_AMOUNT <= v <= AMOUNT_CEILING:
            out["bar_prior_total"] = out["bar_prior_total"] or money_at(fiscal, m.start(1))
            out["bar_change_orders"] = (out["bar_change_orders"]
                                        or money_at(fiscal, m.start(2)))
            return v, "final", m.start()
    return None, None, None


def _find_amount(text):
    """-> (value, kind, offset) for the first AMOUNT_PATTERNS hit, else
    (None, None, None)."""
    for name, kind, rx, guarded in AMOUNT_PATTERNS:
        hits = []
        for mm in rx.finditer(text):
            if guarded and _MONEY_NEGATIVE.search(_sentence_around(text, mm.start())):
                continue
            v = _scaled(text, mm.end(), money_at(text, mm.start(1)))
            if v is None or v < MIN_AMOUNT or v > AMOUNT_CEILING:
                continue
            hits.append((v, mm.start()))
            if name not in UNIQUE_REQUIRED:
                break
        if not hits:
            continue
        if name in UNIQUE_REQUIRED and len({v for v, _ in hits}) > 1:
            continue
        return hits[0][0], kind, hits[0][1]
    return None, None, None


def parse_bar(bar, action_type=None):
    """-> dict of BAR-derived fields (+ ``_pages`` for the citation)."""
    text = bar.text
    fiscal, fiscal_off = _fiscal_text(bar)
    out = {k: None for k in FILLABLE + BAR_ONLY}
    pages = set()

    def note_page(pos_in_full):
        pages.add(page_of(text, pos_in_full))

    out["bar_title"] = bar.title

    # ---- closeout table -------------------------------------------------
    m = _CLOSEOUT_CONTRACT_AMOUNT.search(fiscal) or _CLOSEOUT_ACCEPTED_BID.search(fiscal)
    if m:
        v = _scaled(fiscal, m.end(), money_at(fiscal, m.start(1)))
        if v and v >= MIN_AMOUNT:
            out["bar_prior_total"] = v
            note_page(fiscal_off + m.start())
    m = _CHANGE_ORDERS_TOTALED.search(fiscal) or _CLOSEOUT_CHANGE_ORDERS.search(fiscal)
    if m:
        out["bar_change_orders"] = _scaled(fiscal, m.end(), money_at(fiscal, m.start(1)))

    # ---- amount ---------------------------------------------------------
    # The fiscal-impact section is the authority.  When it carries no figure
    # at all (the 2017-era capital BARs put only the *project budget* there),
    # fall back to the BAR's own RECOMMENDED MOTION -- the same sentence the
    # minutes quote, so it is the right number by construction.
    amount_page = None
    excerpt = None
    amount, kind, pos = _closeout_amount(fiscal, out)
    region = "fiscal" if amount is not None else None
    if amount is not None:
        amount_page = page_of(text, fiscal_off + pos)
        excerpt = norm_ws(_sentence_around(fiscal, pos, 260))
        note_page(fiscal_off + pos)
    else:
        for region_name, (rtext, roff) in (("fiscal", (fiscal, fiscal_off)),
                                           ("motion", _motion_text(bar))):
            if not rtext:
                continue
            amount, kind, pos = _find_amount(rtext)
            if amount is not None:
                region = region_name
                amount_page = page_of(text, roff + pos)
                excerpt = norm_ws(_sentence_around(rtext, pos, 260))
                note_page(roff + pos)
                break
    if amount is not None:
        out["amount_bar"] = amount
        out["amount_bar_kind"] = kind
        out["amount_bar_section"] = region
        out["_amount_excerpt"] = excerpt
        if kind == "final":
            out["bar_revised_total"] = amount

    # ---- identifiers ----------------------------------------------------
    for fld, rx in (("contract_id", _CONTRACT_ID_RE), ("po_number", _PO_RE),
                    ("rfp_number", _RFP_RE), ("bid_number", _BID_RE)):
        m = rx.search(text)
        if m:
            out[fld] = m.group(1)
            note_page(m.start())
    if out["rfp_number"] is None:
        m = _RFQ_RE.search(text)
        if m:
            out["rfp_number"] = "RFQ " + m.group(1)

    # ---- term -----------------------------------------------------------
    for rx in TERM_PATTERNS:
        m = rx.search(norm_ws(text))
        if m:
            out["term_start"] = norm_ws(m.group(1)).rstrip(",")
            out["term_end"] = norm_ws(m.group(2)).rstrip(".,")
            break

    # ---- funding --------------------------------------------------------
    src = None
    for rx in (_REVENUE_SENT, _PAYMENTS_SENT, _REVENUE_SOURCE_IS, _THIS_ACTION_FUNDED):
        m = rx.search(fiscal)
        if m:
            cand = norm_ws(m.group(1))
            if cand and not re.fullmatch(r"(N/?A|not applicable|_+|\(?not applicable\)?|TBD)\.?",
                                         cand, re.I):
                src = cand[:300]
                note_page(fiscal_off + m.start())
                break
    if src:
        out["funding_source_text"] = src
        for label, rx in _FUND_RULES:
            if rx.search(src):
                out["fund"] = label
                break
    if out["fund"] is None:
        for label, rx in _FUND_RULES[:2]:  # BEX/BTA are unambiguous anywhere
            if rx.search(fiscal):
                out["fund"] = label
                break

    # ---- procurement ----------------------------------------------------
    for label, rx in _PROC_RULES:
        if rx.search(text):
            out["procurement_method"] = label
            break

    # ---- department / lead staff ---------------------------------------
    m = _DEPARTMENT_LINE.search(text)
    if m:
        out["department"] = norm_ws(m.group(1))
    m = _LEAD_STAFF.search(text)
    if m:
        out["bar_lead_staff"] = norm_ws(m.group(1))[:140]

    # ---- vendor ---------------------------------------------------------
    vendor, co_vendors, vslice = bar_vendor(bar, fiscal)
    if vendor:
        out["vendor_raw_bar"] = vendor
        out["vendor_bar_slice"] = vslice
        out["co_vendors_raw_bar"] = co_vendors or None
    # The citation should open on the page carrying the money, since that is
    # the field a QA sampler checks first; the range still spans every page a
    # filled field came from.
    ordered = sorted(pages) or [1]
    out["_pages"] = [amount_page or ordered[0],
                     max(ordered + ([amount_page] if amount_page else []))]
    return out


# ---------------------------------------------------------------------------
# merge
# ---------------------------------------------------------------------------

def merge_row(row, bar, parsed, method, confidence):
    """Mutates and returns ``row``; -> (filled_fields, notes)."""
    filled, notes = [], []
    distrust_money = False
    row["bar_doc_id"] = bar.doc_id
    row["bar_match_method"] = method
    row["bar_match_confidence"] = confidence
    pages = parsed.get("_pages") or [1]
    row["bar_citation"] = {"doc_id": bar.doc_id,
                           "page_start": pages[0], "page_end": pages[-1]}
    for f in BAR_ONLY:
        if parsed.get(f) is not None:
            row[f] = parsed[f]

    # amount: the one field with a conflict rule
    bar_amount = parsed.get("amount_bar")
    row_amount = row.get("amount")
    if row_amount is not None:
        row.setdefault("amount_source", "minutes")
        if row.get("amount_source") is None:
            row["amount_source"] = "minutes"
        # Not a conflict when the BAR figure is the same contract seen from a
        # different angle: an amendment row whose `amount` is the increment
        # and whose `revised_total` is what the BAR's fiscal section states.
        same_elsewhere = any(
            row.get(f) is not None and not _disagrees(bar_amount, row[f])
            for f in ("prior_total", "revised_total")) if bar_amount is not None else False
        if bar_amount is not None and not same_elsewhere and _disagrees(bar_amount, row_amount):
            if _implausible_ratio(bar_amount, row_amount):
                # Two orders of magnitude apart is not two readings of the same
                # contract, it is a bad parse on one side. Distrust the whole
                # BAR parse for the money fields: prior_total/revised_total
                # come from the same sentences.
                notes.append("bar_amount_implausible_vs_minutes:%s!=%s"
                             % (bar_amount, row_amount))
                distrust_money = True
            else:
                notes.append("bar_amount_conflict:%s!=%s" % (bar_amount, row_amount))
    elif bar_amount is not None:
        if not amount_printed(bar.text, bar_amount):
            notes.append("bar_amount_not_printed")
        elif not (MIN_AMOUNT <= bar_amount <= AMOUNT_CEILING):
            notes.append("bar_amount_out_of_range")
        else:
            row["amount"] = bar_amount
            bk = parsed.get("amount_bar_kind")
            row["amount_kind"] = (
                "final"
                if (row.get("action_type") == "final_acceptance"
                    and bk in ("final", "revised_total", "total"))
                else ROW_AMOUNT_KIND.get(bk, "unspecified"))
            row["amount_source"] = "bar"
            row["amount_kind_source"] = "bar"
            filled += ["amount", "amount_kind"]

    # prior/revised totals
    for row_f, bar_f in (("prior_total", "bar_prior_total"),
                         ("revised_total", "bar_revised_total")):
        if distrust_money:
            break
        if row.get(row_f) is None and parsed.get(bar_f) is not None:
            row[row_f] = parsed[bar_f]
            row[row_f + "_source"] = "bar"
            filled.append(row_f)

    for f in ("contract_id", "po_number", "term_start", "term_end", "department",
              "fund", "funding_source_text", "procurement_method"):
        if row.get(f) is None and parsed.get(f) is not None:
            row[f] = parsed[f]
            row[f + "_source"] = "bar"
            filled.append(f)

    # vendor: only when the minutes left it null, and only when the string is
    # verbatim in the BAR (whitespace-normalised, the same standard
    # extract.validate applies against the item text).
    vb = parsed.get("vendor_raw_bar")
    if row.get("vendor_raw") is None and vb and norm_ws(vb) in norm_ws(bar.text):
        row["vendor_raw"] = vb
        row["vendor_raw_source"] = "bar"
        filled.append("vendor_raw")

    if notes:
        existing = row.get("extractor_notes")
        if existing is None:
            row["extractor_notes"] = notes
        elif isinstance(existing, list):
            row["extractor_notes"] = existing + notes
        else:
            row["extractor_notes"] = [existing] + notes
    return filled, notes


IMPLAUSIBLE_RATIO = 100.0


def _implausible_ratio(a, b):
    """True when two amounts are >= IMPLAUSIBLE_RATIO apart -- one of them is
    a bad parse (a truncated figure, or the wrong line of a fiscal section),
    not a second honest reading of the same contract."""
    try:
        a, b = abs(float(a)), abs(float(b))
    except (TypeError, ValueError):
        return False
    lo, hi = min(a, b), max(a, b)
    return lo > 0 and hi / lo >= IMPLAUSIBLE_RATIO


def _disagrees(a, b):
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if max(abs(a), abs(b)) == 0:
        return False
    return abs(a - b) / max(abs(a), abs(b)) > CONFLICT_TOLERANCE


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def load_bars(out_root, since, text_idx):
    docs = read_jsonl(os.path.join(out_root, "manifest", "documents_classified.jsonl"))
    floor = since - timedelta(days=MAX_BAR_GAP_DAYS) if since else None
    bars = []
    for d in docs:
        if d.get("kind") != "bar":
            continue
        md = _d(d.get("meeting_date"))
        if md is None:
            continue
        if floor and md < floor:
            continue
        path = text_idx.get(d.get("doc_id"))
        if not path:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        bars.append(Bar(d, text))
    return bars


def run(out_root=ROOT, since="2016-08-01", limit=None, report_path=None,
        extracted=None, write_batches=True):
    since_d = _d(since)
    extracted = extracted or os.path.join(out_root, "contracts", "extracted.jsonl")
    rows = read_jsonl(extracted)
    if not rows:
        raise SystemExit("no rows read from %s" % extracted)

    text_idx = build_text_index(out_root)
    bars = load_bars(out_root, since_d, text_idx)
    bars_by_date = defaultdict(list)
    for b in bars:
        bars_by_date[b.meeting_date].append(b)
    dates_sorted = sorted(bars_by_date)

    stats = {
        "n_rows": len(rows), "n_scope": 0, "n_linked": 0,
        "methods": Counter(), "unlinked": Counter(), "filled": Counter(),
        "amount_filled": Counter(), "amount_null_reason": Counter(),
        "conflicts": [], "by_type": defaultdict(Counter), "examples": [],
        "n_bars": len(bars),
    }
    fallback = []
    n_seen = 0
    for row in rows:
        rd = _d(row.get("meeting_date"))
        if since_d and (rd is None or rd < since_d):
            continue
        if limit is not None and n_seen >= limit:
            continue
        n_seen += 1
        stats["n_scope"] += 1
        at = row.get("action_type") or "none"
        had_amount = row.get("amount") is not None
        stats["by_type"][at]["rows"] += 1
        if had_amount:
            stats["by_type"][at]["amount_before"] += 1
            if row.get("amount_source") is None:
                row["amount_source"] = "minutes"

        bar, method, conf, reason = link_row(row, bars_by_date, dates_sorted)
        if bar is None:
            stats["unlinked"][reason or "no_match"] += 1
            stats["by_type"][at]["unlinked"] += 1
            if not had_amount:
                stats["amount_null_reason"]["no_bar_linked"] += 1
            continue

        stats["n_linked"] += 1
        stats["methods"][method] += 1
        stats["by_type"][at]["linked"] += 1
        parsed = parse_bar(bar, row.get("action_type"))
        before = {f: row.get(f) for f in FILLABLE}
        filled, notes = merge_row(row, bar, parsed, method, conf)
        for f in filled:
            stats["filled"][f] += 1
        for n in notes:
            if n.startswith("bar_amount_conflict") or n.startswith(
                    "bar_amount_implausible_vs_minutes"):
                stats["conflicts"].append(_conflict_record(row, bar, parsed, n))
                stats["by_type"][at]["conflict"] += 1

        if not had_amount:
            if row.get("amount") is not None:
                stats["amount_filled"][at] += 1
                stats["by_type"][at]["amount_filled"] += 1
                if len(stats["examples"]) < 15:
                    stats["examples"].append((row, bar, before, parsed))
            else:
                why = ("bar_has_no_figure" if parsed.get("amount_bar") is None
                       else "bar_amount_rejected")
                stats["amount_null_reason"][why] += 1
                stats["by_type"][at][why] += 1
                fallback.append(_batch_row(row, bar, parsed))

    out_path = os.path.join(out_root, "contracts", "extracted_filled.jsonl")
    write_jsonl(out_path, rows)

    n_batches = 0
    if write_batches:
        n_batches = write_fallback_batches(out_root, fallback)

    conflicts_path = os.path.join(out_root, "qa", "bar_conflicts.jsonl")
    write_jsonl(conflicts_path, stats["conflicts"])

    report_path = report_path or os.path.join(out_root, "qa", "bar_fill_report.md")
    text = write_report(report_path, stats, n_batches, since, out_path, extracted)
    print("wrote %s (%d rows), %s and %s"
          % (out_path, len(rows), report_path, conflicts_path))
    print("scope=%d linked=%d (%.1f%%) amount_filled=%d conflicts=%d fallback_rows=%d"
          % (stats["n_scope"], stats["n_linked"],
             100.0 * stats["n_linked"] / max(1, stats["n_scope"]),
             sum(stats["amount_filled"].values()), len(stats["conflicts"]),
             len(fallback)))
    return rows, stats, text


def _conflict_record(row, bar, parsed, note):
    """One `qa/bar_conflicts.jsonl` row: everything the E1 owner needs to
    decide which figure is right without reopening either PDF."""
    cit = row.get("bar_citation") or {}
    return {
        "meeting_id": row.get("meeting_id"),
        "meeting_date": row.get("meeting_date"),
        "item_no": row.get("item_no"),
        "char_start": row.get("char_start"),
        "title": row.get("title"),
        "action_type": row.get("action_type"),
        "amount_minutes": row.get("amount"),
        "amount_minutes_kind": row.get("amount_kind"),
        "prior_total": row.get("prior_total"),
        "revised_total": row.get("revised_total"),
        "amount_bar": parsed.get("amount_bar"),
        "amount_bar_kind": parsed.get("amount_bar_kind"),
        "amount_bar_section": parsed.get("amount_bar_section"),
        "item_text_excerpt": norm_ws(row.get("item_text") or row.get("title") or "")[:600],
        "bar_excerpt": parsed.get("_amount_excerpt"),
        "bar_doc_id": bar.doc_id,
        "bar_filename": bar.filename,
        "bar_page_start": cit.get("page_start"),
        "bar_match_method": row.get("bar_match_method"),
        "bar_match_confidence": row.get("bar_match_confidence"),
        "note": note,
    }


def _batch_row(row, bar, parsed):
    """One LLM-fallback row, same schema as contracts/batches/*.jsonl plus the
    BAR's fiscal-impact text (<= 2 pages)."""
    fiscal, off = _fiscal_text(bar)
    snippet = "\f".join(fiscal.split("\f")[:2])[:6000]
    return {
        "meeting_id": row.get("meeting_id"),
        "meeting_date": row.get("meeting_date"),
        "era": row.get("era"),
        "item_no": row.get("item_no"),
        "char_start": row.get("char_start"),
        "section": row.get("section"),
        "board_action": row.get("board_action"),
        "vote": row.get("vote"),
        "title": row.get("title"),
        "item_text": row.get("item_text"),
        "residual_category": "bar_detail",
        "citation": row.get("citation"),
        "patterns_fired": [],
        "vendor_raw": row.get("vendor_raw"),
        "amount": None,
        "amount_kind": None,
        "action_type": row.get("action_type"),
        "revised_total": row.get("revised_total"),
        "prior_total": row.get("prior_total"),
        "contract_id": row.get("contract_id"),
        "po_number": row.get("po_number"),
        "extractor_notes": [],
        "bar_doc_id": bar.doc_id,
        "bar_title": bar.title,
        "bar_page_start": page_of(bar.text, off),
        "bar_text": snippet,
    }


def write_fallback_batches(out_root, rows):
    d = os.path.join(out_root, "contracts", "bar_batches")
    if os.path.isdir(d):
        for name in os.listdir(d):
            if re.fullmatch(r"\d{3}\.jsonl", name):
                os.remove(os.path.join(d, name))
    if not rows:
        return 0
    os.makedirs(d, exist_ok=True)
    n = 0
    for i in range(0, len(rows), BATCH_SIZE):
        write_jsonl(os.path.join(d, "%03d.jsonl" % n), rows[i:i + BATCH_SIZE])
        n += 1
    return n


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def write_report(path, stats, n_batches, since, out_path, src_path=None):
    L = []
    A = L.append
    A("# BAR detail pass (E3) -- `bar_fill.py`")
    A("")
    A("Scope: rows in `%s` with `meeting_date >= %s`."
      % (src_path or "contracts/extracted.jsonl", since))
    A("Output: `%s`." % out_path)
    A("")
    A("| | |")
    A("|---|---|")
    A("| BARs in the candidate corpus | %d |" % stats["n_bars"])
    A("| rows in scope | %d |" % stats["n_scope"])
    A("| rows linked to a BAR | %d (%.1f%%) |"
      % (stats["n_linked"], 100.0 * stats["n_linked"] / max(1, stats["n_scope"])))
    A("| amounts filled from the BAR | %d |" % sum(stats["amount_filled"].values()))
    A("| amount conflicts (row kept) | %d |" % len(stats["conflicts"]))
    A("| fallback batch files | %d |" % n_batches)
    A("")
    A("## Link method")
    A("")
    A("| method | rows |")
    A("|---|---:|")
    for m, n in stats["methods"].most_common():
        A("| %s | %d |" % (m, n))
    for m, n in stats["unlinked"].most_common():
        A("| _unlinked: %s_ | %d |" % (m, n))
    A("")
    A("## By action_type")
    A("")
    A("| action_type | rows | linked | amount before | amount filled | still null: no BAR / no figure / rejected | conflicts |")
    A("|---|---:|---:|---:|---:|---:|---:|")
    for at in sorted(stats["by_type"]):
        c = stats["by_type"][at]
        still = c["rows"] - c["amount_before"] - c["amount_filled"]
        A("| %s | %d | %d | %d | %d | %d (%d / %d / %d) | %d |"
          % (at, c["rows"], c["linked"], c["amount_before"], c["amount_filled"],
             still, c["unlinked"], c["bar_has_no_figure"], c["bar_amount_rejected"],
             c["conflict"]))
    A("")
    A("## Fields filled (row was null, BAR supplied a value)")
    A("")
    A("| field | rows |")
    A("|---|---:|")
    for f, n in stats["filled"].most_common():
        A("| %s | %d |" % (f, n))
    A("")
    A("## Why an amount is still null")
    A("")
    A("| reason | rows |")
    A("|---|---:|")
    for r, n in stats["amount_null_reason"].most_common():
        A("| %s | %d |" % (r, n))
    A("")
    A("## Examples (before -> after)")
    A("")
    for row, bar, before, parsed in stats["examples"]:
        A("* `%s` %s **%s** -- %s" % (row.get("meeting_date"), row.get("item_no"),
                                      row.get("action_type"), (row.get("title") or "")[:90]))
        A("  * BAR `%s` (%s, conf %.2f): %s"
          % (bar.doc_id, row.get("bar_match_method"),
             row.get("bar_match_confidence") or 0, (bar.filename or "")[:70]))
        A("  * amount: `%s` -> `%s` (%s), p%s"
          % (before.get("amount"), row.get("amount"), row.get("amount_kind"),
             (row.get("bar_citation") or {}).get("page_start")))
        other = [f for f in FILLABLE
                 if f not in ("amount", "amount_kind") and before.get(f) is None
                 and row.get(f) is not None]
        if other:
            A("  * also filled: %s" % ", ".join(
                "%s=%s" % (f, str(row.get(f))[:40]) for f in other))
    A("")
    if stats["conflicts"]:
        A("## Amount conflicts (BAR vs. minutes; the minutes value was kept)")
        A("")
        A("Full list with excerpts: `qa/bar_conflicts.jsonl` (for the E1 owner).")
        A("")
        for c in stats["conflicts"][:40]:
            A("* `%s` %s minutes=%s bar=%s (%s) -- %s -- %s"
              % (c["meeting_date"], c["item_no"], c["amount_minutes"], c["amount_bar"],
                 c["amount_bar_kind"], c["bar_doc_id"], (c["title"] or "")[:60]))
        A("")
    text = "\n".join(L) + "\n"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


# ---------------------------------------------------------------------------
# LLM fallback merge (--merge-llm)
# ---------------------------------------------------------------------------
#
# The coordinator runs the same haiku batch prompt E2 uses over
# ``contracts/bar_batches/NNN.jsonl`` and drops ``NNN.out.jsonl`` beside it,
# one row per item keyed by ``(meeting_id, item_no, char_start)``.  This step
# validates each of those rows *against that batch row's own ``bar_text``* --
# the only text the model was shown -- and merges the survivors into
# ``extracted_filled.jsonl``.
#
# Order of operations, and why it is idempotent:
#
#     bar_fill.py                 # rewrites extracted_filled.jsonl (regex)
#     bar_fill.py --merge-llm     # re-applies the LLM fills on top
#
# The regex pass always rebuilds the file from ``extracted.jsonl``, so the LLM
# fills are *not* preserved across it -- rerun ``--merge-llm`` afterwards.
# ``--merge-llm`` itself only ever writes fields that are still null, so
# running it twice in a row is a no-op the second time.

LLM_FILLABLE = (
    "amount", "amount_kind", "prior_total", "revised_total",
    "contract_id", "po_number", "rfp_number", "term_start", "term_end",
    "department", "fund", "funding_source_text", "procurement_method",
    "vendor_raw",
)
LLM_SOURCE = "bar_llm"
FUND_VALUES = {"general", "BEX", "BTA", "capital", "ASB", "grant", "other"}
_LLM_MONEY_RE = re.compile(
    r"^\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(million|mil|billion|bil|thousand|[kmb])?\s*$", re.I)
_LLM_SUF_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mil": 1e6, "million": 1e6,
                 "b": 1e9, "bil": 1e9, "billion": 1e9}


def llm_money(v):
    """Parse what a model might write for a money field: 1234567, "1,234,567",
    "$1,234,567.00", "1.2 million", "1.2M". -> float or None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    raw = str(v).strip()
    m = _LLM_MONEY_RE.match(raw)
    if not m:
        return None
    run = m.group(1)
    # Same malformed-comma rule as the regex pass: "$3,700.000" / "5,500250,000"
    # are typos, not values, and must be rejected rather than truncated.
    if not well_formed_money(run) or ("." in run and len(run.split(".", 1)[1]) > 2):
        return None
    try:
        val = float(run.replace(",", ""))
    except ValueError:
        return None
    suf = (m.group(2) or "").lower()
    if suf:
        # Same guard as _scaled: a mantissa already >= 1000 is taken at face
        # value ("$4,352,000 million" is a source typo, not $4.3 trillion).
        if val < 1000:
            val *= _LLM_SUF_MULT[suf]
    return val


def figure_in_text(text, value):
    """Is `value` printed in `text`? Accepts the comma-grouped, bare and
    2-decimal forms (via amount_printed) plus the scaled forms a BAR may use
    for the same number ("$1.75 million" for 1750000)."""
    if value is None:
        return False
    if amount_printed(text, value):
        return True
    squash = re.sub(r"\s+", "", text).lower()
    for unit, mult in (("million", 1e6), ("billion", 1e9)):
        if value >= mult / 1000:
            mant = value / mult
            for form in ("%g" % mant, "%.1f" % mant, "%.2f" % mant, "%.3f" % mant):
                for u in (unit, unit[0]):
                    if re.sub(r"\s+", "", "$%s%s" % (form, u)).lower() in squash:
                        return True
    return False


def _amount_sentence_ok(text, value):
    """False when *every* place `value` is printed in `text` sits in a sentence
    _MONEY_NEGATIVE rejects (state funding assistance, project budget, a
    savings figure, ...). Unknown/unlocatable -> True: the scaled forms
    figure_in_text accepts are not always locatable, and this guard must not
    become a second, blunter printedness check."""
    seen = False
    iv = int(round(value))
    for form in (f"{iv:,}", f"{value:,.2f}", str(iv)):
        for m in re.finditer(re.escape(form), text):
            seen = True
            if not _MONEY_NEGATIVE.search(_sentence_around(text, m.start())):
                return True
    return not seen


def _verbatim(needle, hay):
    return bool(needle) and norm_ws(str(needle)) in norm_ws(hay)


def _squashed_in(needle, hay):
    return re.sub(r"[\s.]+", "", str(needle)).lower() in re.sub(r"[\s.]+", "", hay).lower()


def llm_context(src):
    """Everything the model was shown for one batch row: the BAR excerpt plus
    the item fields the batch file carries.  Identifiers and vendor strings are
    checked against *this*, not against ``bar_text`` alone -- the batch row
    hands the model the item's own ``title``/``item_text``/``contract_id``, so
    echoing one of those back is not fabrication.  Money stays pinned to
    ``bar_text``: the whole point of this pass is that the figure comes from
    the Board Action Report, not from the minutes."""
    return " ".join(str(src.get(f) or "") for f in
                    ("bar_text", "bar_title", "title", "item_text",
                     "contract_id", "po_number", "vendor_raw"))


def validate_llm_row(llm, bar_text, context=None):
    """-> (clean_fields, hard_reasons, soft_drops).

    Hard failures (money out of range or not printed in the BAR, an identifier
    or vendor string absent from everything the model was shown) reject the
    whole row, exactly like E1: a model that invented one field is not trusted
    for the others.  Soft failures (a `fund` value outside the vocabulary, an
    unparseable term date, a funding sentence that is not in the text) drop
    just that field."""
    context = bar_text if context is None else context
    clean, hard, soft = {}, [], []

    for fld in ("amount", "prior_total", "revised_total"):
        raw = llm.get(fld)
        if raw in (None, "", "null"):
            continue
        v = llm_money(raw)
        if v is None:
            hard.append("%s_unparseable:%r" % (fld, raw))
        elif v < MIN_AMOUNT:
            hard.append("%s_below_min:%s" % (fld, v))
        elif v > AMOUNT_CEILING:
            hard.append("%s_implausible:%s" % (fld, v))
        elif not figure_in_text(bar_text, v):
            hard.append("%s_not_printed_in_bar:%s" % (fld, v))
        else:
            clean[fld] = v

    for fld in ("contract_id", "po_number", "rfp_number"):
        raw = llm.get(fld)
        if raw in (None, "", "null"):
            continue
        if not _squashed_in(raw, context):
            hard.append("%s_not_in_bar:%r" % (fld, raw))
        else:
            clean[fld] = str(raw).strip()

    vr = llm.get("vendor_raw")
    if vr not in (None, "", "null"):
        if not _verbatim(vr, context):
            hard.append("vendor_raw_not_verbatim:%r" % vr)
        else:
            clean["vendor_raw"] = norm_ws(vr)

    # Reuse the regex pass's vetted exclusion list on the sentence the model's
    # amount actually sits in. Haiku happily returns "up to $8,501,081 in state
    # funding assistance" as a contract amount; that phrase is exactly what
    # _MONEY_NEGATIVE exists to reject. Soft, not hard: the rest of the row
    # (fund, term, department) is usually still good.
    if "amount" in clean and not _amount_sentence_ok(bar_text, clean["amount"]):
        soft.append("amount_in_excluded_sentence")
        clean.pop("amount")

    if "amount" in clean:
        ak = llm.get("amount_kind")
        ak = ROW_AMOUNT_KIND.get(ak, ak)
        if ak not in AMOUNT_KINDS:
            soft.append("amount_kind_invalid:%r->unspecified" % llm.get("amount_kind"))
            ak = "unspecified"
        clean["amount_kind"] = ak

    fund = llm.get("fund")
    if fund not in (None, "", "null"):
        if fund in FUND_VALUES:
            clean["fund"] = fund
        else:
            soft.append("fund_not_in_vocabulary:%r" % fund)

    fst = llm.get("funding_source_text")
    if fst not in (None, "", "null"):
        if _verbatim(fst, bar_text):
            clean["funding_source_text"] = norm_ws(fst)[:300]
        else:
            soft.append("funding_source_text_not_in_bar")

    for fld in ("term_start", "term_end"):
        raw = llm.get(fld)
        if raw in (None, "", "null"):
            continue
        if parse_us_date(raw) or _d(raw):
            clean[fld] = str(raw).strip()
        else:
            soft.append("%s_unparseable:%r" % (fld, raw))

    for fld in ("department", "procurement_method"):
        raw = llm.get(fld)
        if raw in (None, "", "null"):
            continue
        if len(str(raw)) > 80:
            soft.append("%s_too_long" % fld)
        else:
            clean[fld] = norm_ws(raw)

    return clean, hard, soft


AMOUNT_REJECTS_CSV = os.path.join(os.path.dirname(__file__),
                                  "bar_llm_amount_rejects.csv")


def load_amount_rejects(out_root=ROOT, csv_path=None):
    """-> {key: {"reason": str, "note": str, "amount": float|None}} for rows
    whose LLM-proposed `amount` was hand-checked and judged wrong or partial.

    Two sources, unioned: the checked-in
    ``extractors/sps_web/bar_llm_amount_rejects.csv`` (durable -- it outlives a
    regenerated ``out_sps_web/``) and any row already carrying
    ``persistent: true`` in ``qa/bar_llm_rejects.jsonl``, so an entry the
    coordinator hand-adds there is honoured too. The CSV entries are mirrored
    back into that file on every run, which is why re-reading it is safe."""
    rejects = {}
    csv_path = csv_path or AMOUNT_REJECTS_CSV
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8") as fh:
            reader = csv.DictReader(ln for ln in fh if not ln.lstrip().startswith("#"))
            for r in reader:
                if not r.get("meeting_id"):
                    continue
                rejects[_key(r)] = {
                    "reason": (r.get("reason") or "hand_checked_wrong").strip(),
                    "note": (r.get("note") or "").strip(),
                    "amount": llm_money(r.get("amount")),
                    "source": "curated_csv",
                }
    for r in read_jsonl(os.path.join(out_root, "qa", "bar_llm_rejects.jsonl")):
        if not r.get("persistent"):
            continue
        k = tuple(r.get("key") or ())
        if len(k) == 3 and k not in rejects:
            k = (k[0], k[1], int(k[2]) if str(k[2]).lstrip("-").isdigit() else k[2])
            rejects[k] = {"reason": (r.get("reasons") or ["hand_checked_wrong"])[0],
                          "note": r.get("note") or "", "amount": r.get("amount"),
                          "source": "qa_jsonl"}
    return rejects


def load_bar_batches(batches_dir):
    """-> (inputs_by_key, outputs_by_key, n_out_files, n_bad_lines).
    A later batch file wins on a duplicate key; within a file, the last row."""
    inputs, outputs, n_files, n_bad = {}, {}, 0, 0
    if not os.path.isdir(batches_dir):
        return inputs, outputs, n_files, n_bad
    for name in sorted(os.listdir(batches_dir)):
        path = os.path.join(batches_dir, name)
        if re.fullmatch(r"\d{3}\.jsonl", name):
            for r in read_jsonl(path):
                inputs[_key(r)] = r
        elif re.fullmatch(r"\d{3}\.out\.jsonl", name):
            n_files += 1
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        n_bad += 1
                        continue
                    if isinstance(r, dict):
                        outputs[_key(r)] = r
    return inputs, outputs, n_files, n_bad


def _key(d):
    cs = d.get("char_start")
    try:
        cs = int(cs)
    except (TypeError, ValueError):
        pass
    return (d.get("meeting_id"), d.get("item_no"), cs)


def merge_llm(out_root=ROOT, batches_dir=None, filled_path=None, report_path=None):
    """Apply contracts/bar_batches/NNN.out.jsonl to extracted_filled.jsonl."""
    filled_path = filled_path or os.path.join(out_root, "contracts",
                                              "extracted_filled.jsonl")
    rows = read_jsonl(filled_path)
    if not rows:
        raise SystemExit("no rows read from %s -- run bar_fill.py first" % filled_path)
    batches_dir = batches_dir or os.path.join(out_root, "contracts", "bar_batches")
    inputs, outputs, n_files, n_bad = load_bar_batches(batches_dir)
    amount_rejects = load_amount_rejects(out_root)
    by_key = {}
    for r in rows:
        by_key.setdefault(_key(r), r)

    stats = {"n_out_files": n_files, "n_bad_lines": n_bad, "n_out_rows": len(outputs),
             "n_batch_rows": len(inputs), "filled": Counter(), "soft": Counter(),
             "hard": Counter(), "n_rejected": 0, "n_rejected_with_good_amount": 0,
             "n_merged": 0, "n_nothing_left": 0, "examples": [],
             "n_amount_rejected": 0, "amount_rejects": amount_rejects}
    rejects = []

    for key, llm in sorted(outputs.items(), key=lambda kv: [str(x) for x in kv[0]]):
        src = inputs.get(key)
        row = by_key.get(key)
        if src is None or row is None:
            stats["n_rejected"] += 1
            stats["hard"]["unknown_key"] += 1
            rejects.append({"key": list(key), "reasons": ["unknown_key"], "llm": llm})
            continue
        bar_text = src.get("bar_text") or ""
        clean, hard, soft = validate_llm_row(llm, bar_text, llm_context(src))
        for r in soft:
            stats["soft"][r.split(":")[0]] += 1
        if hard:
            stats["n_rejected"] += 1
            # A row rejected only for, say, a paraphrased vendor may still have
            # carried a money figure that passed every check. Counting those
            # tells the coordinator what whole-row rejection is costing.
            if "amount" in clean and not any(h.startswith("amount") for h in hard):
                stats["n_rejected_with_good_amount"] += 1
            for r in hard:
                stats["hard"][r.split(":")[0]] += 1
            rejects.append({
                "key": list(key), "meeting_date": row.get("meeting_date"),
                "title": row.get("title"), "bar_doc_id": src.get("bar_doc_id"),
                "reasons": hard, "soft_drops": soft, "llm": llm,
                "bar_text_excerpt": norm_ws(bar_text)[:600],
            })
            continue

        # Hand-checked amount rejects: keep every other field the model gave
        # us, but never re-fill the amount, however many times this runs.
        rej = amount_rejects.get(key)
        if rej and "amount" in clean:
            clean.pop("amount", None)
            clean.pop("amount_kind", None)
            stats["n_amount_rejected"] += 1
            soft.append("amount_hand_rejected:" + rej["reason"])

        filled = []
        for fld in LLM_FILLABLE:
            if fld in clean and row.get(fld) is None:
                row[fld] = clean[fld]
                row[fld + "_source"] = LLM_SOURCE
                filled.append(fld)
        if "amount" in filled:
            row["amount_source"] = LLM_SOURCE
            if row.get("amount_kind") is None and "amount_kind" in clean:
                row["amount_kind"] = clean["amount_kind"]
                row["amount_kind_source"] = LLM_SOURCE
        if filled:
            stats["n_merged"] += 1
            if row.get("bar_citation") is None and src.get("bar_doc_id"):
                page = src.get("bar_page_start") or 1
                row["bar_citation"] = {"doc_id": src["bar_doc_id"],
                                       "page_start": page, "page_end": page}
            if llm.get("llm_confidence") is not None:
                row["bar_llm_confidence"] = llm.get("llm_confidence")
            for fld in filled:
                stats["filled"][fld] += 1
            if len(stats["examples"]) < 15:
                stats["examples"].append((row, filled, src))
        else:
            stats["n_nothing_left"] += 1
        if rej:
            soft = [x for x in soft if not x.startswith("amount_hand_rejected")]
            notes = row.get("extractor_notes")
            notes = list(notes) if isinstance(notes, list) else ([notes] if notes else [])
            note = "bar_llm_amount_rejected:" + rej["reason"]
            if note not in notes:
                notes.append(note)
            row["extractor_notes"] = notes

        if soft:
            notes = row.get("extractor_notes")
            notes = list(notes) if isinstance(notes, list) else ([notes] if notes else [])
            # de-duplicate: --merge-llm is rerun after every regex pass, and a
            # second run over the same .out files must not grow the list.
            for r in soft:
                note = "bar_llm_dropped:" + r
                if note not in notes:
                    notes.append(note)
            row["extractor_notes"] = notes or None

    write_jsonl(filled_path, rows)
    for key, meta in sorted(amount_rejects.items(), key=lambda kv: [str(x) for x in kv[0]]):
        row = by_key.get(key)
        rejects.append({
            "key": list(key), "persistent": True, "scope": "amount",
            "meeting_date": row.get("meeting_date") if row else None,
            "title": row.get("title") if row else None,
            "amount": meta.get("amount"),
            "reasons": ["bar_llm_amount_rejected:" + meta["reason"]],
            "note": meta["note"], "source": meta["source"],
        })
    rej_path = os.path.join(out_root, "qa", "bar_llm_rejects.jsonl")
    write_jsonl(rej_path, rejects)
    report_path = report_path or os.path.join(out_root, "qa", "bar_llm_report.md")
    text = write_llm_report(report_path, stats, filled_path, rej_path)
    print("wrote %s (%d rows), %s (%d rejects) and %s"
          % (filled_path, len(rows), rej_path, len(rejects), report_path))
    print("out_files=%d llm_rows=%d merged=%d rejected=%d already_filled=%d "
          "amount_hand_rejected=%d"
          % (n_files, len(outputs), stats["n_merged"], stats["n_rejected"],
             stats["n_nothing_left"], stats["n_amount_rejected"]))
    if stats["filled"].get("vendor_raw"):
        print("NOTE: %d vendor_raw values came from BARs -- rerun vendors.py (F1) "
              "before link/publish or reconcile check 4 will flag them"
              % stats["filled"]["vendor_raw"])
    return rows, stats, text


def write_llm_report(path, stats, filled_path, rej_path):
    L = []
    A = L.append
    A("# BAR LLM fallback merge -- `bar_fill.py --merge-llm`")
    A("")
    A("Applied `contracts/bar_batches/NNN.out.jsonl` to `%s`." % filled_path)
    A("Rejects: `%s`." % rej_path)
    A("")
    A("| | |")
    A("|---|---|")
    A("| batch input rows | %d |" % stats["n_batch_rows"])
    A("| `.out.jsonl` files | %d |" % stats["n_out_files"])
    A("| LLM rows read | %d |" % stats["n_out_rows"])
    A("| malformed JSON lines skipped | %d |" % stats["n_bad_lines"])
    A("| rows merged (>=1 field filled) | %d |" % stats["n_merged"])
    A("| rows rejected (hard validator failure) | %d |" % stats["n_rejected"])
    A("| ...of those, carrying an amount that passed every money check | %d |"
      % stats["n_rejected_with_good_amount"])
    A("| rows with nothing left to fill | %d |" % stats["n_nothing_left"])
    A("| amounts blocked by the hand-checked reject list | %d |"
      % stats["n_amount_rejected"])
    A("")
    A("## Fields filled (`<field>_source=\"bar_llm\"`)")
    A("")
    A("| field | rows |")
    A("|---|---:|")
    for f, n in stats["filled"].most_common():
        A("| %s | %d |" % (f, n))
    A("")
    A("## Hard rejects by reason")
    A("")
    A("| reason | rows |")
    A("|---|---:|")
    for r, n in stats["hard"].most_common():
        A("| %s | %d |" % (r, n))
    A("")
    A("## Soft field drops (row kept, field skipped)")
    A("")
    A("| reason | fields |")
    A("|---|---:|")
    for r, n in stats["soft"].most_common():
        A("| %s | %d |" % (r, n))
    A("")
    A("## Examples")
    A("")
    for row, filled, src in stats["examples"]:
        A("* `%s` %s **%s** -- %s" % (row.get("meeting_date"), row.get("item_no"),
                                      row.get("action_type"), (row.get("title") or "")[:80]))
        A("  * BAR `%s` p%s: %s" % (src.get("bar_doc_id"), src.get("bar_page_start"),
                                    ", ".join("%s=%s" % (f, str(row.get(f))[:40])
                                              for f in filled)))
    A("")
    text = "\n".join(L) + "\n"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out-root", default=ROOT)
    ap.add_argument("--since", default="2004-08-01",
                    help="only fill rows on or after this meeting date")
    ap.add_argument("--limit", type=int, default=None,
                    help="process at most N in-scope rows (smoke test)")
    ap.add_argument("--report", default=None, help="report path override")
    ap.add_argument("--extracted", default=None)
    ap.add_argument("--no-batches", action="store_true",
                    help="skip writing the LLM fallback batch files")
    ap.add_argument("--merge-llm", action="store_true",
                    help=("instead of the regex pass: merge "
                          "contracts/bar_batches/NNN.out.jsonl into "
                          "contracts/extracted_filled.jsonl (run after a plain run)"))
    ap.add_argument("--batches-dir", default=None,
                    help="--merge-llm: batch directory (default contracts/bar_batches)")
    args = ap.parse_args(argv)
    if args.merge_llm:
        merge_llm(out_root=args.out_root, batches_dir=args.batches_dir,
                  filled_path=args.extracted, report_path=args.report)
        return 0
    run(out_root=args.out_root, since=args.since, limit=args.limit,
        report_path=args.report, extracted=args.extracted,
        write_batches=not args.no_batches)
    return 0


if __name__ == "__main__":
    sys.exit(main())
