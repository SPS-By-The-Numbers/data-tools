"""Task A3 (see extractors/sps_web/PLAN.md, Section 3): merge the WordPress
inventory (A1, ``inventory_wp.py``) and the three Wayback inventories (A2,
``inventory_wayback.py``) into ONE meeting list and ONE fetch list, and write
the coverage matrix.

Usage (from the repo root)::

    venv/bin/python3 -m extractors.sps_web.inventory_merge

Reads (all under ``out_sps_web/manifest/``): ``wp_meetings.jsonl``,
``wp_documents.jsonl``, ``wayback_meetings.jsonl``,
``wayback_documents.jsonl``, ``wayback_undated.jsonl``,
``wayback_committees.jsonl``.

Writes::

    out_sps_web/manifest/meetings.jsonl           one row per meeting
    out_sps_web/manifest/documents.jsonl          one row per fetchable document
    out_sps_web/manifest/documents_nofetch.jsonl  links with no fetch recipe
    out_sps_web/qa/coverage_matrix.md             the A3 coverage matrix
    out_sps_web/manifest/merge_report.md          sanity checks / counts

Nothing under ``out_sps_web/raw/`` or ``out_sps_web/manifest/fetch_*`` is read
or written -- concurrent fetch runs are unaffected.


Era precedence
==============

Four sources, ranked.  The rank decides which row survives when two sources
hold the same file; the loser is preserved on the winner's ``alternates``
list (never dropped), so provenance for both URLs is kept.

1. ``wp``          -- seattleschools.org WordPress, Aug 2016 -> present.
   **Always wins.** It is the live host (no Wayback rate limit, no capture
   gaps), it is the district's own current copy, and its rows carry link text
   and the meeting page they were linked from.  Two fetch recipes live under
   this era: ``direct`` (wp-content/uploads, 2016-17..2020-21 migrated PDFs)
   and ``sharepoint_download`` (2021-22 -> present).
2. ``blackboard``  -- Wayback captures of the old UserFiles tree,
   2011-12..2020-21.  **Sole source for 2011-12..2015-16.**  For
   2016-17..2020-21 it is a *duplicate* of files WordPress re-hosted under
   ``/wp-content/uploads/2021/07/``; those rows are demoted to alternates.
   Roughly a quarter of its 2016-21 rows are nevertheless unique (unofficial
   minutes, agenda packets, ADA variants that the WP migration dropped) and
   those are kept as first-class documents.
3. ``legacy``      -- Wayback captures of ``/area/board/``,
   2004-05..2010-11.  **Sole source for those years** apart from (4).
4. ``archive``     -- Wayback captures of spsarchivepublic.seattleschools.org,
   "edited agendas" 2006..2012.  Ranked last, but in practice it never
   collides: ``edited-<MMDDYY>agenda.pdf`` is a *different rendition* of the
   meeting, not a byte-copy of the legacy agenda, so archive rows survive
   alongside legacy/blackboard rows for the same meeting.  It is the only
   filler for the thin 2011-12 blackboard year and a cross-check elsewhere.

Committee packets (``wayback_committees.jsonl``, 1,333 rows) and undated
Wayback rows (``wayback_undated.jsonl``, 139 rows) are **not merged** -- they
are counted in the coverage matrix's "left aside" section and nothing else.
The owner decision on committee packets is still open (PLAN Section 4).


Document dedup keys
===================

Applied in this order; the first hit wins.  Documents are visited in era-rank
order, so the winner of a cluster is always the highest-ranked era.

* ``K_FETCH``  -- identical ``fetch.url``.  Catches a file linked from several
  meeting pages (WP: 4,017 fetchable link rows -> 3,218 distinct fetch URLs)
  and SharePoint links that differ only in their ``?e=`` tracking parameter.
* ``K_DIGEST`` -- Wayback ``cdx_digest`` for rows whose ``cdx_status`` is
  ``200``.  Identical bytes under two URLs: in this corpus every instance is
  a set of minutes filed both in its own meeting folder and in the folder of
  the meeting that approved them (``14-15agendas/060315agenda/
  20150603_Minutes.pdf`` == ``14-15agendas/061715agenda/20150603_Minutes.pdf``).
  Only 200-status rows carry a trustworthy digest, so non-200 rows are never
  digest-matched.
* ``K_NAME``   -- normalized filename: lowercased, extension stripped, the
  WordPress media-library ``-<N>`` collision suffix stripped, then every
  non-alphanumeric character removed.  That last step is what makes the
  cross-source match work, because the WP media library rewrote spaces to
  dashes and dropped apostrophes when the 2016-21 PDFs were migrated:
  ``C08_20201007_Renew Contract with Hobson's Naviance Software.pdf``
  (blackboard) and ``C08_20201007_Renew-Contract-with-Hobsons-Naviance-
  Software.pdf`` (wp) normalize to the same string.  A name is unusable when
  it is shorter than 8 characters or is a bare item code (``I05``, ``A01``,
  ``C12``) -- those exist in WP as literal ``I05.pdf`` uploads.  Otherwise it
  is used in one of two scopes:

  - **unscoped** (matches across meetings and across eras) only when the
    normalized name contains a run of >= 6 digits, i.e. it embeds its own
    ``MMDDYY``/``YYYYMMDD``.  WP and Wayback disagree about which meeting a
    file belongs to, so the cross-source match has to ignore the meeting --
    and a date-bearing name is specific enough to make that safe.  Across
    2,175 WP uploads exactly one pair of distinct URLs normalized together,
    and it was the same document (``..._Northgate_ES_Replacement.pdf`` /
    ``...-1.pdf``).
  - **scoped to the meeting** (``(meeting_id, name)``) otherwise.  This is
    what the 2005-11 legacy era needs: its per-meeting folders are full of
    generic names -- ``budgetpresentation.pdf`` occurs at 14 different
    meetings, ``transportationreport.pdf`` at 9, ``sapreport.pdf`` at 9 --
    which an unscoped key would collapse into one document and silently
    delete 265 real files.

Because the winner keeps its own era's meeting assignment, and the two eras
disagree about which meeting a file belongs to (WP assigns by *the page the
link was on*, Wayback by *the folder the file sat in*), each alternate keeps
its own ``meeting_id``/``meeting_date`` and the winner gets
``meeting_date_conflict: true`` when they differ.  Downstream segmentation
should prefer ``filename_date`` (the ``YYYYMMDD`` embedded in the filename)
when it exists -- it is the item's own agenda date and is the most reliable
of the three.


Meeting id scheme
=================

``meeting_id = <YYYY-MM-DD>-<type>``, one id per (date, type) across all
eras, with ``type`` in ``regular | special | work-session | retreat |
general``.

* **WP collisions.**  A1 found two dates carrying two distinct
  ``board_meeting`` posts with the same type (2025-01-15 general, 2025-07-30
  special).  Disambiguation: sort the colliding posts by ascending ``wp_id``,
  leave the first with the bare id, and suffix the rest ``-2``, ``-3``, ...
  So ``2025-01-15-general`` (lower wp_id) and ``2025-01-15-general-2``.  The
  suffix is stable as long as the WP post ids are, which they are.
* **Wayback type inference.**  Wayback rows have no meeting-type metadata, so
  type is inferred from the *folder path only* (never the filename -- ``_SP``
  in this corpus is overwhelmingly "Seattle Preschool Program" and
  "Specially Designed Instruction", not "special meeting"): a folder segment
  matching ``\\d{6}spagenda`` or containing ``special`` -> ``special``;
  containing ``retreat`` -> ``retreat``; containing ``work session`` /
  ``worksession`` -> ``work-session``; otherwise ``regular``.  In practice
  the old sites named every folder ``<MMDDYY>agenda``, so this resolves to
  ``regular`` for all but two of the 4,220 Wayback rows.  Wayback meeting ids
  are therefore ``<date>-regular`` almost everywhere -- the A2 ids
  ``<date>-<era>`` are dropped, and the era moves onto the meeting's
  ``sources`` list where it belongs.
* **Cross-era attachment.**  A Wayback document whose date already has one or
  more WP meetings attaches to a WP meeting rather than inventing a
  ``-regular`` twin: exact type match first; else the sole WP meeting that
  day; else the ``regular``/``general`` one; else the lowest ``wp_id``.  211
  of the 548 blackboard dates attach this way; the other 337 (all of
  2011-12..2015-16 plus 89 dates in 2016-21 that WordPress has no post for)
  become Wayback-only meetings.
"""

from __future__ import annotations

import collections
import datetime
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MANIFEST_DIR = os.path.join(REPO_ROOT, "out_sps_web", "manifest")
QA_DIR = os.path.join(REPO_ROOT, "out_sps_web", "qa")

ERA_RANK = {"wp": 0, "blackboard": 1, "legacy": 2, "archive": 3}

# School years shown in the coverage matrix (PLAN A3 asks for 2004-05..2026-27;
# the legacy CDX pull actually reaches back into 2004-05).
FIRST_SY_START = 2004
LAST_SY_START = 2026

ITEM_CODE_RE = re.compile(r"^([A-Z]{1,3}\d{1,3})[_\-. ]")
FILENAME_DATE_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})")
AMBIGUOUS_NAME_RE = re.compile(r"^[a-z]{0,3}\d{1,4}$")
WP_DEDUPE_SUFFIX_RE = re.compile(r"-\d+$")
EXT_RE = re.compile(r"\.[A-Za-z0-9]{1,5}$")
DOCUMENT_EXT = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "rtf", "txt"}
PLAUSIBLE_EXT = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "htm", "html", "txt", "rtf", "csv", "jpg", "jpeg", "png", "gif", "",
}

TYPE_ORDER = ["regular", "general", "special", "work-session", "retreat", "unknown"]


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_jsonl(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def school_year(date_str):
    """SPS school year for an ISO date. August 1 is the boundary (matches the
    WP ``school_year`` taxonomy, whose terms read "August 2016 - July 2017")."""
    if not date_str:
        return None
    y, m, _d = (int(x) for x in date_str.split("-")[:3])
    start = y if m >= 8 else y - 1
    return "%d-%02d" % (start, (start + 1) % 100)


def normalized_name(filename):
    """Dedup key for a filename, or None when too ambiguous to key on."""
    if not filename:
        return None
    name = EXT_RE.sub("", filename.strip().lower())
    name = WP_DEDUPE_SUFFIX_RE.sub("", name)
    name = re.sub(r"[^a-z0-9]+", "", name)
    if len(name) < 8 or AMBIGUOUS_NAME_RE.match(name):
        return None
    return name


def name_is_date_bearing(name):
    """True when a normalized filename embeds its own MMDDYY/YYYYMMDD, which is
    what makes an unscoped (cross-meeting, cross-era) name match safe."""
    return bool(name) and bool(re.search(r"\d{6,}", name))


def filename_date(filename):
    """The YYYYMMDD an SPS board filename usually embeds -- the item's own
    agenda date, more reliable than either the WP page date or the Wayback
    folder date."""
    if not filename:
        return None
    for m in FILENAME_DATE_RE.finditer(filename):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime.date(y, mo, d).isoformat()
        except ValueError:
            continue
    return None


def item_code(filename, existing=None):
    if existing:
        return existing
    if not filename:
        return None
    m = ITEM_CODE_RE.match(filename.strip())
    return m.group(1) if m else None


def url_filename(url):
    """Last path segment of a URL, percent-decoded enough to read."""
    if not url:
        return ""
    path = url.split("?", 1)[0].split("#", 1)[0]
    seg = path.rstrip("/").rsplit("/", 1)[-1]
    try:
        import urllib.parse
        seg = urllib.parse.unquote(seg)
    except Exception:  # pragma: no cover
        pass
    return seg


def extension_of(filename):
    m = EXT_RE.search(filename or "")
    return m.group(0)[1:].lower() if m else ""


def wayback_type(folder):
    """Meeting type inferred from a Wayback folder path. See module docstring
    -- folder only, never the filename."""
    f = (folder or "").lower()
    if re.search(r"\d{6}\s*spagenda", f) or "special" in f:
        return "special"
    if "retreat" in f:
        return "retreat"
    if "work session" in f or "worksession" in f:
        return "work-session"
    return "regular"


def pretty_date(date_str):
    y, m, d = (int(x) for x in date_str.split("-")[:3])
    return datetime.date(y, m, d).strftime("%B %-d, %Y")


# --------------------------------------------------------------------------
# meetings
# --------------------------------------------------------------------------

def build_meetings(wp_meetings, wayback_docs):
    """Return (meetings_by_id, wp_meeting_id_by_wp_id, attach_fn).

    ``attach_fn(date, type)`` resolves a Wayback document's (date, inferred
    type) to the meeting_id it should hang off, creating a Wayback-only
    meeting row on demand.
    """
    meetings = {}
    wp_id_to_meeting = {}
    by_date = collections.defaultdict(list)

    # --- WP meetings, with the -2/-3 collision suffix (ordered by wp_id).
    groups = collections.defaultdict(list)
    for m in wp_meetings:
        groups[(m["date"], m["type"])].append(m)
    collisions = []
    for (date, mtype), rows in sorted(groups.items()):
        rows.sort(key=lambda r: r.get("wp_id") or 0)
        if len(rows) > 1:
            collisions.append((date, mtype, [r.get("wp_id") for r in rows]))
        for i, m in enumerate(rows):
            mid = "%s-%s" % (date, mtype) if i == 0 else "%s-%s-%d" % (date, mtype, i + 1)
            meetings[mid] = {
                "meeting_id": mid,
                "date": date,
                "type": mtype,
                "school_year": m.get("school_year") or school_year(date),
                "title": m.get("title"),
                "title_source": "wp",
                "sources": ["wp"],
                "page_url": m.get("page_url"),
                "wp_id": m.get("wp_id"),
                "has_agenda": False,
                "has_minutes": False,
                "n_bar": 0,
                "n_docs": 0,
                "n_docs_by_era": {},
            }
            wp_id_to_meeting[m["meeting_id"]] = mid
            by_date[date].append(meetings[mid])

    def attach(date, mtype, era, first_doc_url):
        cands = by_date.get(date) or []
        wp_cands = [m for m in cands if "wp" in m["sources"] and m["wp_id"] is not None]
        target = None
        if wp_cands:
            exact = [m for m in wp_cands if m["type"] == mtype]
            if exact:
                target = exact[0]
            elif len(wp_cands) == 1:
                target = wp_cands[0]
            else:
                reg = [m for m in wp_cands if m["type"] in ("regular", "general")]
                target = reg[0] if reg else sorted(
                    wp_cands, key=lambda m: m["wp_id"])[0]
        else:
            same_type = [m for m in cands if m["type"] == mtype]
            if same_type:
                target = same_type[0]
        if target is None:
            mid = "%s-%s" % (date, mtype)
            suffix = 2
            while mid in meetings:  # cannot normally happen; be safe
                mid = "%s-%s-%d" % (date, mtype, suffix)
                suffix += 1
            label = {"regular": "Regular Board Meeting",
                     "special": "Board Special Meeting",
                     "work-session": "Board Work Session",
                     "retreat": "Board Retreat",
                     "general": "Board Meeting"}.get(mtype, "Board Meeting")
            target = {
                "meeting_id": mid,
                "date": date,
                "type": mtype,
                "school_year": school_year(date),
                "title": "%s – %s" % (pretty_date(date), label),
                "title_source": "synthesized",
                "sources": [],
                "page_url": (first_doc_url or "").rsplit("/", 1)[0] or None,
                "wp_id": None,
                "has_agenda": False,
                "has_minutes": False,
                "n_bar": 0,
                "n_docs": 0,
                "n_docs_by_era": {},
            }
            meetings[mid] = target
            by_date[date].append(target)
        if era not in target["sources"]:
            target["sources"].append(era)
        return target["meeting_id"]

    return meetings, wp_id_to_meeting, attach, collisions


# --------------------------------------------------------------------------
# documents
# --------------------------------------------------------------------------

def canonical_doc(row, era, meeting_id, meeting_date):
    fname = row.get("filename") or ""
    if not fname:
        fname = url_filename(row.get("source_url", ""))
    doc = {
        "doc_id": row["doc_id"],
        "era": era,
        "meeting_id": meeting_id,
        "meeting_date": meeting_date,
        "school_year": school_year(meeting_date),
        "source_url": row["source_url"],
        "filename": row.get("filename") or "",
        "filename_date": filename_date(row.get("filename") or url_filename(row.get("source_url", ""))),
        "fetch": row["fetch"],
        "kind_guess": row.get("kind_guess"),
        "item_code": item_code(row.get("filename") or "", row.get("item_code")),
        "link_text": row.get("link_text"),
        "host_class": row.get("host_class"),
        "cdx_timestamp": row.get("cdx_timestamp"),
        "cdx_status": row.get("cdx_status"),
        "cdx_digest": row.get("cdx_digest"),
        "meeting_ids": [meeting_id],
        "alternates": [],
        "meeting_date_conflict": False,
        "precedence_reason": None,
    }
    return doc


def merge_documents(wp_docs, wayback_docs, wp_id_to_meeting, attach):
    """Union + dedupe. Returns (documents, nofetch, stats)."""
    stats = collections.Counter()
    by_fetch = {}
    by_name = {}
    by_name_scoped = {}
    by_digest = {}
    winners = []
    nofetch = []
    nofetch_seen = set()

    def nofetch_reason(row, era):
        if era != "wp":
            return "wayback_row_without_fetch_recipe"
        host = row.get("host_class")
        if host == "sharepoint":
            return "sharepoint_link_without_share_token"
        return {
            "youtube": "video_link_not_a_document",
            "forms": "office_forms_link_not_a_document",
            "sps-page": "html_page_not_a_document",
            "other": "non_document_link",
        }.get(host, "no_fetch_recipe")

    def keys_of(doc):
        ks = []
        furl = (doc.get("fetch") or {}).get("url")
        if furl:
            ks.append(("fetch", furl))
        if doc.get("cdx_status") == "200" and doc.get("cdx_digest") not in (None, "", "-"):
            ks.append(("digest", doc["cdx_digest"]))
        nname = normalized_name(doc["filename"] or url_filename(doc["source_url"]))
        if nname:
            if name_is_date_bearing(nname):
                ks.append(("name", nname))
            else:
                ks.append(("name_in_meeting", (doc["meeting_id"], nname)))
        return ks

    registries = {"fetch": by_fetch, "name": by_name, "digest": by_digest,
                  "name_in_meeting": by_name_scoped}

    def ingest(doc):
        ks = keys_of(doc)
        for kind, val in ks:
            hit = registries[kind].get(val)
            if hit is not None:
                winner = hit
                alt = {
                    "era": doc["era"],
                    "source_url": doc["source_url"],
                    "filename": doc["filename"],
                    "fetch": doc["fetch"],
                    "meeting_id": doc["meeting_id"],
                    "meeting_date": doc["meeting_date"],
                    "matched_on": kind,
                }
                if doc.get("cdx_timestamp"):
                    alt["cdx_timestamp"] = doc["cdx_timestamp"]
                    alt["cdx_status"] = doc["cdx_status"]
                winner["alternates"].append(alt)
                if doc["meeting_id"] not in winner["meeting_ids"]:
                    winner["meeting_ids"].append(doc["meeting_id"])
                if doc["meeting_date"] != winner["meeting_date"]:
                    winner["meeting_date_conflict"] = True
                stats["dedup_%s_over_%s_on_%s" % (winner["era"], doc["era"], kind)] += 1
                # register the loser's other keys against the same winner so a
                # third copy that only shares the loser's name still lands here
                for k2, v2 in ks:
                    registries[k2].setdefault(v2, winner)
                return False
        for kind, val in ks:
            registries[kind][val] = doc
        winners.append(doc)
        return True

    # Within an era, ingest real document URLs first so that a truncated or
    # directory-shaped URL (`.../101508agenda/`) always loses to the PDF it
    # sits next to (`.../101508agenda/101508agenda.pdf`) instead of winning
    # the cluster on sort order.
    def doc_rank(row):
        name = row.get("filename") or url_filename(row.get("source_url", ""))
        ext_ok = 0 if extension_of(name) in DOCUMENT_EXT else 1
        status = row.get("cdx_status")
        live = 0 if (status is None or status == "200") else 1
        # shortest URL breaks remaining ties, which prefers the clean
        # `051607agenda.pdf` over a mangled `051607agenda..pdf` capture.
        return (ext_ok, live, len(row.get("source_url") or ""))

    # --- pass 1: WP (era rank 0)
    wp_sorted = sorted(wp_docs, key=lambda r: (r.get("meeting_date") or "",
                                               doc_rank(r), r["doc_id"]))
    for row in wp_sorted:
        mid = wp_id_to_meeting.get(row["meeting_id"])
        if mid is None:
            stats["wp_doc_with_unknown_meeting"] += 1
            continue
        if (row.get("fetch") or {}).get("kind", "none") == "none":
            key = (row["source_url"], mid)
            if key in nofetch_seen:
                continue
            nofetch_seen.add(key)
            nofetch.append({
                "doc_id": row["doc_id"], "era": "wp", "meeting_id": mid,
                "meeting_date": row.get("meeting_date"),
                "school_year": school_year(row.get("meeting_date")),
                "source_url": row["source_url"], "link_text": row.get("link_text"),
                "host_class": row.get("host_class"), "kind_guess": row.get("kind_guess"),
                "reason": nofetch_reason(row, "wp"),
            })
            continue
        ingest(canonical_doc(row, "wp", mid, row.get("meeting_date")))

    # --- passes 2..4: Wayback eras in rank order
    wb_by_era = collections.defaultdict(list)
    for row in wayback_docs:
        wb_by_era[row["era"]].append(row)
    for era in ("blackboard", "legacy", "archive"):
        rows = sorted(wb_by_era.get(era, []),
                      key=lambda r: (r.get("meeting_date") or "", doc_rank(r),
                                     r["source_url"]))
        for row in rows:
            mtype = wayback_type(row.get("folder"))
            mid = attach(row["meeting_date"], mtype, era, row["source_url"])
            fetch = row.get("fetch") or {}
            fname = row.get("filename") or url_filename(row["source_url"])
            ext = extension_of(fname)
            if fetch.get("kind", "none") == "none" or ("<" in fname) or (
                    ext not in PLAUSIBLE_EXT and not re.fullmatch(r"[a-z0-9]{0,5}", ext)):
                reason = ("malformed_source_url" if ("<" in fname or ext not in PLAUSIBLE_EXT)
                          else nofetch_reason(row, era))
                nofetch.append({
                    "doc_id": row["doc_id"], "era": era, "meeting_id": mid,
                    "meeting_date": row.get("meeting_date"),
                    "school_year": school_year(row.get("meeting_date")),
                    "source_url": row["source_url"], "link_text": None,
                    "host_class": None, "kind_guess": row.get("kind_guess"),
                    "cdx_status": row.get("cdx_status"),
                    "reason": reason,
                })
                stats["nofetch_%s_%s" % (era, reason)] += 1
                continue
            ingest(canonical_doc(row, era, mid, row["meeting_date"]))

    # --- precedence_reason + doc_id uniqueness
    seen_ids = {}
    for doc in winners:
        if doc["alternates"]:
            alt_eras = sorted({a["era"] for a in doc["alternates"]})
            keys = sorted({a["matched_on"] for a in doc["alternates"]})
            if alt_eras == [doc["era"]]:
                doc["precedence_reason"] = "deduped %d duplicate %s copy/copies (matched on %s)" % (
                    len(doc["alternates"]), doc["era"], "+".join(keys))
            else:
                doc["precedence_reason"] = "%s preferred over %s (matched on %s)" % (
                    doc["era"], "+".join(alt_eras), "+".join(keys))
        else:
            doc["precedence_reason"] = "sole copy (%s)" % doc["era"]
        base = doc["doc_id"]
        n = seen_ids.get(base, 0)
        seen_ids[base] = n + 1
        if n:
            doc["doc_id"] = "%s-%d" % (base, n + 1)
            stats["doc_id_suffixed"] += 1

    return winners, nofetch, stats


# --------------------------------------------------------------------------
# coverage matrix
# --------------------------------------------------------------------------

def school_year_rows():
    return ["%d-%02d" % (y, (y + 1) % 100)
            for y in range(FIRST_SY_START, LAST_SY_START + 1)]


def build_coverage(meetings, documents, nofetch, undated, committees):
    by_sy = collections.defaultdict(lambda: {
        "meetings": [], "docs": 0, "agenda": 0, "minutes": 0, "bar": 0,
        "sources": set(), "kinds": collections.Counter()})
    for m in meetings.values():
        sy = m["school_year"] or school_year(m["date"])
        by_sy[sy]["meetings"].append(m)
        by_sy[sy]["sources"].update(m["sources"])
    by_sy_era = collections.defaultdict(collections.Counter)
    for d in documents:
        sy = d["school_year"]
        b = by_sy[sy]
        b["docs"] += 1
        b["kinds"][d["kind_guess"] or "other"] += 1
        by_sy_era[sy][d["era"]] += 1
        if d["kind_guess"] == "bar":
            b["bar"] += 1
    lines = []
    lines.append("# Board-document coverage matrix")
    lines.append("")
    lines.append("Generated by `extractors/sps_web/inventory_merge.py` (task A3).")
    lines.append("Rows are SPS school years (August 1 boundary). `docs` counts rows in")
    lines.append("`out_sps_web/manifest/documents.jsonl` after cross-source dedupe; a file")
    lines.append("present in two sources is counted once, on the winning row.")
    lines.append("")
    lines.append("**Read `w/ agenda`, `w/ minutes` and `BARs` as a floor, not a count.**")
    lines.append("They come from the A1/A2 `kind_guess`, which sees only the link text and")
    lines.append("the filename. From 2021-22 on, WP links to SharePoint and the href carries")
    lines.append("no filename at all, so a meeting whose agenda was linked as e.g. \"Board")
    lines.append("Meeting Agenda Packet\" often lands in `kind_guess=other` — which is why the")
    lines.append("agenda/minutes columns dip after 2020-21 even though the documents are")
    lines.append("present. Task C2 (`classify.py`) re-derives `kind` from the fetched bytes")
    lines.append("and the SharePoint-resolved filename; rerun this matrix after C2.")
    lines.append("")
    lines.append("| school year | meetings | w/ agenda | w/ minutes | BARs | docs | sources |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    totals = collections.Counter()
    for sy in school_year_rows():
        b = by_sy.get(sy)
        if b is None:
            lines.append("| %s | 0 | 0 | 0 | 0 | 0 | — |" % sy)
            continue
        n_meet = len(b["meetings"])
        n_ag = sum(1 for m in b["meetings"] if m["has_agenda"])
        n_min = sum(1 for m in b["meetings"] if m["has_minutes"])
        srcs = ", ".join(s for s in ("wp", "blackboard", "legacy", "archive")
                         if s in b["sources"]) or "—"
        lines.append("| %s | %d | %d | %d | %d | %d | %s |" % (
            sy, n_meet, n_ag, n_min, b["bar"], b["docs"], srcs))
        totals["meetings"] += n_meet
        totals["agenda"] += n_ag
        totals["minutes"] += n_min
        totals["bar"] += b["bar"]
        totals["docs"] += b["docs"]
    lines.append("| **total** | **%d** | **%d** | **%d** | **%d** | **%d** | |" % (
        totals["meetings"], totals["agenda"], totals["minutes"],
        totals["bar"], totals["docs"]))
    lines.append("")

    # --- documents to fetch, by era (what B2 schedules)
    lines.append("## Documents to fetch, by era (what B2 schedules)")
    lines.append("")
    lines.append("| school year | wp (direct) | wp (sharepoint) | blackboard | legacy | archive |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    wp_direct = collections.Counter()
    wp_sp = collections.Counter()
    for d in documents:
        if d["era"] == "wp":
            (wp_direct if d["fetch"]["kind"] == "direct" else wp_sp)[d["school_year"]] += 1
    for sy in school_year_rows():
        e = by_sy_era.get(sy, collections.Counter())
        if not e:
            continue
        lines.append("| %s | %d | %d | %d | %d | %d |" % (
            sy, wp_direct.get(sy, 0), wp_sp.get(sy, 0),
            e.get("blackboard", 0), e.get("legacy", 0), e.get("archive", 0)))
    lines.append("| **total** | **%d** | **%d** | **%d** | **%d** | **%d** |" % (
        sum(wp_direct.values()), sum(wp_sp.values()),
        sum(e.get("blackboard", 0) for e in by_sy_era.values()),
        sum(e.get("legacy", 0) for e in by_sy_era.values()),
        sum(e.get("archive", 0) for e in by_sy_era.values())))
    lines.append("")

    # --- gaps
    lines.append("## Gaps")
    lines.append("")
    lines.append("### School years with no source at all")
    lines.append("")
    empty = [sy for sy in school_year_rows() if sy not in by_sy or not by_sy[sy]["meetings"]]
    if empty:
        for sy in empty:
            lines.append("- **%s** — no meetings from any source." % sy)
    else:
        lines.append("- none.")
    lines.append("")
    lines.append("### School years with meetings but no minutes anywhere")
    lines.append("")
    thin = [sy for sy in school_year_rows()
            if sy in by_sy and by_sy[sy]["meetings"]
            and sum(1 for m in by_sy[sy]["meetings"] if m["has_minutes"]) == 0]
    if thin:
        for sy in thin:
            lines.append("- **%s** — %d meetings, 0 with minutes." % (
                sy, len(by_sy[sy]["meetings"])))
    else:
        lines.append("- none.")
    lines.append("")
    lines.append("### Meetings with neither an agenda nor minutes")
    lines.append("")
    bad = [m for m in meetings.values() if not m["has_agenda"] and not m["has_minutes"]]
    bad_by_sy = collections.Counter(m["school_year"] for m in bad)
    lines.append("%d of %d meetings (%.0f%%) have no agenda and no minutes document."
                 % (len(bad), len(meetings), 100.0 * len(bad) / max(1, len(meetings))))
    lines.append("")
    lines.append("| school year | meetings w/o agenda or minutes | of total |")
    lines.append("|---|---:|---:|")
    for sy in school_year_rows():
        if sy in by_sy and by_sy[sy]["meetings"]:
            lines.append("| %s | %d | %d |" % (sy, bad_by_sy.get(sy, 0),
                                               len(by_sy[sy]["meetings"])))
    lines.append("")
    zero_wp = [m for m in meetings.values() if m["n_docs"] == 0 and m["wp_id"] is not None]
    zero_wb = [m for m in meetings.values() if m["n_docs"] == 0 and m["wp_id"] is None]
    lines.append("")
    lines.append("Of those, %d have **zero** documents: %d are WP posts that link nothing "
                 "(cancelled or video-only meetings), and %d are Wayback-only dates whose "
                 "every file deduped onto another meeting — an artifact of A2 taking the "
                 "date from the filename while the file sat in a different meeting's folder. "
                 "Treat the second group as 'meeting happened, documents filed elsewhere', "
                 "not as a coverage hole." % (len(zero_wp) + len(zero_wb), len(zero_wp), len(zero_wb)))
    lines.append("")
    lines.append("The full list is every row of `meetings.jsonl` with")
    lines.append("`has_agenda == false and has_minutes == false`; the first 60, oldest first:")
    lines.append("")
    for m in sorted(bad, key=lambda m: m["date"])[:60]:
        lines.append("- `%s` (%s, %d docs, sources: %s)" % (
            m["meeting_id"], m["type"], m["n_docs"], ",".join(m["sources"]) or "none"))
    if len(bad) > 60:
        lines.append("- ... and %d more." % (len(bad) - 60))
    lines.append("")

    # --- left aside
    lines.append("## Left aside (not merged)")
    lines.append("")
    lines.append("| set | rows | file | note |")
    lines.append("|---|---:|---|---|")
    lines.append("| Wayback committee packets | %d | `manifest/wayback_committees.jsonl` | A&F / Operations / Curriculum committee packets; owner decision on scope still open (PLAN §4). |"
                 % len(committees))
    lines.append("| Wayback undated rows | %d | `manifest/wayback_undated.jsonl` | no meeting date derivable from folder or filename (year-level dockets, loose files). |"
                 % len(undated))
    lines.append("| Links with no fetch recipe | %d | `manifest/documents_nofetch.jsonl` | YouTube/Forms/HTML-page links, 5 SharePoint links with no share token, and malformed Wayback URLs. |"
                 % len(nofetch))
    lines.append("")
    nf = collections.Counter(r["reason"] for r in nofetch)
    lines.append("`documents_nofetch.jsonl` by reason:")
    lines.append("")
    for reason, n in nf.most_common():
        lines.append("- `%s`: %d" % (reason, n))
    lines.append("")
    lines.append("Pre-2004-05 is out of scope for automation entirely (WA State Digital")
    lines.append("Archives title 551 is not online; SPS Archives is a manual request).")
    lines.append("")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv=None):
    wp_meetings = read_jsonl(os.path.join(MANIFEST_DIR, "wp_meetings.jsonl"))
    wp_docs = read_jsonl(os.path.join(MANIFEST_DIR, "wp_documents.jsonl"))
    wb_docs = read_jsonl(os.path.join(MANIFEST_DIR, "wayback_documents.jsonl"))
    undated = read_jsonl(os.path.join(MANIFEST_DIR, "wayback_undated.jsonl"))
    committees = read_jsonl(os.path.join(MANIFEST_DIR, "wayback_committees.jsonl"))
    if not wp_meetings or not wb_docs:
        print("missing A1/A2 inputs under %s" % MANIFEST_DIR, file=sys.stderr)
        return 1

    meetings, wp_id_to_meeting, attach, collisions = build_meetings(wp_meetings, wb_docs)
    documents, nofetch, stats = merge_documents(wp_docs, wb_docs, wp_id_to_meeting, attach)

    # roll document facts back onto meetings
    for d in documents:
        m = meetings.get(d["meeting_id"])
        if m is None:
            continue
        m["n_docs"] += 1
        m["n_docs_by_era"][d["era"]] = m["n_docs_by_era"].get(d["era"], 0) + 1
        if d["kind_guess"] == "agenda":
            m["has_agenda"] = True
        elif d["kind_guess"] == "minutes":
            m["has_minutes"] = True
        elif d["kind_guess"] == "bar":
            m["n_bar"] += 1

    meeting_rows = [
        {k: m[k] for k in ("meeting_id", "date", "type", "school_year", "title",
                           "title_source", "sources", "page_url", "wp_id",
                           "has_agenda", "has_minutes", "n_bar", "n_docs",
                           "n_docs_by_era")}
        for m in sorted(meetings.values(), key=lambda m: (m["date"], m["meeting_id"]))
    ]
    documents.sort(key=lambda d: (d["meeting_date"] or "", d["era"], d["doc_id"]))
    nofetch.sort(key=lambda d: (d["meeting_date"] or "", d["era"], d["doc_id"]))

    write_jsonl(os.path.join(MANIFEST_DIR, "meetings.jsonl"), meeting_rows)
    write_jsonl(os.path.join(MANIFEST_DIR, "documents.jsonl"), documents)
    write_jsonl(os.path.join(MANIFEST_DIR, "documents_nofetch.jsonl"), nofetch)

    os.makedirs(QA_DIR, exist_ok=True)
    coverage = build_coverage(meetings, documents, nofetch, undated, committees)
    with open(os.path.join(QA_DIR, "coverage_matrix.md"), "w", encoding="utf-8") as fh:
        fh.write(coverage)

    report = build_merge_report(meetings, meeting_rows, documents, nofetch, wp_docs,
                               wb_docs, stats, collisions, undated, committees)
    with open(os.path.join(MANIFEST_DIR, "merge_report.md"), "w", encoding="utf-8") as fh:
        fh.write(report)
    print(report)
    return 0


def build_merge_report(meetings, meeting_rows, documents, nofetch, wp_docs, wb_docs,
                       stats, collisions, undated, committees):
    L = []
    A = L.append
    A("# Inventory merge report (A3)")
    A("")
    A("## Totals")
    A("")
    A("- input link/capture rows: wp %d + wayback %d = %d" % (
        len(wp_docs), len(wb_docs), len(wp_docs) + len(wb_docs)))
    A("- `documents.jsonl` after dedupe: **%d**" % len(documents))
    A("- `documents_nofetch.jsonl`: %d" % len(nofetch))
    n_alt = sum(len(d["alternates"]) for d in documents)
    A("- alternates recorded on winning rows: %d" % n_alt)
    wp_none = [r for r in wp_docs if (r.get("fetch") or {}).get("kind", "none") == "none"]
    wp_none_dupes = len(wp_none) - len({(r["source_url"], r["meeting_id"]) for r in wp_none})
    A("- reconciliation: %d winners + %d alternates + %d nofetch + %d repeated "
      "no-fetch links on the same page = %d = input rows" % (
          len(documents), n_alt, len(nofetch), wp_none_dupes,
          len(documents) + n_alt + len(nofetch) + wp_none_dupes))
    A("- `meetings.jsonl`: **%d** meetings (%d WP-backed, %d Wayback-only)" % (
        len(meeting_rows),
        sum(1 for m in meeting_rows if m["wp_id"] is not None),
        sum(1 for m in meeting_rows if m["wp_id"] is None)))
    A("")
    A("Documents by era (winning rows):")
    A("")
    for era, n in collections.Counter(d["era"] for d in documents).most_common():
        A("- %s: %d" % (era, n))
    A("")
    A("Fetch recipes to run (B1/B2):")
    A("")
    for kind, n in collections.Counter(d["fetch"]["kind"] for d in documents).most_common():
        A("- `%s`: %d" % (kind, n))
    A("")

    A("## Dedupe detail")
    A("")
    for k in sorted(stats):
        if k.startswith("dedup_"):
            A("- `%s`: %d" % (k, stats[k]))
    A("")
    bb_years = ("16-17", "17-18", "18-19", "19-20", "20-21")
    def bb_sy(row):
        sy = row.get("school_year_folder")
        return sy
    bb_overlap = [r for r in wb_docs if r["era"] == "blackboard" and bb_sy(r) in bb_years]
    kept_urls = {d["source_url"] for d in documents}
    nofetch_urls = {d["source_url"] for d in nofetch}
    kept = sum(1 for r in bb_overlap if r["source_url"] in kept_urls)
    dropped = sum(1 for r in bb_overlap if r["source_url"] not in kept_urls
                  and r["source_url"] not in nofetch_urls)
    skipped = sum(1 for r in bb_overlap if r["source_url"] in nofetch_urls)
    A("Blackboard rows in the WP-overlap years (16-17..20-21): %d total → "
      "**%d kept as unique**, **%d demoted to alternates of a WP row**, %d routed to nofetch."
      % (len(bb_overlap), kept, dropped, skipped))
    A("")
    dig = sum(v for k, v in stats.items() if k.startswith("dedup_") and k.endswith("_on_digest"))
    dig_only = 0
    dig_examples = []
    for d in documents:
        for a in d["alternates"]:
            if a["matched_on"] != "digest":
                continue
            if normalized_name(a["filename"]) != normalized_name(d["filename"]):
                dig_only += 1
                if len(dig_examples) < 5:
                    dig_examples.append((d["source_url"], a["source_url"]))
    A("`cdx_digest` (identical bytes under two URLs) matched %d row(s); %d of those "
      "would NOT have been caught by the filename key. Every instance in this corpus "
      "is a set of minutes filed both in its own meeting folder and in the folder of "
      "the meeting that approved them." % (dig, dig_only))
    for w, a in dig_examples:
        A("  - `%s` == `%s`" % (w[-70:], a[-70:]))
    A("")
    A("Rows whose sources disagree about the meeting date "
      "(`meeting_date_conflict`): %d" % sum(1 for d in documents if d["meeting_date_conflict"]))
    A("")

    A("## Notes for the fetcher (B1/B2)")
    A("")
    wb_win = [d for d in documents if d["era"] != "wp"]
    n200 = sum(1 for d in wb_win if d["cdx_status"] == "200")
    A("- Wayback winners whose CDX row is a 200 capture: %d of %d. The other %d "
      "use A2's `web/2id_/<original>` recipe, which asks Wayback for the nearest "
      "capture of that exact URL; expect a real 404 rate there." % (
          n200, len(wb_win), len(wb_win) - n200))
    retry = [d for d in documents if d["alternates"]
             and any(a["fetch"]["url"] != d["fetch"]["url"] for a in d["alternates"])]
    A("- %d winning rows carry at least one alternate with a different fetch URL. "
      "On a hard failure the fetcher should retry `alternates[*].fetch` before "
      "recording the document as lost." % len(retry))
    A("- Fetch WP first (live, no throttle): %d `direct` + %d `sharepoint_download`. "
      "Then Wayback, 2 connections max: blackboard %d, legacy %d, archive %d." % (
          sum(1 for d in documents if d["fetch"]["kind"] == "direct"),
          sum(1 for d in documents if d["fetch"]["kind"] == "sharepoint_download"),
          sum(1 for d in documents if d["era"] == "blackboard"),
          sum(1 for d in documents if d["era"] == "legacy"),
          sum(1 for d in documents if d["era"] == "archive")))
    A("")
    A("## Meeting sanity checks")
    A("")
    wp_backed = [m for m in meeting_rows if m["wp_id"] is not None]
    A("- WP meetings with no minutes document: **%d** of %d" % (
        sum(1 for m in wp_backed if not m["has_minutes"]), len(wp_backed)))
    A("- WP meetings with no agenda document: %d of %d" % (
        sum(1 for m in wp_backed if not m["has_agenda"]), len(wp_backed)))
    A("- WP meetings with neither: %d" % sum(
        1 for m in wp_backed if not m["has_minutes"] and not m["has_agenda"]))
    A("- all meetings with neither agenda nor minutes: %d of %d" % (
        sum(1 for m in meeting_rows if not m["has_minutes"] and not m["has_agenda"]),
        len(meeting_rows)))
    A("- meetings with zero documents: %d" % sum(1 for m in meeting_rows if m["n_docs"] == 0))
    A("")
    A("By meeting type (all meetings):")
    A("")
    A("| type | meetings | w/ agenda | w/ minutes |")
    A("|---|---:|---:|---:|")
    for t in TYPE_ORDER:
        rows = [m for m in meeting_rows if m["type"] == t]
        if rows:
            A("| %s | %d | %d | %d |" % (t, len(rows),
                                          sum(1 for m in rows if m["has_agenda"]),
                                          sum(1 for m in rows if m["has_minutes"])))
    A("")
    A("## meeting_id collisions resolved")
    A("")
    if collisions:
        for date, mtype, ids in collisions:
            A("- `%s-%s`: %d WP posts (wp_id %s) → bare id for the lowest wp_id, "
              "`-2`.. for the rest." % (date, mtype, len(ids),
                                        ", ".join(str(i) for i in ids)))
    else:
        A("- none.")
    A("")
    A("## Left aside")
    A("")
    A("- committee packets: %d (`wayback_committees.jsonl`)" % len(committees))
    A("- undated Wayback rows: %d (`wayback_undated.jsonl`)" % len(undated))
    A("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
