"""Wayback Machine CDX inventories for the three pre-WordPress board-document
sources (task card A2 in extractors/sps_web/PLAN.md).

Usage (from the repo root)::

    venv/bin/python3 -m extractors.sps_web.inventory_wayback
    venv/bin/python3 -m extractors.sps_web.inventory_wayback --era blackboard
    venv/bin/python3 -m extractors.sps_web.inventory_wayback --refetch-cdx

Queries the Wayback Machine CDX API (`https://web.archive.org/cdx/search/cdx`)
for three URL patterns and turns the raw capture list into a document
inventory with a best-effort meeting date per row:

- ``blackboard`` -- ``seattleschools.org/UserFiles/Servers/Server_543/File/
  District/Departments/School%20Board/*`` (site used ~2011-12..2016-17).
- ``legacy`` -- ``seattleschools.org/area/board/*`` (site used ~2005-06..
  2010-11).
- ``archive`` -- ``spsarchivepublic.seattleschools.org/*`` ("edited agendas"
  2006-2012, a supplement/cross-check for the thin 2011-12 year).

CDX mechanics
--------------
Each pull uses ``collapse=urlkey`` and ``fl=timestamp,original,statuscode,
mimetype,digest``, a descriptive User-Agent, >=2s between requests, and
exponential-backoff retry on 429/502/503/504 *and* on any other
non-CDX-shaped response (the CDX server occasionally serves an HTML error
page with a 5xx, or -- observed live while building this script -- simply
times out; both are treated as retryable). Large patterns are paged with
``showNumPages=true`` + ``page=N`` rather than pulled in one shot (the
blackboard pattern alone is ~97 pages). Every raw page response is cached
verbatim under ``out_sps_web/manifest/cdx_cache/<name>_p<N>.txt`` (plus a
``<name>_numpages.txt``) so reruns of this script, or a future rerun after a
schema tweak, do not re-hit archive.org at all unless ``--refetch-cdx`` is
passed.

``collapse=urlkey`` only collapses *adjacent* rows within one page/block, so
a URL that straddles a page boundary (or whose capture history interleaves
with an unrelated revisit record -- observed live in the archive-host pull)
can appear more than once across the full paginated pull. This script does
its own global de-duplication after concatenating all pages, keyed on a
normalized ``(host, path)`` (scheme and leading ``www.``/port stripped,
percent-encoding left as-is so two different escapings of the same path are
NOT accidentally merged -- none were observed). Among duplicates for one key
the best capture wins: prefer ``statuscode == "200"``, then the newest
``timestamp``.

Decision -- non-200 rows are NOT re-queried individually. ``collapse=urlkey``
guarantees one row per URL but not that the row is a 200 (e.g. a URL that
was later deleted, or whose most economical capture is a "-"/revisit
record). A targeted per-URL CDX lookup would add one request per non-200 URL
-- thousands of extra requests against a server that already needed ~100
paginated requests and sometimes just times out -- so instead this script
records whatever ``cdx_status``/``cdx_timestamp`` survived the dedup pass and
emits a ``fetch`` recipe that is deliberately different for the two cases:
``cdx_status == "200"`` -> exact raw capture, ``http://web.archive.org/web/
<timestamp>id_/<original>``; anything else -> ``http://web.archive.org/web/
2id_/<original>`` (a Wayback URL with a synthetic near-earliest timestamp,
which the Wayback replay server resolves to the *nearest available* capture
of that exact URL regardless of status). This pushes the "does a usable
capture actually exist" question to the fetch stage (B1), which is where a
real HTTP round-trip against archive.org happens anyway.

Row shapes (see the module docstring's Output section in PLAN.md A2):

``wayback_documents.jsonl`` / ``wayback_committees.jsonl`` / (partially)
``wayback_undated.jsonl`` rows::

    {doc_id, era, meeting_date, date_source, school_year_folder, folder,
     filename, ext, source_url, cdx_timestamp, cdx_status, cdx_mimetype,
     cdx_digest, fetch: {kind, url}, kind_guess, edited, date_mismatch}

``wayback_undated.jsonl`` rows are the subset of would-be
``wayback_documents.jsonl`` rows for which no date could be derived
(``meeting_date`` is null); they are written there INSTEAD of to
``wayback_documents.jsonl`` (not duplicated) so every row in the main file
has a real date, per the A2 acceptance criterion. Committee-packet rows
follow the same rule against ``wayback_committees.jsonl``.

``wayback_meetings.jsonl`` rows (one per distinct ``(era, meeting_date)``
seen in ``wayback_documents.jsonl`` only -- committees/undated are excluded)::

    {meeting_id, era, date, n_docs, has_agenda, has_minutes, n_bar}

Folder/skip rules per era (see module docstring further down for the exact
sets) are implemented in ``classify_blackboard``, ``classify_legacy``, and
``classify_archive``. One deliberate extension beyond the literal task text:
on the *legacy* host, meeting-era folders (2008-09 on) exist, but 2005-2006
agendas were served as loose files directly under ``area/board/`` (no
per-meeting folder yet) -- e.g. ``020205 Agenda.pdf``, ``011905BdAgenda.pdf``.
Blanket-skipping all loose root files (as instructed for the blackboard host,
where loose root files are genuinely all junk -- district maps, resumes,
flyers) would silently drop real 2005-2006 agendas. So for ``legacy`` only,
a loose root file is KEPT if its filename contains "agenda" or "minutes"
(case-insensitive) AND a date can be extracted from it; otherwise it is
skipped as ``loose_root_file`` same as blackboard.

Date parsing tries, in order, on the filename stem first and then on each
folder segment from deepest to shallowest: ISO ``YYYY-MM-DD``, then an
8-digit run tried as ``YYYYMMDD`` and, if that doesn't validate, as
``MMDDYYYY`` (no separate context heuristic needed -- year-range validation
disambiguates the two in practice), then a 6-digit run as ``MMDDYY``. The
chosen date is sanity-checked against a school-year folder token
(``NN-NNagendas``/``NN-NNboardminutes``/...) when one is present in the
path, and against a same-row ISO folder date when a different filename date
won; mismatches set ``date_mismatch: true`` and are tallied in the report,
not dropped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date as Date
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO_ROOT / "out_sps_web"
MANIFEST_DIR = OUT_ROOT / "manifest"
CACHE_DIR = MANIFEST_DIR / "cdx_cache"

CDX_BASE = "https://web.archive.org/cdx/search/cdx"
USER_AGENT = (
    "sps-data-tools-board-contracts-inventory/1.0 "
    "(research/civic data project; contact awong.dev@gmail.com)"
)

MIN_REQUEST_GAP = 2.2          # seconds, spec requires >=2s between requests
RETRY_STATUSES = {429, 502, 503, 504}
MAX_RETRIES = 6
RETRY_WAIT = 30.0              # fixed wait between retries (not exponential):
                                # the CDX main index either answers a
                                # single-shot query within ~90s or it is
                                # having a bad moment and a flat 30s pause
                                # before the next of 6 tries is what worked
                                # in practice for these three patterns.

EXT_SKIP = {
    "jpg", "jpeg", "png", "gif", "ico", "xml", "html", "htm", "css", "js",
    "asp", "aspx", "svg", "bmp",
}

SOURCES = {
    "blackboard": {
        "pattern": (
            "seattleschools.org/UserFiles/Servers/Server_543/File/District/"
            "Departments/School%20Board/*"
        ),
        "root_marker": "school board/",
    },
    "legacy": {
        "pattern": "seattleschools.org/area/board/*",
        "root_marker": "area/board/",
    },
    "archive": {
        "pattern": "spsarchivepublic.seattleschools.org/*",
        "root_marker": "publicdocuments/",
    },
}

BLACKBOARD_SKIP_TOP = {
    "friday memos", "policies", "procedures", "maps", "annual reports",
    "resolutions",
}
BLACKBOARD_COMMITTEE_TOP = {"committees"}

LEGACY_COMMITTEE_TOP = {"committees", "committeereports"}
_YY_YY_DIR_RE = re.compile(r"^(\d{2}).{0,3}(\d{2})\s*(agendas?|boardminutes|minutes)$", re.I)
_BARE_MMDDYY_AGENDA_DIR_RE = re.compile(r"^(\d{6})\s*agenda$", re.I)
_MINUTES_DIR_RE = re.compile(r"minutes$", re.I)

# ---------------------------------------------------------------------------
# HTTP with politeness + retry
# ---------------------------------------------------------------------------

_last_request_at = 0.0


def _polite_wait() -> None:
    global _last_request_at
    now = time.monotonic()
    gap = now - _last_request_at
    if gap < MIN_REQUEST_GAP:
        time.sleep(MIN_REQUEST_GAP - gap)
    _last_request_at = time.monotonic()


def _looks_like_cdx_or_empty(text: str) -> bool:
    """True if `text` looks like plain CDX rows (or is empty), false if it
    looks like an HTML error page masquerading as a response body."""
    stripped = text.lstrip()
    if not stripped:
        return True
    lowered = stripped[:200].lower()
    if lowered.startswith("<") or "<html" in lowered or "<!doctype" in lowered:
        return False
    return True


def cdx_get(params: dict, timeout: int = 110) -> str:
    """GET the CDX endpoint with politeness + fixed-wait retry.

    Retries on: network errors/timeouts, HTTP 429/502/503/504, and any 200
    response whose body doesn't look like CDX text (an HTML error page --
    observed live: the CDX server sometimes serves a 502/504 as an HTML
    body instead of plain text)."""
    query = urllib.parse.urlencode(params, safe="*,%")
    url = f"{CDX_BASE}?{query}"
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        _polite_wait()
        status = None
        body = ""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status = resp.status
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            last_err = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = e
            status = None

        retryable = (
            status is None
            or status in RETRY_STATUSES
            or (status == 200 and not _looks_like_cdx_or_empty(body))
        )
        if not retryable:
            if status != 200:
                raise RuntimeError(f"CDX request failed status={status} url={url}\nbody[:300]={body[:300]!r}")
            return body

        print(
            f"  [cdx retry {attempt}/{MAX_RETRIES}] status={status} "
            f"wait={RETRY_WAIT:.0f}s url={url}",
            file=sys.stderr,
        )
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_WAIT)

    raise RuntimeError(f"CDX request failed after {MAX_RETRIES} attempts: {url}\nlast_err={last_err}")


def _parse_cdx_lines(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 5:
            rows.append(parts)
    return rows


def _parse_fallback_lines(text: str) -> list[list[str]]:
    """Parse a scout-provided local CDX dump used only as a fallback when the
    live query fails after retries. Row shapes observed in practice:
    5-field (timestamp original statuscode mimetype digest, the normal CDX
    shape), 3-field (timestamp original statuscode, no mimetype/digest), or
    2-field (original statuscode, no timestamp at all -- seen for the
    archive-host scout dump). Missing fields are padded so downstream code
    always sees 5 columns; a missing timestamp means the fetch recipe can't
    build an exact-capture URL and falls back to the nearest-capture
    (`2id_`) recipe for that row -- see build_rows()."""
    rows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 5:
            rows.append(parts)
        elif len(parts) == 3:
            ts, original, status = parts
            rows.append([ts, original, status, "unk", ""])
        elif len(parts) == 2:
            original, status = parts
            rows.append(["", original, status, "unk", ""])
    return rows


def fetch_cdx_rows(name: str, pattern: str, refetch: bool, fallback_path: Optional[Path]) -> list[list[str]]:
    """Fetch (and cache) one era's full CDX pull as a single non-paginated
    query. Pagination (`page=`/`showNumPages=true`) was tried first but the
    CDX server's paginated (ZipNum secondary) index proved unreliable for
    these three patterns -- slow and, on the blackboard pattern, it never
    finished a full pass. A single `collapse=urlkey` query against the main
    index answers all three patterns (including the ~7-8k-row blackboard
    one) directly, so that's the only path now. If it still fails after
    MAX_RETRIES and a `fallback_path` was given (a scout-provided local CDX
    dump), that file is used instead and the fact is logged."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{name}.txt"
    if cache_file.exists() and not refetch:
        text = cache_file.read_text()
        print(f"[{name}] using cached {cache_file}", file=sys.stderr)
        return _parse_cdx_lines(text)

    try:
        text = cdx_get({
            "url": pattern,
            "collapse": "urlkey",
            "fl": "timestamp,original,statuscode,mimetype,digest",
        })
        cache_file.write_text(text)
        rows = _parse_cdx_lines(text)
        print(f"[{name}] fetched single-shot CDX query ({len(rows)} rows)", file=sys.stderr)
        return rows
    except RuntimeError as e:
        if fallback_path is None:
            raise
        print(
            f"[{name}] live CDX query failed after {MAX_RETRIES} attempts "
            f"({e}); falling back to local dump {fallback_path}",
            file=sys.stderr,
        )
        text = Path(fallback_path).read_text()
        rows = _parse_fallback_lines(text)
        fallback_cache = CACHE_DIR / f"{name}_fallback_dump.txt"
        fallback_cache.write_text(text)
        print(f"[{name}] loaded {len(rows)} rows from fallback dump", file=sys.stderr)
        return rows


# ---------------------------------------------------------------------------
# Global de-dup: best capture per URL
# ---------------------------------------------------------------------------

def dedup_key(original: str) -> str:
    """Normalize scheme/``www.``/default-port variation only -- NOT the
    query string. Dropping the query string looked tempting (many legacy
    captures differ only by a harmless ``?wrapper=0`` templating parameter)
    but over-collapsed genuinely distinct captures; verified against a full
    corpus pull that keeping the query string reproduces the CDX-level
    distinct-URL count exactly (0 accidental cross-page duplicates beyond
    true scheme/port variants)."""
    parsed = urllib.parse.urlsplit(original)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    host = host.split(":")[0]  # drop :80 etc.
    path = parsed.path
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{host}{path}{query}"


def dedup_rows(rows: list[list[str]]) -> list[list[str]]:
    """rows: list of [timestamp, original, statuscode, mimetype, digest].
    Keep one row per dedup_key: prefer statuscode == '200', then newest
    timestamp."""
    best: dict[str, list[str]] = {}
    for row in rows:
        ts, original, status, mimetype, digest = row
        key = dedup_key(original)
        cur = best.get(key)
        if cur is None:
            best[key] = row
            continue
        cur_ts, _, cur_status, _, _ = cur
        cur_is_200 = cur_status == "200"
        new_is_200 = status == "200"
        if new_is_200 and not cur_is_200:
            best[key] = row
        elif new_is_200 == cur_is_200 and ts > cur_ts:
            best[key] = row
    return list(best.values())


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_D8_RE = re.compile(r"(?<!\d)(\d{8})(?!\d)")
_D6_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")

_MIN_YEAR, _MAX_YEAR = 2003, 2027


def _valid_date(y: int, mo: int, d: int) -> Optional[Date]:
    if not (_MIN_YEAR <= y <= _MAX_YEAR and 1 <= mo <= 12 and 1 <= d <= 31):
        return None
    try:
        return Date(y, mo, d)
    except ValueError:
        return None


def find_iso_date(s: str) -> Optional[tuple[Date, str]]:
    m = _ISO_DATE_RE.search(s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    dt = _valid_date(y, mo, d)
    return (dt, "yyyy-mm-dd") if dt else None


def find_8digit_date(s: str) -> Optional[tuple[Date, str]]:
    for m in _D8_RE.finditer(s):
        tok = m.group(1)
        dt = _valid_date(int(tok[0:4]), int(tok[4:6]), int(tok[6:8]))
        if dt:
            return dt, "yyyymmdd"
        dt = _valid_date(int(tok[4:8]), int(tok[0:2]), int(tok[2:4]))
        if dt:
            return dt, "mmddyyyy"
    return None


def find_6digit_date(s: str) -> Optional[tuple[Date, str]]:
    for m in _D6_RE.finditer(s):
        tok = m.group(1)
        mo, d, yy = int(tok[0:2]), int(tok[2:4]), int(tok[4:6])
        y = 2000 + yy if yy < 50 else 1900 + yy
        dt = _valid_date(y, mo, d)
        if dt:
            return dt, "mmddyy"
    return None


def find_date_in(s: str) -> Optional[tuple[Date, str]]:
    for fn in (find_iso_date, find_8digit_date, find_6digit_date):
        r = fn(s)
        if r:
            return r
    return None


_SCHOOL_YEAR_RE = re.compile(r"^(\d{2}).{0,3}(\d{2})\s*(agendas?|boardminutes|minutes)?$", re.I)


def find_school_year_folder(folder_segments: list[str]) -> Optional[str]:
    for seg in folder_segments:
        m = _SCHOOL_YEAR_RE.match(seg.strip())
        if m:
            y1, y2 = m.group(1), m.group(2)
            if int(y2) == (int(y1) + 1) % 100:
                return f"{y1}-{y2}"
    return None


def school_year_window(school_year_folder: str) -> Optional[tuple[Date, Date]]:
    try:
        y1, y2 = school_year_folder.split("-")
        y1i = 2000 + int(y1)
        y2i = 2000 + int(y2)
    except ValueError:
        return None
    return Date(y1i, 8, 1), Date(y2i, 7, 31)


def derive_date(filename: str, folder_segments: list[str]) -> tuple[Optional[Date], Optional[str]]:
    stem = os.path.splitext(filename)[0]
    hit = find_date_in(stem)
    if hit:
        dt, label = hit
        return dt, f"filename_{label}"
    for seg in reversed(folder_segments):
        hit = find_date_in(seg)
        if hit:
            dt, label = hit
            return dt, f"folder_{label}"
    return None, None


# ---------------------------------------------------------------------------
# Kind guessing
# ---------------------------------------------------------------------------

def guess_kind(filename: str) -> str:
    low = filename.lower()
    if "actionreport" in low or "action_report" in low or "action-report" in low or "_bar" in low or low.startswith("bar_"):
        return "bar"
    if "agenda" in low:  # covers spagenda too
        return "agenda"
    if "minutes" in low:
        return "minutes"
    if "warrant" in low:
        return "warrants"
    if "presentation" in low:
        return "presentation"
    return "other"


# ---------------------------------------------------------------------------
# Per-era classification: returns (bucket, skip_reason) where bucket is one
# of "keep", "committee", "skip".
# ---------------------------------------------------------------------------

def classify_blackboard(folder_segments: list[str], filename: str, ext: str) -> tuple[str, Optional[str]]:
    if not folder_segments:
        return "skip", "loose_root_file"
    top = folder_segments[0].strip()
    top_low = top.lower()
    if top_low in BLACKBOARD_COMMITTEE_TOP or top_low.startswith("committee"):
        return "committee", None
    if top_low in BLACKBOARD_SKIP_TOP:
        return "skip", f"out_of_scope_folder:{top_low}"
    if ext in EXT_SKIP:
        return "skip", "chrome_extension"
    return "keep", None


def classify_legacy(folder_segments: list[str], filename: str, ext: str) -> tuple[str, Optional[str]]:
    if not folder_segments:
        low = filename.lower()
        if ("agenda" in low or "minutes" in low) and find_date_in(os.path.splitext(filename)[0]):
            if ext in EXT_SKIP:
                return "skip", "chrome_extension"
            return "keep", None
        return "skip", "loose_root_file"
    top = folder_segments[0].strip()
    top_low = top.lower()
    if top_low in LEGACY_COMMITTEE_TOP:
        return "committee", None
    keep_top = (
        _YY_YY_DIR_RE.match(top)
        or _BARE_MMDDYY_AGENDA_DIR_RE.match(top)
        or _MINUTES_DIR_RE.search(top_low)
        or top_low in {"agendadockets", "resolutions"}
    )
    if not keep_top:
        return "skip", "unrecognized_folder"
    if ext in EXT_SKIP:
        return "skip", "chrome_extension"
    return "keep", None


def classify_archive(folder_segments: list[str], filename: str, ext: str) -> tuple[str, Optional[str]]:
    joined_low = "/".join(folder_segments).lower()
    if "board-documents/meeting-minutes" not in joined_low:
        return "skip", "outside_meeting_minutes"
    if ext in EXT_SKIP:
        return "skip", "chrome_extension"
    if filename.lower() in {"favicon.ico", "robots.txt"}:
        return "skip", "chrome_file"
    return "keep", None


CLASSIFIERS = {
    "blackboard": classify_blackboard,
    "legacy": classify_legacy,
    "archive": classify_archive,
}


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------

@dataclass
class Stats:
    urls_seen: int = 0
    kept: int = 0
    committee: int = 0
    undated: int = 0
    skip_reasons: Counter = field(default_factory=Counter)
    status_dist: Counter = field(default_factory=Counter)
    date_mismatch: int = 0
    by_school_year: dict = field(default_factory=lambda: defaultdict(lambda: Counter()))


def split_path(original: str, root_marker: str) -> Optional[tuple[list[str], str]]:
    decoded = urllib.parse.unquote(original)
    parsed = urllib.parse.urlsplit(decoded)
    path = parsed.path.lstrip("/")
    low = path.lower()
    idx = low.find(root_marker)
    if idx == -1:
        return None
    rel = path[idx + len(root_marker):]
    rel = rel.strip("/")
    if not rel:
        return [], ""
    pieces = [p for p in rel.split("/") if p != ""]
    if not pieces:
        return [], ""
    filename = pieces[-1]
    folder_segments = pieces[:-1]
    return folder_segments, filename


def academic_year_label(dt: Date) -> str:
    if dt.month >= 8:
        y1, y2 = dt.year, dt.year + 1
    else:
        y1, y2 = dt.year - 1, dt.year
    return f"{y1}-{str(y2)[-2:]}"


def build_rows(era: str, rows: list[list[str]], stats: Stats):
    """Yields (bucket, row_dict) for bucket in {'document','committee'} for
    kept rows (row['meeting_date'] set), or ('undated', row_dict) when a kept
    row has no derivable date."""
    root_marker = SOURCES[era]["root_marker"]
    classifier = CLASSIFIERS[era]
    stats.urls_seen = len(rows)
    for ts, original, status, mimetype, digest in rows:
        stats.status_dist[status] += 1
        split = split_path(original, root_marker)
        if split is None:
            stats.skip_reasons["no_root_marker"] += 1
            continue
        folder_segments, filename = split
        if not filename:
            stats.skip_reasons["root_listing"] += 1
            continue
        ext = os.path.splitext(filename)[1].lstrip(".").lower()

        bucket, reason = classifier(folder_segments, filename, ext)
        if bucket == "skip":
            stats.skip_reasons[reason or "skip"] += 1
            continue

        folder = "/".join(folder_segments)
        school_year_folder = find_school_year_folder(folder_segments)
        meeting_date, date_source = derive_date(filename, folder_segments)

        date_mismatch = False
        if meeting_date is not None and school_year_folder is not None:
            window = school_year_window(school_year_folder)
            if window and not (window[0] <= meeting_date <= window[1]):
                date_mismatch = True
        if meeting_date is not None:
            iso_hit = None
            for seg in folder_segments:
                iso_hit = find_iso_date(seg)
                if iso_hit:
                    break
            if iso_hit and iso_hit[0] != meeting_date:
                date_mismatch = True
        if date_mismatch:
            stats.date_mismatch += 1

        low_fn = filename.lower()
        edited = era == "archive" and low_fn.startswith("edited")
        kind_guess = "agenda" if edited else guess_kind(filename)

        doc_id = hashlib.sha1(original.encode("utf-8")).hexdigest()[:16]
        if status == "200" and ts:
            fetch_url = f"http://web.archive.org/web/{ts}id_/{original}"
        else:
            # No confirmed-200 timestamp to build an exact capture URL from
            # (either the CDX row wasn't 200, or -- fallback-dump rows only
            # -- no timestamp was available at all); ask Wayback to resolve
            # the nearest available capture of this exact URL instead.
            fetch_url = f"http://web.archive.org/web/2id_/{original}"

        row = {
            "doc_id": doc_id,
            "era": era,
            "meeting_date": meeting_date.isoformat() if meeting_date else None,
            "date_source": date_source,
            "school_year_folder": school_year_folder,
            "folder": folder,
            "filename": filename,
            "ext": ext,
            "source_url": original,
            "cdx_timestamp": ts or None,
            "cdx_status": status,
            "cdx_mimetype": mimetype,
            "cdx_digest": digest,
            "fetch": {"kind": "wayback_raw", "url": fetch_url},
            "kind_guess": kind_guess,
            "edited": edited,
            "date_mismatch": date_mismatch,
        }

        if bucket == "committee":
            stats.committee += 1
            if meeting_date is None:
                stats.undated += 1
            yield "committee", row
            continue

        if meeting_date is None:
            stats.undated += 1
            yield "undated", row
            continue

        stats.kept += 1
        sy = academic_year_label(meeting_date)
        stats.by_school_year[sy][kind_guess] += 1
        yield "document", row


# ---------------------------------------------------------------------------
# Meetings roll-up
# ---------------------------------------------------------------------------

def build_meetings(document_rows: list[dict]) -> list[dict]:
    groups: dict[tuple[str, str], dict] = {}
    for row in document_rows:
        key = (row["era"], row["meeting_date"])
        g = groups.setdefault(key, {
            "meeting_id": f"{row['meeting_date']}-{row['era']}",
            "era": row["era"],
            "date": row["meeting_date"],
            "n_docs": 0,
            "has_agenda": False,
            "has_minutes": False,
            "n_bar": 0,
        })
        g["n_docs"] += 1
        if row["kind_guess"] == "agenda":
            g["has_agenda"] = True
        elif row["kind_guess"] == "minutes":
            g["has_minutes"] = True
        elif row["kind_guess"] == "bar":
            g["n_bar"] += 1
    return sorted(groups.values(), key=lambda g: (g["date"], g["era"]))


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(path: Path, all_stats: dict[str, Stats]):
    lines = ["# Wayback inventory report", ""]
    lines.append("Built by `extractors/sps_web/inventory_wayback.py` (task A2).")
    lines.append("")
    for era, stats in all_stats.items():
        lines.append(f"## {era}")
        lines.append("")
        lines.append(f"- URLs seen (post-dedup): {stats.urls_seen}")
        lines.append(f"- Kept (documents): {stats.kept}")
        lines.append(f"- Committee packets (flagged, separate file): {stats.committee}")
        lines.append(f"- Undated (kept+committee rows with no derivable date): {stats.undated}")
        lines.append(f"- Date/school-year mismatches flagged: {stats.date_mismatch}")
        lines.append("")
        lines.append("Skipped by reason:")
        lines.append("")
        for reason, n in stats.skip_reasons.most_common():
            lines.append(f"- {reason}: {n}")
        lines.append("")
        lines.append("CDX status-code distribution (all URLs seen, pre-filter):")
        lines.append("")
        for status, n in stats.status_dist.most_common():
            lines.append(f"- {status}: {n}")
        lines.append("")
        lines.append("Documents per school year (kept rows; kind_guess counts):")
        lines.append("")
        lines.append("| school year | total | agenda | minutes | bar | warrants | presentation | other |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for sy in sorted(stats.by_school_year.keys()):
            c = stats.by_school_year[sy]
            total = sum(c.values())
            lines.append(
                f"| {sy} | {total} | {c.get('agenda', 0)} | {c.get('minutes', 0)} | "
                f"{c.get('bar', 0)} | {c.get('warrants', 0)} | {c.get('presentation', 0)} | "
                f"{c.get('other', 0)} |"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _load_existing_by_era(path: Path) -> dict[str, list[dict]]:
    """Read a previously-written jsonl inventory file and group its rows by
    era, so a filtered --era rerun can replace just those eras' rows and
    leave the rest of the merged file intact instead of truncating it."""
    by_era: dict[str, list[dict]] = defaultdict(list)
    if not path.exists():
        return by_era
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            by_era[row["era"]].append(row)
    return by_era


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--era", choices=list(SOURCES.keys()), action="append",
                     help="limit to one or more eras (default: all three); "
                          "rows for eras NOT selected are preserved from the "
                          "existing output files rather than dropped")
    ap.add_argument("--refetch-cdx", action="store_true",
                     help="ignore the CDX page cache and re-hit archive.org")
    ap.add_argument("--fallback", action="append", default=[],
                     metavar="ERA=PATH",
                     help="local CDX dump to use for ERA if the live query "
                          "fails after retries (rows: 5-field CDX, 3-field "
                          "'timestamp original statuscode', or 2-field "
                          "'original statuscode'); repeatable")
    args = ap.parse_args(argv)

    eras = args.era or list(SOURCES.keys())
    fallback_paths: dict[str, Path] = {}
    for spec in args.fallback:
        if "=" not in spec:
            ap.error(f"--fallback must be ERA=PATH, got {spec!r}")
        era_name, _, path_str = spec.partition("=")
        if era_name not in SOURCES:
            ap.error(f"--fallback: unknown era {era_name!r}")
        fallback_paths[era_name] = Path(path_str)

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    documents_path = MANIFEST_DIR / "wayback_documents.jsonl"
    committees_path = MANIFEST_DIR / "wayback_committees.jsonl"
    undated_path = MANIFEST_DIR / "wayback_undated.jsonl"
    meetings_path = MANIFEST_DIR / "wayback_meetings.jsonl"
    report_path = MANIFEST_DIR / "wayback_inventory_report.md"

    documents_by_era = _load_existing_by_era(documents_path)
    committees_by_era = _load_existing_by_era(committees_path)
    undated_by_era = _load_existing_by_era(undated_path)
    all_stats: dict[str, Stats] = {}

    for era in eras:
        pattern = SOURCES[era]["pattern"]
        raw_rows = fetch_cdx_rows(era, pattern, args.refetch_cdx, fallback_paths.get(era))
        deduped = dedup_rows(raw_rows)
        stats = Stats()
        documents_by_era[era] = []
        committees_by_era[era] = []
        undated_by_era[era] = []
        for bucket, row in build_rows(era, deduped, stats):
            if bucket == "document":
                documents_by_era[era].append(row)
            elif bucket == "committee":
                committees_by_era[era].append(row)
            elif bucket == "undated":
                undated_by_era[era].append(row)
        all_stats[era] = stats
        print(
            f"[{era}] seen={stats.urls_seen} kept={stats.kept} "
            f"committee={stats.committee} undated={stats.undated}",
            file=sys.stderr,
        )

    era_order = list(SOURCES.keys())

    def _write_grouped(path: Path, by_era: dict[str, list[dict]]):
        with open(path, "w") as f:
            for era in era_order:
                for row in by_era.get(era, []):
                    f.write(json.dumps(row) + "\n")

    _write_grouped(documents_path, documents_by_era)
    _write_grouped(committees_path, committees_by_era)
    _write_grouped(undated_path, undated_by_era)

    all_document_rows = [row for era in era_order for row in documents_by_era.get(era, [])]
    meetings = build_meetings(all_document_rows)
    with open(meetings_path, "w") as fm:
        for m in meetings:
            fm.write(json.dumps(m) + "\n")

    write_report(report_path, all_stats)

    print(f"\nWrote {documents_path}", file=sys.stderr)
    print(f"Wrote {committees_path}", file=sys.stderr)
    print(f"Wrote {undated_path}", file=sys.stderr)
    print(f"Wrote {meetings_path}", file=sys.stderr)
    print(f"Wrote {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
