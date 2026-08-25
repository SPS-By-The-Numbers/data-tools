"""
link.py -- Task F2 (see ``extractors/sps_web/PLAN.md``, Section 3): fold the
Introduction and Action appearances of the same board item into ONE row per
board **action**, then group those rows into contract **chains** (a new
contract and its later amendments / change orders / renewals / final
acceptance) so the spreadsheet can show one contract's value over time.

Usage (from the repo root)::

    venv/bin/python3 -m extractors.sps_web.link                 # whole corpus + QA report
    venv/bin/python3 -m extractors.sps_web.link --era modern
    venv/bin/python3 -m extractors.sps_web.link --out-root /tmp/scratch

Inputs (read-only):

* ``out_sps_web/contracts/extracted.jsonl`` -- one row per admitted item, from
  ``e2_merge.py``.  Fields used here: ``meeting_id, meeting_date, item_no,
  item_code, char_start, era, section, title, board_action, vote, vendor_raw,
  vendor_name, action_type, amount, amount_kind, prior_total, revised_total,
  contract_id, po_number, immediate_action, citation, extractor``.
* ``out_sps_web/contracts/vendor_map.jsonl`` -- **optional**, produced by task
  F1 (``vendors.py``): ``{"vendor_raw": ..., "vendor_id": ...}``.  When the
  file is absent (F1 not run yet) every vendor falls back to
  ``_fallback_vendor_key`` -- casefold, punctuation stripped, corporate
  suffixes (inc/llc/corp/...) removed -- and ``vendor_id_source`` on each
  output row records which was used.  Rerunning after F1 lands silently
  upgrades every ``vendor_id``; nothing else in this module changes.
* ``out_sps_web/contracts/vendors.jsonl`` -- optional, F1's canonical vendor
  table; only ``vendor_id -> vendor_name`` is read, to fill
  ``vendor_canonical`` when present.

Outputs (both rewritten from scratch on every run; this module owns only
these two paths):

* ``out_sps_web/contracts/contract_actions.jsonl``
* ``out_sps_web/qa/link_report.md``

=============================================================================
Part 1 -- Introduction <-> Action pairing
=============================================================================

The board votes on most items twice.  The item is *introduced* at one meeting
(``section="introduction"``, ``board_action="introduced"``, no vote) and voted
on at the next regular meeting two to four weeks later
(``section="consent"|"action"``).  Those are two rows in ``extracted.jsonl``
and ONE board action.  ``immediate`` items ("Immediate action is in the best
interest of the district") appear once, and so do consent items that were
pulled and re-voted from the "Items Removed from the Consent Agenda" section.

Row roles::

    section=introduction              -> pairing *source*
    section=consent|action            -> pairing *target*  (unless board_action
                                         is "removed"/"withdrawn": no vote was
                                         taken, so it is not an action)
    section=immediate|other           -> pass through, paired=null
    board_action=removed|withdrawn    -> pass through, paired=null

**Thresholds and rules.** Every one of these is deliberately tight: a wrong
pairing silently merges two different contracts and is far worse than an
introduction that stays on its own row.

1. ``MAX_PAIR_GAP_DAYS = 60``.  Measured on the corpus the observed gap
   distribution is 7d:13, 13d:17, **14d:350**, 15d:5, 21d:99, 22d:6, 28d:33,
   35d:4, 42d:3, 43d:7, 49d:4, 56d:1 -- i.e. the two-week cadence with a tail
   through the summer recess.  Widening the window to 180 days would gain only
   3 more pairs and would start to cross fiscal years, so 60 stands.
2. ``MIN_PAIR_GAP_DAYS = 0``.  The action meeting is never before the
   introduction.  Same-day is allowed (some minutes list an intro and an
   immediate action of the same item).
3. **Era**.  Preferred: identical ``era``.  ``legacy``/``archive`` and
   ``wp1620``/``modern`` are *overlapping sources for the same meetings*
   (spsarchivepublic covers 2006-2012 alongside the legacy site; the
   2021 summer meetings appear in both wp-content and SharePoint), so a
   cross-era pair *inside one of those two families* (``ERA_FAMILY``) is
   allowed, but only on an exact-title match and only after every same-era
   candidate has been claimed.  18 real pairs come from this; no pair ever
   crosses ``early`` <-> ``wp``.
4. **Match tiers**, tried strictly in order.  A lower tier is only consulted
   for introductions the higher tiers could not place:

   ===  ======================  =====================================================
   1    ``title_exact``         ``_norm_title`` equal, >= ``MIN_TITLE_CHARS`` (15)
                                characters, same era.
   2    ``title_exact_nopar``   tier 1 after deleting every ``(...)`` span.  The
                                2005-2012 agendas append the sponsoring department
                                or the superintendent's name to the title -- "BTA II,
                                Approval of the ERP Project (Audit & Finance)" at
                                introduction, no parenthetical at action -- and that
                                is the single largest class of near-misses.
   3    ``title_prefix``        paren-stripped, one normalized title is a prefix of
                                the other (the minutes glue the first sentence of the
                                body onto the title), shorter side >=
                                ``TITLE_PREFIX_CHARS`` (40) characters, same era, and
                                either *corroborated* -- equal vendor keys or equal
                                amounts, both non-null -- or the shorter side is at
                                least ``TITLE_PREFIX_SOLO_CHARS`` (60) characters.
                                A vendor-key disagreement always vetoes the tier.
   4    ``vendor_amount``       same vendor key and the same amount to the cent
                                (amount > 0), same era.  Used for the ~19 items whose
                                title was rewritten between the two meetings.
   5    ``title_exact_xera``    tier 1 relaxed to ``ERA_FAMILY`` (see 3).
   6    ``title_nopar_xera``    tier 2 relaxed to ``ERA_FAMILY``.
   ===  ======================  =====================================================

5. **Ambiguity kills the pair.**  Inside a tier, candidates are ranked by day
   gap.  If two or more unclaimed candidates tie for the smallest gap, the
   introduction is left unpaired with reason ``ambiguous`` -- it is never
   broken by item order or by amount.
6. **One action, one introduction.**  Targets are claimed; a claimed action row
   is invisible to later introductions and later tiers.
7. Amount disagreement does **not** veto a pair (20 of 373 exact-title pairs
   disagree -- the amount is routinely refined between introduction and
   action, and the extractors are noisy).  It is recorded as
   ``amount_conflict=true`` instead, so QA can sample it.

**Merge.** The action meeting is the event, so ``meeting_id, meeting_date,
item_no, item_code, section, board_action, vote, era, citation`` come from the
action row.  Every other (detail) field is the union of the two rows with the
action row winning any conflict -- an introduction row often carries a Board
Action Report's ``contract_id`` that the minutes do not repeat.  Both
citations are kept, introduction first: ``citations=[intro, action]``.
``paired=true``; unpaired introductions keep ``board_action="introduced"``,
``paired=false`` and ``unpaired_reason``; pass-through rows get
``paired=null``.

``action_id`` = ``<action meeting date>-<item_no>-<8 hex>`` where the hash is
over the identity of both source rows, so it is stable across reruns and
distinct for two items that share a date and item number across documents.

=============================================================================
Part 2 -- Contract chains
=============================================================================

A chain is one contract over time: the ``new``/``purchase`` root plus every
later ``amendment``/``change_order``/``renewal``/``final_acceptance``.

``chain_method`` (recorded per row):

* ``id`` -- the rows share a normalized ``contract_id`` or ``po_number``
  (upper-cased, non-alphanumerics dropped).  This is the only method that is
  evidence on its own; 682 of 2,044 input rows carry one, and it is the
  dominant method for construction contracts (``D5050`` ties the 2007 award to
  the 2008 final acceptance).
* ``vendor_project`` -- no id, but the rows share a vendor **and** a project.
  Grouping is a union-find over rows of one ``vendor_id`` with two link
  predicates:

  - *project similarity*: the distinctive-token sets of the two titles
    (stopwords, month names, money, and the action vocabulary removed; tokens
    shorter than ``MIN_TOKEN_LEN`` = 4 dropped except levy programs like
    ``BEX V``) satisfy ``Jaccard >= PROJECT_JACCARD`` (0.60) **and** share at
    least ``MIN_SHARED_TOKENS`` (2) tokens.  Long legacy titles (which carry
    the whole item body) score low and therefore under-merge, which is the
    intended failure direction.
  - *money continuity*: one row's ``prior_total`` equals the other's
    ``revised_total`` or ``amount`` to the cent.  This is the strongest signal
    the minutes give ("...for a revised total contract amount of $Z" followed
    months later by "...a prior total of $Z"), so it links regardless of the
    title, but still only inside a single vendor.  Recorded in
    ``chain_evidence``.

  Rows with no vendor key are never grouped this way.
* ``singleton`` -- everything else: the row is its own chain.

Within a chain rows are ordered by (meeting_date, item_no) and numbered
``sequence`` 0..n-1.  The **root** is the first ``new`` or ``purchase`` row,
else sequence 0; ``is_root`` marks it.  ``chain_total_latest`` is the last
non-null ``revised_total`` in date order, else the root's ``amount``, else
null.  ``orphan_amendment=true`` on any amendment/change_order/renewal/
final_acceptance row whose chain contains no ``new``/``purchase`` row at or
before it -- for the 2005-2012 agenda eras this is common and expected, since
the parent contract predates the corpus.

=============================================================================
Known upstream noise this module does not fix
=============================================================================

``action_type="amendment"`` is over-applied by the extractors on the legacy and
archive agendas to *policy* amendments ("Proposed Amendments to Student
Assignment Plan", "Annual Review of Board Bylaws").  Those rows have no vendor
and no contract id, so they land as singletons and are counted as orphan
amendments; the report breaks orphans down by whether a vendor is present so
the noise is separable from real orphans.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

# --------------------------------------------------------------------------
# Thresholds (all documented in the module docstring)
# --------------------------------------------------------------------------
MAX_PAIR_GAP_DAYS = 60
MIN_PAIR_GAP_DAYS = 0
MIN_TITLE_CHARS = 15
TITLE_PREFIX_CHARS = 40
TITLE_PREFIX_SOLO_CHARS = 60
PROJECT_JACCARD = 0.60
MIN_SHARED_TOKENS = 2
MIN_TOKEN_LEN = 4
AMOUNT_EPSILON = 0.01

INTRO_SECTIONS = ("introduction",)
ACTION_SECTIONS = ("consent", "action")
PASSTHROUGH_SECTIONS = ("immediate", "other")
NON_ACTION_BOARD_ACTIONS = ("removed", "withdrawn")

ROOT_ACTION_TYPES = ("new", "purchase")
DESCENDANT_ACTION_TYPES = ("amendment", "change_order", "renewal", "final_acceptance")

# Overlapping-source era families (see docstring rule 3).
ERA_FAMILY = {
    "legacy": "early",
    "archive": "early",
    "blackboard": "wp",   # same site generation/format as wp1620; intro->action pairs straddle 2016-08-01
    "wp1620": "wp",
    "modern": "wp",
}

# Fields taken verbatim from the ACTION row (the event).
EVENT_FIELDS = (
    "meeting_id",
    "meeting_date",
    "item_no",
    "item_code",
    "char_start",
    "era",
    "section",
    "board_action",
    "vote",
)

# Detail fields: union of intro+action, action wins on conflict.
DETAIL_FIELDS = (
    "title",
    "vendor_raw",
    "vendor_name",
    "action_type",
    "amount",
    "amount_kind",
    "prior_total",
    "revised_total",
    "contract_id",
    "po_number",
    "term_start",
    "term_end",
    "department",
    "program_or_project",
    "immediate_action",
    "fund",
    "funding_source_text",
    "procurement_method",
    "llm_confidence",
    "extractor_notes",
)

_CORP_SUFFIXES = {
    "inc", "incorporated", "llc", "llp", "lp", "ltd", "co", "corp", "corporation",
    "company", "pllc", "pc", "ps", "plc", "sa", "nv", "gmbh", "the", "and",
}

_TITLE_STOPWORDS = {
    # generic board / motion vocabulary -- never distinctive of a project
    "approval", "approve", "approved", "authorize", "authorizing", "authorization",
    "superintendent", "board", "directors", "district", "seattle", "public",
    "schools", "school", "item", "items", "would", "this", "that", "with", "from",
    "for", "the", "and", "into", "shall", "will", "amount", "total", "contract",
    "contracts", "agreement", "agreements", "amendment", "amendments", "change",
    "order", "orders", "renewal", "renew", "final", "acceptance", "accept",
    "purchase", "purchases", "award", "awarding", "execute", "execution",
    "enter", "entering", "not", "exceed", "revised", "prior", "consent", "action",
    "introduction", "motion", "vote", "unanimously", "recommendation", "report",
    "department", "departments", "project", "projects", "fiscal", "year", "years",
    "budget", "funds", "funding", "resolution", "including", "between", "regarding",
    "provide", "provided", "services", "service", "work", "portion", "february",
    "january", "march", "april", "june", "july", "august", "september", "october",
    "november", "december", "operations", "executive",
}

_LEVY_RE = re.compile(r"\b(bex|bta)\s+(i{1,3}v?|vi{0,3}|\d)\b", re.I)


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def _date(s):
    return _dt.date.fromisoformat(str(s)[:10])


def school_year(date_str):
    """Sept-Aug school year label, e.g. '2020-21'."""
    d = _date(date_str)
    start = d.year if d.month >= 9 else d.year - 1
    return "%d-%02d" % (start, (start + 1) % 100)


def _norm_title(t):
    t = (t or "").lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_PAREN_RE = re.compile(r"\([^()]*\)")


def _norm_title_nopar(t):
    """`_norm_title` after deleting every parenthesised span (repeatedly, so
    nested parentheses go too).  The legacy agendas append the sponsoring
    department or the superintendent's name in parentheses at introduction and
    drop it -- or replace it -- at action."""
    s = t or ""
    for _ in range(3):
        s2 = _PAREN_RE.sub(" ", s)
        if s2 == s:
            break
        s = s2
    return _norm_title(s)


def _fallback_vendor_key(vendor_raw):
    """Casefold + strip punctuation + drop corporate suffixes. Used only when
    F1's ``vendor_map.jsonl`` is missing (or does not know this string)."""
    if not vendor_raw:
        return None
    s = re.sub(r"[^a-z0-9 ]", " ", str(vendor_raw).lower())
    toks = [t for t in s.split() if t and t not in _CORP_SUFFIXES]
    key = " ".join(toks).strip()
    return key or None


def _norm_id(v):
    if not v:
        return None
    s = re.sub(r"[^A-Za-z0-9]", "", str(v)).upper()
    return s or None


def _amounts_equal(a, b):
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= AMOUNT_EPSILON


def _short_hash(*parts):
    h = hashlib.sha1("|".join("" if p is None else str(p) for p in parts).encode("utf-8"))
    return h.hexdigest()[:8]


def _slug_item_no(item_no):
    s = re.sub(r"[^A-Za-z0-9]", "", str(item_no or "x"))
    return s or "x"


def _project_tokens(title):
    """Distinctive tokens of a title, for the vendor_project chain predicate."""
    norm = _norm_title(title)
    toks = set()
    for m in _LEVY_RE.finditer(title or ""):
        toks.add(("%s%s" % (m.group(1), m.group(2))).lower())
    for t in norm.split():
        if t in _TITLE_STOPWORDS:
            continue
        if t.isdigit():
            continue
        if len(t) < MIN_TOKEN_LEN:
            continue
        toks.add(t)
    return toks


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / float(len(a | b))


# --------------------------------------------------------------------------
# IO
# --------------------------------------------------------------------------
def _read_jsonl(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=False) + "\n")
    os.replace(tmp, path)


def load_vendor_map(out_root):
    """Return (vendor_raw -> vendor_id, vendor_id -> canonical name, source)."""
    vm_path = os.path.join(out_root, "contracts", "vendor_map.jsonl")
    vendors_path = os.path.join(out_root, "contracts", "vendors.jsonl")
    vmap, names = {}, {}
    for r in _read_jsonl(vm_path):
        raw, vid = r.get("vendor_raw"), r.get("vendor_id")
        if raw and vid:
            vmap[raw] = vid
    for r in _read_jsonl(vendors_path):
        vid = r.get("vendor_id")
        if vid:
            names[vid] = r.get("vendor_name") or r.get("canonical_name")
    return vmap, names, ("vendor_map" if vmap else "fallback")


def vendor_key_for(row, vmap):
    """(vendor_id, source). Prefers F1's map, falls back to a local key."""
    raw = row.get("vendor_raw") or row.get("vendor_name")
    if not raw:
        return None, "none"
    if raw in vmap:
        return vmap[raw], "vendor_map"
    return _fallback_vendor_key(raw), "fallback"


# --------------------------------------------------------------------------
# Part 1 -- pairing
# --------------------------------------------------------------------------
def _row_key(r):
    return (r.get("meeting_id"), r.get("item_no"), r.get("char_start"))


def _same_family(a, b):
    fa, fb = ERA_FAMILY.get(a.get("era")), ERA_FAMILY.get(b.get("era"))
    return fa is not None and fa == fb   # two unmapped eras must not pass by accident


def _vendor_conflict(intro, action):
    vi, va = intro.get("_vendor_id"), action.get("_vendor_id")
    return bool(vi and va and vi != va)


def _corroborated(intro, action):
    vi, va = intro.get("_vendor_id"), action.get("_vendor_id")
    if vi and va and vi == va:
        return True
    return _amounts_equal(intro.get("amount"), action.get("amount"))


def _tier_candidates(intro, targets, tier):
    """Targets matching `intro` under one tier, ignoring the claim state."""
    it = _norm_title(intro.get("title"))
    inp = _norm_title_nopar(intro.get("title"))
    out = []
    for a in targets:
        gap = (_date(a["meeting_date"]) - _date(intro["meeting_date"])).days
        if gap < MIN_PAIR_GAP_DAYS or gap > MAX_PAIR_GAP_DAYS:
            continue
        at = _norm_title(a.get("title"))
        anp = _norm_title_nopar(a.get("title"))
        same_era = a.get("era") == intro.get("era")
        if tier == "title_exact":
            if not same_era or len(it) < MIN_TITLE_CHARS or it != at:
                continue
        elif tier == "title_exact_nopar":
            if not same_era or len(inp) < MIN_TITLE_CHARS or inp != anp:
                continue
        elif tier == "title_prefix":
            if not same_era:
                continue
            if _vendor_conflict(intro, a):
                continue
            short, long_ = (inp, anp) if len(inp) <= len(anp) else (anp, inp)
            # (a) one paren-stripped title is a prefix of the other
            ok = (len(short) >= TITLE_PREFIX_CHARS and long_.startswith(short)
                  and (len(short) >= TITLE_PREFIX_SOLO_CHARS or _corroborated(intro, a)))
            # (b) both titles share their first TITLE_PREFIX_SOLO_CHARS characters
            #     (they diverge later: the minutes glue on a different body)
            if not ok:
                ok = (len(it) >= TITLE_PREFIX_SOLO_CHARS and len(at) >= TITLE_PREFIX_SOLO_CHARS
                      and it[:TITLE_PREFIX_SOLO_CHARS] == at[:TITLE_PREFIX_SOLO_CHARS])
            if not ok:
                continue
        elif tier == "vendor_amount":
            if not same_era:
                continue
            vi, va = intro.get("_vendor_id"), a.get("_vendor_id")
            if not vi or not va or vi != va:
                continue
            if intro.get("amount") is None or not _amounts_equal(intro.get("amount"), a.get("amount")):
                continue
            if float(intro.get("amount") or 0) <= 0:
                continue
        elif tier == "title_exact_xera":
            if same_era or not _same_family(intro, a):
                continue
            if len(it) < MIN_TITLE_CHARS or it != at:
                continue
        elif tier == "title_nopar_xera":
            if same_era or not _same_family(intro, a):
                continue
            if len(inp) < MIN_TITLE_CHARS or inp != anp:
                continue
        else:
            raise ValueError(tier)
        out.append((gap, a))
    out.sort(key=lambda p: (p[0], str(p[1].get("meeting_id")), str(p[1].get("item_no"))))
    return out


PAIR_TIERS = (
    "title_exact",
    "title_exact_nopar",
    "title_prefix",
    "vendor_amount",
    "title_exact_xera",
    "title_nopar_xera",
)


def pair_rows(rows):
    """Return (pairs, unpaired_intros, passthrough, actions_unclaimed).

    `pairs` is a list of (intro_row, action_row, tier).  Rejection diagnostics
    for every unpaired introduction are stashed on the row under
    ``_unpaired_reason`` / ``_nearest``.
    """
    intros = [r for r in rows if r.get("section") in INTRO_SECTIONS]
    actions = [
        r for r in rows
        if r.get("section") in ACTION_SECTIONS
        and r.get("board_action") not in NON_ACTION_BOARD_ACTIONS
    ]
    passthrough = [
        r for r in rows
        if r.get("section") in PASSTHROUGH_SECTIONS
        or (r.get("section") in ACTION_SECTIONS and r.get("board_action") in NON_ACTION_BOARD_ACTIONS)
    ]

    claimed = set()
    pairs = []
    paired_intro = set()
    # Tier-major: every introduction gets its best shot at tier 1 before any
    # introduction is allowed to consume a target at tier 2.
    for tier in PAIR_TIERS:
        for intro in intros:
            if _row_key(intro) in paired_intro:
                continue
            cands = [(g, a) for (g, a) in _tier_candidates(intro, actions, tier)
                     if _row_key(a) not in claimed]
            if not cands:
                continue
            best_gap = cands[0][0]
            tied = [a for (g, a) in cands if g == best_gap]
            if len(tied) > 1:
                intro["_ambiguous"] = (tier, best_gap, len(tied))
                continue
            a = tied[0]
            claimed.add(_row_key(a))
            paired_intro.add(_row_key(intro))
            pairs.append((intro, a, tier))

    unpaired = []
    for intro in intros:
        if _row_key(intro) in paired_intro:
            continue
        _diagnose_unpaired(intro, actions, claimed)
        unpaired.append(intro)

    leftovers = [a for a in actions if _row_key(a) not in claimed]
    return pairs, unpaired, passthrough, leftovers


def _diagnose_unpaired(intro, actions, claimed):
    """Attach the nearest plausible candidate and why it was not taken."""
    if intro.get("_ambiguous"):
        tier, gap, n = intro["_ambiguous"]
        intro["_unpaired_reason"] = "ambiguous: %d candidates tied at %dd on tier %s" % (n, gap, tier)
        intro["_nearest"] = None
        return
    it = _norm_title(intro.get("title"))
    idate = _date(intro["meeting_date"])
    best = None
    for a in actions:
        at = _norm_title(a.get("title"))
        gap = (_date(a["meeting_date"]) - idate).days
        score = None
        if it and at and it == at:
            score = (0, abs(gap))
        else:
            j = _jaccard(_project_tokens(intro.get("title")), _project_tokens(a.get("title")))
            if j >= 0.5:
                score = (1, abs(gap))
        if score is None:
            continue
        if best is None or score < best[0]:
            best = (score, a, gap)
    if best is None:
        intro["_unpaired_reason"] = "no candidate action row with a similar title in any window"
        intro["_nearest"] = None
        return
    _score, a, gap = best
    if gap < MIN_PAIR_GAP_DAYS:
        why = "nearest candidate is %d days BEFORE the introduction" % (-gap,)
    elif gap > MAX_PAIR_GAP_DAYS:
        why = "nearest candidate is %d days later (> %d-day window)" % (gap, MAX_PAIR_GAP_DAYS)
    elif _row_key(a) in claimed:
        why = "nearest candidate (%dd) already claimed by another introduction" % gap
    elif not _same_family(intro, a):
        why = "nearest candidate (%dd) is in era %s, a different era family" % (gap, a.get("era"))
    elif _vendor_conflict(intro, a):
        why = "nearest candidate (%dd) names a different vendor (%s vs %s)" % (
            gap, intro.get("vendor_raw"), a.get("vendor_raw"))
    elif len(it) < MIN_TITLE_CHARS:
        why = "title shorter than %d chars, exact-title tier not allowed" % MIN_TITLE_CHARS
    else:
        why = "title only similar, not equal (below every tier's threshold)"
    intro["_unpaired_reason"] = why
    intro["_nearest"] = {
        "meeting_date": a.get("meeting_date"),
        "item_no": a.get("item_no"),
        "era": a.get("era"),
        "title": (a.get("title") or "")[:120],
        "gap_days": gap,
    }


def _merge_detail(intro, action):
    out = {}
    for f in DETAIL_FIELDS:
        av = action.get(f) if action else None
        iv = intro.get(f) if intro else None
        out[f] = av if av not in (None, "", []) else iv
    return out


def build_action_rows(rows, vmap, vnames):
    for r in rows:
        vid, src = vendor_key_for(r, vmap)
        r["_vendor_id"] = vid
        r["_vendor_id_source"] = src

    pairs, unpaired, passthrough, leftovers = pair_rows(rows)
    out = []

    def _base(action, intro, paired, pair_method):
        src = action if action is not None else intro
        row = {}
        for f in EVENT_FIELDS:
            row[f] = src.get(f)
        row.update(_merge_detail(intro, action))
        vid, vsrc = vendor_key_for(row, vmap)
        row["vendor_id"] = vid
        row["vendor_id_source"] = vsrc
        row["vendor_canonical"] = vnames.get(vid) if vid else None
        row["school_year"] = school_year(row["meeting_date"])
        cits = []
        if intro is not None and intro.get("citation"):
            cits.append(dict(intro["citation"], role="introduction",
                             meeting_date=intro.get("meeting_date")))
        if action is not None and action.get("citation"):
            cits.append(dict(action["citation"], role="action",
                             meeting_date=action.get("meeting_date")))
        row["citations"] = cits
        row["paired"] = paired
        row["pair_method"] = pair_method
        row["intro_meeting_id"] = intro.get("meeting_id") if intro is not None else None
        row["intro_meeting_date"] = intro.get("meeting_date") if intro is not None else None
        row["intro_item_no"] = intro.get("item_no") if intro is not None else None
        row["intro_era"] = intro.get("era") if intro is not None else None
        row["extractor"] = src.get("extractor")
        row["intro_extractor"] = intro.get("extractor") if intro is not None else None
        row["amount_conflict"] = bool(
            intro is not None and action is not None
            and intro.get("amount") is not None and action.get("amount") is not None
            and not _amounts_equal(intro.get("amount"), action.get("amount"))
        )
        # How much the two titles actually agree, for H1's sampling: a
        # `vendor_amount` pair whose titles share nothing is the highest-risk
        # class of pairing this module produces.
        row["title_similarity"] = round(
            _jaccard(_project_tokens(intro.get("title")), _project_tokens(action.get("title"))), 3
        ) if (intro is not None and action is not None) else None
        row["unpaired_reason"] = None
        row["action_id"] = "%s-%s-%s" % (
            row["meeting_date"],
            _slug_item_no(row["item_no"]),
            _short_hash(
                src.get("meeting_id"), src.get("item_no"), src.get("char_start"),
                intro.get("meeting_id") if intro is not None else None,
                intro.get("item_no") if intro is not None else None,
                intro.get("char_start") if intro is not None else None,
            ),
        )
        return row

    for intro, action, tier in pairs:
        out.append(_base(action, intro, True, tier))
    for intro in unpaired:
        row = _base(None, intro, False, None)
        row["board_action"] = intro.get("board_action") or "introduced"
        row["unpaired_reason"] = intro.get("_unpaired_reason")
        row["_nearest"] = intro.get("_nearest")
        out.append(row)
    for a in leftovers:
        out.append(_base(a, None, False, None))
    for p in passthrough:
        row = _base(p, None, None, None)
        out.append(row)

    out.sort(key=lambda r: (r["meeting_date"], str(r.get("item_no") or ""), r["action_id"]))
    return out, pairs, unpaired, passthrough, leftovers


# --------------------------------------------------------------------------
# Part 2 -- chains
# --------------------------------------------------------------------------
class _DSU(object):
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def build_chains(actions):
    """Assign chain_id / sequence / chain_method / chain_total_latest in place."""
    dsu = _DSU()
    method = {}
    evidence = defaultdict(list)

    # (a) id method -----------------------------------------------------
    by_id = defaultdict(list)
    for r in actions:
        key = _norm_id(r.get("contract_id")) or _norm_id(r.get("po_number"))
        r["_id_key"] = key
        if key:
            by_id[key].append(r)
    for key, group in by_id.items():
        anchor = group[0]["action_id"]
        for r in group:
            dsu.union(anchor, r["action_id"])
            method[dsu.find(anchor)] = ("id", key)
        if len(group) > 1:
            for r in group:
                evidence[r["action_id"]].append("contract_id=%s" % key)

    # (b) vendor_project method ------------------------------------------
    # Only rows that carry NO contract id / PO participate.  Letting an
    # id-bearing row into a fuzzy vendor+project cluster lets one bad
    # `contract_id` from the extractors drag a whole id block into an
    # unrelated chain (observed: a "K5111" mis-stamped on a Yellow Wood
    # Academy amendment merged Wayne's Roofing with Yellow Wood Academy), and
    # single-linkage would then bridge two distinct contract ids.  Id blocks
    # stay closed; vendor_project only chains the id-less remainder.
    by_vendor = defaultdict(list)
    for r in actions:
        if r.get("vendor_id") and not r.get("_id_key"):
            by_vendor[r["vendor_id"]].append(r)
    for vid, group in by_vendor.items():
        toks = {r["action_id"]: _project_tokens(r.get("title")) for r in group}
        n = len(group)
        for i in range(n):
            ri = group[i]
            for j in range(i + 1, n):
                rj = group[j]
                linked = None
                if _amounts_equal(ri.get("prior_total"), rj.get("revised_total")) or \
                   _amounts_equal(rj.get("prior_total"), ri.get("revised_total")) or \
                   _amounts_equal(ri.get("prior_total"), rj.get("amount")) or \
                   _amounts_equal(rj.get("prior_total"), ri.get("amount")):
                    linked = "money_continuity"
                else:
                    ti, tj = toks[ri["action_id"]], toks[rj["action_id"]]
                    if len(ti & tj) >= MIN_SHARED_TOKENS and _jaccard(ti, tj) >= PROJECT_JACCARD:
                        linked = "project_tokens"
                if linked:
                    dsu.union(ri["action_id"], rj["action_id"])
                    root = dsu.find(ri["action_id"])
                    method.setdefault(root, ("vendor_project", vid))
                    evidence[ri["action_id"]].append(linked)
                    evidence[rj["action_id"]].append(linked)

    # (c) assemble --------------------------------------------------------
    groups = defaultdict(list)
    for r in actions:
        groups[dsu.find(r["action_id"])].append(r)

    chains = []
    for root_key, group in groups.items():
        group.sort(key=lambda r: (r["meeting_date"], str(r.get("item_no") or ""), r["action_id"]))
        meth, mkey = method.get(root_key, (None, None))
        if len(group) == 1:
            meth, mkey = "singleton", group[0]["action_id"]
        elif meth is None:
            meth, mkey = "singleton", root_key
        # One vendor can own several distinct projects, so the vendor id alone
        # is not a unique chain key -- the earliest member's action_id
        # disambiguates and is deterministic for a given grouping.
        if meth == "id":
            chain_id = "CH-I-%s" % _short_hash(meth, mkey)
        else:
            chain_id = "CH-%s-%s" % (meth[0].upper(),
                                     _short_hash(meth, mkey, group[0]["action_id"]))
        root_row = None
        for r in group:
            if r.get("action_type") in ROOT_ACTION_TYPES:
                root_row = r
                break
        if root_row is None:
            root_row = group[0]
        latest_revised = None
        for r in group:
            if r.get("revised_total") is not None:
                latest_revised = r["revised_total"]
        chain_total = latest_revised if latest_revised is not None else root_row.get("amount")
        seen_root = False
        for seq, r in enumerate(group):
            r["chain_id"] = chain_id
            r["sequence"] = seq
            r["chain_method"] = meth
            r["chain_size"] = len(group)
            r["chain_total_latest"] = chain_total
            r["is_root"] = (r is root_row)
            r["chain_evidence"] = sorted(set(evidence.get(r["action_id"], []))) or None
            if r.get("action_type") in ROOT_ACTION_TYPES:
                seen_root = True
            r["orphan_amendment"] = bool(
                r.get("action_type") in DESCENDANT_ACTION_TYPES and not seen_root
            )
            r.pop("_id_key", None)
        chains.append((chain_id, group))
    chains.sort(key=lambda c: (c[1][0]["meeting_date"], c[0]))
    return chains


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def _pct(n, d):
    return "0.0%" if not d else "%.1f%%" % (100.0 * n / d)


def write_report(path, actions, pairs, unpaired, passthrough, leftovers, chains,
                 vendor_source, n_input):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    L = []
    A = L.append
    A("# F2 link report -- intro/action pairing and contract chains\n")
    A("Generated by `extractors/sps_web/link.py`. Thresholds: pairing window "
      "%d-%d days, exact-title tier needs >=%d chars, prefix tier %d chars, "
      "project Jaccard >=%.2f with >=%d shared tokens.\n"
      % (MIN_PAIR_GAP_DAYS, MAX_PAIR_GAP_DAYS, MIN_TITLE_CHARS,
         TITLE_PREFIX_CHARS, PROJECT_JACCARD, MIN_SHARED_TOKENS))
    A("Vendor identity source: **%s** (`contracts/vendor_map.jsonl` %s).\n"
      % (vendor_source, "present" if vendor_source == "vendor_map" else "absent -- rerun after F1"))

    A("## Totals\n")
    A("| quantity | n |")
    A("|---|---|")
    A("| input rows (`extracted.jsonl`) | %d |" % n_input)
    A("| output action rows | %d |" % len(actions))
    A("| paired intro+action | %d |" % len(pairs))
    A("| unpaired introductions | %d |" % len(unpaired))
    A("| action rows with no introduction | %d |" % len(leftovers))
    A("| pass-through (immediate / other / removed) | %d |" % len(passthrough))
    A("")
    A("Pair tiers: " + ", ".join("`%s`=%d" % (k, v) for k, v in
                                 sorted(Counter(t for _, _, t in pairs).items())) + "\n")

    # ---- pairing rate by era
    A("## Pairing rate by era\n")
    tot = Counter()
    got = Counter()
    for i, _a, _t in pairs:
        tot[i["era"]] += 1
        got[i["era"]] += 1
    for i in unpaired:
        tot[i["era"]] += 1
    A("| era | introductions | paired | rate |")
    A("|---|---:|---:|---:|")
    for era in sorted(tot):
        A("| %s | %d | %d | %s |" % (era, tot[era], got[era], _pct(got[era], tot[era])))
    A("| **all** | %d | %d | %s |" % (sum(tot.values()), sum(got.values()),
                                      _pct(sum(got.values()), sum(tot.values()))))
    A("")

    # ---- pairing rate by school year
    A("## Pairing rate by school year\n")
    tot_y, got_y = Counter(), Counter()
    for i, _a, _t in pairs:
        y = school_year(i["meeting_date"])
        tot_y[y] += 1
        got_y[y] += 1
    for i in unpaired:
        tot_y[school_year(i["meeting_date"])] += 1
    A("| school year | introductions | paired | rate |")
    A("|---|---:|---:|---:|")
    for y in sorted(tot_y):
        A("| %s | %d | %d | %s |" % (y, tot_y[y], got_y[y], _pct(got_y[y], tot_y[y])))
    A("")

    # ---- riskiest pairs
    risky = sorted(
        [r for r in actions if r.get("paired") and (r.get("title_similarity") or 0) < 0.2],
        key=lambda r: r["meeting_date"])
    A("## Highest-risk pairs (title similarity < 0.20) -- %d\n" % len(risky))
    A("These pairs rest on the vendor and the amount, not on the title, "
      "usually because the segmenter gave the action row a wrong title "
      "(\"Warrants\", \"Personnel Report\"). Sample these first in H1.\n")
    A("| action date | intro date | method | sim | vendor | amount | action-row title |")
    A("|---|---|---|---:|---|---:|---|")
    for r in risky:
        A("| %s | %s | %s | %.2f | %s | %s | %s |" % (
            r["meeting_date"], r["intro_meeting_date"], r["pair_method"],
            r.get("title_similarity") or 0.0,
            (r.get("vendor_raw") or "")[:28].replace("|", "/"), r.get("amount"),
            (r.get("title") or "")[:60].replace("|", "/")))
    A("")

    # ---- unpaired list
    A("## Unpaired introductions (%d)\n" % len(unpaired))
    A("Reason histogram:\n")
    rh = Counter(re.sub(r"\d+", "N", i.get("_unpaired_reason") or "?") for i in unpaired)
    for k, v in rh.most_common():
        A("* %d -- %s" % (v, k))
    A("")
    A("| intro date | era | item | title | nearest candidate | why rejected |")
    A("|---|---|---|---|---|---|")
    for i in sorted(unpaired, key=lambda r: r["meeting_date"]):
        near = i.get("_nearest")
        neartxt = ("%s %s (+%dd) %s" % (near["meeting_date"], near["item_no"],
                                        near["gap_days"], near["title"][:60])) if near else "--"
        A("| %s | %s | %s | %s | %s | %s |" % (
            i["meeting_date"], i["era"], i.get("item_no"),
            (i.get("title") or "")[:70].replace("|", "/"),
            neartxt.replace("|", "/"),
            (i.get("_unpaired_reason") or "").replace("|", "/")))
    A("")

    # ---- orphan amendments
    orphans = [r for r in actions if r.get("orphan_amendment")]
    with_vendor = [r for r in orphans if r.get("vendor_id")]
    A("## Orphan amendments (%d)\n" % len(orphans))
    A("No `new`/`purchase` root at or before them in their chain. %d have a "
      "vendor (candidate real orphans -- the parent contract predates the "
      "corpus or its meeting's minutes are missing); %d have none and are "
      "mostly the extractors' policy-amendment false positives.\n"
      % (len(with_vendor), len(orphans) - len(with_vendor)))
    A("| era | orphans | of which with a vendor |")
    A("|---|---:|---:|")
    oe, ov = Counter(), Counter()
    for r in orphans:
        oe[r["era"]] += 1
        if r.get("vendor_id"):
            ov[r["era"]] += 1
    for era in sorted(oe):
        A("| %s | %d | %d |" % (era, oe[era], ov[era]))
    A("")
    A("First 40 orphans with a vendor:\n")
    A("| date | era | action_type | vendor | amount | title |")
    A("|---|---|---|---|---:|---|")
    for r in with_vendor[:40]:
        A("| %s | %s | %s | %s | %s | %s |" % (
            r["meeting_date"], r["era"], r.get("action_type"),
            (r.get("vendor_raw") or "")[:34].replace("|", "/"),
            r.get("amount"), (r.get("title") or "")[:60].replace("|", "/")))
    A("")

    # ---- chains
    A("## Chains\n")
    sizes = Counter(len(g) for _c, g in chains)
    mm = Counter(g[0]["chain_method"] for _c, g in chains)
    A("| chain_method | chains | rows |")
    A("|---|---:|---:|")
    for k in sorted(mm):
        A("| %s | %d | %d |" % (k, mm[k], sum(len(g) for _c, g in chains if g[0]["chain_method"] == k)))
    A("| **all** | %d | %d |" % (len(chains), sum(len(g) for _c, g in chains)))
    A("")
    A("Size distribution:\n")
    A("| chain size | chains |")
    A("|---:|---:|")
    for s in sorted(sizes):
        A("| %d | %d |" % (s, sizes[s]))
    A("")

    # ---- 10 example chains
    multi = [c for c in chains if len(c[1]) > 1]
    multi.sort(key=lambda c: (-len(c[1]), c[0]))
    by_id = [c for c in multi if c[1][0]["chain_method"] == "id"][:5]
    by_vp = [c for c in multi if c[1][0]["chain_method"] == "vendor_project"][:5]
    examples = by_id + by_vp
    seen = set()
    A("## 10 example chains\n")
    n = 0
    for chain_id, group in examples:
        if chain_id in seen:
            continue
        seen.add(chain_id)
        n += 1
        if n > 10:
            break
        head = group[0]
        A("**%d. `%s`** (method=%s, size=%d, latest total=%s) -- vendor `%s`\n"
          % (n, chain_id, head["chain_method"], len(group),
             head.get("chain_total_latest"), head.get("vendor_raw") or head.get("vendor_id")))
        for r in group:
            A("  * `%s` seq %d %s%s -- **%s** amount=%s revised_total=%s -- %s"
              % (r["meeting_date"], r["sequence"], r.get("action_type"),
                 " (root)" if r.get("is_root") else "",
                 r.get("board_action"), r.get("amount"), r.get("revised_total"),
                 (r.get("title") or "")[:70]))
        A("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    return "\n".join(L)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def run(out_root="out_sps_web", era=None, extracted=None):
    extracted = extracted or os.path.join(out_root, "contracts", "extracted.jsonl")
    rows = _read_jsonl(extracted)
    if not rows:
        raise SystemExit("no rows read from %s" % extracted)
    n_input = len(rows)
    if era:
        rows = [r for r in rows if r.get("era") == era]

    vmap, vnames, vsource = load_vendor_map(out_root)
    actions, pairs, unpaired, passthrough, leftovers = build_action_rows(rows, vmap, vnames)
    chains = build_chains(actions)

    clean = []
    for r in actions:
        r.pop("_nearest", None)
        clean.append({k: v for k, v in r.items() if not k.startswith("_")})
    out_path = os.path.join(out_root, "contracts", "contract_actions.jsonl")
    _write_jsonl(out_path, clean)

    rpt = os.path.join(out_root, "qa", "link_report.md")
    write_report(rpt, actions, pairs, unpaired, passthrough, leftovers, chains,
                 vsource, n_input)
    print("wrote %s (%d rows) and %s" % (out_path, len(clean), rpt))
    print("paired=%d unpaired_intro=%d passthrough=%d action_only=%d chains=%d"
          % (len(pairs), len(unpaired), len(passthrough), len(leftovers), len(chains)))
    return clean, chains


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out-root", default="out_sps_web")
    ap.add_argument("--extracted", default=None)
    ap.add_argument("--era", default=None)
    args = ap.parse_args(argv)
    run(out_root=args.out_root, era=args.era, extracted=args.extracted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
