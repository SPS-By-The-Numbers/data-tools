"""
Downloads documents listed in sps_web inventory manifests to local disk.

Usage (from repo root):
    $ venv/bin/python3 -m extractors.sps_web.fetch
    $ venv/bin/python3 -m extractors.sps_web.fetch --era wp --limit 20 --dry-run
    $ venv/bin/python3 -m extractors.sps_web.fetch --manifest out_sps_web/manifest/wp_documents.jsonl
    $ venv/bin/python3 -m extractors.sps_web.fetch --outdir /tmp/scratch --workers 2

Consumes one or more JSONL manifests (default: every
`<outdir>/manifest/*_documents.jsonl`), one row per document:
    {"doc_id": "...", "era": "wp|blackboard|legacy|archive",
     "meeting_date": "YYYY-MM-DD" | null, "source_url": "...", "filename": "...",
     "fetch": {"kind": "direct|sharepoint_download|wayback_raw|none",
               "url": "...", "token": "..."}}   # token only for sharepoint_download
Rows with `fetch.kind == "none"` are counted and skipped (dead link, embed, etc).

Recipes:
  direct — plain GET of fetch.url (falls back to source_url).
  sharepoint_download — GET
    https://seattleschools.sharepoint.com/sites/SPSBoardOffice-O365/_layouts/15/download.aspx?share=<TOKEN>
    (built from fetch.token if present, else fetch.url verbatim), shared cookie
    jar, redirects followed. Never use the plain `:b:` share link (MS login
    bounce). A 200 response that is actually an HTML login page -> failure
    reason "login_wall".
  wayback_raw — GET http://web.archive.org/web/<ts>id_/<original> (id_ = raw
    original bytes). A 404 is retried once against
    http://web.archive.org/web/2id_/<original> (nearest capture). Resolved
    capture timestamp is parsed from the final response URL. A "page not
    archived" HTML response (at either URL) -> failure reason "wayback_missing".

Destination layout:
    <outdir>/raw/<era>/<meeting_date or "undated">/<safe_filename>
    <outdir>/raw/<era>/<meeting_date or "undated">/<safe_filename>.prov.json
If two docs in the same (era, meeting_date) share a safe filename, every
doc_id in that collision group gets a `-<doc_id>` suffix before the extension
(computed once over the full, unfiltered manifest set, so the mapping is
stable regardless of which --era/--year/--limit subset a given run fetches).

Provenance schema (<file>.prov.json): doc_id, source_url, fetch_url (URL
actually requested), fetch_kind, fetched_at (UTC ISO), http_status,
content_type, bytes, sha256, wayback_timestamp (or null), final_url
(post-redirect response URL).

A file is "already fetched" (skipped on rerun) when both the destination file
and its .prov.json exist and the destination is non-empty. Writes are atomic
(temp file + os.replace) so a killed run never leaves a partial file mistaken
for a real one.

Content is validated by magic bytes, not by the guessed extension: %PDF,
JPEG/PNG/GIF, and OLE/ZIP-based office formats are all accepted and saved
with the extension/content_type the bytes actually imply (a district link
that resolves to a JPEG, say, is saved as .jpg even though a sharepoint_
download row with no filename guesses .pdf). Only HTML or otherwise
unrecognized bytes where a document was expected fail, as not_pdf (or
wayback_missing / login_wall per recipe, see above).

Rate limits/retries: per-host pacing of request *starts*, independent of
thread count — www.seattleschools.org and seattleschools.sharepoint.com
1 req/s; web.archive.org 0.5 req/s, <=2 concurrent connections. 429/5xx/
connection errors retry with exponential backoff (honoring Retry-After);
after 5 tries the row is appended to <outdir>/manifest/fetch_failures.jsonl
as {run_id, doc_id, fetch_url, status, error, tries} with no partial file
left. That file is append-only across runs (never truncated), so failure
history survives reruns; `run_id` (this run's UTC start timestamp) marks
which run produced each line, and the stdout/fetch_report.md summary still
covers only the current run. Other 4xx (e.g. a plain 404 outside the
wayback_raw retry path) fails immediately.

robots.txt for www.seattleschools.org is fetched once at startup and logged;
it is known to allow everything except /wp-admin/, which this never touches.
"""

import argparse
import glob
import json
import os
import random
import re
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
from http.client import IncompleteRead
from http.cookiejar import CookieJar
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

USER_AGENT = "sps-data-tools/board-contracts (github.com/SPS-By-The-Numbers)"
SHAREPOINT_TEMPLATE = (
    "https://seattleschools.sharepoint.com/sites/SPSBoardOffice-O365"
    "/_layouts/15/download.aspx?share={token}"
)
MAX_TRIES = 6
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
OFFICE_EXTS = {".doc", ".xls", ".ppt", ".docx", ".xlsx", ".pptx"}
DEFAULT_OUTDIR = "out_sps_web"


class FetchError(Exception):
    def __init__(self, reason, status=None, tries=0, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.tries = tries
        self.detail = detail


class HostLimiter:
    """Paces request *starts* to a minimum interval, optionally also
    capping concurrent in-flight requests via a semaphore."""

    def __init__(self, interval, max_concurrent=None):
        self.interval = interval
        self._lock = threading.Lock()
        self._next_time = 0.0
        self._sem = threading.BoundedSemaphore(max_concurrent) if max_concurrent else None

    def acquire(self):
        if self._sem is not None:
            self._sem.acquire()

    def release(self):
        if self._sem is not None:
            self._sem.release()

    def wait_turn(self):
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_time - now)
            self._next_time = max(now, self._next_time) + self.interval
        if delay > 0:
            time.sleep(delay)

    def penalize(self, seconds):
        """Push the whole host's next start out by `seconds` (shared
        cooldown after a refused connection, so every worker backs off)."""
        with self._lock:
            self._next_time = max(self._next_time, time.monotonic()) + seconds


# web.archive.org refuses TCP connections (port 80 and 443 alike) for a few
# seconds after it decides a client is too eager -- observed 2026-08-24 as
# a strict 200/refused alternation at ~5s spacing. One connection at a time,
# 3s apart, and a shared cooldown on every refusal keeps it happy.
WAYBACK_REFUSED_COOLDOWN = 20.0   # seconds, multiplied by the attempt number


def make_limiters():
    return {
        "www.seattleschools.org": HostLimiter(1.0),
        "seattleschools.sharepoint.com": HostLimiter(1.0),
        "web.archive.org": HostLimiter(3.0, max_concurrent=1),
        "default": HostLimiter(0.5),
    }


def limiter_for(url, limiters):
    host = urlparse(url).hostname or "default"
    return limiters.get(host, limiters["default"])


def compute_backoff(attempt, http_error=None):
    if http_error is not None:
        retry_after = http_error.headers.get("Retry-After") if http_error.headers else None
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
    return min(30.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)


def http_get(url, opener):
    req = urlrequest.Request(url, headers={"User-Agent": USER_AGENT})
    resp = opener.open(req, timeout=60)
    data = resp.read()
    status = getattr(resp, "status", None) or resp.getcode()
    return data, status, dict(resp.headers), resp.geturl()


def fetch_with_retries(url, opener, limiter):
    last_reason = "exhausted_retries"
    for attempt in range(1, MAX_TRIES + 1):
        limiter.acquire()
        try:
            limiter.wait_turn()
            try:
                data, status, headers, final_url = http_get(url, opener)
                return data, status, headers, final_url, attempt
            except urlerror.HTTPError as e:
                status = e.code
                if status in RETRYABLE_STATUSES and attempt < MAX_TRIES:
                    time.sleep(compute_backoff(attempt, e))
                    continue
                raise FetchError("http_error", status=status, tries=attempt, detail=str(e)) from e
            except (urlerror.URLError, IncompleteRead, ConnectionResetError, TimeoutError) as e:
                # IncompleteRead: Wayback sometimes truncates large bodies
                # mid-transfer (~130 KB); treat like a dropped connection.
                if attempt < MAX_TRIES:
                    if "web.archive.org" in url:
                        # refused connection: cool the whole host down, and
                        # release our slot while we wait so the cooldown is
                        # shared rather than serialized behind this worker
                        limiter.penalize(WAYBACK_REFUSED_COOLDOWN * attempt)
                    else:
                        time.sleep(compute_backoff(attempt))
                    continue
                raise FetchError("connection_error", status=None, tries=attempt, detail=str(e)) from e
        finally:
            limiter.release()
    raise FetchError(last_reason, tries=MAX_TRIES)


def extract_wayback_ts(url):
    m = re.search(r"/web/(\d{1,14})(?:id_)?/", url or "")
    return m.group(1) if m else None


def build_wayback_alt_url(url):
    if "id_/" not in url:
        return None
    original = url.split("id_/", 1)[1]
    return f"https://web.archive.org/web/2id_/{original}"


def force_https_wayback(url):
    """web.archive.org stopped accepting plain HTTP (port 80 refuses
    connections as of 2026-08); the manifests carry http:// fetch URLs."""
    return url.replace("http://web.archive.org/", "https://web.archive.org/", 1)


def fetch_direct(row, opener, limiters):
    url = (row.get("fetch") or {}).get("url") or row["source_url"]
    limiter = limiter_for(url, limiters)
    data, status, headers, final_url, tries = fetch_with_retries(url, opener, limiter)
    return data, status, headers, final_url, url, tries, None


def fetch_sharepoint(row, opener, limiters):
    token = (row.get("fetch") or {}).get("token")
    url = SHAREPOINT_TEMPLATE.format(token=token) if token else row["fetch"]["url"]
    limiter = limiters["seattleschools.sharepoint.com"]
    data, status, headers, final_url, tries = fetch_with_retries(url, opener, limiter)
    return data, status, headers, final_url, url, tries, None


def fetch_wayback(row, opener, limiters):
    url = force_https_wayback(row["fetch"]["url"])
    limiter = limiters["web.archive.org"]
    try:
        data, status, headers, final_url, tries = fetch_with_retries(url, opener, limiter)
        ts = extract_wayback_ts(final_url) or extract_wayback_ts(url)
        return data, status, headers, final_url, url, tries, ts
    except FetchError as e:
        if not (e.reason == "http_error" and e.status == 404):
            raise
        alt = build_wayback_alt_url(url)
        if not alt:
            raise
        try:
            data, status, headers, final_url, tries2 = fetch_with_retries(alt, opener, limiter)
        except FetchError as e2:
            total = e.tries + e2.tries
            if e2.reason == "http_error" and e2.status == 404:
                raise FetchError("wayback_missing", status=404, tries=total, detail="no capture at either timestamp") from e2
            e2.tries = total
            raise e2
        ts = extract_wayback_ts(final_url) or extract_wayback_ts(alt)
        return data, status, headers, final_url, alt, e.tries + tries2, ts


RECIPES = {
    "direct": fetch_direct,
    "sharepoint_download": fetch_sharepoint,
    "wayback_raw": fetch_wayback,
}


def looks_like_html(data):
    head = data[:2000].lower()
    return b"<html" in head or b"<!doctype html" in head


# Magic-byte prefix -> (extension, content_type). Checked regardless of what
# extension the manifest/URL guessed: district links sometimes point at an
# image (JFIF thumbnails, screenshots) rather than the PDF a filename or
# sharepoint_download fallback name would imply.
MAGIC_TABLE = (
    (b"%PDF", ".pdf", "application/pdf"),
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    (b"GIF87a", ".gif", "image/gif"),
    (b"GIF89a", ".gif", "image/gif"),
)
OLE_MAGIC = b"\xd0\xcf\x11\xe0"


def sniff_magic(data):
    """Identify content purely from its bytes. Returns (ext, content_type)
    for a recognized format, or (None, None) if unrecognized."""
    for magic, ext, content_type in MAGIC_TABLE:
        if data[: len(magic)] == magic:
            return ext, content_type
    return None, None


def validate_content(data, filename, kind, content_type):
    """Returns (ok, reason, resolved_ext, resolved_content_type).
    On success resolved_ext/resolved_content_type reflect what the bytes
    actually are (which may differ from the manifest's guessed extension);
    on failure they are None and `reason` is one of not_pdf/login_wall/
    wayback_missing."""
    ext = os.path.splitext(filename)[1].lower()
    html = looks_like_html(data) or "text/html" in (content_type or "").lower()

    def html_reason():
        if kind == "wayback_raw":
            return "wayback_missing"
        if kind == "sharepoint_download":
            return "login_wall"
        return "not_pdf"

    sniff_ext, sniff_ctype = sniff_magic(data)
    if sniff_ext:
        return True, None, sniff_ext, sniff_ctype

    if data[:4] == OLE_MAGIC or data[:2] == b"PK":
        # OLE (.doc/.xls/.ppt) or ZIP-based (.docx/.xlsx/.pptx) office file.
        # Keep the guessed extension if it's plausible; otherwise pick a
        # generic one for the magic family so the file isn't mistyped.
        final_ext = ext if ext in OFFICE_EXTS else (".docx" if data[:2] == b"PK" else ".doc")
        return True, None, final_ext, content_type or "application/octet-stream"

    if ext == ".pdf" or ext in OFFICE_EXTS or html:
        # Expected a document (or got HTML back) but the bytes are neither
        # a recognized document format nor a known image -- a real failure.
        return False, html_reason() if html else "not_pdf", None, None

    return True, None, ext, content_type  # unrecognized extension and bytes: best effort, no validation possible


def safe_filename(name):
    base = os.path.basename(name or "file")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base or "file"


def resolve_filename(row):
    """Some inventories (e.g. WP sharepoint links, which have no filename
    until fetched) leave `filename` blank. Fall back to the source URL's
    last path segment, or `<doc_id>.pdf` for sharepoint_download (the only
    recipe verified to return PDFs anonymously), so every row still carries
    an extension for validate_content's magic-byte check."""
    filename = (row.get("filename") or "").strip()
    if filename:
        return filename
    kind = (row.get("fetch") or {}).get("kind")
    src_base = os.path.basename(urlparse(row.get("source_url") or "").path)
    if src_base and "." in src_base:
        return src_base
    if kind == "sharepoint_download":
        return f"{row['doc_id']}.pdf"
    return f"{row['doc_id']}.bin"


def school_year_of(date_str):
    y, m, _ = (int(p) for p in date_str.split("-"))
    start = y if m >= 8 else y - 1
    return f"{start}-{str(start + 1)[-2:]}"


def build_dest_map(rows, outdir):
    """Maps doc_id -> (dirpath, stem, guessed_ext). The final saved filename
    is `stem + resolved_ext`, where resolved_ext comes from validate_content
    (magic bytes) at fetch time and may differ from guessed_ext -- so
    collisions are grouped by stem alone, not stem+extension."""
    groups = {}
    for row in rows:
        if row.get("fetch", {}).get("kind") == "none":
            continue
        fname = safe_filename(row["filename"])
        stem, _ = os.path.splitext(fname)
        key = (row.get("era", "unknown"), row.get("meeting_date") or "undated", stem)
        groups.setdefault(key, []).append(row["doc_id"])

    dest_map = {}
    for row in rows:
        if row.get("fetch", {}).get("kind") == "none":
            continue
        era = row.get("era", "unknown")
        meeting = row.get("meeting_date") or "undated"
        fname = safe_filename(row["filename"])
        stem, ext = os.path.splitext(fname)
        key = (era, meeting, stem)
        if len(groups[key]) > 1:
            stem = f"{stem}-{row['doc_id']}"
        dest_map[row["doc_id"]] = (os.path.join(outdir, "raw", era, meeting), stem, ext)
    return dest_map


def find_existing(dirpath, stem, guessed_ext):
    """Returns the path of an already-fetched, non-empty file for this doc
    (with a sibling .prov.json), or None. Checks the guessed extension first
    (the common case), then falls back to scanning the directory in case a
    prior run resolved a different extension from magic bytes (e.g. a .jpg
    saved where a .pdf was guessed)."""
    candidate = os.path.join(dirpath, stem + guessed_ext)
    if os.path.exists(candidate) and os.path.exists(candidate + ".prov.json") and os.path.getsize(candidate) > 0:
        return candidate
    if not os.path.isdir(dirpath):
        return None
    for name in os.listdir(dirpath):
        if not name.endswith(".prov.json"):
            continue
        data_name = name[: -len(".prov.json")]
        if os.path.splitext(data_name)[0] == stem:
            data_path = os.path.join(dirpath, data_name)
            if os.path.exists(data_path) and os.path.getsize(data_path) > 0:
                return data_path
    return None


def atomic_write(path, data):
    dirn = os.path.dirname(path)
    os.makedirs(dirn, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=dirn)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


class Stats:
    FIELDS = ("attempted", "fetched", "skipped_existing", "skipped_none", "failed")

    def __init__(self):
        self.lock = threading.Lock()
        self.counts = {}
        self.bytes = {}
        self.fail_reasons = {}

    def bump(self, era, field, nbytes=0):
        with self.lock:
            self.counts.setdefault(era, dict.fromkeys(self.FIELDS, 0))[field] += 1
            if nbytes:
                self.bytes[era] = self.bytes.get(era, 0) + nbytes

    def attempted(self, era):
        self.bump(era, "attempted")

    def skip_none(self, era):
        self.bump(era, "skipped_none")

    def skip_existing(self, era):
        self.bump(era, "skipped_existing")

    def ok(self, era, nbytes):
        self.bump(era, "fetched", nbytes)

    def fail(self, era, reason):
        self.bump(era, "failed")
        with self.lock:
            self.fail_reasons.setdefault(era, {})
            self.fail_reasons[era][reason] = self.fail_reasons[era].get(reason, 0) + 1

    def report(self):
        lines = ["| era | attempted | fetched | skipped-existing | skipped-none | failed | bytes |",
                 "|---|---|---|---|---|---|---|"]
        for era in sorted(self.counts):
            c = self.counts[era]
            lines.append(f"| {era} | {c['attempted']} | {c['fetched']} | {c['skipped_existing']} | {c['skipped_none']} | {c['failed']} | {self.bytes.get(era, 0)} |")
        lines.append("")
        for era in sorted(self.fail_reasons):
            lines.append(f"**{era} failures by reason:**")
            for reason, n in sorted(self.fail_reasons[era].items()):
                lines.append(f"- {reason}: {n}")
            lines.append("")
        return "\n".join(lines)


class FailureLog:
    """Append-only across runs (never truncated) so failure history survives
    reruns; each row carries the run_id (this run's UTC start timestamp) so
    a given run's failures can still be picked out of the accumulated log."""

    def __init__(self, path, run_id):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.Lock()
        self._run_id = run_id
        self._fh = open(path, "a")

    def write(self, doc_id, fetch_url, status, error, tries):
        row = {"run_id": self._run_id, "doc_id": doc_id, "fetch_url": fetch_url, "status": status, "error": error, "tries": tries}
        with self._lock:
            self._fh.write(json.dumps(row) + "\n")
            self._fh.flush()

    def close(self):
        self._fh.close()


def process_row(row, opener, limiters, dest_map, stats, failure_log):
    kind = (row.get("fetch") or {}).get("kind")
    era = row.get("era", "unknown")
    stats.attempted(era)

    if kind == "none":
        stats.skip_none(era)
        return

    dirpath, stem, guessed_ext = dest_map[row["doc_id"]]
    if find_existing(dirpath, stem, guessed_ext) is not None:
        stats.skip_existing(era)
        return

    recipe = RECIPES.get(kind)
    if recipe is None:
        failure_log.write(row["doc_id"], (row.get("fetch") or {}).get("url"), None, f"unknown_recipe:{kind}", 0)
        stats.fail(era, "unknown_recipe")
        return

    try:
        data, status, headers, final_url, fetch_url, tries, wayback_ts = recipe(row, opener, limiters)
    except FetchError as e:
        failure_log.write(row["doc_id"], (row.get("fetch") or {}).get("url"), e.status, f"{e.reason}: {e.detail}", e.tries)
        stats.fail(era, e.reason)
        return
    except Exception as e:  # noqa: BLE001 - never let one bad row kill the run
        failure_log.write(row["doc_id"], (row.get("fetch") or {}).get("url"), None, f"unexpected_error: {e}", 1)
        stats.fail(era, "unexpected_error")
        return

    content_type = headers.get("Content-Type", "") if headers else ""
    ok, reason, resolved_ext, resolved_ctype = validate_content(data, row["filename"], kind, content_type)
    if not ok:
        sample = repr(data[:200])
        failure_log.write(row["doc_id"], fetch_url, status, f"{reason}: {sample}", tries)
        stats.fail(era, reason)
        return

    dest_path = os.path.join(dirpath, stem + resolved_ext)
    prov_path = dest_path + ".prov.json"
    atomic_write(dest_path, data)
    prov = {
        "doc_id": row["doc_id"],
        "source_url": row.get("source_url"),
        "fetch_url": fetch_url,
        "fetch_kind": kind,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "http_status": status,
        "content_type": resolved_ctype or content_type,
        "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "wayback_timestamp": wayback_ts,
        "final_url": final_url,
    }
    atomic_write(prov_path, json.dumps(prov, indent=2).encode("utf-8"))
    stats.ok(era, len(data))


def check_robots():
    try:
        rp = RobotFileParser()
        rp.set_url("https://www.seattleschools.org/robots.txt")
        rp.read()
        allowed = rp.can_fetch(USER_AGENT, "https://www.seattleschools.org/wp-content/uploads/2021/07/x.pdf")
        blocked_admin = not rp.can_fetch(USER_AGENT, "https://www.seattleschools.org/wp-admin/")
        print(f"[robots] www.seattleschools.org/robots.txt: wp-content allowed={allowed}, wp-admin blocked={blocked_admin}")
    except Exception as e:  # noqa: BLE001
        print(f"[robots] could not read robots.txt ({e}); proceeding, known to allow all except /wp-admin/")


def load_rows(manifest_paths):
    rows = []
    for path in manifest_paths:
        with open(path) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"[warn] {path}:{lineno}: skipping malformed row: {e}", file=sys.stderr)
                    continue
                row["filename"] = resolve_filename(row)
                rows.append(row)
    return rows


def default_manifests(outdir):
    return sorted(glob.glob(os.path.join(outdir, "manifest", "*_documents.jsonl")))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--manifest", action="append", help="manifest JSONL path (repeatable); default: <outdir>/manifest/*_documents.jsonl")
    p.add_argument("--era", choices=["wp", "blackboard", "legacy", "archive"], help="only fetch rows from this era")
    p.add_argument("--year", help="only fetch rows whose meeting_date falls in this school year, e.g. 2020-21")
    p.add_argument("--limit", type=int, help="only process the first N matching rows")
    p.add_argument("--dry-run", action="store_true", help="print counts and destination paths without fetching")
    p.add_argument("--workers", type=int, default=4, help="thread pool size (default 4); per-host rate limits still apply")
    p.add_argument("--outdir", default=DEFAULT_OUTDIR, help=f"output root (default {DEFAULT_OUTDIR})")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    manifests = args.manifest or default_manifests(args.outdir)
    if not manifests:
        print(f"No manifests found (looked in {args.outdir}/manifest/*_documents.jsonl)", file=sys.stderr)
        return 1
    print(f"[manifests] {len(manifests)}: {', '.join(manifests)}")

    all_rows = load_rows(manifests)
    dest_map = build_dest_map(all_rows, args.outdir)

    rows = all_rows
    if args.era:
        rows = [r for r in rows if r.get("era") == args.era]
    if args.year:
        rows = [r for r in rows if r.get("meeting_date") and school_year_of(r["meeting_date"]) == args.year]
    if args.limit:
        rows = rows[: args.limit]

    print(f"[rows] {len(rows)} of {len(all_rows)} manifest rows selected")
    check_robots()

    if args.dry_run:
        by_era_kind = {}
        for row in rows:
            kind = (row.get("fetch") or {}).get("kind")
            key = (row.get("era", "unknown"), kind)
            by_era_kind[key] = by_era_kind.get(key, 0) + 1
            if kind != "none":
                dirpath, stem, ext = dest_map[row["doc_id"]]
                print(os.path.join(dirpath, stem + ext))
        print("\n[dry-run counts by era/recipe]")
        for (era, kind), n in sorted(by_era_kind.items()):
            print(f"  {era:12s} {kind:20s} {n}")
        return 0

    run_id = datetime.now(timezone.utc).isoformat()
    print(f"[run_id] {run_id}")
    cookiejar = CookieJar()
    opener = urlrequest.build_opener(urlrequest.HTTPCookieProcessor(cookiejar))
    limiters = make_limiters()
    stats = Stats()
    failure_log = FailureLog(os.path.join(args.outdir, "manifest", "fetch_failures.jsonl"), run_id)

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(process_row, row, opener, limiters, dest_map, stats, failure_log) for row in rows]
            for f in as_completed(futures):
                f.result()
    finally:
        failure_log.close()

    report = stats.report()
    print("\n" + report)
    report_path = os.path.join(args.outdir, "manifest", "fetch_report.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as f:
        f.write("# Fetch report\n\n" + report + "\n")
    print(f"\n[report] {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
