"""
segment.py -- Task D1 (see extractors/sps_web/PLAN.md, Section 3): turn board
*minutes* (first choice) and *agendas* (fallback) into one row per business
item, with exact page and character offsets so Phase E can cite them.

Usage (from the repo root)::

    venv/bin/python3 -m extractors.sps_web.segment                       # whole corpus + QA report
    venv/bin/python3 -m extractors.sps_web.segment --era wp --limit 20
    venv/bin/python3 -m extractors.sps_web.segment --meeting 2024-10-09-regular

Inputs (all read-only, all still filling in while the crawl runs):

* ``out_sps_web/manifest/documents_classified.jsonl`` -- one row per document
  (``doc_id, era, meeting_id, meeting_date, school_year, filename,
  resolved_filename, kind, item_code, ...``); see ``classify.py``.
* ``out_sps_web/manifest/meetings.jsonl`` -- one row per meeting
  (``meeting_id, date, type, school_year, title``).
* ``out_sps_web/text/<era>/<date>/<stem>.txt`` -- ``pdftotext -layout`` output
  with ``\\f`` between pages.  The stem is *not* reliably the filename (2021-22+
  SharePoint documents are stored under their ``doc_id``), so documents are
  located through the sibling ``<stem>.textmeta.json``, which always carries
  ``doc_id``.

Output: ``out_sps_web/items/<meeting_id>.jsonl`` (one JSON row per item, schema
in ``Item``) plus ``out_sps_web/qa/segmentation_report.md``.

-----------------------------------------------------------------------------
Format families and their cues
-----------------------------------------------------------------------------

Every family, 2005 through 2026, uses the *same* three-level outline, which is
why there is one structural parser and only the result/title heuristics differ:

    <ROMAN>. Business Action Items          <- the business block
        <LETTER>. Consent Agenda            <- the subsection = `section`
            <N>. <title> <description>      <- the item
        <LETTER>. Items Removed from the Consent Agenda
        <LETTER>. Action Items
        <LETTER>. Introduction Items

Letters keep counting across repeated "Business Action Items (Continued)"
roman blocks (a 2019-2021 habit), so subsections are collected per document,
not per block.  Indentation drifts wildly within a single document (pdftotext
-layout preserves the original tab stops, which change page to page), so
headings are matched by *shape and vocabulary*, never by column, and numbered
items additionally have to form an unbroken 1,2,3,... run to be accepted --
that single rule is what keeps warrant tables and public-testimony lists out.

(a) **Modern minutes, 2021-22 -> present** (`era=wp`, SharePoint PDFs).
    Sections A Consent / B Items Removed from the Consent Agenda / C Action /
    D Introduction.  Item bodies are "Approval of this item would authorize the
    Superintendent to ...", frequently ending "Immediate action is in the best
    interest of the district. (Introduction & Action)".  Per-item outcome
    sentences: "This motion was approved unanimously (Directors ... voted
    yes)", "This item was approved with a vote of 6-1 (...)".  Consent is
    approved en bloc by a subsection-level paragraph ("The motion to approve
    the Consent Agenda as amended was approved unanimously"); items pulled out
    of it are named in "Director X moved to remove Item 7 (...)" and reappear,
    with their own vote, under "Items Removed from the Consent Agenda".

(b) **WP-era minutes, 2016-17 -> 2020-21** (`era=wp`, wp-content PDFs).
    Structurally identical to (a).  Outcome sentence is usually "This motion
    passed with a vote of 5-0-1 (...)".  Titles carry a committee annotation
    "(Ops, September 5, for Approval)" between title and description.  The
    *filename* is `C01_<posting meeting>_Minutes_<meeting the minutes are of>`
    -- the manifest's `meeting_id` is the meeting where the minutes were
    approved as consent item C01, NOT the meeting they describe, so the subject
    date is re-derived here (see `subject_date`).

(c) **WP/Blackboard agendas** (`era=blackboard`, and the 2016-17 wp copies).
    `<YYYYMMDD>_Agenda.pdf`; same outline, item bodies "Approval of this item
    will ...", right-margin annotations `(action)` / `(introduction)` /
    `(introduction/action)`.  Item codes C01/SC01/A01/I01 come from the sibling
    BAR filenames, not from the agenda text.  The era's *minutes*
    (`YYYYMMDD_Minutes.pdf`) use the same outline with those right-margin
    annotations *and* a per-item outcome sentence ("The motion passed
    unanimously."), so they need no separate parser -- fixtures at 2013-01-23,
    2014-03-19, 2015-09-23.  Blackboard also published
    `..._Minutes_UNOFFICIAL.pdf` drafts alongside the copies WordPress later
    carried as the official record; the two paginate differently, hence the
    draft/era precedence in `source_rank`.

(d) **Archive "edited agendas", 2006 -> 2012** (`era=archive`).  Same outline.
    Item bodies "Approval of this item will ..." or "The <X> Committee
    recommends approval of this item which would ...".  These are pre-meeting
    documents: they almost never record an outcome, so action/consent items get
    `result="unknown"` and introduction items `result="introduced"`.  The few
    outcome annotations that do occur are parenthetical -- "(postponed)",
    "(Postponed to a later date)", "(Withdrawn by Director ...)" -- and are
    honoured.

(a2) **Short one-topic special-meeting minutes, 2020 -> present.**  A variant
    of (a) with no outline at all: "Action Item" / "Action Items:" /
    "Action Item: <the item's title>" sit on bare lines and the items are
    bullets or nothing but a title, followed straight by the motion and the
    vote.  `find_subsections` falls back to bare section lines when no roman
    outline exists, and `find_items_unenumerated` / `find_items_single` pick
    up items with no 1./A. prefix.  A heading of the form "Action Item: X"
    donates X as the item title when the item body has none.

(e) **Legacy, 2005 -> 2011** (`era=legacy`).  Two-page agendas identical in
    shape to (d), and a handful of minutes whose outcome sentence is the terse
    "This item passed unanimously." / "This item passed, with all members
    present voting yes."  Legacy PDFs sometimes carry a wrong date in the page
    header (010908agenda.pdf says "January 9, 2007"), so the *filename* date
    wins over the header date for this era.  2005-06 legacy minutes and
    agendas also park introduction items under a roman "New Business" heading
    whose items are enumerated **A., B., C.** rather than 1., 2., 3., with the
    per-item `(introduction)` / `(action)` right-margin annotation carrying the
    section (see `_Sub.enum == "alpha"`).

Source-document precedence (per meeting)
----------------------------------------
1. **Which meeting a document belongs to** is the document's *subject* meeting,
   re-derived by `subject_date`, never the manifest's `meeting_id` (which is
   the meeting where the minutes were approved as consent item C01).  An
   unambiguous filename date wins; a filename that can only name the posting
   meeting yields to the page header, and an implausible header (>400 days
   before or >30 days after the posting meeting -- OCR garbage) falls back to
   the leading filename date.
2. **Minutes beat agendas** as the primary source: only the minutes carry
   `result` and `vote`.
3. Among copies of the same kind, prefer an *amended* copy, then an
   *official/approved/final* one, then a *revised/updated* one, then the
   longest text (a partial scan loses).
4. **The agenda supplements the minutes.**  2005-2012 minutes are terse and
   sometimes leave "Introduction Items" empty or drop an item entirely, yet
   those items are real board business whose only primary source is the
   agenda.  After the minutes are parsed, the meeting's best agenda is parsed
   too and any item whose title does not match a minutes item (`same_item`:
   40-char slug prefix, or >=0.6 Jaccard on 4+ letter words) is inserted at
   its printed position with `source_kind="agenda"` and the note
   "agenda-only item; not recorded in the minutes".  Items the minutes DO
   carry are never duplicated, so Phase E cannot double-count.

`section` comes from the heading, never from the filename code
--------------------------------------------------------------
A Board Action Report keeps the item code of the meeting where the item was
**introduced** (`I04_...`) even when it is re-linked at the action meeting, so
the `C`/`A`/`I` letter in a sibling filename does not say what section the item
sat in at *this* meeting -- 79 consent items in this corpus have `I` as their
only sibling code.  The subsection heading in the document is therefore the
authority for `section`; `item_code` is provenance only.

Design notes
------------
* ``char_start``/``char_end`` are byte-exact offsets into the ``.txt`` file as
  read; ``page_start``/``page_end`` are ``1 + text.count("\\f", 0, offset)``.
  ``title``/``body``/``motion_text`` are whitespace-normalised *copies*; the
  offsets always point back at the raw slice.
* ``result`` prefers ``"unknown"`` over a guess.  Amendment sub-motions
  ("The motion to approve Amendment 1 did not pass") never set the item's
  result; only the last item-level outcome sentence does.
* An item that is removed from consent and re-voted is emitted **once**, from
  the "Items Removed" subsection (``section="action"``, note "removed from
  consent agenda"); the consent copy is suppressed so Phase E cannot
  double-count it.  An item removed with no re-vote keeps ``result="removed"``.
* A title never runs past the meeting prose (`_title_zone`).  Without that,
  an item with no description of its own ("2. Personnel Report") has the
  *motion's* words "moved approval of this item" taken for its description
  cue, and the title swallows the motion -- and any following item whose
  number line was missed.
* No contract extraction happens here (that is E1), but ``motion_text`` keeps
  the whole "Approval of this item would ..." formula that E1's regexes read.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Iterable

ROOT = os.path.join(os.getcwd(), "out_sps_web")
MANIFEST = os.path.join(ROOT, "manifest", "documents_classified.jsonl")
MEETINGS = os.path.join(ROOT, "manifest", "meetings.jsonl")
TEXT_DIR = os.path.join(ROOT, "text")
ITEMS_DIR = os.path.join(ROOT, "items")
QA_DIR = os.path.join(ROOT, "qa")

SECTIONS = ("consent", "action", "introduction", "immediate", "other")
RESULTS = ("approved", "failed", "postponed", "removed", "introduced",
           "withdrawn", "unknown")


# --------------------------------------------------------------------------
# row schema
# --------------------------------------------------------------------------

@dataclass
class Item:
    meeting_id: str
    meeting_date: str
    source_doc_id: str
    source_kind: str          # minutes | agenda
    item_no: str              # as printed: "C.4", "6", "SC01"
    section: str              # consent | action | introduction | immediate | other
    title: str
    body: str
    motion_text: str
    result: str               # approved|failed|postponed|removed|introduced|withdrawn|unknown
    vote: str | None          # "7-0", "6-1-0", "unanimous", or free text
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    item_code: str | None     # C01 / SC01 / A01 / I01 when a sibling BAR gives one
    extractor_notes: list = field(default_factory=list)


# --------------------------------------------------------------------------
# structural regexes
# --------------------------------------------------------------------------

# "Il." / "lI." occur where the PDF text layer renders II. with a lowercase L.
ROMAN_RE = re.compile(r"^[ \t\f]{0,12}(?P<num>[IVXL]{1,6}|[Il]{2,4})[\.:\)][ \t]+(?P<title>\S.*?)[ \t]*$")
LETTER_RE = re.compile(r"^[ \t\f]{0,24}(?P<let>[A-Z])[\.\)][ \t]+(?P<title>\S.*?)[ \t]*$")
ITEM_RE = re.compile(r"^(?P<ind>[ \t\f]{0,34})(?P<num>\d{1,2})[\.\)][ \t]+(?P<rest>\S.*?)[ \t]*$")

BUSINESS_BLOCK_RE = re.compile(r"^business\s+action\s+items?\b", re.I)
# 2005-06 legacy minutes/agendas park the introduction items under a roman
# "New Business" heading whose items are enumerated A., B., C. instead of 1., 2.
NEW_BUSINESS_RE = re.compile(r"^new\s+business\b", re.I)
# used only when a document has no roman-numeral outline at all
FLAT_BLOCK_END_RE = re.compile(
    r"^(adjourn|board\s+comments|public\s+testimony|executive\s+session|"
    r"informational\s+items?|information\s+items?|superintendent|"
    r"board\s+committee|minutes\s+submitted)", re.I)

# ordered: the "introduction and action" variant must be tested before the
# plain "action"/"introduction" ones.
SECTION_TITLE_RES = [
    ("removed", re.compile(r"^items?\s+removed\s+from\s+(the\s+)?consent\s+agenda\b", re.I)),
    ("consent", re.compile(r"^consent\s+agenda\b", re.I)),
    ("immediate", re.compile(r"^(introduction|intro)\s*(and|&|/)\s*action\s+items?\b", re.I)),
    ("action", re.compile(r"^action\s+items?\b", re.I)),
    ("introduction", re.compile(r"^introduction\s+items?\b", re.I)),
]

# Right-margin annotations on agenda item / section lines.  `pdftotext -layout`
# keeps them at the end of each *physical* line, so a wrapped
# "(Intro/ Action)" arrives as "(Intro/" on one line and "Action)" on the next,
# interleaved with the title text.  They are stripped line-wise, before the
# item is flattened, and remembered so the section can be refined.
ANNOT_TAIL_RE = re.compile(
    r"[ \t]{3,}\(?\s*(?:action|introduction|intro)\s*(?:[/&]|and)?\s*"
    r"(?:action)?\s*\)?[ \t]*$", re.I)
ANNOT_RE = re.compile(
    r"\(\s*(?:action|introduction|intro)\s*(?:[/&]|and)?\s*(?:action)?\s*\)", re.I)
COMMITTEE_ANNOT_RE = re.compile(
    r"\([^()]{0,80}?,\s*(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\.?\s*\d{1,2}(?:st|nd|rd|th)?,?\s*(?:for\s+[A-Za-z ]{0,25})?\)",
    re.I)

# footers / page furniture removed from the *rendered* strings only
FOOTER_RES = [
    re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.I),
    re.compile(r"^\s*Page\s*[|\uff5c]\s*\d{1,3}\s*$", re.I),
    re.compile(r"^\s*\d{1,3}\s*$"),
    re.compile(r"^\s*\d{6}\s*(?:agenda|minutes)(?:\.doc)?\s*\d{0,3}\s*$", re.I),
    re.compile(r"^\s*\d{6}\s+(?:agenda|minutes)\s*\d{0,3}\s*$", re.I),
    re.compile(r"^\s*(?:edited-)?\d{6,8}[- ]?(?:agenda|minutes)[a-z.]*\s*\d{0,3}\s*$", re.I),
]

# a paragraph that belongs to the consent *subsection*, not to its last item
CONSENT_MOTION_RE = re.compile(
    r"(?is)\bconsent\s+agenda\b.{0,400}?\b(moved|motion|approved|passed|removed|"
    r"vote|second)", )
CONSENT_MOTION_ALT_RE = re.compile(
    r"(?is)\b(moved|motion|vote|removed)\b.{0,200}?\bconsent\s+agenda\b")

# the sentence(s) that decide `result`
POS_RE = re.compile(r"(?i)\b(passed|was\s+approved|were\s+approved|is\s+approved|"
                    r"was\s+passed|were\s+passed|carried|adopted\s+unanimously|"
                    r"approved\s+unanimously)\b")
NEG_RE = re.compile(r"(?i)\b(did\s+not\s+pass|failed|was\s+not\s+approved|"
                    r"were\s+not\s+approved|was\s+defeated|was\s+denied)\b")
POSTPONE_RE = re.compile(r"(?i)\b(postpone[ds]?|tabled?|delay(?:ed)?)\b")
WITHDRAW_RE = re.compile(r"(?i)\bwithdrawn|withdrew\b")
AMENDMENT_SUBJECT_RE = re.compile(
    r"(?i)\bmotion\s+(?:to\s+(?:approve|adopt)\s+)?amendment\b|"
    r"\bmotion\s+to\s+amend\b|\bamendment\s+\d+\s+(?:to|was|passed|did)\b|"
    r"\bthe\s+amendment\s+(?:passed|failed|was)\b|"
    r"\bmotion\s+to\s+(?:table|suspend|extend|call)\b")
RESULT_SUBJECT_RE = re.compile(
    r"(?i)\b(this|the)\s+(motion|item|action|resolution)\b|"
    r"\bmotion\s+(to|on)\b|\bthis\s+(item|motion)\b")

UNANIMOUS_RE = re.compile(r"(?i)\bunanimous(?:ly)?\b")

REMOVE_ITEM_RE = re.compile(
    r"(?i)\b(?:moved\s+to\s+remove|removed?)\s+(?:consent\s+agenda\s+)?"
    r"[Ii]tems?\s+((?:\d{1,2}\s*(?:\([^()]*\))?\s*(?:,|and|&)?\s*)+)")
REMOVED_PRIOR_RE = re.compile(
    r"(?i)consent\s+agenda\s+item\s+(\d{1,2})\s+was\s+removed\s+from\s+the\s+agenda")
# 2007-08 legacy minutes put the item first: "Item 2 was removed from the
# consent agenda. All other items passed unanimously."
REMOVED_SUBJECT_FIRST_RE = re.compile(
    r"(?i)\bitems?\s+((?:\d{1,2}\s*(?:,|and|&)?\s*)+)(?:was|were)\s+removed")

# title / description boundary
DESC_CUES = [
    re.compile(r"(?i)\bApproval\s+of\s+th(?:is|e)\s+(?:item|action|resolution|"
               r"motion|contract|policy|report)\b"),
    re.compile(r"(?i)\bApproval\s+of\s+(?:this\s+)?Resolution\s+(?:No\.\s*)?[\d/\-]+\s+"
               r"w(?:ill|ould)\b"),
    re.compile(r"(?i)\bThe\s+[A-Z][\w&/,'’ ]{2,45}?\s+Committee\s+recommends\b"),
    re.compile(r"(?i)\b[A-Z][\w&/,' ]{2,45}?\s+recommends\s+approval\s+of\s+th(?:is|e)\b"),
    re.compile(r"(?i)(?<!approval of )\bThis\s+item\s+w(?:ill|ould)\s+"
               r"(?:approve|authorize|accept)\b"),
    re.compile(r"(?i)\bRequest\s+for\s+PESB\b"),
    # warrants boilerplate, so the title stays "Warrants Report - August"
    re.compile(r"(?i)\bThe\s+Warrant\s+Register\s+represents\b"),
    re.compile(r"(?i)\bThe\s+following\s+warrants\s+as\s+audited\b"),
]

MOTION_START_RE = re.compile(
    r"(?i)\b(?:Director|President|Vice\s+President)\s+[A-Z][\w'’-]+\s+"
    r"(?:moved|move[sd]?)\b|^\s*This\s+(?:motion|item|action)\b|"
    r"\bThe\s+motion\s+(?:to|on|was|passed)\b")

# an outcome/motion clause glued onto a title with no sentence break, e.g.
# "2. Personnel Report / This item passed unanimously."
TITLE_TAIL_RE = re.compile(
    r"\s+(?:this|the)\s+(?:item|motion|action)\s+(?:passed|was|is|did|as)\b|"
    r"\s+(?:Director|President)\s+[A-Z][\w'\u2019-]+\s+move[sd]\b|"
    r"\s+all\s+other\s+items\s+passed\b", re.I)

DEGENERATE_TITLE_RE = re.compile(
    r"(?i)^(approval of th(?:is|e) (?:item|action)|the .{0,40} committee recommends)")

IMMEDIATE_RE = re.compile(r"(?i)immediate\s+action\s+is\s+in\s+the\s+best\s+interest")

WORKISH_RE = re.compile(
    r"(?i)\b(work\s*session|workshop|retreat|study\s+session|executive\s+session|"
    r"community\s+meeting|public\s+hearing|oath\s+of\s+office|engagement|"
    r"board\s+self[- ]evaluation|progress\s+monitoring|orientation|"
    r"town\s+hall|joint\s+meeting|special\s+attention)\b")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def norm_ws(s: str) -> str:
    """Collapse whitespace, join words broken by a hard hyphen at EOL."""
    s = s.replace(" ", " ")
    s = re.sub(r"(?<=[A-Za-z0-9])-[ \t]*\n[ \t]*(?=[A-Za-z0-9])", "-", s)
    return re.sub(r"[ \t\r\n\f]+", " ", s).strip()


def strip_footers(s: str) -> str:
    keep = []
    for line in s.split("\n"):
        if any(r.match(line) for r in FOOTER_RES):
            continue
        keep.append(line)
    return "\n".join(keep)


def strip_line_annotations(raw: str) -> tuple[str, str]:
    """(text without right-margin annotations, the annotations joined)."""
    kept, annots = [], []
    for line in raw.split("\n"):
        m = ANNOT_TAIL_RE.search(line)
        if m and line[:m.start()].strip():
            annots.append(m.group(0).strip())
            line = line[:m.start()]
        kept.append(line)
    return "\n".join(kept), " ".join(annots).lower()


def clean_title(s: str) -> str:
    s = norm_ws(s)
    s = ANNOT_RE.sub(" ", s)
    s = COMMITTEE_ANNOT_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^[\-–—:;,\s]+", "", s)
    s = re.sub(r"[\-–—:;,\.\s]+$", "", s)
    return s.strip()


def page_of(text: str, offset: int) -> int:
    return 1 + text.count("\f", 0, max(0, offset))


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = re.sub(r"[^a-z0-9]+", "", s.lower())
    return s


def sentences(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", s) if x.strip()]


# --------------------------------------------------------------------------
# manifest / text plumbing
# --------------------------------------------------------------------------

def read_jsonl(path: str) -> list[dict]:
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def build_text_index() -> dict[str, str]:
    """doc_id -> path of its .txt.

    The stem under text/ is the resolved filename for wp-content/Wayback
    documents but the bare doc_id for SharePoint ones, so the authoritative
    link is the sibling .textmeta.json, which always carries doc_id.
    """
    index: dict[str, str] = {}
    for era in sorted(os.listdir(TEXT_DIR)) if os.path.isdir(TEXT_DIR) else []:
        era_dir = os.path.join(TEXT_DIR, era)
        if not os.path.isdir(era_dir):
            continue
        for date in os.listdir(era_dir):
            ddir = os.path.join(era_dir, date)
            if not os.path.isdir(ddir):
                continue
            for name in os.listdir(ddir):
                if not name.endswith(".textmeta.json"):
                    continue
                try:
                    with open(os.path.join(ddir, name), encoding="utf-8") as fh:
                        meta = json.load(fh)
                except Exception:
                    continue
                doc_id = meta.get("doc_id")
                if not doc_id or meta.get("error"):
                    continue
                txt = os.path.join(ddir, name[: -len(".textmeta.json")] + ".txt")
                if os.path.exists(txt):
                    index[doc_id] = txt
    return index


DATE_TOKEN_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")
# 2016-17 minutes name the meeting they cover as MMDDYYYY ("..._Minutes_04202017").
# The two forms cannot collide: a YYYYMMDD string always starts 19xx/20xx, which
# is never a valid month.
DATE_TOKEN_MDY_RE = re.compile(
    r"(?<!\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])((?:19|20)\d{2})(?!\d)")
ITEMCODE_PREFIX_RE = re.compile(r"^(?:approved[_-])?(?:[A-Z]{1,2}\d{2})[_-]", re.I)
SUPERSEDED_DATE_RE = re.compile(r"(?i)(?:updated|revised|rev|posted|amended|approved)[_\- ]*$")

HEADER_DATE_RE = re.compile(
    r"(?i)\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)?,?\s*"
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2}),?\s+((?:19|20)\d{2})\b")
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"])}


def _stem_dates(stem: str) -> list[str]:
    """Every meeting-looking date in a filename stem, in the order printed.

    Skips re-posting stamps ("...Updated20191120", "...REVISED20200825").
    """
    hits: list[tuple[int, str]] = []
    for m in DATE_TOKEN_RE.finditer(stem):
        if SUPERSEDED_DATE_RE.search(stem[max(0, m.start() - 12):m.start()]):
            continue
        hits.append((m.start(), f"{m.group(1)}-{m.group(2)}-{m.group(3)}"))
    for m in DATE_TOKEN_MDY_RE.finditer(stem):
        if SUPERSEDED_DATE_RE.search(stem[max(0, m.start() - 12):m.start()]):
            continue
        hits.append((m.start(), f"{m.group(3)}-{m.group(1)}-{m.group(2)}"))
    hits.sort()
    return [d for _, d in hits]


def filename_leading_date(stem: str) -> str | None:
    """The first date in the stem, whatever it means."""
    dates = _stem_dates(stem)
    if dates:
        return dates[0]
    return _mmddyy_date(stem)


def _mmddyy_date(stem: str) -> str | None:
    """legacy/archive stems use MMDDYY: 010908agenda, edited-081909agenda."""
    m = re.match(r"^(?:edited[-_])?(\d{2})(\d{2})(\d{2})(?!\d)", stem or "", re.I)
    if not m:
        return None
    mm, dd, yy = (int(x) for x in m.groups())
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None
    year = 2000 + yy if yy <= 30 else 1900 + yy
    return f"{year:04d}-{mm:02d}-{dd:02d}"


def filename_subject_date(stem: str, posting_date: str | None = None) -> str | None:
    """Date of the meeting a document is *about*, from the filename.

    The WP naming convention is ``<ITEMCODE>_<posting meeting>_Minutes_<the
    meeting the minutes cover>`` -- the leading date is the meeting at which
    the minutes were approved as consent item C01, so it is dropped:

    * ``C01_20191002_Minutes_20190918``  -> 2019-09-18
    * ``C01_20170517_Minutes_04202017``  -> 2017-04-20 (MMDDYYYY tail)

    When an item-coded stem carries only ONE date it is ambiguous, and the
    manifest's meeting date settles it: ``C01_20221012_Minutes.pdf`` filed
    under the 2022-10-12 meeting is the minutes *of another meeting*
    (2022-09-28, per its own first page), so None is returned and the caller
    falls back to the page header.  ``C02_20160824_Minutes_FINAL.pdf`` filed
    under 2016-09-07 keeps 2016-08-24, because the date is not the meeting it
    was posted at.

    Returns None when the filename cannot name the subject meeting.
    """
    if not stem:
        return None
    hits = _stem_dates(stem)
    if not hits:
        return _mmddyy_date(stem)
    if ITEMCODE_PREFIX_RE.match(stem):
        if len(hits) > 1:
            return hits[1]
        if posting_date and hits[0] == posting_date:
            return None
    return hits[0]


def _within_days(a: str, b: str, lo: int, hi: int) -> bool:
    """lo <= (b - a) in days <= hi, on YYYY-MM-DD strings."""
    from datetime import date
    try:
        da = date(int(a[:4]), int(a[5:7]), int(a[8:10]))
        db = date(int(b[:4]), int(b[5:7]), int(b[8:10]))
    except (ValueError, TypeError):
        return False
    return lo <= (db - da).days <= hi


def header_subject_date(text: str) -> str | None:
    head = text[:2500]
    for m in HEADER_DATE_RE.finditer(head):
        mon = MONTHS.get(m.group(1).lower())
        if not mon:
            continue
        return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"
    return None


def subject_date(row: dict, text: str) -> tuple[str, str]:
    """(date, how) -- the date of the meeting the document describes.

    Precedence: an unambiguous filename date beats the page header (legacy
    headers carry typos -- 010908agenda.pdf says "January 9, 2007", and
    C01_20170104_Minutes_Official.pdf says "January 4, 2016").  When the
    filename can only offer the *posting* meeting the header wins, but only if
    it is plausible: within 400 days before and 30 days after the posting
    meeting.  Implausible headers (C01_20160914_WorkSession_Minutes.pdf OCRs
    its date as 2010-09-16) fall back to the leading filename date.
    """
    stem = os.path.splitext(row.get("resolved_filename") or row.get("filename") or "")[0]
    posting = row.get("meeting_date")
    fd = filename_subject_date(stem, posting)
    hd = header_subject_date(text)
    if fd:
        return fd, "filename"
    if hd and (not posting or _within_days(hd, posting, -30, 400)):
        return hd, "header"
    lead = filename_leading_date(stem)
    if lead:
        return lead, "filename-leading"
    if hd:
        return hd, "header"
    return posting, "manifest"


# --------------------------------------------------------------------------
# the structural parser
# --------------------------------------------------------------------------

@dataclass
class _Sub:
    section: str
    letter: str | None
    start: int          # char offset just after the heading line
    end: int
    heading: str
    enum: str = "num"   # "num" (1., 2., ...) or "alpha" (A., B., ...)
    title_hint: str = ""  # "Action Item: <title>" headings carry the item title
    speculative: bool = False  # inferred from a bare line, not an outline prefix


def _line_spans(text: str) -> list[tuple[int, int, str]]:
    spans, pos = [], 0
    for line in text.split("\n"):
        spans.append((pos, pos + len(line), line))
        pos += len(line) + 1
    return spans


def _section_of(title: str) -> str | None:
    t = clean_title(title)
    for name, rx in SECTION_TITLE_RES:
        if rx.match(t):
            return name
    return None


def _bare_section_line(line: str) -> tuple[str, str] | None:
    """A heading line with no A./1. prefix, e.g. "Action Items:" or
    "Action Item: Amendment to the 2023-24 Regular Board Meeting Schedule."

    Returns (section, title hint after the colon) or None.  Requires the line
    to be short or to put a colon right after the section name, so ordinary
    prose ("Action items were discussed") is not mistaken for a heading.
    """
    t = line.strip()
    if not t or len(t) > 140:
        return None
    sec = _section_of(t)
    if not sec:
        return None
    m = re.match(r"^\s*[A-Za-z &/]{3,40}?\s*:\s*(.*)$", t)
    if m:
        return sec, m.group(1).strip()
    if len(t) <= 60:
        return sec, ""
    return None


def find_subsections(text: str) -> list[_Sub]:
    """Locate every business subsection in a document.

    A subsection is a LETTER heading whose title names a known section and that
    sits inside (or immediately after) a "Business Action Items" roman block.
    Documents that jump straight to "III. Action Items" without the wrapper are
    handled by treating such roman headings as subsections themselves.
    """
    spans = _line_spans(text)
    romans: list[tuple[int, int, str, str]] = []   # (idx, start, num, title)
    letters: list[tuple[int, int, str, str]] = []
    for i, (s, e, line) in enumerate(spans):
        if not line.strip():
            continue
        m = ROMAN_RE.match(line)
        if m:
            romans.append((i, s, m.group("num"), m.group("title")))
            continue
        m = LETTER_RE.match(line)
        if m and _section_of(m.group("title")):
            letters.append((i, s, m.group("let"), m.group("title")))

    # business regions = [start_line, end_line) covered by a Business Action
    # Items roman heading (or by a roman heading that is itself a section).
    flat_subs: list[_Sub] = []
    if not romans:
        # Short special-meeting minutes (2021+) drop the outline entirely: the
        # block and section names are bare lines.  Each bare section heading
        # runs to the next one, or to the next bare "Adjourn"/"Board Comments"
        # style line.
        bare = []
        for i, (s, e, line) in enumerate(spans):
            hit = _bare_section_line(line)
            if hit:
                bare.append((i, s, e, hit[0], hit[1]))
        for j, (i, s, e, sec, hint) in enumerate(bare):
            end_line = bare[j + 1][0] if j + 1 < len(bare) else len(spans)
            for k in range(i + 1, end_line):
                t = spans[k][2].strip()
                if len(t) <= 60 and FLAT_BLOCK_END_RE.match(clean_title(t)):
                    end_line = k
                    break
            end = spans[end_line - 1][1] if end_line - 1 < len(spans) else len(text)
            if end > e + 1:
                flat_subs.append(_Sub(sec, None, e + 1, min(end, len(text)),
                                      clean_title(line), "num", clean_title(hint),
                                      speculative=True))

    regions: list[tuple[int, int, str | None, str, str]] = []
    for k, (i, s, num, title) in enumerate(romans):
        nxt = romans[k + 1][0] if k + 1 < len(romans) else len(spans)
        t = clean_title(title)
        if BUSINESS_BLOCK_RE.match(t):
            regions.append((i + 1, nxt, None, t, "num"))
        elif NEW_BUSINESS_RE.match(t):
            regions.append((i + 1, nxt, "introduction", t, "alpha"))
        else:
            sec = _section_of(title)
            if sec:
                regions.append((i + 1, nxt, sec, t, "num"))

    subs: list[_Sub] = []
    for (lo, hi, forced, rtitle, enum) in regions:
        inner = [l for l in letters if lo <= l[0] < hi]
        if forced and (not inner or enum == "alpha"):
            start = spans[lo][0] if lo < len(spans) else len(text)
            end = spans[hi - 1][1] if hi - 1 < len(spans) else len(text)
            subs.append(_Sub(forced, None, start, end, rtitle, enum))
            continue
        if forced is None and not inner:
            # Short special-meeting minutes drop the A./B./C. prefixes: the
            # subsection name sits on a bare line ("Action Items (Introduction
            # & Action)").  Fall back to those; failing that, treat the whole
            # block as one unnamed subsection.
            bare = [(i, spans[i]) for i in range(lo, min(hi, len(spans)))
                    if len(spans[i][2].strip()) <= 60 and _section_of(spans[i][2])]
            if bare:
                for j, (i, (bs, be, _line)) in enumerate(bare):
                    end_line = bare[j + 1][0] if j + 1 < len(bare) else hi
                    end = spans[end_line - 1][1] if end_line - 1 < len(spans) else len(text)
                    subs.append(_Sub(_section_of(spans[i][2]), None, be + 1,
                                     min(end, len(text)), clean_title(spans[i][2])))
                continue
            start = spans[lo][0] if lo < len(spans) else len(text)
            end = spans[hi - 1][1] if hi - 1 < len(spans) else len(text)
            if end > start:
                subs.append(_Sub("other", None, start, min(end, len(text)),
                                 rtitle, "alpha", speculative=True))
            continue
        for j, (i, s, let, title) in enumerate(inner):
            end_line = inner[j + 1][0] if j + 1 < len(inner) else hi
            start = spans[i][1] + 1 if i < len(spans) else len(text)
            end = spans[end_line - 1][1] if end_line - 1 < len(spans) else len(text)
            subs.append(_Sub(_section_of(title), let, start, min(end, len(text)),
                             clean_title(title)))
    if not subs:
        subs = flat_subs
    # merge duplicate/overlapping subsections that pdftotext split across pages
    subs.sort(key=lambda x: x.start)
    return subs


def _accept_item_line(rest: str) -> bool:
    if len(rest) < 3:
        return False
    if "$" in rest:
        return False
    if re.match(r"^[\d.,%]+$", rest):
        return False
    return True


def find_items(text: str, sub: _Sub) -> list[tuple[int, int, int]]:
    """(ordinal, char_start, char_end) for each item in a subsection.

    Ordinals must form an unbroken run (n, n+1, n+2, ...).  That constraint,
    not indentation, is what rejects warrant-table rows and stray enumerations.
    Alpha subsections ("New Business" in 2005-06 legacy documents) enumerate
    A., B., C. instead; the same run rule applies.
    """
    region = text[sub.start:sub.end]
    rx = LETTER_RE if sub.enum == "alpha" else ITEM_RE
    starts: list[tuple[int, int]] = []
    expected: int | None = None
    pos = 0
    for line in region.split("\n"):
        m = rx.match(line)
        if m:
            rest = m.group("title") if sub.enum == "alpha" else m.group("rest")
            if _accept_item_line(rest):
                n = (ord(m.group("let")) - 64) if sub.enum == "alpha" else int(m.group("num"))
                grp = "let" if sub.enum == "alpha" else "num"
                # The run must move forward, but minutes typists do drop a
                # number (the 2017-01-04 consent agenda goes 1, 2, 4, 5 ...),
                # so a gap of up to three is tolerated when the line still
                # looks like an item start.
                ok = ((expected is None and 1 <= n <= 25)
                      or (expected is not None and n == expected)
                      or (expected is not None and expected < n <= expected + 3
                          and len(rest) >= 8 and rest[:1].isupper()))
                if ok:
                    starts.append((n, sub.start + pos + m.start(grp)))
                    expected = n + 1
        pos += len(line) + 1
    out = []
    for k, (n, s) in enumerate(starts):
        e = starts[k + 1][1] if k + 1 < len(starts) else sub.end
        out.append((n, s, e))
    return out


def find_items_unenumerated(text: str, sub: _Sub) -> list[tuple[int, int, int]]:
    """Last-resort item finder for subsections with no 1./A. enumeration.

    Short special-meeting minutes (e.g. 2025-06-18) just stack
    "<title>\nApproval of this item would ..." paragraphs.  Each paragraph
    that opens a description cue starts an item.  Only used when the
    enumerated passes found nothing, so the false-positive risk is contained.
    """
    starts: list[int] = []
    for ps, pe in split_paragraphs(text, sub.start, sub.end):
        flat = norm_ws(text[ps:pe])
        for rx in DESC_CUES:
            m = rx.search(flat)
            if m and m.start() < 400:
                starts.append(ps)
                break
    out = []
    for k, ps in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else sub.end
        out.append((k + 1, ps, e))
    return out


def find_items_single(text: str, sub: _Sub) -> list[tuple[int, int, int]]:
    """Very last resort: an unlettered subsection that holds exactly one item.

    2020-2025 one-topic special meetings write the item as a bare bullet
    ("- Action Item: Suspending provisions of Board Policy No. 2420") with no
    "Approval of this item" description at all, followed straight by the
    motion and the vote.  Only fires for unlettered subsections that actually
    contain motion/vote prose, so ordinary narrative sections stay empty.
    """
    if sub.letter is not None:
        return []
    paras = split_paragraphs(text, sub.start, sub.end)
    if not paras:
        return []
    body = norm_ws(text[sub.start:sub.end])
    if len(body) < 60:
        return []
    if not (MOTION_START_RE.search(body) or decide_result(body)[0] != "unknown"):
        return []
    first = paras[0]
    if MOTION_START_RE.search(norm_ws(text[first[0]:first[1]])):
        return []
    return [(1, first[0], sub.end)]


def split_paragraphs(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Blank-line separated paragraph spans within [start, end)."""
    chunk = text[start:end]
    spans, pos = [], 0
    for para in re.split(r"\n[ \t]*\n", chunk):
        s = start + pos
        e = s + len(para)
        if para.strip():
            spans.append((s, e))
        pos += len(para) + 2
    return spans


def _is_consent_level(para: str) -> bool:
    p = norm_ws(para)
    if len(p) > 900:
        return False
    return bool(CONSENT_MOTION_RE.search(p) or CONSENT_MOTION_ALT_RE.search(p))


# --------------------------------------------------------------------------
# result / vote
# --------------------------------------------------------------------------

CONSENT_SUBJECT_RE = re.compile(
    r"(?i)\b(all\s+)?(other\s+)?items?\b|\bconsent\s+agenda\b|\bbalance\s+of\b")


def _outcome_of_sentence(s: str, consent: bool = False) -> str | None:
    if AMENDMENT_SUBJECT_RE.search(s):
        if POSTPONE_RE.search(s) and POS_RE.search(s) and re.search(
                r"(?i)motion\s+to\s+(table|postpone|delay)", s):
            return "postponed"
        return None
    if not RESULT_SUBJECT_RE.search(s) and not (consent and CONSENT_SUBJECT_RE.search(s)):
        return None
    if re.search(r"(?i)\bmotion\s+to\s+(postpone|table|delay)\b", s) and POS_RE.search(s):
        return "postponed"
    if NEG_RE.search(s):
        return "failed"
    if WITHDRAW_RE.search(s):
        return "withdrawn"
    if POSTPONE_RE.search(s) and not POS_RE.search(s):
        return "postponed"
    if re.search(r"(?i)\b(was|were|is)\s+(tabled|postponed)\b", s):
        return "postponed"
    if POS_RE.search(s):
        return "approved"
    return None


def decide_result(text_block: str, consent: bool = False) -> tuple[str, str | None]:
    """(result, vote) from a block of minutes prose -- last decisive sentence wins.

    ``consent=True`` relaxes the subject test so the en-bloc wording of the
    2005-2012 minutes ("All other items passed unanimously.") is recognised;
    it is never used on an individual item's prose.
    """
    result, chosen = "unknown", None
    for s in sentences(norm_ws(text_block)):
        o = _outcome_of_sentence(s, consent)
        if o:
            result, chosen = o, s
    vote = None
    if chosen:
        m = re.search(r"(?i)vote\s+of\s+(\d{1,2}\s*[-‐-―]\s*\d{1,2}"
                      r"(?:\s*[-‐-―]\s*\d{1,2})?)", chosen)
        if not m:
            m = re.search(r"(\d{1,2}\s*[-‐-―]\s*\d{1,2}"
                          r"(?:\s*[-‐-―]\s*\d{1,2})?)\s+vote", chosen)
        if m:
            vote = re.sub(r"\s*[-‐-―]\s*", "-", m.group(1))
        elif UNANIMOUS_RE.search(chosen):
            vote = "unanimous"
    return result, vote


# --------------------------------------------------------------------------
# item construction
# --------------------------------------------------------------------------

def _title_zone(text: str) -> str:
    """Everything before the meeting prose starts.

    A title can never run past "Director X moved ..." / "This motion passed
    ...".  Cutting there first matters because an item with no description of
    its own ("2. Personnel Report") would otherwise have the *motion's* words
    "moved approval of this item" mistaken for its description cue, dragging
    the motion -- and, when a numbered line was missed, the whole next item --
    into the title.
    """
    cuts = []
    for rx in (TITLE_TAIL_RE, MOTION_START_RE):
        m = rx.search(text)
        if m and m.start() > 0:
            cuts.append(m.start())
    for sent in sentences(text):
        if _outcome_of_sentence(sent):
            i = text.find(sent)
            if i > 0:
                cuts.append(i)
            break
    return text[:min(cuts)] if cuts else text


def split_title_body(raw: str) -> tuple[str, str]:
    cleaned, _ = strip_line_annotations(strip_footers(raw))
    cleaned = cleaned.lstrip("\n\r\f")
    cleaned = re.sub(r"^[ \t\f]*(?:\d{1,2}|[A-Z])[\.\)][ \t]*", "", cleaned)
    # bullets, including the single mis-decoded letter Wingdings leaves behind
    cleaned = re.sub(r"^[ \t\f]*[\u2022\u00b7\u25cf\-\u2013\u2014][ \t]*", "", cleaned)
    cleaned = re.sub(r"^[ \t\f]*[a-z][ \t]+(?=[A-Z])", "", cleaned)
    # "Action Item: <title>" restates the section name; drop it
    cleaned = re.sub(r"^[ \t\f]*(?:action|introduction|intro|consent)\s+items?\s*:"
                     r"[ \t]*", "", cleaned, flags=re.I)
    paras = [norm_ws(p) for p in re.split(r"\n[ \t]*\n", cleaned) if p.strip()]
    if not paras:
        return "", ""
    # right-margin "(action)" / "(introduction/action)" annotations land in the
    # middle of a wrapped title ("... Prevention - Approval (introduction) of
    # this item will ...") and would hide the description cue.
    paras = [ANNOT_RE.sub(" ", p) for p in paras]
    paras = [re.sub(r"\s+", " ", p).strip() for p in paras if p.strip()]
    if not paras:
        return "", ""
    flat = norm_ws(" ".join(paras))
    zone = _title_zone(flat)
    best = None
    for rx in DESC_CUES:
        m = rx.search(zone)
        if m and m.start() >= 8:
            if best is None or m.start() < best:
                best = m.start()
    if best is not None:
        return clean_title(zone[:best]), flat
    # no description cue: the first paragraph is the title, trimmed to its
    # first sentence if it runs long.
    head = _title_zone(paras[0])
    if len(head) > 320:
        m = re.search(r"(?<=[a-z\)\u201d\"0-9])\.\s+(?=[A-Z])", head)
        head = head[:m.start() + 1] if m and m.start() < 320 else head[:320]
    return clean_title(head), flat


def extract_motion_text(body_flat: str) -> str:
    """The formulaic paragraph E1's regexes read.

    Starts at the "Approval of this item would ..." cue (or the whole body when
    there is none) and stops where the meeting prose ("Director X moved ...")
    takes over.
    """
    start = None
    for rx in DESC_CUES:
        m = rx.search(body_flat)
        if m and (start is None or m.start() < start):
            start = m.start()
    tail = body_flat[start or 0:]
    m = MOTION_START_RE.search(tail)
    if m and m.start() > 40:
        tail = tail[:m.start()]
    return tail.strip()


def _item_no(sub: _Sub, n: int) -> str:
    printed = chr(64 + n) if sub.enum == "alpha" else str(n)
    return f"{sub.letter}.{printed}" if sub.letter else printed


def parse_document(text: str, kind: str) -> tuple[list[dict], list[str]]:
    """Return (raw item dicts, document-level notes)."""
    notes: list[str] = []
    subs = find_subsections(text)
    if not subs:
        return [], notes

    is_minutes = kind == "minutes"
    raw_items: list[dict] = []
    consent_removed_numbers: set[int] = set()
    consent_result: tuple[str, str | None] = ("unknown", None)
    removed_titles: list[str] = []

    # first pass: the "Items Removed" subsections, so consent copies can be
    # suppressed.
    for sub in subs:
        if sub.section != "removed":
            continue
        for n, s, e in find_items(text, sub):
            t, _ = split_title_body(text[s:e])
            if t:
                removed_titles.append(slug(t)[:60])

    for sub in subs:
        items = find_items(text, sub)
        if not items and sub.enum == "alpha":
            sub = _Sub(sub.section, sub.letter, sub.start, sub.end, sub.heading, "num")
            items = find_items(text, sub)
        if not items:
            items = find_items_unenumerated(text, sub)
        if not items:
            items = find_items_single(text, sub)
        sub_tail = ""
        if sub.section == "consent" and items:
            # The en-bloc motion lives at the end of the subsection and would
            # otherwise be swallowed by the last item.  Modern minutes name the
            # Consent Agenda in it; legacy minutes just say "This item passed
            # unanimously.", so fall back to the last paragraph that decides a
            # result.
            n, s, e = items[-1]
            paras = split_paragraphs(text, s, e)
            cut = None
            for pi, (ps, pe) in enumerate(paras):
                if pi == 0:
                    continue
                if _is_consent_level(text[ps:pe]):
                    cut = ps
                    break
            if cut is None and is_minutes:
                for pi in range(len(paras) - 1, 0, -1):
                    ps, pe = paras[pi]
                    if decide_result(text[ps:pe], consent=True)[0] != "unknown":
                        cut = ps
                        while (pi - 1 > 0 and
                               MOTION_START_RE.search(norm_ws(
                                   text[paras[pi - 1][0]:paras[pi - 1][1]]))):
                            pi -= 1
                            cut = paras[pi][0]
                        break
            if cut is not None:
                sub_tail = text[cut:sub.end]
                items[-1] = (n, s, cut)
            else:
                sub_tail = text[e:sub.end]
            consent_result = (decide_result(sub_tail, consent=True) if is_minutes
                              else ("unknown", None))
            for m in REMOVE_ITEM_RE.finditer(norm_ws(sub_tail)):
                for num in re.findall(r"\d{1,2}", re.sub(r"\([^()]*\)", " ", m.group(1))):
                    consent_removed_numbers.add(int(num))
            for m in REMOVED_PRIOR_RE.finditer(norm_ws(sub_tail)):
                consent_removed_numbers.add(int(m.group(1)))
            for m in REMOVED_SUBJECT_FIRST_RE.finditer(norm_ws(sub_tail)):
                for num in re.findall(r"\d{1,2}", m.group(1)):
                    consent_removed_numbers.add(int(num))

        for n, s, e in items:
            raw = text[s:e]
            title, body = split_title_body(raw)
            if sub.title_hint and (not title or len(title) < 25
                                   or DEGENERATE_TITLE_RE.match(title)):
                title = sub.title_hint
            if not title:
                continue
            if not re.search(r"[a-z]", title) and len(title) < 60:
                # "RECOMMENDED MOTION", "FISCAL IMPACT/REVENUE SOURCE" -- the
                # section headings of a Board Action Report that was filed (or
                # misclassified) as an agenda.  Never a real item title.
                continue
            motion = extract_motion_text(body)
            section = sub.section if sub.section != "removed" else "action"
            item_notes: list[str] = []

            _, line_ann = strip_line_annotations(raw)
            ann = (line_ann + " " +
                   " ".join(a.group(0).lower() for a in ANNOT_RE.finditer(raw)))
            if sub.enum == "alpha":
                # "New Business" items carry their own (action)/(introduction)
                # right-margin annotation; the heading says nothing.
                if "intro" in ann and "action" in ann:
                    section = "immediate"
                elif "action" in ann:
                    section = "action"
                elif "intro" in ann:
                    section = "introduction"

            if sub.section == "removed":
                item_notes.append("removed from consent agenda")

            # section refinement: "(Introduction & Action)" / immediate action
            if (IMMEDIATE_RE.search(body)
                    or ("intro" in ann and "action" in ann)):
                item_notes.append("immediate action")
                if section in ("introduction", "action"):
                    # introduced and acted on at the same meeting
                    section = "immediate"

            if is_minutes:
                if sub.section == "consent":
                    if slug(title)[:60] in removed_titles or n in consent_removed_numbers:
                        # re-voted under "Items Removed"; emit only that row,
                        # unless it never reappears
                        if slug(title)[:60] in removed_titles:
                            continue
                        result, vote = "removed", None
                        item_notes.append("removed from consent agenda; no separate vote found")
                    else:
                        result, vote = consent_result
                elif sub.section == "introduction":
                    result, vote = decide_result(body)
                    if result == "unknown":
                        result = "introduced"
                else:
                    result, vote = decide_result(body)
            else:
                # agendas are pre-meeting documents
                result, vote = "unknown", None
                low = norm_ws(raw).lower()
                if re.search(r"\bpostpon", low):
                    result = "postponed"
                elif re.search(r"\bwithdrawn\b", low):
                    result = "withdrawn"
                elif sub.section == "introduction":
                    result = "introduced"

            raw_items.append(dict(
                item_no=_item_no(sub, n),
                section=section,
                title=title,
                body=body,
                motion_text=motion,
                result=result,
                vote=vote,
                char_start=s,
                char_end=e,
                page_start=page_of(text, s),
                page_end=page_of(text, max(s, e - 1)),
                notes=item_notes,
                number=n,
            ))
    return raw_items, notes


# --------------------------------------------------------------------------
# per-meeting driver
# --------------------------------------------------------------------------

MINUTES_RANK_RE = [
    (re.compile(r"(?i)amend"), 3),
    # "(?<!un)" matters: "20180829_Unofficial_Minutes" contains "official"
    (re.compile(r"(?i)(?<!un)official|approved|\bfinal\b"), 2),
    (re.compile(r"(?i)\brev(?:ised)?\b|updated"), 1),
]
# a draft copy of the minutes -- the same meeting, but not the record the Board
# adopted, and paginated differently
# "\b" is useless here: filenames glue the word to an underscore
# ("20190918_Minutes_UNOFFICIAL", "20160601_Minutes_Draft_v2"), and "_" is a
# word character.  Letter-only lookarounds still reject "drafted".
DRAFT_RE = re.compile(r"(?<![a-z])(un[- _]?official|draft)(?![a-z])", re.I)
ERA_RANK = {"wp": 3, "blackboard": 2, "legacy": 1, "archive": 0}


def _doc_stem(row: dict) -> str:
    return os.path.splitext(row.get("resolved_filename") or row.get("filename") or "")[0]


def is_draft(doc: dict, text: str) -> bool:
    """Is this an unofficial / draft copy of the minutes?

    Blackboard published `YYYYMMDD_Minutes_UNOFFICIAL.pdf` alongside the
    official copy that WordPress later carried, and the two paginate
    differently, so the choice has to be deterministic.
    """
    if DRAFT_RE.search(_doc_stem(doc) or ""):
        return True
    first_page = text.split("\f", 1)[0][:1500]
    return bool(DRAFT_RE.search(first_page))


def source_rank(doc: dict, text: str) -> tuple:
    """Sort key for competing copies of the same meeting, best first.

    1. official beats unofficial/draft
    2. wp beats blackboard beats legacy beats archive
    3. amended beats official/approved/final beats revised/updated beats plain
    4. longest text (a truncated or partial scan loses)
    """
    stem = _doc_stem(doc)
    rev = 0
    for rx, w in MINUTES_RANK_RE:
        if rx.search(stem):
            rev = max(rev, w)
    return (0 if is_draft(doc, text) else 1,
            ERA_RANK.get(doc.get("era"), 0),
            rev,
            len(text))


def pick_source(docs: list[dict], texts: dict[str, str],
                kind: str = None) -> tuple[dict | None, list[dict]]:
    """(best document of a given kind, the copies it beat).

    With ``kind=None`` this applies the source precedence -- minutes first,
    agenda as fallback -- and then ``source_rank`` among the copies of the
    winning kind.
    """
    kinds = (kind,) if kind else ("minutes", "agenda")
    for k in kinds:
        cands = [d for d in docs if d.get("kind") == k and d["doc_id"] in texts]
        if not cands:
            continue
        cands.sort(key=lambda d: source_rank(d, texts[d["doc_id"]]), reverse=True)
        return cands[0], cands[1:]
    return None, []


def item_sort_key(item_no: str) -> tuple:
    """Order key for an item number as printed ("C.4" -> ("C", 4))."""
    m = re.match(r"^([A-Z])\.(\d+)$", item_no or "")
    if m:
        return (0, m.group(1), int(m.group(2)))
    if re.match(r"^\d+$", item_no or ""):
        return (0, "", int(item_no))
    if re.match(r"^[A-Z]$", item_no or ""):
        return (1, item_no, 0)
    return (2, item_no or "", 0)


def _title_key(title: str) -> tuple[str, frozenset]:
    sl = slug(title)
    words = frozenset(w for w in re.findall(r"[a-z0-9]+", title.lower())
                      if len(w) > 3)
    return sl, words


def same_item(a: str, b: str) -> bool:
    """Do two item titles from the agenda and the minutes name the same item?"""
    sa, wa = _title_key(a)
    sb, wb = _title_key(b)
    if not sa or not sb:
        return False
    n = min(len(sa), len(sb), 40)
    if n >= 12 and sa[:n] == sb[:n]:
        return True
    if wa and wb:
        j = len(wa & wb) / len(wa | wb)
        if j >= 0.6:
            return True
    return False


def bar_item_codes(docs: list[dict], meeting_date: str) -> dict[tuple[str, int], str]:
    """(section-letter, number) -> item code, from sibling BAR filenames.

    Only documents attached to *this* meeting count.  The manifest's
    ``meeting_id`` for a minutes PDF is the meeting where the minutes were
    approved, not the meeting they describe, so the lookup is done on the
    resolved subject meeting and re-checked against its date.
    """
    out: dict[tuple[str, int], str] = {}
    dupes: set[tuple[str, int]] = set()
    for d in docs:
        if meeting_date and d.get("meeting_date") != meeting_date:
            continue
        code = d.get("item_code")
        if not code or d.get("kind") not in ("bar", "personnel", "warrants", "resolution",
                                             "policy", "presentation", "other"):
            continue
        m = re.match(r"^(SC|[CAIS])(\d{1,2})$", code, re.I)
        if not m:
            continue
        key = (m.group(1).upper(), int(m.group(2)))
        if key in out and out[key] != code:
            dupes.add(key)
        out[key] = code
    for k in dupes:
        out.pop(k, None)
    return out


SECTION_CODE_LETTERS = {
    "consent": ("C", "SC"),
    "action": ("A",),
    "introduction": ("I",),
    "immediate": ("A", "I"),
    "other": (),
}


def school_year_of(date: str) -> str:
    y, m = int(date[:4]), int(date[5:7])
    return f"{y}-{str(y + 1)[2:]}" if m >= 8 else f"{y - 1}-{str(y)[2:]}"


def segment_corpus(era: str | None, meeting_filter: str | None, limit: int | None,
                   out_dir: str) -> dict:
    docs = read_jsonl(MANIFEST)
    meetings = {m["meeting_id"]: m for m in read_jsonl(MEETINGS)}
    by_date: dict[str, list[dict]] = defaultdict(list)
    for m in meetings.values():
        by_date[m["date"]].append(m)
    texts_index = build_text_index()

    # group candidate source documents by the meeting they *describe*
    per_meeting: dict[str, list[dict]] = defaultdict(list)
    doc_text: dict[str, str] = {}
    resolved: dict[str, str] = {}
    for row in docs:
        if row.get("kind") not in ("minutes", "agenda"):
            continue
        if era and row.get("era") != era:
            continue
        path = texts_index.get(row["doc_id"])
        if not path:
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        if len(text.strip()) < 200:
            continue
        date, how = subject_date(row, text)
        if not date:
            continue
        mid = resolve_meeting_id(date, text, by_date, row)
        row = dict(row)
        row["_subject_date"] = date
        row["_date_source"] = how
        row["_path"] = path
        doc_text[row["doc_id"]] = text
        resolved[row["doc_id"]] = mid
        per_meeting[mid].append(row)

    # sibling documents (BARs) for item codes, keyed by the manifest meeting id
    siblings: dict[str, list[dict]] = defaultdict(list)
    for row in docs:
        if row.get("meeting_id"):
            siblings[row["meeting_id"]].append(row)

    os.makedirs(out_dir, exist_ok=True)
    stats = {
        "meetings": {},
        "items": [],
        "zero": [],
        "date_sources": Counter(),
    }
    mids = sorted(per_meeting)
    if meeting_filter:
        mids = [m for m in mids if m == meeting_filter or m.startswith(meeting_filter)]
    if limit:
        mids = mids[:limit]

    for mid in mids:
        group = per_meeting[mid]
        src, alternates = pick_source(group, doc_text)
        if src is None:
            continue
        stats["date_sources"][src["_date_source"]] += 1
        text = doc_text[src["doc_id"]]
        kind = src["kind"]
        mdate = src["_subject_date"]
        raw_items, _notes = parse_document(text, kind)
        # only outline-derived subsections count as "this document has a
        # business section"; bare-line ones are speculative
        n_subs = sum(1 for sub in find_subsections(text) if not sub.speculative)
        has_cue = bool(re.search(r"(?i)approval of th(?:is|e) (?:item|action)", text))
        codes = bar_item_codes(siblings.get(mid, []), mdate)
        # The row schema has no alternates field, so the copies this document
        # beat are recorded as a note -- they cite the same meeting and are a
        # usable fallback if the winning PDF ever goes missing.
        alt_note = ""
        if alternates:
            alt_note = "alternate copies: " + "; ".join(
                f"{a['doc_id']} ({_doc_stem(a) or a['era']})" for a in alternates[:3])

        def build(ri, doc, doc_kind, extra_note=None):
            code = None
            for letter in SECTION_CODE_LETTERS.get(ri["section"], ()):
                if (letter, ri["number"]) in codes:
                    code = codes[(letter, ri["number"])]
                    break
            notes = list(ri["notes"])
            if extra_note:
                notes.append(extra_note)
            if doc is src and alt_note:
                notes.append(alt_note)
            return Item(
                meeting_id=mid,
                meeting_date=mdate,
                source_doc_id=doc["doc_id"],
                source_kind=doc_kind,
                item_no=ri["item_no"],
                section=ri["section"],
                title=ri["title"],
                body=ri["body"],
                motion_text=ri["motion_text"],
                result=ri["result"],
                vote=ri["vote"],
                page_start=ri["page_start"],
                page_end=ri["page_end"],
                char_start=ri["char_start"],
                char_end=ri["char_end"],
                item_code=code,
                extractor_notes=notes,
            )

        rows = [build(ri, src, kind) for ri in raw_items]

        # Supplement: an agenda for the same meeting often lists items the
        # minutes never mention (2005-2012 legacy minutes are terse and
        # sometimes leave "Introduction Items" empty).  Those items are real
        # board business and the agenda is their only primary source, so they
        # are appended -- but only the ones the minutes do not already carry,
        # so Phase E cannot double-count.
        n_supp = 0
        if kind == "minutes":
            agenda, _ = pick_source(group, doc_text, kind="agenda")
            if agenda is not None and agenda["doc_id"] != src["doc_id"]:
                atext = doc_text[agenda["doc_id"]]
                if not any(not sub.speculative for sub in find_subsections(atext)):
                    atext = None  # a BAR or packet misfiled as an agenda
                aitems, _ = parse_document(atext, "agenda") if atext else ([], [])
                for ri in aitems:
                    if any(same_item(ri["title"], r.title) for r in rows):
                        continue
                    row = build(ri, agenda, "agenda",
                                "agenda-only item; not recorded in the minutes")
                    # slot it where it was printed, without disturbing the
                    # document order of the minutes rows (combined-minutes
                    # PDFs repeat item numbers, so a full sort would interleave)
                    key = item_sort_key(row.item_no)
                    at = len(rows)
                    for i in range(len(rows) - 1, -1, -1):
                        if item_sort_key(rows[i].item_no) <= key:
                            at = i + 1
                            break
                    rows.insert(at, row)
                    n_supp += 1
        path = os.path.join(out_dir, f"{mid}.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
        meta = meetings.get(mid, {})
        sy = meta.get("school_year") or school_year_of(mdate)
        stats["meetings"][mid] = {
            "school_year": sy,
            "type": meta.get("type") or mid.split("-", 3)[-1],
            "kind": kind,
            "era": src.get("era"),
            "n_items": len(rows),
            "n_agenda_only": n_supp,
            "n_subs": n_subs,
            "has_cue": has_cue,
            "title": meta.get("title") or "",
            "doc_stem": _doc_stem(src) or src["doc_id"],
            "filed_under": src.get("meeting_id"),
        }
        stats["items"].extend(asdict(r) for r in rows)
        if not rows:
            stats["zero"].append((mid, sy, kind, meta.get("type", "?"),
                                  meta.get("title", ""), _doc_stem(src) or src["doc_id"],
                                  zero_reason(text, kind, meta)))
    return stats


def resolve_meeting_id(date: str, text: str, by_date: dict[str, list[dict]],
                       row: dict) -> str:
    cands = by_date.get(date, [])
    if not cands:
        return f"{date}-{guess_type(text)}"
    if len(cands) == 1:
        return cands[0]["meeting_id"]
    want = guess_type(text)
    for c in cands:
        if c.get("type") == want:
            return c["meeting_id"]
    for c in cands:
        if c.get("type") == "regular":
            return c["meeting_id"]
    return cands[0]["meeting_id"]


def guess_type(text: str) -> str:
    head = norm_ws(text[:600]).lower()
    if "work session" in head:
        return "work-session"
    if "retreat" in head:
        return "retreat"
    if "special" in head:
        return "special"
    return "regular"


def zero_reason(text: str, kind: str, meta: dict) -> str:
    head = norm_ws(text[:1200])
    mtype = (meta.get("type") or "").lower()
    if mtype in ("work-session", "retreat"):
        return f"{mtype} -- agenda has no business items"
    if WORKISH_RE.search(head) and "business action" not in text.lower():
        m = WORKISH_RE.search(head)
        return f"{m.group(0).lower()} -- no business action items section"
    if "business action" not in text.lower() and "consent agenda" not in text.lower():
        return "no Business Action Items / Consent Agenda section in the document"
    if len(text.strip()) < 1500:
        return "very short document (stub / cancellation notice)"
    return "PARSER MISS -- document has a business section but no items were parsed"


# --------------------------------------------------------------------------
# QA report
# --------------------------------------------------------------------------

def write_report(stats: dict, path: str) -> None:
    per_year: dict[str, dict] = defaultdict(lambda: {
        "meetings": 0, "with_items": 0, "counts": [], "sections": Counter(),
        "results": Counter(), "minutes": 0, "minutes_with_items": 0,
        "business": 0, "business_with_items": 0,
        "cue": 0, "cue_with_items": 0})
    for mid, m in stats["meetings"].items():
        y = per_year[m["school_year"]]
        y["meetings"] += 1
        if m["n_items"]:
            y["with_items"] += 1
        y["counts"].append(m["n_items"])
        if m["kind"] == "minutes":
            y["minutes"] += 1
            if m["n_items"]:
                y["minutes_with_items"] += 1
            if m.get("n_subs"):
                y["business"] += 1
                if m["n_items"]:
                    y["business_with_items"] += 1
            if m.get("has_cue"):
                y["cue"] += 1
                if m["n_items"]:
                    y["cue_with_items"] += 1
    for it in stats["items"]:
        y = per_year[school_year_of(it["meeting_date"])]
        y["sections"][it["section"]] += 1
        y["results"][it["result"]] += 1

    years = sorted(per_year)
    lines = ["# Segmentation report (D1)", "",
             f"Generated by `extractors/sps_web/segment.py`. "
             f"{len(stats['meetings'])} meetings segmented, "
             f"{len(stats['items'])} business items.", ""]

    tot_min = sum(per_year[y]["minutes"] for y in years)
    tot_min_ok = sum(per_year[y]["minutes_with_items"] for y in years)
    tot_bus = sum(per_year[y]["business"] for y in years)
    tot_bus_ok = sum(per_year[y]["business_with_items"] for y in years)
    lines += [
        "**Acceptance check.** The card asks that >=95% of meetings that have "
        "minutes yield >=1 business item. Most minutes in this corpus are of "
        "work sessions, retreats, executive sessions and community engagements, "
        "which have no business items at all, so the meaningful denominator is "
        "minutes that actually contain a business outline "
        "(Business Action Items / Consent Agenda / New Business):", "",
        f"- minutes-sourced meetings **with a business section**: {tot_bus}; "
        f"yielding >=1 item: {tot_bus_ok} "
        f"(**{(100.0 * tot_bus_ok / tot_bus if tot_bus else 0):.1f}%**)",
        f"- minutes-sourced meetings whose text contains an \"Approval of this "
        f"item\" clause anywhere (the strictest test that business happened): "
        f"{sum(per_year[y]['cue'] for y in years)}; yielding >=1 item: "
        f"{sum(per_year[y]['cue_with_items'] for y in years)} "
        f"(**{(100.0 * sum(per_year[y]['cue_with_items'] for y in years) / max(1, sum(per_year[y]['cue'] for y in years))):.1f}%**)",
        f"- all minutes-sourced meetings: {tot_min}; yielding >=1 item: "
        f"{tot_min_ok} ({(100.0 * tot_min_ok / tot_min if tot_min else 0):.1f}%) "
        f"-- the remainder are itemless by nature, listed at the end.", ""]

    lines += ["## Per school year", "",
              "| year | meetings w/ minutes-or-agenda | >=1 item | items/mtg p10 | median | max "
              "| consent | action | intro | immediate | approved | introduced | removed "
              "| postponed | failed | withdrawn | unknown |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for y in years:
        d = per_year[y]
        c = sorted(d["counts"])
        nz = [x for x in c if x]
        p10 = (statistics.quantiles(nz, n=10)[0] if len(nz) >= 10 else (min(nz) if nz else 0))
        med = statistics.median(nz) if nz else 0
        s, r = d["sections"], d["results"]
        lines.append(
            f"| {y} | {d['meetings']} | {d['with_items']} | {p10:.0f} | {med:.0f} | "
            f"{max(c) if c else 0} | {s['consent']} | {s['action']} | {s['introduction']} | "
            f"{s['immediate']} | {r['approved']} | {r['introduced']} | {r['removed']} | "
            f"{r['postponed']} | {r['failed']} | {r['withdrawn']} | {r['unknown']} |")

    # suspicious dips
    lines += ["", "## Flags", ""]
    meds = {y: (statistics.median([x for x in per_year[y]["counts"] if x]) or 0)
            for y in years if any(per_year[y]["counts"])}
    flagged = False
    vals = list(meds.values())
    overall = statistics.median(vals) if vals else 0
    for y in years:
        d = per_year[y]
        cov = d["with_items"] / d["meetings"] if d["meetings"] else 0
        if d["business"] and d["business_with_items"] / d["business"] < 0.95:
            lines.append(f"- **{y}**: only {d['business_with_items']}/{d['business']} "
                         f"minutes with a business section produced items (<95%).")
            flagged = True
        if y in meds and overall and meds[y] < 0.5 * overall:
            lines.append(f"- **{y}**: median items/meeting {meds[y]:.0f} is less than half "
                         f"the corpus median {overall:.0f}.")
            flagged = True

    if not flagged:
        lines.append("- No year flagged.")

    lines += ["", "## Meetings that produced zero items", ""]
    reasons = Counter(z[6].split(" -- ")[0] for z in stats["zero"])
    for k, v in reasons.most_common():
        lines.append(f"- {v} x {k}")
    lines += ["", "| meeting | year | source | reason |", "|---|---|---|---|"]
    for mid, sy, kind, mtype, title, stem, reason in sorted(stats["zero"]):
        lines.append(f"| {mid} | {sy} | {kind} (`{stem}`) | {reason} |")

    dup = Counter((it["meeting_id"], it["item_no"]) for it in stats["items"])
    n_dup = sum(1 for v in dup.values() if v > 1)
    rehomed = [(mid, m) for mid, m in sorted(stats["meetings"].items())
               if m.get("filed_under") and m["filed_under"] != mid]
    supp = [(mid, m) for mid, m in sorted(stats["meetings"].items())
            if m.get("n_agenda_only")]
    lines += ["", "## Documents re-homed to the meeting they describe", "",
              "The manifest files minutes under the meeting where they were "
              "*approved* (consent item C01). These are the ones whose subject "
              "meeting differs -- cite them under the left column.", "",
              "| items written to | manifest filed it under | source |",
              "|---|---|---|"]
    for mid, m in rehomed:
        lines.append(f"| {mid} | {m['filed_under']} | `{m['doc_stem']}` |")
    lines += ["", "## Meetings where the agenda supplemented the minutes", "",
              "Rows with `source_kind=\"agenda\"` and the note *agenda-only "
              "item; not recorded in the minutes*.", "",
              "| meeting | items | of which agenda-only |", "|---|---|---|"]
    for mid, m in supp:
        lines.append(f"| {mid} | {m['n_items']} | {m['n_agenda_only']} |")

    lines += ["", "## Known caveats", "",
              "- **Blackboard era (2011-12 -> 2015-16) is missing entirely** -- the "
              "Wayback crawl had not landed when this ran, so `out_sps_web/text/"
              "blackboard/` is empty and there are no fixtures for format family "
              "(c). Rerun this module once it lands; no code change is expected, "
              "the outline is the same.",
              "- **2016-17 and part of 2017-18 wp text is not extracted yet** "
              "(`totext.py` was still running), so those years are thin here.",
              "- **`item_code` is only filled where a sibling Board Action Report "
              f"filename carries one** ({sum(1 for i in stats['items'] if i['item_code'])}"
              f"/{len(stats['items'])} items). 2021-22+ SharePoint documents have no "
              "resolved filename yet, so those years get none; this fills in by "
              "itself once `classify.py` resolves them.",
              f"- **{n_dup} (meeting, item_no) pairs are duplicated** -- combined "
              "PDFs that contain two meetings' minutes, and legacy items that were "
              "tabled and retaken later in the same meeting. Phase F should key on "
              "(meeting_id, item_no, char_start), not (meeting_id, item_no).",
              "- Agenda-sourced items keep `result=\"unknown\"` for consent and "
              "action sections on purpose: an agenda is a pre-meeting document and "
              "records no outcome. Only `introduction` gets `introduced`.",
              ""]
    lines += ["", "## Date-of-subject provenance", "",
              ", ".join(f"{k}={v}" for k, v in stats["date_sources"].most_common()), ""]

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--era", choices=["wp", "blackboard", "legacy", "archive"])
    ap.add_argument("--meeting", help="single meeting_id (or prefix, e.g. a date)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out-dir", default=ITEMS_DIR)
    ap.add_argument("--report", default=os.path.join(QA_DIR, "segmentation_report.md"))
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    stats = segment_corpus(args.era, args.meeting, args.limit, args.out_dir)
    n_items = len(stats["items"])
    n_meet = len(stats["meetings"])
    n_zero = len(stats["zero"])
    print(f"segmented {n_meet} meetings -> {n_items} items "
          f"({n_zero} meetings with zero items) into {args.out_dir}")
    if not args.no_report:
        write_report(stats, args.report)
        print(f"wrote {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
