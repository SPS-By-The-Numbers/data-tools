"""
resolve_sharepoint_names.py -- resolves the real Shared-Documents path and
filename for every `sharepoint_download` row in
`out_sps_web/manifest/documents.jsonl`, without downloading the document
body.

Background (see extractors/sps_web/PLAN.md Section 1 and classify.py's
`RESOLVED_FILENAME_GAP`): `fetch.py`'s `sharepoint_download` recipe hits
    https://seattleschools.sharepoint.com/sites/SPSBoardOffice-O365
        /_layouts/15/download.aspx?share=<TOKEN>
which returns the PDF bytes directly with no redirect, so the real filename
(which carries item codes and dates, e.g.
`C01_20250122_Minutes_20250108.pdf`) is never recovered that way -- every
2021-22+ SharePoint document is saved as `<doc_id>.pdf` and classify.py's
rule 1 (filename-based classification) is unavailable for it.

A different endpoint *does* redirect:
    https://seattleschools.sharepoint.com/sites/SPSBoardOffice-O365
        /_layouts/15/guestaccess.aspx?share=<TOKEN>&download=1
redirects (given a cookie jar) to the real item path under the site's
document library, e.g.:
    .../Shared Documents/School Board/Board Meetings/2025-26/
        2025-12-10 Regular/20251119_RBM_Minutes_rev20251205.pdf?ga=1
This script follows that redirect for every sharepoint_download token and
records the final URL -- HEAD first (verified to work: SharePoint answers
HEAD on guestaccess.aspx with the same redirect chain and Content-Type it
would give a GET, with no body sent), falling back to a GET with a
`Range: bytes=0-0` header (closed immediately after headers are read,
without calling .read() on the body) if a given response ever refuses HEAD
(405/501).

A share token that doesn't resolve (bad/expired token, access denied, some
other redirect target) answers 200 with an HTML error/login page *at the
same guestaccess.aspx URL* -- no redirect happens at all. That's the
"unresolved" case: final_url's path contains no "/Shared Documents/"
segment.

Usage (from the repo root)::

    venv/bin/python3 -m extractors.sps_web.resolve_sharepoint_names
    venv/bin/python3 -m extractors.sps_web.resolve_sharepoint_names --limit 20
    venv/bin/python3 -m extractors.sps_web.resolve_sharepoint_names --outdir out_sps_web

Reads ``<outdir>/manifest/documents.jsonl``, selecting every row with
``fetch.kind == "sharepoint_download"``. Writes
``<outdir>/manifest/sharepoint_names.jsonl``, one row per doc_id::

    {doc_id, token, final_url, resolved_path, resolved_filename, folder,
     resolved_at, status, reason}

``resolved_path`` is the URL-decoded path under "Shared Documents/"
(includes the constant "School Board/" top segment). ``folder`` is
``resolved_path``'s directory with that constant "School Board/" prefix
stripped (e.g. "Board Meetings/2025-26/2025-12-10 Regular") -- pure
convenience for grouping/QA, not used by classify.py. ``status`` is
"resolved" or "unresolved"; unresolved rows carry a ``reason`` (e.g.
"no_redirect", "http_error_403", "connection_error") and null path fields.

Resume support: rows whose token already has ``status == "resolved"`` in an
existing output file are skipped and carried forward unchanged; every other
row (including previously "unresolved" ones, in case of a transient
failure) is re-resolved. Rerun with no args to keep going after an
interrupted run.

Rate limit: 1 request/second to seattleschools.sharepoint.com (single
connection, sequential -- same policy as fetch.py's SharePoint limiter).
429/5xx and connection errors retry with exponential backoff (honoring
Retry-After), up to 6 tries; other 4xx fail immediately as unresolved.
"""

import argparse
import json
import os
import random
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from urllib import error as urlerror
from urllib import request as urlrequest

USER_AGENT = "sps-data-tools/board-contracts (github.com/SPS-By-The-Numbers)"
GUESTACCESS_TEMPLATE = (
    "https://seattleschools.sharepoint.com/sites/SPSBoardOffice-O365"
    "/_layouts/15/guestaccess.aspx?share={token}&download=1"
)
DEFAULT_OUTDIR = "out_sps_web"
RATE_INTERVAL = 1.0  # seconds, 1 req/s to seattleschools.sharepoint.com
MAX_TRIES = 6
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
METHOD_NOT_ALLOWED_STATUSES = {405, 501}
SHARED_DOCS_MARKER = "/Shared Documents/"
SCHOOL_BOARD_PREFIX = "School Board/"


# --------------------------------------------------------------------------
# io helpers (same conventions as the rest of extractors/sps_web)
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


# --------------------------------------------------------------------------
# rate limiting (single host, sequential -- mirrors fetch.py's HostLimiter)
# --------------------------------------------------------------------------

class RateLimiter:
    def __init__(self, interval):
        self.interval = interval
        self._next_time = 0.0

    def wait_turn(self):
        now = time.monotonic()
        delay = max(0.0, self._next_time - now)
        self._next_time = max(now, self._next_time) + self.interval
        if delay > 0:
            time.sleep(delay)


def compute_backoff(attempt, http_error=None):
    if http_error is not None and http_error.headers:
        retry_after = http_error.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
    return min(30.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5)


# --------------------------------------------------------------------------
# the actual resolve: HEAD, falling back to ranged GET, no body downloaded
# --------------------------------------------------------------------------

class ResolveError(Exception):
    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail


def _open_no_body(url, opener, method):
    headers = {"User-Agent": USER_AGENT}
    if method == "GET":
        headers["Range"] = "bytes=0-0"
    req = urlrequest.Request(url, headers=headers, method=method)
    resp = opener.open(req, timeout=30)
    try:
        status = getattr(resp, "status", None) or resp.getcode()
        final_url = resp.geturl()
        content_type = resp.headers.get("Content-Type") if resp.headers else None
        return status, final_url, content_type
    finally:
        # Never read the body. For a HEAD there is none; for the Range GET
        # fallback this closes the connection without draining it.
        resp.close()


def resolve_one(token, opener, limiter):
    """Returns a dict with keys final_url/status/reason/resolved_path/
    resolved_filename/folder -- resolved_path etc. are None on failure."""
    url = GUESTACCESS_TEMPLATE.format(token=token)
    last_exc = None
    for attempt in range(1, MAX_TRIES + 1):
        limiter.wait_turn()
        method = "HEAD"
        try:
            try:
                status, final_url, content_type = _open_no_body(url, opener, "HEAD")
            except urlerror.HTTPError as e:
                if e.code in METHOD_NOT_ALLOWED_STATUSES:
                    method = "GET"
                    status, final_url, content_type = _open_no_body(url, opener, "GET")
                else:
                    raise
            return _classify_result(url, status, final_url, content_type)
        except urlerror.HTTPError as e:
            if e.code in RETRYABLE_STATUSES and attempt < MAX_TRIES:
                time.sleep(compute_backoff(attempt, e))
                last_exc = e
                continue
            return _failure(f"http_error_{e.code}", str(e))
        except urlerror.URLError as e:
            if attempt < MAX_TRIES:
                time.sleep(compute_backoff(attempt))
                last_exc = e
                continue
            return _failure("connection_error", str(e))
        except TimeoutError as e:
            if attempt < MAX_TRIES:
                time.sleep(compute_backoff(attempt))
                last_exc = e
                continue
            return _failure("timeout", str(e))
    return _failure("exhausted_retries", str(last_exc) if last_exc else None)


def _failure(reason, detail):
    return {
        "final_url": None, "status": "unresolved", "reason": reason,
        "resolved_path": None, "resolved_filename": None, "folder": None,
    }


def _classify_result(request_url, status, final_url, content_type):
    path = urllib.parse.unquote(urllib.parse.urlparse(final_url).path)
    if SHARED_DOCS_MARKER not in path:
        reason = "no_redirect" if final_url == request_url else "unexpected_final_url"
        return {
            "final_url": final_url, "status": "unresolved", "reason": reason,
            "resolved_path": None, "resolved_filename": None, "folder": None,
        }
    resolved_path = path.split(SHARED_DOCS_MARKER, 1)[1]
    resolved_filename = resolved_path.rsplit("/", 1)[-1]
    folder = resolved_path.rsplit("/", 1)[0] if "/" in resolved_path else ""
    if folder == SCHOOL_BOARD_PREFIX.rstrip("/"):
        folder = ""
    elif folder.startswith(SCHOOL_BOARD_PREFIX):
        folder = folder[len(SCHOOL_BOARD_PREFIX):]
    return {
        "final_url": final_url, "status": "resolved", "reason": None,
        "resolved_path": resolved_path, "resolved_filename": resolved_filename,
        "folder": folder,
    }


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Resolve real filenames/paths for sharepoint_download "
                     "documents via guestaccess.aspx, without downloading bodies.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--outdir", default=DEFAULT_OUTDIR, help=f"output root (default {DEFAULT_OUTDIR})")
    p.add_argument("--limit", type=int, help="only process the first N unresolved rows (smoke test)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    outdir = args.outdir
    manifest_path = os.path.join(outdir, "manifest", "documents.jsonl")
    out_path = os.path.join(outdir, "manifest", "sharepoint_names.jsonl")

    manifest_rows = read_jsonl(manifest_path)
    if not manifest_rows:
        print("no rows in %s" % manifest_path, file=sys.stderr)
        return 1

    sp_rows = [r for r in manifest_rows if (r.get("fetch") or {}).get("kind") == "sharepoint_download"]
    print("[manifest] %d sharepoint_download rows of %d total" % (len(sp_rows), len(manifest_rows)))

    existing = {r["doc_id"]: r for r in read_jsonl(out_path)}
    already_resolved = {doc_id for doc_id, r in existing.items() if r.get("status") == "resolved"}
    todo = [r for r in sp_rows if r["doc_id"] not in already_resolved]
    print("[resume] %d already resolved, %d to do" % (len(already_resolved), len(todo)))

    if args.limit:
        todo = todo[: args.limit]
        print("[limit] processing %d rows" % len(todo))

    cj = CookieJar()
    opener = urlrequest.build_opener(urlrequest.HTTPCookieProcessor(cj))
    limiter = RateLimiter(RATE_INTERVAL)

    results = dict(existing)  # doc_id -> row, updated in place as we go
    n_resolved = 0
    n_unresolved = 0
    reasons = {}
    t_start = time.monotonic()
    for i, row in enumerate(todo, 1):
        doc_id = row["doc_id"]
        token = row["fetch"]["token"]
        res = resolve_one(token, opener, limiter)
        out_row = {
            "doc_id": doc_id,
            "token": token,
            "final_url": res["final_url"],
            "resolved_path": res["resolved_path"],
            "resolved_filename": res["resolved_filename"],
            "folder": res["folder"],
            "resolved_at": datetime.now(timezone.utc).isoformat(),
            "status": res["status"],
        }
        if res["status"] == "unresolved":
            out_row["reason"] = res["reason"]
            n_unresolved += 1
            reasons[res["reason"]] = reasons.get(res["reason"], 0) + 1
        else:
            n_resolved += 1
        results[doc_id] = out_row

        if i % 25 == 0 or i == len(todo):
            elapsed = time.monotonic() - t_start
            print("[%d/%d] resolved=%d unresolved=%d (%.0fs elapsed)"
                  % (i, len(todo), n_resolved, n_unresolved, elapsed))
            # periodic checkpoint so a killed run doesn't lose progress
            write_jsonl(out_path, list(results.values()))

    write_jsonl(out_path, list(results.values()))
    print("[out] %s (%d rows: %d resolved, %d unresolved this run)"
          % (out_path, len(results), n_resolved, n_unresolved))
    if reasons:
        print("[unresolved reasons] " + ", ".join("%s=%d" % (k, v) for k, v in sorted(reasons.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
