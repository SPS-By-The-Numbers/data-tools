"""Reconciliation checks for the board-contracts pipeline (PLAN.md task H2).

Runs checks that do not need a human, over the outputs of Phases A-F, and
writes ``out_sps_web/qa/reconcile_report.md`` with a PASS/WARN/FAIL verdict
per check, counts, and up to 10 examples per failing check. Exits non-zero
if any check FAILs.

**This is meant to be rerun.** As of the first run (2026-08-24) the Wayback
crawl (Phase B, blackboard/legacy/archive eras) and a following
extract/link rerun are both still in flight, so gaps that are really just
"not fetched yet" are expected and reported as such (WARN, not FAIL) rather
than papered over. Rerun after the crawl/extract/link settle and diff the
report.

Usage (from the repo root)::

    $ venv/bin/python3 -m extractors.sps_web.reconcile
    $ venv/bin/python3 -m extractors.sps_web.reconcile --no-network
    $ venv/bin/python3 -m extractors.sps_web.reconcile --sample 20
    $ venv/bin/python3 -m extractors.sps_web.reconcile --out-root /tmp/scratch

Inputs read (all under ``--out-root``, default ``out_sps_web/``) and the
subset of each schema this module relies on:

* ``manifest/meetings.jsonl`` -- one row per meeting: ``meeting_id, date,
  type, title, ...``. Cancelled meetings are detected from ``title``
  (``Cancel``/``Canceled``/``Cancelled``, any case, anywhere in the string
  -- legacy titles say "Canceled:", others say "... CANCELLED").
* ``manifest/documents_classified.jsonl`` (falls back to
  ``manifest/documents.jsonl`` if C2 hasn't run yet) -- one row per
  document: ``doc_id, meeting_id, source_url, fetch {kind, url, token?},
  kind`` (C2's re-derived document type, ``null`` if the doc hasn't been
  fetched yet), ``has_text`` (bool), ``pages`` (int|null, from C1's
  textmeta -- may be stale vs. the live ``text/**/*.textmeta.json`` files,
  which this module also reads directly for the citation page-bounds
  check).
* ``items/*.jsonl`` (one file per meeting, D1/D2) -- one row per segmented
  agenda/minutes item: ``meeting_id, item_no, char_start, char_end,
  page_start, page_end, source_doc_id, ...``.
* ``contracts/extracted.jsonl`` (E1/E2) -- one row per *admitted* item (the
  contract-like pre-filter passed): ``meeting_id, meeting_date, item_no,
  char_start, era, vendor_raw, action_type, amount, amount_kind,
  prior_total, revised_total, citation {doc_id, page_start, page_end},
  extractor, ...``. This is the "admitted items" series in check 6 --
  ``manual_review.jsonl`` rows are a subset of this file (still-null
  fields awaiting a second E2 round), not a separate population.
* ``contracts/contract_actions.jsonl`` (F2 ``link.py``) -- one row per
  linked contract *action* (introduction+action merged, or a singleton):
  everything in ``extracted.jsonl`` plus ``vendor_id, vendor_id_source
  (vendor_map|fallback|none), vendor_canonical, school_year, citations``
  (list of ``{doc_id, page_start, page_end, role, meeting_date}``,
  0-2 entries), ``paired (bool), intro_meeting_date, action_id (unique),
  chain_id, sequence (0-based, contiguous within a chain), chain_size``.
* ``contracts/vendors.jsonl`` (F1 ``vendors.py``) -- one row per canonical
  vendor: ``vendor_id, canonical_name, vendor_class, ...``.
* ``contracts/vendor_map.jsonl`` (F1, same run) -- one row per raw vendor
  string seen in ``extracted.jsonl``: ``vendor_raw, vendor_id (null for
  ``vendor_class == "not_a_vendor"``), vendor_class``. Not in the H2 card's
  input list verbatim, but it is the *only* place the ``not_a_vendor`` flag
  the card asks for (check 4) actually lives, so this module reads it too;
  a stale copy (F1 run before the latest F2/E2 merge) shows up as check 4
  WARN/FAIL findings rather than silently passing.
* ``contracts/manual_review.jsonl`` -- residual items E2 could not fill
  after two rounds; read only to report a count for context (they are
  already counted inside ``extracted.jsonl``, see above).
* ``text/**/*.textmeta.json`` (C1) -- one file per fetched document:
  ``doc_id, pages, chars, method, ocr_pages, error``. This is the
  authoritative ``doc_id -> pages`` map used for the citation page-bounds
  check (independent of whatever ``documents_classified.jsonl`` cached).
* ``qa/coverage_matrix.md`` (A3), if present -- used only to look up, for a
  school year flagged by check 6 as a >50% dip, whether that year still has
  documents pending fetch (parsed from its "Documents to fetch, by era"
  table) -- i.e. whether the crawl explains the dip.

Output: ``qa/reconcile_report.md``.

The seven checks (see PLAN.md Sec. 3 H2 for the prose spec):

1. Every meeting has >=1 agenda/minutes doc fetched *with text*, or a
   reason (``cancelled``, ``no_docs``, ``not_fetched``, ``text_failed``, or
   the residual ``fetched_no_agenda_minutes`` -- fetched and classified,
   but nothing came out as agenda/minutes).
2. Every ``contract_actions.jsonl`` citation resolves: ``doc_id`` is in the
   manifest, ``page_start <= page_end <= pages`` (from textmeta, when
   known), the resolved fetch URL is well-formed; a random sample of N
   unique cited documents (``--sample``, default 40) gets a live
   HEAD-then-Range-GET check, 1 req/s per host, User-Agent
   ``sps-data-tools/board-contracts (github.com/SPS-By-The-Numbers)``
   (``--no-network`` skips this).
3. Money sanity: amounts in [0, 2e9]; ``revised_total >= amount`` for
   amendments/change orders; ``prior_total + amount == revised_total``
   when all three are present **on an amendment/change order** (that identity
   assumes ``amount`` is the increment; a final_acceptance closeout's
   ``amount`` is the final total, so those rows are excluded) -- mismatch rate
   + examples; ``amount_kind``
   present whenever ``amount`` is.
4. Vendors: every ``vendor_raw`` maps to a ``vendor_id`` that exists in
   ``vendors.jsonl``, or is flagged ``not_a_vendor`` in ``vendor_map.jsonl``.
5. Pairing/chains: no ``action_id`` claimed by two chains; ``sequence``
   contiguous per chain; no paired intro dated after its action.
6. Time series: action rows (``contract_actions.jsonl``) and admitted items
   (``extracted.jsonl``) per school year, as a table + ASCII sparkline;
   flags a year that drops >50% vs. *both* neighbours and reports whether
   ``coverage_matrix.md`` explains it (pending-fetch count > 0 that year).
7. Key uniqueness: ``action_id`` unique in ``contract_actions.jsonl``
   (a multi-vendor motion's co-vendor rows carry ``<primary>-v2``, ``-v3``,
   ... ids -- those are accepted, and each is checked to name a real primary
   row via ``multi_vendor_group`` with a matching ``multi_vendor_n``);
   ``(meeting_id, item_no, char_start)`` unique across ``items/*.jsonl``.
"""

from __future__ import annotations

import argparse
import collections
import datetime as _dt
import glob
import json
import os
import random
import re
import socket
import sys
import time
import urllib.error as urlerror
import urllib.request as urlrequest
from urllib.parse import urlparse

NETWORK_USER_AGENT = "sps-data-tools/board-contracts (github.com/SPS-By-The-Numbers)"
CANCEL_RE = re.compile(r"cancel", re.I)
AMENDMENT_LIKE_TYPES = {"amendment", "change_order"}
MAX_REASONABLE_AMOUNT = 2_000_000_000
_ASCII_RAMP = " .:-=+*#%@"


# --------------------------------------------------------------------------
# generic I/O helpers
# --------------------------------------------------------------------------
def read_jsonl(path):
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def read_jsonl_glob(pattern):
    rows = []
    for path in sorted(glob.glob(pattern)):
        rows.extend(read_jsonl(path))
    return rows


def load_textmeta_pages(out_root):
    """doc_id -> pages, scanned straight from text/**/*.textmeta.json."""
    pages = {}
    pattern = os.path.join(out_root, "text", "**", "*.textmeta.json")
    for path in glob.glob(pattern, recursive=True):
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            continue
        doc_id = d.get("doc_id")
        if doc_id:
            pages[doc_id] = d.get("pages")
    return pages


def school_year(date_str):
    """Sept-Aug school year label, e.g. '2020-21'. Mirrors link.py."""
    if not date_str:
        return None
    try:
        d = _dt.date.fromisoformat(str(date_str)[:10])
    except ValueError:
        return None
    start = d.year if d.month >= 9 else d.year - 1
    return "%d-%02d" % (start, (start + 1) % 100)


def doc_url(doc):
    """The URL that was actually used (or would be used) to fetch a
    document's bytes -- the "primary source" a citation resolves to."""
    fetch = doc.get("fetch") or {}
    url = fetch.get("url") or doc.get("source_url")
    if url and fetch.get("kind") == "wayback_raw":
        url = url.replace("http://web.archive.org/", "https://web.archive.org/", 1)
    return url


def well_formed_url(url):
    if not url:
        return False
    p = urlparse(url)
    return p.scheme in ("http", "https") and bool(p.netloc)


# --------------------------------------------------------------------------
# Check result container
# --------------------------------------------------------------------------
class Check:
    def __init__(self, key, title):
        self.key = key
        self.title = title
        self.status = "PASS"
        self.summary = ""
        self.counts = []      # [(label, value), ...]
        self.examples = []    # [str, ...], caller caps at 10
        self.notes = []       # free-form markdown blocks (tables, sparklines)

    def set(self, status, summary):
        assert status in ("PASS", "WARN", "FAIL")
        self.status = status
        self.summary = summary


# --------------------------------------------------------------------------
# Check 1 -- meeting coverage
# --------------------------------------------------------------------------
def check_meeting_coverage(meetings, docs_by_meeting):
    c = Check("1", "Meeting coverage (agenda/minutes text)")
    reasons = collections.Counter()
    examples = collections.defaultdict(list)
    covered = 0

    for m in meetings:
        mid = m.get("meeting_id")
        docs = docs_by_meeting.get(mid, [])
        am_text = [d for d in docs if d.get("kind") in ("agenda", "minutes") and d.get("has_text")]
        if am_text:
            covered += 1
            continue
        if CANCEL_RE.search(m.get("title") or ""):
            reasons["cancelled"] += 1
            continue
        if not docs:
            reasons["no_docs"] += 1
            examples["no_docs"].append(f"{mid} ({m.get('date')}) -- 0 documents in manifest")
            continue
        fetched = [d for d in docs if d.get("kind") is not None]
        if not fetched:
            reasons["not_fetched"] += 1
            examples["not_fetched"].append(
                f"{mid} ({m.get('date')}) -- {len(docs)} doc(s) in manifest, none fetched/classified yet")
            continue
        am_fetched = [d for d in fetched if d.get("kind") in ("agenda", "minutes")]
        if am_fetched:
            reasons["text_failed"] += 1
            examples["text_failed"].append(
                f"{mid} ({m.get('date')}) -- agenda/minutes fetched but no text: "
                + ", ".join(d.get("doc_id", "?") for d in am_fetched[:3]))
            continue
        reasons["fetched_no_agenda_minutes"] += 1
        kinds = sorted({str(d.get("kind")) for d in fetched})
        examples["fetched_no_agenda_minutes"].append(
            f"{mid} ({m.get('date')}) -- {len(fetched)} doc(s) fetched, kinds={kinds}, none agenda/minutes")

    total = len(meetings)
    bad = reasons["text_failed"] + reasons["fetched_no_agenda_minutes"]
    provisional = reasons["no_docs"] + reasons["not_fetched"]
    rate = bad / total if total else 0.0

    c.counts = [
        ("total meetings", total),
        ("covered (agenda/minutes with text)", covered),
        ("cancelled", reasons["cancelled"]),
        ("no docs in manifest", reasons["no_docs"]),
        ("not fetched/classified yet (crawl in progress)", reasons["not_fetched"]),
        ("fetched but text extraction failed", reasons["text_failed"]),
        ("fetched+classified, but no agenda/minutes kind", reasons["fetched_no_agenda_minutes"]),
    ]
    if rate > 0.05:
        c.set("FAIL", f"{bad}/{total} meetings ({rate:.1%}) have documents but no usable agenda/minutes text")
    elif bad:
        c.set("WARN", f"{bad}/{total} meetings ({rate:.1%}) have documents but no usable agenda/minutes text")
    elif provisional:
        c.set("WARN", f"{provisional}/{total} meetings still awaiting fetch (provisional -- crawl in progress); "
                       f"{covered} already covered, {reasons['cancelled']} cancelled")
    else:
        c.set("PASS", f"all {total} meetings have agenda/minutes text or an explained reason")
    c.examples = (examples["text_failed"] + examples["fetched_no_agenda_minutes"]
                  + examples["not_fetched"] + examples["no_docs"])[:10]
    return c


# --------------------------------------------------------------------------
# Check 2 -- citations
# --------------------------------------------------------------------------
class _HostPacer:
    """1 request/s per host, blocking."""

    def __init__(self, interval=1.0):
        self.interval = interval
        self._next = collections.defaultdict(float)

    def wait(self, host):
        now = time.monotonic()
        nxt = self._next[host]
        if nxt > now:
            time.sleep(nxt - now)
        self._next[host] = max(now, nxt) + self.interval


def _check_one_url(url, opener, pacer, timeout=15):
    host = urlparse(url).hostname or "?"
    pacer.wait(host)
    req = urlrequest.Request(url, method="HEAD", headers={"User-Agent": NETWORK_USER_AGENT})
    try:
        resp = opener.open(req, timeout=timeout)
        return resp.status or resp.getcode(), "HEAD"
    except urlerror.HTTPError as e:
        if e.code in (403, 405, 501):
            pacer.wait(host)
            req2 = urlrequest.Request(
                url, headers={"User-Agent": NETWORK_USER_AGENT, "Range": "bytes=0-0"})
            try:
                resp2 = opener.open(req2, timeout=timeout)
                return resp2.status or resp2.getcode(), f"GET-range (HEAD->{e.code})"
            except urlerror.HTTPError as e2:
                return e2.code, "GET-range"
            except (urlerror.URLError, OSError, socket.timeout) as e2:
                return "error", f"GET-range: {e2}"
        return e.code, "HEAD"
    except (urlerror.URLError, OSError, socket.timeout) as e:
        return "error", f"HEAD: {e}"


def run_network_sample(sample):
    """sample: [(doc_id, url), ...] -> [(doc_id, url, status, note), ...]"""
    opener = urlrequest.build_opener()
    pacer = _HostPacer(1.0)
    results = []
    for doc_id, url in sample:
        if not url:
            results.append((doc_id, url, "error", "no url"))
            continue
        status, note = _check_one_url(url, opener, pacer)
        results.append((doc_id, url, status, note))
    return results


def check_citations(actions, doc_index, pages_by_doc, sample_n, no_network, seed):
    c = Check("2", "Citation resolution")
    total_cit = 0
    unresolved, bad_url, bad_pages = [], [], []
    pages_unknown = 0
    unique_docs = {}

    for a in actions:
        for cit in a.get("citations") or []:
            total_cit += 1
            doc_id = cit.get("doc_id")
            doc = doc_index.get(doc_id)
            if doc is None:
                unresolved.append(f"{a.get('action_id')}: citation doc_id {doc_id!r} not in manifest")
                continue
            url = doc_url(doc)
            unique_docs.setdefault(doc_id, url)
            if not well_formed_url(url):
                bad_url.append(f"{a.get('action_id')}: doc {doc_id} url {url!r} not well-formed")
            pages = pages_by_doc.get(doc_id)
            if pages is None:
                pages_unknown += 1
                continue
            ps, pe = cit.get("page_start"), cit.get("page_end")
            if not (isinstance(ps, int) and isinstance(pe, int) and 1 <= ps <= pe <= pages):
                bad_pages.append(f"{a.get('action_id')}: doc {doc_id} page_start={ps} page_end={pe} pages={pages}")

    c.counts = [
        ("total citations", total_cit),
        ("unique cited documents", len(unique_docs)),
        ("doc_id not found in manifest", len(unresolved)),
        ("malformed source URL", len(bad_url)),
        ("page_start/page_end out of [1, pages] (pages known)", len(bad_pages)),
        ("pages not yet known (doc not text-extracted)", pages_unknown),
    ]

    net_failures = []
    sample = []
    if no_network:
        c.notes = ["network HEAD/GET-range check skipped (`--no-network`)."]
    else:
        rng = random.Random(seed)
        pop = list(unique_docs.items())
        sample = rng.sample(pop, min(sample_n, len(pop)))
        results = run_network_sample(sample)
        status_counts = collections.Counter(r[2] for r in results)
        for doc_id, url, status, note in results:
            if not (isinstance(status, int) and 200 <= status < 400):
                net_failures.append(f"doc {doc_id} -> {status} [{note}] ({url})")
        c.counts.append(("sampled for live check", f"{len(sample)}/{len(pop)}"))
        c.notes = ["Sampled status codes: "
                   + ", ".join(f"{k}={v}" for k, v in sorted(status_counts.items(), key=lambda kv: str(kv[0])))]

    structural_bad = len(unresolved) + len(bad_url) + len(bad_pages)
    if structural_bad:
        c.set("FAIL", f"{structural_bad} structural citation problems "
                       f"({len(unresolved)} unresolved doc_id, {len(bad_url)} malformed URL, "
                       f"{len(bad_pages)} page-bounds)")
    elif not no_network and net_failures:
        c.set("WARN", f"citations structurally sound; {len(net_failures)}/{len(sample)} sampled live "
                       f"fetches did not return 2xx/3xx")
    elif pages_unknown:
        c.set("WARN", f"citations structurally sound; {pages_unknown} reference documents not yet "
                       f"text-extracted (provisional -- crawl in progress)")
    else:
        c.set("PASS", "all citations resolve, pages in bounds, URLs well-formed")
    c.examples = (unresolved + bad_url + bad_pages + net_failures)[:10]
    return c


# --------------------------------------------------------------------------
# Check 3 -- money sanity
# --------------------------------------------------------------------------
def check_money(actions):
    c = Check("3", "Money sanity")
    neg, too_big, revised_lt, missing_kind, sum_examples = [], [], [], [], []
    sum_checked = 0
    sum_mismatch = 0

    for a in actions:
        aid = a.get("action_id")
        amt, rt, pt = a.get("amount"), a.get("revised_total"), a.get("prior_total")
        ak, at = a.get("amount_kind"), a.get("action_type")
        if amt is not None:
            if amt < 0:
                neg.append(f"{aid}: amount={amt}")
            if amt > MAX_REASONABLE_AMOUNT:
                too_big.append(f"{aid}: amount={amt} title={str(a.get('title') or '')[:80]!r}")
            if ak is None:
                missing_kind.append(f"{aid}: amount={amt}, amount_kind is null")
        if at in AMENDMENT_LIKE_TYPES and amt is not None and rt is not None and rt < amt:
            revised_lt.append(f"{aid}: action_type={at} amount={amt} revised_total={rt}")
        # Only amendment-like rows carry the increment semantics this identity
        # assumes (amount = the increase). On a final_acceptance closeout,
        # bar_fill.py sets prior_total = the original contract, revised_total =
        # the final contract including change orders and sales tax, and
        # amount = revised_total, so prior+amount==revised is meaningless there.
        if (at in AMENDMENT_LIKE_TYPES
                and pt is not None and amt is not None and rt is not None):
            sum_checked += 1
            if abs((pt + amt) - rt) > 0.01:
                sum_mismatch += 1
                if len(sum_examples) < 10:
                    sum_examples.append(f"{aid}: prior_total={pt} + amount={amt} != revised_total={rt}")

    mismatch_rate = sum_mismatch / sum_checked if sum_checked else 0.0
    c.counts = [
        ("total action rows", len(actions)),
        ("negative amount", len(neg)),
        (f"amount > ${MAX_REASONABLE_AMOUNT:,}", len(too_big)),
        ("amount present, amount_kind null", len(missing_kind)),
        ("amendment/change_order with revised_total < amount", len(revised_lt)),
        ("amendment/change_order rows with prior_total + amount + revised_total all present",
         sum_checked),
        ("...of those, prior_total + amount != revised_total", sum_mismatch),
    ]
    hard_bad = len(neg) + len(too_big) + len(revised_lt) + len(missing_kind)
    if hard_bad:
        c.set("FAIL", f"{hard_bad} rows fail a hard money-sanity rule "
                       f"({len(neg)} negative, {len(too_big)} oversized, {len(revised_lt)} revised<amount, "
                       f"{len(missing_kind)} amount w/o amount_kind)")
    elif sum_checked and mismatch_rate > 0.2:
        c.set("WARN", f"prior_total+amount!=revised_total mismatch rate {mismatch_rate:.0%} "
                       f"({sum_mismatch}/{sum_checked})")
    elif not sum_checked:
        c.set("PASS", "no negative/oversized amounts, no amendment revised_total<amount, no amount w/o "
                       "amount_kind; 0 rows currently have prior_total+amount+revised_total all populated "
                       "(too early to check the sum rule)")
    else:
        c.set("PASS", f"no negative/oversized amounts, no amendment revised_total<amount, no amount w/o "
                       f"amount_kind; {sum_checked} rows checked for prior+amount==revised, "
                       f"{sum_mismatch} mismatches ({mismatch_rate:.0%})")
    c.examples = (neg + too_big + revised_lt + missing_kind + sum_examples)[:10]
    return c


# --------------------------------------------------------------------------
# Check 4 -- vendors
# --------------------------------------------------------------------------
def check_vendors(actions, vendors_rows, vendor_map_rows):
    c = Check("4", "Vendor mapping")
    vendor_ids_known = {v.get("vendor_id") for v in vendors_rows if v.get("vendor_id")}
    vmap = {r.get("vendor_raw"): r for r in vendor_map_rows if r.get("vendor_raw") is not None}

    unmapped, unknown_id = [], []
    n_vendor_raw = 0
    n_not_a_vendor = 0

    for a in actions:
        raw = a.get("vendor_raw")
        if raw is None:
            continue
        n_vendor_raw += 1
        vid = a.get("vendor_id")
        entry = vmap.get(raw)
        is_nav = bool(entry and entry.get("vendor_class") == "not_a_vendor")
        if is_nav:
            n_not_a_vendor += 1
        if vid is None:
            if not is_nav:
                unmapped.append(f"{a.get('action_id')}: vendor_raw={raw!r} has no vendor_id "
                                 f"and is not flagged not_a_vendor")
            continue
        if vid not in vendor_ids_known and not is_nav:
            unknown_id.append(f"{a.get('action_id')}: vendor_raw={raw!r} vendor_id={vid!r} "
                               f"(source={a.get('vendor_id_source')}) not in vendors.jsonl")

    bad = len(unmapped) + len(unknown_id)
    rate = bad / n_vendor_raw if n_vendor_raw else 0.0
    c.counts = [
        ("action rows with vendor_raw", n_vendor_raw),
        ("known canonical vendors", len(vendor_ids_known)),
        ("vendor_raw w/ no vendor_id, not flagged not_a_vendor", len(unmapped)),
        ("vendor_id set but missing from vendors.jsonl", len(unknown_id)),
        ("vendor_raw flagged not_a_vendor", n_not_a_vendor),
    ]
    if bad:
        status = "FAIL" if rate > 0.02 else "WARN"
        c.set(status, f"{bad}/{n_vendor_raw} vendor-bearing rows ({rate:.1%}) fail mapping -- most likely "
                       f"vendor_map.jsonl/vendors.jsonl (F1) is stale vs. contract_actions.jsonl (F2); "
                       f"rerun vendors.py then link.py")
    else:
        c.set("PASS", f"all {n_vendor_raw} vendor_raw values map to a known vendor_id or are flagged not_a_vendor")
    c.examples = (unmapped + unknown_id)[:10]
    return c


# --------------------------------------------------------------------------
# Check 5 -- pairing / chains
# --------------------------------------------------------------------------
def check_pairing_chains(actions):
    c = Check("5", "Pairing / chains")

    by_action_id = collections.defaultdict(list)
    for a in actions:
        by_action_id[a.get("action_id")].append(a)
    dup_action_id = {k: v for k, v in by_action_id.items() if k is not None and len(v) > 1}

    chains = collections.defaultdict(list)
    for a in actions:
        chains[a.get("chain_id")].append(a)

    two_chain_rows = []
    seen_action_chain = {}
    for cid, rows in chains.items():
        for r in rows:
            aid = r.get("action_id")
            if aid in seen_action_chain and seen_action_chain[aid] != cid:
                two_chain_rows.append(f"action_id {aid} claimed by chains {seen_action_chain[aid]!r} and {cid!r}")
            else:
                seen_action_chain[aid] = cid

    noncontig = []
    for cid, rows in chains.items():
        seqs = sorted(r.get("sequence") for r in rows if r.get("sequence") is not None)
        if len(seqs) != len(rows) or seqs != list(range(len(rows))):
            noncontig.append(f"chain {cid}: {len(rows)} rows, sequence values={seqs}")

    intro_after = []
    for a in actions:
        if a.get("paired") and a.get("intro_meeting_date") and a.get("meeting_date"):
            if a["intro_meeting_date"] > a["meeting_date"]:
                intro_after.append(
                    f"{a.get('action_id')}: intro {a['intro_meeting_date']} after action {a['meeting_date']}")

    bad = len(dup_action_id) + len(two_chain_rows) + len(noncontig) + len(intro_after)
    c.counts = [
        ("action rows", len(actions)),
        ("distinct chains", len(chains)),
        ("duplicate action_id groups", len(dup_action_id)),
        ("action rows claimed by >1 chain", len(two_chain_rows)),
        ("chains with non-contiguous sequence", len(noncontig)),
        ("paired rows with intro dated after action", len(intro_after)),
    ]
    if bad:
        c.set("FAIL", f"{bad} pairing/chain integrity problems")
    else:
        c.set("PASS", f"{len(chains)} chains, all sequences contiguous, no cross-chain duplicates, "
                       f"no intro-after-action pairs")
    examples = [f"duplicate action_id {k!r}: {len(v)} rows" for k, v in list(dup_action_id.items())[:3]]
    examples += two_chain_rows[:3] + noncontig[:3] + intro_after[:4]
    c.examples = examples[:10]
    return c


# --------------------------------------------------------------------------
# Check 6 -- time series
# --------------------------------------------------------------------------
def build_year_range(meetings):
    years = [school_year(m.get("date")) for m in meetings if m.get("date")]
    years = [y for y in years if y]
    if not years:
        return []
    starts = sorted(int(y.split("-")[0]) for y in years)
    lo, hi = starts[0], starts[-1]
    return ["%d-%02d" % (y, (y + 1) % 100) for y in range(lo, hi + 1)]


def ascii_sparkline(values):
    vmax = max(values) if values else 0
    if vmax <= 0:
        return _ASCII_RAMP[0] * len(values)
    n = len(_ASCII_RAMP) - 1
    chars = []
    for v in values:
        if v <= 0:
            chars.append(_ASCII_RAMP[0])
        else:
            idx = max(1, round(v / vmax * n))
            chars.append(_ASCII_RAMP[min(idx, n)])
    return "".join(chars)


def parse_pending_fetch_table(coverage_text):
    """{school_year: total docs still to fetch} from coverage_matrix.md's
    '## Documents to fetch, by era' table (A3). Empty dict if the section
    or the file is absent -- callers treat that as "cannot explain"."""
    pending = {}
    in_table = False
    row_re = re.compile(r"^\|\s*(\d{4}-\d{2})\s*\|(.+)\|\s*$")
    for line in coverage_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## Documents to fetch"):
            in_table = True
            continue
        if not in_table:
            continue
        if stripped.startswith("##"):
            break
        m = row_re.match(stripped)
        if not m:
            continue
        y = m.group(1)
        cells = [x.strip() for x in m.group(2).split("|")]
        nums = []
        for x in cells:
            try:
                nums.append(int(x))
            except ValueError:
                pass
        if nums:
            pending[y] = sum(nums)
    return pending


def check_time_series(actions, extracted, meetings, pending_by_year):
    c = Check("6", "Time series -- action rows & admitted items per school year")
    years = build_year_range(meetings)
    if not years:
        c.set("WARN", "no meetings with a parseable date; cannot build a time series")
        return c

    action_counts = collections.Counter(a.get("school_year") for a in actions if a.get("school_year"))
    admitted_counts = collections.Counter()
    for r in extracted:
        sy = school_year(r.get("meeting_date"))
        if sy:
            admitted_counts[sy] += 1

    rows = [(y, action_counts.get(y, 0), admitted_counts.get(y, 0)) for y in years]
    action_series = [r[1] for r in rows]
    admitted_series = [r[2] for r in rows]

    table_lines = ["| school year | action rows | admitted items |", "|---|---:|---:|"]
    for y, ac, ic in rows:
        table_lines.append(f"| {y} | {ac} | {ic} |")

    label_w = max(len("action rows:"), len("admitted items:")) + 1
    spark_lines = [
        "```",
        f"{'':<{label_w}}{years[0]} .. {years[-1]}  ({len(years)} school years)",
        f"{'action rows:':<{label_w}}{ascii_sparkline(action_series)}",
        f"{'admitted items:':<{label_w}}{ascii_sparkline(admitted_series)}",
        "```",
    ]

    def flagged(series):
        # Compare against the *nearest non-zero* neighbour on each side, not
        # the immediate one -- a multi-year gap (e.g. three straight zero
        # years) would otherwise hide itself: every interior year's immediate
        # neighbours are also zero, so a naive "both immediate neighbours >
        # 0" test never fires for the whole run. Walking outward to the
        # nearest non-zero year on each side flags every year inside the
        # gap, not just a lone dip between two healthy years.
        out = []
        n = len(series)
        for i in range(n):
            left = next((series[j] for j in range(i - 1, -1, -1) if series[j] > 0), None)
            right = next((series[j] for j in range(i + 1, n) if series[j] > 0), None)
            if left is None or right is None:
                continue
            if series[i] < 0.5 * left and series[i] < 0.5 * right:
                out.append(i)
        return out

    flagged_idx = sorted(set(flagged(action_series)) | set(flagged(admitted_series)))
    explained, unexplained = [], []
    for i in flagged_idx:
        y = rows[i][0]
        pending = pending_by_year.get(y, 0)
        (explained if pending > 0 else unexplained).append((y, rows[i][1], rows[i][2], pending))

    c.counts = [
        ("school years spanned", len(years)),
        ("years with a >50% dip vs. both neighbours", len(flagged_idx)),
        ("...explained by coverage_matrix.md pending-fetch counts", len(explained)),
        ("...NOT explained", len(unexplained)),
    ]
    if unexplained:
        names = ", ".join(y for y, _, _, _ in unexplained)
        c.set("FAIL", f"{len(unexplained)} school year(s) show an unexplained >50% dip vs. both "
                       f"neighbours: {names}")
    elif explained:
        names = ", ".join(y for y, _, _, _ in explained)
        c.set("WARN", f"{len(explained)} school year(s) show a >50% dip vs. both neighbours, all with "
                       f"documents still pending fetch per coverage_matrix.md (provisional): {names}")
    else:
        c.set("PASS", "no school year drops >50% vs. both neighbours")
    c.notes = table_lines + [""] + spark_lines
    c.examples = (
        [f"{y}: action_rows={ac} admitted={ic} -- explained, {p} docs pending fetch"
         for y, ac, ic, p in explained][:5]
        + [f"{y}: action_rows={ac} admitted={ic} -- NOT explained by coverage_matrix.md"
           for y, ac, ic, p in unexplained][:10]
    )[:10]
    return c


# --------------------------------------------------------------------------
# Check 7 -- key uniqueness
# --------------------------------------------------------------------------
def check_key_uniqueness(actions, items):
    c = Check("7", "Key uniqueness")

    action_ids = collections.Counter(a.get("action_id") for a in actions)
    dup_actions = {k: v for k, v in action_ids.items() if k is not None and v > 1}
    null_action_id = action_ids.get(None, 0)

    item_keys = collections.Counter((r.get("meeting_id"), r.get("item_no"), r.get("char_start")) for r in items)
    dup_items = {k: v for k, v in item_keys.items() if v > 1}

    # Multi-vendor motions: link.py emits one row per vendor, the primary
    # keeping its action_id and each co-vendor getting a `-v2`, `-v3`, ...
    # suffix. Those suffixed ids are legitimate distinct keys -- what has to
    # hold is that every member points at a `multi_vendor_group` that exists
    # as a real primary row, that the suffix is well-formed, and that the
    # group's actual size matches the `multi_vendor_n` recorded on it.
    id_set = set(action_ids)
    member_re = re.compile(r"^(?P<base>.+)-v(?P<n>[2-9]\d*)$")
    groups = collections.defaultdict(list)
    bad_members = []
    for a in actions:
        gid = a.get("multi_vendor_group")
        if gid:
            groups[gid].append(a)
    for a in actions:
        aid = a.get("action_id") or ""
        m = member_re.match(aid)
        gid = a.get("multi_vendor_group")
        if m and not gid:
            bad_members.append(f"{aid}: -vN action_id with no multi_vendor_group")
        if not gid:
            continue
        if gid not in id_set:
            bad_members.append(f"{aid}: multi_vendor_group {gid!r} is not an action_id")
        elif aid != gid and (not m or m.group("base") != gid):
            bad_members.append(f"{aid}: not <{gid}>-vN")
    for gid, members in groups.items():
        declared = {m.get("multi_vendor_n") for m in members}
        if declared != {len(members)}:
            bad_members.append(
                f"group {gid}: {len(members)} rows but multi_vendor_n={sorted(declared, key=str)}")

    bad = len(dup_actions) + null_action_id + len(dup_items) + len(bad_members)
    c.counts = [
        ("contract_actions rows", len(actions)),
        ("distinct action_id", len([k for k in action_ids if k is not None])),
        ("duplicate action_id values", len(dup_actions)),
        ("null action_id", null_action_id),
        ("multi-vendor groups", len(groups)),
        ("multi-vendor member rows (`-vN` ids)",
         sum(1 for a in actions if member_re.match(a.get("action_id") or ""))),
        ("malformed multi-vendor keys", len(bad_members)),
        ("items rows", len(items)),
        ("distinct (meeting_id, item_no, char_start)", len(item_keys)),
        ("duplicate (meeting_id, item_no, char_start) keys", len(dup_items)),
    ]
    if bad:
        c.set("FAIL", f"{len(dup_actions)} duplicate action_id, {null_action_id} null action_id, "
                       f"{len(dup_items)} duplicate item keys, "
                       f"{len(bad_members)} malformed multi-vendor keys")
    else:
        c.set("PASS", "action_id unique in contract_actions.jsonl (co-vendor `-vN` ids "
                       "included, each resolving to a real primary row); "
                       "(meeting_id, item_no, char_start) unique in items")
    examples = [f"action_id {k!r} appears {v}x" for k, v in list(dup_actions.items())[:5]]
    examples += [f"item key {k!r} appears {v}x" for k, v in list(dup_items.items())[:5]]
    examples += bad_members[:5]
    c.examples = examples[:10]
    return c


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
def write_report(path, checks, meta):
    lines = []
    lines.append("# Board contracts -- reconciliation report (task H2)")
    lines.append("")
    lines.append(f"Generated {meta['generated_at']} by `extractors/sps_web/reconcile.py`.")
    lines.append("")
    lines.append("**Provisional.** The Wayback/Blackboard crawl (Phase B) and a following "
                 "extract/link rerun were still in flight as of this run. Gaps categorized below as "
                 "`not fetched`, `no docs`, or a crawl-explained time-series dip are expected to shrink "
                 "on the next run -- rerun this checker after the crawl/extract/link settle.")
    lines.append("")
    lines.append(f"Inputs: {meta['n_meetings']} meetings, {meta['n_docs']} documents, {meta['n_items']} "
                 f"items, {meta['n_extracted']} admitted items (extracted.jsonl), {meta['n_actions']} "
                 f"linked action rows (contract_actions.jsonl), {meta['n_manual_review']} rows still in "
                 f"manual_review.jsonl (a subset of extracted.jsonl awaiting a second E2 round).")
    lines.append("")
    lines.append("| # | check | status | summary |")
    lines.append("|---|---|---|---|")
    for c in checks:
        lines.append(f"| {c.key} | {c.title} | **{c.status}** | {c.summary} |")
    lines.append("")

    for c in checks:
        lines.append(f"## {c.key}. {c.title} -- {c.status}")
        lines.append("")
        lines.append(c.summary)
        lines.append("")
        if c.counts:
            lines.append("| metric | value |")
            lines.append("|---|---:|")
            for k, v in c.counts:
                lines.append(f"| {k} | {v} |")
            lines.append("")
        if c.notes:
            lines.extend(c.notes)
            lines.append("")
        if c.examples:
            lines.append("Examples (up to 10):")
            lines.append("")
            for ex in c.examples[:10]:
                lines.append(f"- {ex}")
            lines.append("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


# --------------------------------------------------------------------------
# run / CLI
# --------------------------------------------------------------------------
def run(out_root="out_sps_web", sample_n=40, no_network=False, seed=20260824):
    meetings = read_jsonl(os.path.join(out_root, "manifest", "meetings.jsonl"))
    docs = read_jsonl(os.path.join(out_root, "manifest", "documents_classified.jsonl"))
    if not docs:
        docs = read_jsonl(os.path.join(out_root, "manifest", "documents.jsonl"))
    items = read_jsonl_glob(os.path.join(out_root, "items", "*.jsonl"))
    extracted = read_jsonl(os.path.join(out_root, "contracts", "extracted.jsonl"))
    actions = read_jsonl(os.path.join(out_root, "contracts", "contract_actions.jsonl"))
    vendors_rows = read_jsonl(os.path.join(out_root, "contracts", "vendors.jsonl"))
    vendor_map_rows = read_jsonl(os.path.join(out_root, "contracts", "vendor_map.jsonl"))
    manual_review = read_jsonl(os.path.join(out_root, "contracts", "manual_review.jsonl"))
    pages_by_doc = load_textmeta_pages(out_root)

    doc_index = {d.get("doc_id"): d for d in docs}
    docs_by_meeting = collections.defaultdict(list)
    for d in docs:
        mid = d.get("meeting_id")
        if mid:
            docs_by_meeting[mid].append(d)

    coverage_path = os.path.join(out_root, "qa", "coverage_matrix.md")
    coverage_text = ""
    if os.path.isfile(coverage_path):
        with open(coverage_path, encoding="utf-8") as fh:
            coverage_text = fh.read()
    pending_by_year = parse_pending_fetch_table(coverage_text)

    if not meetings and not actions:
        raise SystemExit(f"no meetings.jsonl or contract_actions.jsonl found under {out_root!r}")

    checks = [
        check_meeting_coverage(meetings, docs_by_meeting),
        check_citations(actions, doc_index, pages_by_doc, sample_n, no_network, seed),
        check_money(actions),
        check_vendors(actions, vendors_rows, vendor_map_rows),
        check_pairing_chains(actions),
        check_time_series(actions, extracted, meetings, pending_by_year),
        check_key_uniqueness(actions, items),
    ]

    meta = {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "n_meetings": len(meetings), "n_docs": len(docs), "n_items": len(items),
        "n_extracted": len(extracted), "n_actions": len(actions),
        "n_manual_review": len(manual_review),
    }
    report_path = os.path.join(out_root, "qa", "reconcile_report.md")
    write_report(report_path, checks, meta)

    print(f"wrote {report_path}")
    for c in checks:
        print(f"  [{c.status}] {c.key}. {c.title} -- {c.summary}")
    n_fail = sum(1 for c in checks if c.status == "FAIL")
    return checks, n_fail


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Reconciliation checks for the board-contracts pipeline (PLAN.md task H2).")
    ap.add_argument("--out-root", default="out_sps_web")
    ap.add_argument("--sample", type=int, default=40,
                     help="number of unique cited documents to HEAD/GET-range check live (default 40)")
    ap.add_argument("--no-network", action="store_true",
                     help="skip the live HEAD/GET-range URL check (check 2 stays structural-only)")
    ap.add_argument("--seed", type=int, default=20260824,
                     help="random seed for the URL sample, for reproducible reruns")
    args = ap.parse_args(argv)
    _checks, n_fail = run(out_root=args.out_root, sample_n=args.sample,
                          no_network=args.no_network, seed=args.seed)
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
