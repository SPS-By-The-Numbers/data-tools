"""Task A1 (see extractors/sps_web/PLAN.md, Section 3): inventory the
WordPress-era SPS board_meeting posts (Aug 2016 -> present) via the public
WP REST API, and every document link they carry.

Usage (from repo root):

    venv/bin/python3 -m extractors.sps_web.inventory_wp

No third-party packages are used (the venv's `requests` install was
unavailable in this environment, and stdlib `urllib` is sufficient for a
few dozen polite GET requests), so this also runs under any bare python3.

What it does
------------
1. Pages ``GET /wp-json/wp/v2/board_meeting?per_page=100&page=N`` until
   ``X-WP-TotalPages`` is exhausted (443 meetings / 5 pages as of
   2026-08-24). Sleeps 1s between every HTTP request; retries 5xx with
   exponential backoff.
2. Resolves the ``school_year`` and ``board-meetings/meeting-type``
   taxonomies (the latter's REST route was found via a post's
   ``_links.wp:term`` -- it is NOT ``/wp-json/wp/v2/meeting-type``).
   School year names ("August 2016 - July 2017") are normalized to
   "2016-17"; meeting type slugs are normalized to lowercase
   (``board-retreat`` -> ``retreat``, the rest pass through as-is:
   ``regular|special|work-session|general``).
3. Derives the meeting date: try a full date (month/day/year) in the
   title, then in the slug; if only month/day is present in either, use
   the school_year taxonomy to resolve the year (Aug-Dec -> the school
   year's start year, Jan-Jul -> its end year); otherwise fall back to
   the post's own ``date`` field. ``date_source`` records which path won:
   one of ``title``, ``slug``, ``title+school_year``, ``slug+school_year``,
   ``post_date``.
4. Parses every ``<a href>`` in ``content.rendered`` (stdlib
   ``html.parser``) into a document row, classifying the host:
   ``wp-upload`` (seattleschools.org under /wp-content/uploads/),
   ``sharepoint`` (seattleschools.sharepoint.com), ``sps-page`` (other
   seattleschools.org URLs), ``youtube``, ``forms`` (forms.office.com),
   ``other`` (everything else -- mailto:, bare "#" anchors,
   governor.wa.gov, teams.microsoft.com, etc. -- still recorded, never
   dropped, so "unclassifiable" never happens; it just means fetch.kind
   is "none").
5. Guesses a document kind from link text + filename
   (agenda|minutes|bar|warrants|personnel|presentation|video|other) and,
   for wp-upload filenames, an item code (the leading
   ``[A-Z]{1,3}\\d{1,3}`` token, e.g. ``C01``, ``SC01``, ``A01``, ``I01``).

Row schemas
-----------
``out_sps_web/manifest/wp_meetings.jsonl`` (one row per meeting)::

    {meeting_id, era: "wp", date, date_source, type, title, page_url,
     school_year, wp_id, wp_modified, n_docs}

``out_sps_web/manifest/wp_documents.jsonl`` (one row per <a href>)::

    {doc_id, era: "wp", meeting_id, meeting_date, source_url, link_text,
     host_class, filename, fetch: {...}, kind_guess, item_code}

``out_sps_web/manifest/wp_inventory_report.md`` -- counts and anomalies.

Known SharePoint link shapes (see ``SHAREPOINT_TOKEN_RE``): the vast
majority are ``/:b:/s/SPSBoardOffice-O365/<TOKEN>?e=...`` (b = PDF; a
handful are i/f for image/folder, and this handles any single-letter
share type, e.g. w/x for Word/Excel, the same way). A few (~5 seen in the
2026-08-24 crawl) are "resolved" ``/:b:/r/sites/SPSBoardOffice-O365/Shared
Documents/...`` paths or ``.../Forms/AllItems.aspx?id=...`` links with no
short opaque token; those still get ``host_class="sharepoint"`` (so
nothing is lost) but ``fetch={"kind":"none"}`` since the anonymous
``download.aspx?share=<TOKEN>`` trick needs the short token.
"""

import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

API_BASE = "https://www.seattleschools.org/wp-json/wp/v2"
USER_AGENT = "sps-data-tools/board-contracts (github.com/SPS-By-The-Numbers)"
PER_PAGE = 100
SLEEP_SECONDS = 1
MAX_RETRIES = 5

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(REPO_ROOT, "out_sps_web", "manifest")

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_MONTH_ALT = "|".join(MONTHS)
_MONTH_ALT_LOWER = "|".join(m.lower() for m in MONTHS)

FULL_DATE_RE = re.compile(
    rf"\b({_MONTH_ALT}),?\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b"
)
MONTHDAY_RE = re.compile(rf"\b({_MONTH_ALT}),?\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b")
FULL_DATE_SLUG_RE = re.compile(rf"\b({_MONTH_ALT_LOWER})-(\d{{1,2}})-(\d{{4}})\b")
MONTHDAY_SLUG_RE = re.compile(rf"\b({_MONTH_ALT_LOWER})-(\d{{1,2}})(?:-|$)")
SCHOOL_YEAR_NAME_RE = re.compile(r"([A-Za-z]+)\s+(\d{4})\s*-\s*([A-Za-z]+)\s+(\d{4})")

SHAREPOINT_TOKEN_RE = re.compile(r"/:(\w):/s/SPSBoardOffice-O365/([^/?]+)")
ITEM_CODE_RE = re.compile(r"^[A-Z]{1,3}\d{1,3}$")

MEETING_TYPE_NORMALIZE = {
    "board-retreat": "retreat",
}

KIND_PATTERNS = [
    ("minutes", re.compile(r"minutes", re.I)),
    ("warrants", re.compile(r"warrant", re.I)),
    ("personnel", re.compile(r"personnel", re.I)),
    ("bar", re.compile(r"action[\s_-]*report|\bbar\b", re.I)),
    ("agenda", re.compile(r"agenda", re.I)),
    ("presentation", re.compile(r"presentation|powerpoint|\.pptx?\b", re.I)),
    ("video", re.compile(r"\bvideo\b|\brecording\b", re.I)),
]


def http_get(url):
    """GET url with a descriptive UA; retry 5xx/network errors with backoff.
    Returns (body_bytes, headers). Always sleeps SLEEP_SECONDS afterward.
    """
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                headers = resp.headers
            time.sleep(SLEEP_SECONDS)
            return body, headers
        except urllib.error.HTTPError as e:
            if e.code >= 500 and attempt < MAX_RETRIES - 1:
                last_err = e
                time.sleep(2 ** attempt)
                continue
            raise
        except urllib.error.URLError as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_err  # pragma: no cover


def http_get_json(url):
    body, headers = http_get(url)
    return json.loads(body), headers


def fetch_all_meetings():
    meetings = []
    page = 1
    total_pages = None
    while total_pages is None or page <= total_pages:
        url = f"{API_BASE}/board_meeting?per_page={PER_PAGE}&page={page}"
        data, headers = http_get_json(url)
        if total_pages is None:
            total_pages = int(headers.get("X-WP-TotalPages", "1"))
        meetings.extend(data)
        page += 1
    return meetings


def fetch_taxonomy_terms(url):
    """Returns {id: {"slug":..., "name":...}} for a taxonomy terms endpoint."""
    data, _ = http_get_json(url)
    return {t["id"]: {"slug": t["slug"], "name": html.unescape(t["name"])} for t in data}


def normalize_school_year(name):
    """"August 2016 - July 2017" -> "2016-17"."""
    m = SCHOOL_YEAR_NAME_RE.search(name)
    if not m:
        return None
    start_year, end_year = m.group(2), m.group(4)
    return f"{start_year}-{end_year[2:]}"


def resolve_year_from_school_year(month_name, school_year_name):
    m = SCHOOL_YEAR_NAME_RE.search(school_year_name or "")
    if not m:
        return None
    start_month, start_year, _end_month, end_year = m.groups()
    start_idx = MONTHS.index(start_month) if start_month in MONTHS else 7
    month_idx = MONTHS.index(month_name.capitalize())
    return int(start_year) if month_idx >= start_idx else int(end_year)


def derive_date(title_text, slug, post_date_iso, school_year_name):
    """Returns (YYYY-MM-DD, date_source)."""
    m = FULL_DATE_RE.search(title_text)
    if m:
        month, day, year = m.groups()
        return f"{int(year):04d}-{MONTHS.index(month) + 1:02d}-{int(day):02d}", "title"

    m = FULL_DATE_SLUG_RE.search(slug)
    if m:
        month, day, year = m.groups()
        return (
            f"{int(year):04d}-{MONTHS.index(month.capitalize()) + 1:02d}-{int(day):02d}",
            "slug",
        )

    m = MONTHDAY_RE.search(title_text)
    if m:
        month, day = m.groups()
        year = resolve_year_from_school_year(month, school_year_name)
        if year:
            return f"{year:04d}-{MONTHS.index(month) + 1:02d}-{int(day):02d}", "title+school_year"

    m = MONTHDAY_SLUG_RE.search(slug)
    if m:
        month, day = m.groups()
        year = resolve_year_from_school_year(month, school_year_name)
        if year:
            return (
                f"{year:04d}-{MONTHS.index(month.capitalize()) + 1:02d}-{int(day):02d}",
                "slug+school_year",
            )

    return post_date_iso[:10], "post_date"


class AnchorExtractor(HTMLParser):
    """Collects (href, visible_text) for every <a href=...>...</a> in HTML,
    flattening any nested tags (e.g. <strong>) inside the link text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._in_a = False
        self._href = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._in_a = True
            self._href = dict(attrs).get("href")
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "a" and self._in_a:
            text = " ".join("".join(self._buf).split())
            if self._href:
                self.links.append((self._href, text))
            self._in_a = False
            self._href = None
            self._buf = []

    def handle_data(self, data):
        if self._in_a:
            self._buf.append(data)


def extract_links(content_html):
    parser = AnchorExtractor()
    parser.feed(content_html)
    return parser.links


def classify_host(href):
    href = href.strip()
    if href.startswith("mailto:") or href in ("", "#"):
        return "other"
    parsed = urllib.parse.urlparse(href)
    host = parsed.netloc.lower()
    if host in ("www.seattleschools.org", "seattleschools.org"):
        return "wp-upload" if "/wp-content/uploads/" in parsed.path else "sps-page"
    if host == "seattleschools.sharepoint.com":
        return "sharepoint"
    if host in ("www.youtube.com", "youtu.be"):
        return "youtube"
    if host == "forms.office.com":
        return "forms"
    return "other"


def sharepoint_token(href):
    m = SHAREPOINT_TOKEN_RE.search(href)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def build_fetch_recipe(host_class, href):
    if host_class == "wp-upload":
        return {"kind": "direct", "url": href}
    if host_class == "sharepoint":
        share_type, token = sharepoint_token(href)
        if token:
            download_url = (
                "https://seattleschools.sharepoint.com/sites/SPSBoardOffice-O365"
                f"/_layouts/15/download.aspx?share={token}"
            )
            return {
                "kind": "sharepoint_download",
                "url": download_url,
                "token": token,
                "share_type": share_type,
            }
        return {"kind": "none"}
    return {"kind": "none"}


def filename_from_url(href):
    path = urllib.parse.urlparse(href).path
    name = path.rsplit("/", 1)[-1]
    return urllib.parse.unquote(name)


def guess_item_code(filename):
    token = filename.split("_", 1)[0]
    return token if ITEM_CODE_RE.match(token) else None


def guess_kind(link_text, filename, host_class):
    if host_class == "youtube":
        return "video"
    haystack = f"{link_text} {filename}"
    for kind, pattern in KIND_PATTERNS:
        if pattern.search(haystack):
            return kind
    return "other"


def doc_id_for(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def build_meeting_row(post, school_year_map, meeting_type_map, anomalies):
    title_raw = html.unescape(post["title"]["rendered"])
    slug = post["slug"]

    sy_ids = post.get("school_year", [])
    school_year_name = school_year_map[sy_ids[0]]["name"] if sy_ids else None
    school_year_norm = normalize_school_year(school_year_name) if school_year_name else None
    if school_year_norm is None:
        anomalies["no_school_year_taxonomy"].append(post["id"])

    mt_ids = post.get("board-meetings/meeting-type", [])
    if len(mt_ids) > 1:
        anomalies["multi_meeting_type"].append(post["id"])
    if mt_ids:
        slug_type = meeting_type_map[mt_ids[0]]["slug"]
        mtype = MEETING_TYPE_NORMALIZE.get(slug_type, slug_type).lower()
    else:
        anomalies["no_meeting_type"].append(post["id"])
        mtype = "unknown"

    date_str, date_source = derive_date(title_raw, slug, post["date"], school_year_name)
    if date_source == "post_date":
        anomalies["date_from_post_date"].append(post["id"])

    # School year fallback derived from the resolved date (Aug-Jul), used
    # only when the taxonomy term was missing (16 recent/untagged posts as
    # of 2026-08-24), so downstream merge steps still get a value.
    if school_year_norm is None:
        y, mo, _d = (int(x) for x in date_str.split("-"))
        start_year = y if mo >= 8 else y - 1
        school_year_norm = f"{start_year}-{str(start_year + 1)[2:]}"

    meeting_id = f"{date_str}-{mtype}"

    return meeting_id, {
        "meeting_id": meeting_id,
        "era": "wp",
        "date": date_str,
        "date_source": date_source,
        "type": mtype,
        "title": title_raw,
        "page_url": post["link"],
        "school_year": school_year_norm,
        "wp_id": post["id"],
        "wp_modified": post["modified"],
        "n_docs": 0,  # filled in after documents are counted
    }


def build_document_rows(post, meeting_id, meeting_date, anomalies):
    rows = []
    for href, link_text in extract_links(post["content"]["rendered"]):
        host_class = classify_host(href)
        # Only wp-upload hrefs carry a real filename in the URL path; a
        # SharePoint href's last path segment is an opaque share token
        # (see SHAREPOINT_TOKEN_RE), not a filename -- treating it as one
        # produces bogus item_code/kind_guess matches, so leave it blank
        # and rely on link_text for those docs instead.
        filename = filename_from_url(href) if host_class == "wp-upload" else ""
        fetch = build_fetch_recipe(host_class, href)
        if host_class == "sharepoint" and fetch["kind"] == "none":
            anomalies["sharepoint_no_token"].append(href)
        rows.append({
            "doc_id": doc_id_for(href),
            "era": "wp",
            "meeting_id": meeting_id,
            "meeting_date": meeting_date,
            "source_url": href,
            "link_text": link_text,
            "host_class": host_class,
            "filename": filename,
            "fetch": fetch,
            "kind_guess": guess_kind(link_text, filename, host_class),
            "item_code": guess_item_code(filename) if filename else None,
        })
    return rows


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_report(path, meetings, documents, anomalies):
    from collections import Counter

    by_sy_type = Counter((m["school_year"], m["type"]) for m in meetings)
    by_sy_host = Counter((d["meeting_date"][:4], d["host_class"]) for d in documents)
    # roll host counts up by school_year instead of calendar year for readability
    meeting_sy_by_id = {m["meeting_id"]: m["school_year"] for m in meetings}
    by_sy_host = Counter(
        (meeting_sy_by_id.get(d["meeting_id"], "?"), d["host_class"]) for d in documents
    )
    kind_counts = Counter(d["kind_guess"] for d in documents)
    host_counts = Counter(d["host_class"] for d in documents)
    unclassifiable = [d for d in documents if d["host_class"] not in
                       ("wp-upload", "sharepoint", "sps-page", "youtube", "forms", "other")]
    no_docs = [m["meeting_id"] for m in meetings if m["n_docs"] == 0]

    lines = []
    lines.append("# WP inventory report\n")
    lines.append(f"Meetings: {len(meetings)}  Documents: {len(documents)}\n")

    lines.append("\n## Meetings per school year / type\n")
    lines.append("| school_year | type | count |")
    lines.append("|---|---|---|")
    for (sy, mtype), count in sorted(by_sy_type.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        lines.append(f"| {sy} | {mtype} | {count} |")

    lines.append("\n## Documents per school year by host_class\n")
    lines.append("| school_year | host_class | count |")
    lines.append("|---|---|---|")
    for (sy, host), count in sorted(by_sy_host.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        lines.append(f"| {sy} | {host} | {count} |")

    lines.append("\n## host_class totals\n")
    for host, count in host_counts.most_common():
        lines.append(f"- {host}: {count}")

    lines.append("\n## kind_guess totals\n")
    for kind, count in kind_counts.most_common():
        lines.append(f"- {kind}: {count}")

    lines.append("\n## Anomalies\n")
    lines.append(f"- hrefs with unclassifiable host (should be 0): {len(unclassifiable)}")
    lines.append(f"- sharepoint links with no extractable token (fetch.kind=none): "
                  f"{len(anomalies['sharepoint_no_token'])}")
    for href in anomalies["sharepoint_no_token"]:
        lines.append(f"  - {href}")
    lines.append(f"- meetings with date_source=post_date (no date in title/slug): "
                  f"{len(anomalies['date_from_post_date'])}")
    for wp_id in anomalies["date_from_post_date"]:
        lines.append(f"  - wp_id={wp_id}")
    lines.append(f"- meetings with no school_year taxonomy term (school_year "
                  f"derived from date instead): {len(anomalies['no_school_year_taxonomy'])}")
    lines.append(f"- meetings with no meeting-type taxonomy term (type=unknown): "
                  f"{len(anomalies['no_meeting_type'])}")
    for wp_id in anomalies["no_meeting_type"]:
        lines.append(f"  - wp_id={wp_id}")
    lines.append(f"- meetings with more than one meeting-type term (first one used): "
                  f"{len(anomalies['multi_meeting_type'])}")
    for wp_id in anomalies["multi_meeting_type"]:
        lines.append(f"  - wp_id={wp_id}")
    lines.append(f"- meetings with zero documents: {len(no_docs)}")
    for mid in no_docs:
        lines.append(f"  - {mid}")

    dup_ids = [mid for mid, count in Counter(m["meeting_id"] for m in meetings).items() if count > 1]
    lines.append(f"- duplicate meeting_id collisions (date+type not unique): {len(dup_ids)}")
    for mid in dup_ids:
        lines.append(f"  - {mid}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("Fetching school_year taxonomy...")
    school_year_map = fetch_taxonomy_terms(f"{API_BASE}/school_year?per_page=100")
    print(f"  {len(school_year_map)} school years")

    print("Fetching board-meetings/meeting-type taxonomy...")
    meeting_type_map = fetch_taxonomy_terms(f"{API_BASE}/board-meetings/meeting-type?per_page=100")
    print(f"  {len(meeting_type_map)} meeting types")

    print("Paging board_meeting posts...")
    posts = fetch_all_meetings()
    print(f"  {len(posts)} meetings")

    anomalies = {
        "no_school_year_taxonomy": [],
        "no_meeting_type": [],
        "multi_meeting_type": [],
        "date_from_post_date": [],
        "sharepoint_no_token": [],
    }

    meetings = []
    documents = []
    for post in posts:
        meeting_id, meeting_row = build_meeting_row(
            post, school_year_map, meeting_type_map, anomalies
        )
        doc_rows = build_document_rows(post, meeting_id, meeting_row["date"], anomalies)
        meeting_row["n_docs"] = len(doc_rows)
        meetings.append(meeting_row)
        documents.extend(doc_rows)

    meetings_path = os.path.join(OUT_DIR, "wp_meetings.jsonl")
    documents_path = os.path.join(OUT_DIR, "wp_documents.jsonl")
    report_path = os.path.join(OUT_DIR, "wp_inventory_report.md")

    write_jsonl(meetings_path, meetings)
    write_jsonl(documents_path, documents)
    write_report(report_path, meetings, documents, anomalies)

    print(f"Wrote {len(meetings)} meetings -> {meetings_path}")
    print(f"Wrote {len(documents)} documents -> {documents_path}")
    print(f"Wrote report -> {report_path}")


if __name__ == "__main__":
    main()
