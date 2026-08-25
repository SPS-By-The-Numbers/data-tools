"""
classify.py -- Task C2 (see extractors/sps_web/PLAN.md, Section 3): assign a
document `kind` to every fetched row of the merged manifest
(`out_sps_web/manifest/documents.jsonl`, built by A3 / `inventory_merge.py`).

Usage (from the repo root)::

    venv/bin/python3 -m extractors.sps_web.classify
    venv/bin/python3 -m extractors.sps_web.classify --era wp
    venv/bin/python3 -m extractors.sps_web.classify --era legacy --limit 50

Reads ``documents.jsonl`` (one row per document; see ``inventory_merge.py``'s
docstring for the row schema: ``doc_id, era, meeting_id, meeting_date,
filename, filename_date, kind_guess, item_code, fetch, alternates, ...``),
plus, for every row whose ``doc_id`` has actually been fetched, its
provenance file (``out_sps_web/raw/<era>/<date>/<stem>.prov.json``, from
``fetch.py``) and its extracted text
(``out_sps_web/text/<era>/<date>/<stem>.txt`` + ``.textmeta.json``, from
``totext.py``). Both trees are read-only and may still be filling in -- a
document with no raw file yet, or no text yet, is handled, not an error.

Writes ``out_sps_web/manifest/documents_classified.jsonl`` (one row per input
row: original fields plus ``kind, confidence, signals, resolved_filename,
has_text, pages``; an unfetched document passes through with
``kind=null, confidence=null, signals=[], resolved_filename=null,
has_text=false, pages=null``) and ``out_sps_web/qa/classify_report.md``.
Rerunning with ``--era``/``--limit`` only reclassifies the matching rows;
everything else carries forward from the previous output, so the file stays
complete as the crawl and text extraction keep filling in.

Kind vocabulary
================
``agenda | minutes | bar | warrants | personnel | presentation | packet |
policy | resolution | image | video | other``

agenda = the meeting's business-item list. minutes = the narrative record of
what happened (attendance, motions, votes). bar = a Board Action Report
(legacy: "School Board Action Report") -- one item's staff writeup (title,
purpose, fiscal impact, recommended motion), *not* any document that merely
mentions a BAR/policy/resolution in passing. warrants = the monthly Audit
Report of Warrants Issued. personnel = the HR/Personnel Report. presentation
= a slide deck. packet = a bundle that isn't cleanly one of the above (rare
-- most "*_Packet.pdf" files are agendas or BARs with attachments and get
caught by those rules first). policy = a board policy/superintendent
procedure document itself. resolution = a numbered Board resolution. image =
fetched bytes that are a JPEG/PNG/GIF. video = a YouTube/recording link
(rarely reachable here -- such links today have `fetch.kind == "none"` and
live in `documents_nofetch.jsonl`). other = financial/compliance reports,
memos, exhibits, contracts, Q&A compilations -- genuinely "other" for this
corpus (see the hand-check notes in the guide/PLAN), not a catch-all for
rule gaps.

Rules, in priority order
=========================
1. **Resolved filename.** The manifest's ``filename`` is blank for most
   2021-22+ SharePoint links (the href's last segment is an opaque share
   token -- see ``inventory_wp.py``). This tries the *fetched* file instead:
   for a ``direct``/``wayback_raw`` fetch, ``.prov.json``'s ``final_url``
   carries the real path and its decoded last segment is used. **This does
   NOT work for ``sharepoint_download``**: `download.aspx?share=<TOKEN>`
   returns bytes with no redirect, so `final_url` is just the request URL
   again -- of 1,713 fetched SharePoint rows, 0 resolve a real name this
   way, contrary to the PLAN's Section-2 assumption. So rule 1 is
   unavailable for most 2021-22+ documents; rule 2 carries that era (see
   ``RESOLVED_FILENAME_GAP``, reproduced in the QA report).

   Once a name is available, keyword substrings are matched most-specific
   first (see ``FILENAME_RULES``) so e.g. "Action_Report..._Packet.pdf"
   resolves to ``bar`` not ``packet``: minutes, warrants, personnel, bar,
   agenda (also matches "spagenda"), presentation, resolution, policy,
   packet. Image/video are decided first from the fetched bytes' real
   extension and `host_class`. "resolution"/"policy" filename hits are
   *weak* (``WEAK_FILENAME_KINDS``): a BAR is routinely named after the
   policy/resolution it concerns ("Amendment-1-to-A01_..._Policy-2190_...
   pdf" is a BAR, not the policy), so a strong rule-2 "bar" match overrides
   them.

   **The sharepoint_download gap above is now closed by a sidecar.**
   ``resolve_sharepoint_names.py`` (task: resolve real SharePoint paths)
   hits a different endpoint (``guestaccess.aspx?share=<TOKEN>&download=1``,
   which *does* redirect, unlike ``download.aspx``) for every
   ``sharepoint_download`` row and records the resolved item path/filename
   in ``<outdir>/manifest/sharepoint_names.jsonl`` (one row per doc_id:
   ``doc_id, token, final_url, resolved_path, resolved_filename, folder,
   resolved_at, status``). When that file is present, ``resolved_filename_for``
   uses its ``resolved_filename`` for any fetched ``sharepoint_download`` doc
   with ``status == "resolved"``, so rule 1 (filename keyword matching)
   applies to those rows same as any other era. Rows the sidecar could not
   resolve (``status == "unresolved"``, e.g. an expired/invalid token) fall
   through to rule 2 exactly as before. Run ``resolve_sharepoint_names.py``
   before (re)classifying an era with SharePoint documents to get the
   benefit; if the sidecar file doesn't exist yet, behavior is unchanged
   from the gap described above.

2. **First-page text cues** (``TEXT_RULES`` / the ``_check_*`` functions),
   tried when rule 1 found nothing. Each check runs over the first one or
   two whitespace-normalized pages (survives `pdftotext -layout` column
   wrapping); first hit wins. bar needs its header near the very top OR >=2
   of {header, "1. TITLE", "FISCAL IMPACT", "RECOMMENDED MOTION", paired
   "For Introduction:"/"For Action:"} -- a lone header match is too easily
   an incidental mention inside unrelated minutes narrative. minutes needs
   "called the meeting to order" (alone sufficient), or an early "Minutes"
   heading *plus* a real "Call to Order" section (guards against governance
   forms with a "Link to Meeting Agenda(s) / Minutes:" label line). agenda
   needs an early "Agenda" heading plus a "Call to Order" section, same
   reasoning. warrants/personnel are single-phrase matches. resolution/
   policy require their marker within the first ~250 chars *and* not
   preceded by citation phrasing ("per Board Policy No. ...", "consistent
   with Resolution No. ...") -- otherwise a passing citation inside some
   unrelated form or BAR false-positives. presentation (weak, last resort):
   >=2 pages and chars/page < 1,200, calibrated against this corpus's own
   `.textmeta.json` stats (median cpp: presentation 602 vs. every other
   kind >= 1,700).

3. **Fallback to the manifest's `kind_guess`** when neither rule fires
   (`kind = "other"` if that's also absent).

When rule 1 and rule 2 disagree, both land in `signals`
(`disagreement:filename=X,text=Y`) and `confidence` drops -- these rows are
the best spot-check candidates. Confidence: 0.95 filename+text agree; 0.85
filename only, or strong text with no filename signal, or a weak-filename-
kind overridden by strong text; 0.65 filename/text disagree (non-weak); 0.55
weak text match only (presentation heuristic); 0.35 / 0.15 kind_guess
fallback (0.15 when that fallback is itself "other").
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import os
import re
import sys
import urllib.parse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_OUTDIR = "out_sps_web"

KIND_VOCAB = (
    "agenda", "minutes", "bar", "warrants", "personnel", "presentation",
    "packet", "policy", "resolution", "image", "video", "other",
)

RESOLVED_FILENAME_GAP = (
    "SharePoint fetches (`sharepoint_download`) never resolve to a real "
    "filename via `.prov.json` alone: `download.aspx?share=<TOKEN>` returns "
    "PDF bytes with no redirect, so `final_url` is just the request URL "
    "again, and the saved raw file is literally `<doc_id>.pdf`. This is now "
    "worked around by a sidecar, `resolve_sharepoint_names.py`, which hits "
    "the `guestaccess.aspx` endpoint instead (it does redirect) and writes "
    "`manifest/sharepoint_names.jsonl`; `resolved_filename_for` consumes it "
    "for rule 1 (see the module docstring's 'sidecar' paragraph). Rows the "
    "sidecar couldn't resolve, or rows classified before it was run, still "
    "fall back to rule 2 (text cues) or `kind_guess`."
)

# --------------------------------------------------------------------------
# small helpers (same conventions as inventory_merge.py / fetch.py)
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


ITEM_CODE_RE = re.compile(r"^([A-Z]{1,3}\d{1,3})[_\-. ]")
FILENAME_DATE_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})")
DOC_ID_STEM_RE = re.compile(r"^[0-9a-f]{16}(-\d+)?\.[A-Za-z0-9]+$")


def derive_item_code(filename):
    if not filename:
        return None
    m = ITEM_CODE_RE.match(filename.strip())
    return m.group(1) if m else None


def derive_filename_date(filename):
    if not filename:
        return None
    for m in FILENAME_DATE_RE.finditer(filename):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime.date(y, mo, d).isoformat()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# indices over out_sps_web/raw and out_sps_web/text
# --------------------------------------------------------------------------

def build_fetch_index(outdir, era=None):
    """doc_id -> {"raw_path": str, "prov": dict}, from raw/<era>/<date>/*.prov.json."""
    idx = {}
    raw_root = os.path.join(outdir, "raw")
    if not os.path.isdir(raw_root):
        return idx
    eras = [era] if era else sorted(
        d for d in os.listdir(raw_root) if os.path.isdir(os.path.join(raw_root, d)))
    for e in eras:
        era_dir = os.path.join(raw_root, e)
        if not os.path.isdir(era_dir):
            continue
        for date in os.listdir(era_dir):
            date_dir = os.path.join(era_dir, date)
            if not os.path.isdir(date_dir):
                continue
            for name in os.listdir(date_dir):
                if not name.endswith(".prov.json"):
                    continue
                prov_path = os.path.join(date_dir, name)
                raw_path = prov_path[: -len(".prov.json")]
                if not os.path.isfile(raw_path):
                    continue
                try:
                    with open(prov_path, encoding="utf-8") as fh:
                        prov = json.load(fh)
                except Exception:  # noqa: BLE001 - a corrupt prov file must not kill the run
                    continue
                doc_id = prov.get("doc_id")
                if doc_id:
                    idx[doc_id] = {"raw_path": raw_path, "prov": prov}
    return idx


def build_text_index(outdir, era=None):
    """doc_id -> {"text_path": str, "meta": dict}, from text/<era>/<date>/*.textmeta.json."""
    idx = {}
    text_root = os.path.join(outdir, "text")
    if not os.path.isdir(text_root):
        return idx
    eras = [era] if era else sorted(
        d for d in os.listdir(text_root) if os.path.isdir(os.path.join(text_root, d)))
    for e in eras:
        era_dir = os.path.join(text_root, e)
        if not os.path.isdir(era_dir):
            continue
        for date in os.listdir(era_dir):
            date_dir = os.path.join(era_dir, date)
            if not os.path.isdir(date_dir):
                continue
            for name in os.listdir(date_dir):
                if not name.endswith(".textmeta.json"):
                    continue
                meta_path = os.path.join(date_dir, name)
                stem = name[: -len(".textmeta.json")]
                text_path = os.path.join(date_dir, stem + ".txt")
                try:
                    with open(meta_path, encoding="utf-8") as fh:
                        meta = json.load(fh)
                except Exception:  # noqa: BLE001
                    continue
                doc_id = meta.get("doc_id")
                if doc_id and os.path.isfile(text_path):
                    idx[doc_id] = {"text_path": text_path, "meta": meta}
    return idx


def build_sharepoint_names_index(outdir):
    """doc_id -> resolved_filename, from manifest/sharepoint_names.jsonl
    (resolve_sharepoint_names.py), for rows it managed to resolve. Built
    directly from the post-merge manifest (same doc_ids as documents.jsonl),
    so unlike fetch_idx/text_idx no doc_id-suffix `lookup()` fallback is
    needed here."""
    path = os.path.join(outdir, "manifest", "sharepoint_names.jsonl")
    idx = {}
    for row in read_jsonl(path):
        if row.get("status") == "resolved" and row.get("resolved_filename"):
            idx[row["doc_id"]] = row["resolved_filename"]
    return idx


def lookup(idx, doc_id):
    """doc_id, then (defensively) its base id with a merge collision suffix
    (`-2`, `-3`, ...) stripped -- fetch.py fetched the pre-merge manifests,
    whose doc_ids never carry that suffix (see inventory_merge.py)."""
    hit = idx.get(doc_id)
    if hit is not None:
        return hit
    m = re.match(r"^(.*)-\d+$", doc_id)
    return idx.get(m.group(1)) if m else None


# --------------------------------------------------------------------------
# rule 1: resolved filename
# --------------------------------------------------------------------------

def resolved_filename_for(prov, manifest_filename, raw_path, sharepoint_name=None):
    """Best-effort real filename for a fetched document. See the module
    docstring's "Resolved filename" section for why `.prov.json` alone is
    empty for sharepoint_download rows, and the "sidecar" paragraph for how
    `sharepoint_name` (looked up by the caller from
    manifest/sharepoint_names.jsonl) fills that gap."""
    if prov:
        kind = prov.get("fetch_kind")
        final_url = prov.get("final_url") or ""
        if kind in ("direct", "wayback_raw") and final_url:
            name = final_url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
            name = urllib.parse.unquote(name)
            if name and "." in name:
                return name
        if kind == "sharepoint_download" and sharepoint_name:
            return sharepoint_name
    if manifest_filename:
        return manifest_filename
    base = os.path.basename(raw_path) if raw_path else ""
    if base and not DOC_ID_STEM_RE.match(base):
        return base
    return ""


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif"}

# Ordered most-specific-first so e.g. "..._Action_Report_..._Packet.pdf"
# resolves to "bar", not "packet".
FILENAME_RULES = [
    ("minutes", re.compile(r"minutes", re.I)),
    ("warrants", re.compile(r"warrants?", re.I)),
    ("personnel", re.compile(r"personnel", re.I)),
    ("bar", re.compile(r"action[_\s-]*report|actionreport|(?:^|[^a-z])bar(?:[^a-z]|$)", re.I)),
    ("agenda", re.compile(r"agenda", re.I)),  # also matches "spagenda"
    ("presentation", re.compile(r"presentation|powerpoint|\.pptx?$", re.I)),
    ("resolution", re.compile(r"resolution", re.I)),
    ("policy", re.compile(r"polic(?:y|ies)", re.I)),
    ("packet", re.compile(r"packet", re.I)),
]

# "resolution"/"policy" name-matches are demoted below a strong text signal
# (see classify_document) -- filenames often name a BAR's *subject*, not its
# type, e.g. "Amendment-1-to-A01_..._Policy-2190_...pdf" is a Board Action
# Report about Policy 2190, not the policy document itself.
WEAK_FILENAME_KINDS = {"resolution", "policy"}


def classify_by_extension_or_host(ext, host_class):
    if ext in IMAGE_EXTS:
        return "image", ["ext:image(%s)" % ext]
    if host_class == "youtube":
        return "video", ["host:youtube"]
    return None, []


def classify_by_filename(name):
    if not name:
        return None, []
    for kind, pat in FILENAME_RULES:
        if pat.search(name):
            return kind, ["filename:%s" % kind]
    return None, []


# --------------------------------------------------------------------------
# rule 2: first-page text cues
# --------------------------------------------------------------------------

BAR_HEADER_RE = re.compile(r"\bboard\s+action\s+report\b", re.I)
BAR_SECTION_RE = re.compile(r"\b1\.\s*title\b", re.I)
BAR_FISCAL_RE = re.compile(r"\bfiscal impact\b", re.I)
BAR_MOTION_RE = re.compile(r"\brecommended motion\b", re.I)
BAR_DATES_RE = re.compile(r"for introduction:.{0,80}?for action:", re.I)

CALLED_TO_ORDER_RE = re.compile(
    r"call(?:ed)?\s+the\s+meeting\s+to\s+order|meeting\s+was\s+called\s+to\s+order", re.I)
# Excludes both "Approval of the Minutes" agenda-item titles and label-style
# mentions like "Link to Meeting Agenda(s) / Minutes: <url>" (seen on Board
# Monthly Time Use Evaluation forms, which are not minutes documents).
APPROVAL_OF_MINUTES_RE = re.compile(r"approval of (?:the )?minutes|/\s*minutes\s*:", re.I)
MINUTES_WORD_RE = re.compile(r"\bminutes\b(?!\s*:)", re.I)
AGENDA_WORD_RE = re.compile(r"\bagenda\b", re.I)
CALL_TO_ORDER_SECTION_RE = re.compile(r"\bcall to order\b", re.I)

WARRANTS_RE = re.compile(
    r"audit report of warrants|warrants?\s+issued|warrant\s+register", re.I)
PERSONNEL_RE = re.compile(r"personnel report|human resources board report", re.I)
RESOLUTION_RE = re.compile(
    r"a resolution of the (?:board|district)|resolution\s+\d{4}\s*/\s*\d{2,4}\s*-\s*\d+", re.I)
POLICY_RE = re.compile(
    r"\bpolicy no\.?\s*\d|\bsuperintendent procedure\b|\bboard policy\b", re.I)
# Excludes an incidental citation ("Per Board Policy No. 2170...", seen in a
# Director Questions and Staff Responses Q&A compilation) from counting as a
# policy/resolution document identifying itself.
CITATION_PREFIX_RE = re.compile(
    r"(?:per|consistent with|in accordance with|pursuant to|complian(?:t|ce)\s+with)\s+"
    r"(?:the\s+)?(?:board\s+)?(?:policy|resolution)", re.I)

HEAD_CHARS = 900  # window for "is this heading near the top" checks
TITLE_CHARS = 250  # tighter window for resolution/policy self-identification


def _check_bar(norm):
    # A genuine BAR opens with this header (within ~400 chars, after at most
    # a short title line) and that alone is trustworthy. A single *other*
    # marker (e.g. just "recommended motion") is not -- minutes narrative
    # sometimes references an item's BAR in passing ("...as attached to the
    # School Board Action Report...", "the Board discussed the recommended
    # motion..."), so require at least 2 independent markers when the header
    # itself isn't right at the top.
    header_near_top = bool(BAR_HEADER_RE.search(norm[:400]))
    hits = []
    if BAR_HEADER_RE.search(norm):
        hits.append("text:board_action_report_header")
    if BAR_SECTION_RE.search(norm):
        hits.append("text:section_1_title")
    if BAR_FISCAL_RE.search(norm):
        hits.append("text:fiscal_impact")
    if BAR_MOTION_RE.search(norm):
        hits.append("text:recommended_motion")
    if BAR_DATES_RE.search(norm):
        hits.append("text:for_intro_and_action_dates")
    if hits and (header_near_top or len(hits) >= 2):
        return hits
    return []


def _check_minutes(norm):
    if CALLED_TO_ORDER_RE.search(norm):
        return ["text:called_meeting_to_order"]
    # An isolated "Minutes" heading alone is too weak on its own -- board
    # governance forms ("Board Monthly Time Use Evaluation") carry a "Link to
    # Meeting Agenda(s) / Minutes:" label in the same spot and would
    # otherwise false-positive. Require the "Call to Order" section too,
    # which every real minutes document in this corpus has.
    head = norm[:HEAD_CHARS]
    if (MINUTES_WORD_RE.search(head) and not APPROVAL_OF_MINUTES_RE.search(head)
            and CALL_TO_ORDER_SECTION_RE.search(norm)):
        return ["text:early_minutes_heading", "text:call_to_order_section"]
    return []


def _check_agenda(norm):
    # Same reasoning as _check_minutes: an early "Agenda" heading by itself
    # matches the same governance-form label line ("...Agenda(s) / Minutes:
    # <url>"), so require a real "Call to Order" section too.
    head = norm[:HEAD_CHARS]
    if AGENDA_WORD_RE.search(head) and CALL_TO_ORDER_SECTION_RE.search(norm):
        return ["text:early_agenda_heading", "text:call_to_order_section"]
    return []


def _check_warrants(norm):
    return ["text:warrants_issued"] if WARRANTS_RE.search(norm) else []


def _check_personnel(norm):
    return ["text:personnel_report_header"] if PERSONNEL_RE.search(norm) else []


def _check_resolution(norm):
    # A genuine resolution announces itself in its own title/preamble, right
    # at the top -- restricting to TITLE_CHARS and excluding citation
    # phrasing keeps "consistent with Resolution No. 2023/24-1..." inside an
    # unrelated BAR from matching.
    head = norm[:TITLE_CHARS]
    if RESOLUTION_RE.search(head) and not CITATION_PREFIX_RE.search(head):
        return ["text:resolution_preamble_or_number"]
    return []


def _check_policy(norm):
    # Same reasoning as _check_resolution: "Per Board Policy No. 2170..." is
    # a citation inside some other kind of document (seen in a Director
    # Questions and Staff Responses Q&A compilation), not a policy
    # identifying itself.
    head = norm[:TITLE_CHARS]
    if POLICY_RE.search(head) and not CITATION_PREFIX_RE.search(head):
        return ["text:policy_or_procedure_header"]
    return []


# (check_fn, "p1" or "p2") -- resolution/policy are page-1-only: a genuine
# resolution/policy document identifies itself in its own header, whereas an
# incidental "Board Policy 5251" citation deep in an unrelated form (e.g. a
# Statement of Financial Interest) tends to show up on a later page.
TEXT_RULES = [
    ("bar", _check_bar, "p2"),
    ("minutes", _check_minutes, "p2"),
    ("agenda", _check_agenda, "p2"),
    ("warrants", _check_warrants, "p2"),
    ("personnel", _check_personnel, "p2"),
    ("resolution", _check_resolution, "p1"),
    ("policy", _check_policy, "p1"),
]


def classify_by_text(text, meta):
    """Returns (kind, signals, strength) or (None, [], None)."""
    if text:
        pages_text = text.split("\f")
        norm_p1 = re.sub(r"\s+", " ", pages_text[0] if pages_text else "")
        norm_p2 = re.sub(r"\s+", " ", " ".join(pages_text[:2]))
        for kind, check, window in TEXT_RULES:
            hits = check(norm_p1 if window == "p1" else norm_p2)
            if hits:
                return kind, hits, "strong"
    # weak fallback: slide-like short pages (see docstring for the
    # chars/page calibration against this corpus).
    pages = (meta or {}).get("pages")
    cpp = (meta or {}).get("chars_per_page")
    if pages and pages >= 2 and cpp is not None and cpp < 1200:
        return "presentation", ["text:short_pages_heuristic(cpp=%.0f)" % cpp], "weak"
    return None, [], None


# --------------------------------------------------------------------------
# per-row classification
# --------------------------------------------------------------------------

def classify_document(row, fetch_idx, text_idx, sharepoint_idx=None):
    doc_id = row["doc_id"]
    fe = lookup(fetch_idx, doc_id)
    if fe is None:
        out = dict(row)
        out.update(kind=None, confidence=None, signals=[],
                   resolved_filename=None, has_text=False, pages=None)
        return out

    raw_path, prov = fe["raw_path"], fe["prov"]
    te = lookup(text_idx, doc_id)
    text_path, meta = (te["text_path"], te["meta"]) if te else (None, None)
    sharepoint_name = (sharepoint_idx or {}).get(doc_id)

    resolved = resolved_filename_for(prov, row.get("filename"), raw_path, sharepoint_name)
    ext = os.path.splitext(raw_path)[1].lower()

    signals = []
    fname_kind, fname_sig = classify_by_extension_or_host(ext, row.get("host_class"))
    if fname_kind is None:
        fname_kind, fname_sig = classify_by_filename(resolved)
    signals += fname_sig

    text = None
    if text_path and os.path.isfile(text_path):
        try:
            with open(text_path, encoding="utf-8") as fh:
                text = fh.read()
        except Exception:  # noqa: BLE001
            text = None
    has_text = bool(text)

    text_kind, text_sig, text_strength = classify_by_text(text, meta)
    signals += text_sig

    if fname_kind and fname_kind in WEAK_FILENAME_KINDS and text_kind and text_kind != fname_kind:
        # "resolution"/"policy" in a filename is often just naming the
        # *subject* of a BAR ("Amendment-1-to-A01_..._Policy-2190_...pdf" is
        # a Board Action Report about Policy 2190, not the policy itself) --
        # unlike the PLAN's explicitly-named filename markers (_Minutes,
        # _Agenda, _BAR, Action_Report, ...), these two are not reliable
        # enough to override a strong text-cue match, so text wins here.
        kind = text_kind
        signals.append("disagreement:filename=%s,text=%s (text wins: weak filename category)"
                       % (fname_kind, text_kind))
        confidence = 0.8
    elif fname_kind:
        kind = fname_kind
        if text_kind and text_kind != fname_kind:
            signals.append("disagreement:filename=%s,text=%s" % (fname_kind, text_kind))
            confidence = 0.65
        elif text_kind == fname_kind:
            confidence = 0.95
        else:
            confidence = 0.85
    elif text_kind:
        kind = text_kind
        confidence = 0.85 if text_strength == "strong" else 0.55
    else:
        kg = row.get("kind_guess")
        if kg:
            kind = kg
            signals.append("fallback:kind_guess")
            confidence = 0.35 if kg != "other" else 0.15
        else:
            kind = "other"
            signals.append("fallback:none")
            confidence = 0.10

    out = dict(row)
    out["item_code"] = derive_item_code(resolved) or row.get("item_code")
    out["filename_date"] = derive_filename_date(resolved) or row.get("filename_date")
    out["kind"] = kind
    out["confidence"] = round(confidence, 2)
    out["signals"] = signals
    out["resolved_filename"] = resolved or None
    out["has_text"] = has_text
    out["pages"] = (meta or {}).get("pages")
    return out


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def build_report(rows):
    L = []
    A = L.append
    A("# Document classification report (C2)")
    A("")
    A("Generated by `extractors/sps_web/classify.py`. %d rows in "
      "`documents_classified.jsonl`." % len(rows))
    A("")
    A("**Known gap** (see the module docstring for detail): " + RESOLVED_FILENAME_GAP)
    A("")

    eras = sorted({r["era"] for r in rows})
    A("## Counts by era x kind")
    A("")
    header = ["era"] + list(KIND_VOCAB) + ["not_fetched", "total"]
    A("| " + " | ".join(header) + " |")
    A("|" + "---|" * len(header))
    totals = collections.Counter()
    for era in eras:
        era_rows = [r for r in rows if r["era"] == era]
        counts = collections.Counter(r["kind"] for r in era_rows)
        not_fetched = counts.pop(None, 0)
        line = [era] + [str(counts.get(k, 0)) for k in KIND_VOCAB] + \
               [str(not_fetched), str(len(era_rows))]
        A("| " + " | ".join(line) + " |")
        totals["total"] += len(era_rows)
        totals["not_fetched"] += not_fetched
        for k in KIND_VOCAB:
            totals[k] += counts.get(k, 0)
    line = ["**total**"] + [str(totals[k]) for k in KIND_VOCAB] + \
           [str(totals["not_fetched"]), str(totals["total"])]
    A("| " + " | ".join(line) + " |")
    A("")

    A("## Confidence histogram (fetched rows only)")
    A("")
    fetched = [r for r in rows if r["kind"] is not None]
    buckets = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    A("| range | count | share |")
    A("|---|---:|---:|")
    for lo, hi in buckets:
        n = sum(1 for r in fetched if lo <= r["confidence"] < hi)
        share = 100.0 * n / len(fetched) if fetched else 0.0
        A("| [%.1f, %.1f) | %d | %.1f%% |" % (lo, min(hi, 1.0), n, share))
    A("")

    A("## Disagreements with `kind_guess`")
    A("")
    disagree = [r for r in fetched if r["kind"] != (r.get("kind_guess") or "other")]
    A("%d of %d fetched rows (%.1f%%) differ from the manifest's `kind_guess`."
      % (len(disagree), len(fetched), 100.0 * len(disagree) / len(fetched) if fetched else 0.0))
    A("")
    pair_counts = collections.Counter(
        (r.get("kind_guess") or "other", r["kind"]) for r in disagree)
    A("| kind_guess | -> kind | count |")
    A("|---|---|---:|")
    for (kg, k), n in pair_counts.most_common():
        A("| %s | %s | %d |" % (kg, k, n))
    A("")
    A("First 40 disagreements (doc_id, era, resolved_filename, kind_guess -> kind, "
      "confidence, top signal):")
    A("")
    for r in disagree[:40]:
        sig = r["signals"][0] if r["signals"] else "-"
        A("- `%s` (%s) `%s`: %s -> **%s** (%.2f, %s)" % (
            r["doc_id"], r["era"], r.get("resolved_filename") or r.get("filename") or "",
            r.get("kind_guess") or "other", r["kind"], r["confidence"], sig))
    if len(disagree) > 40:
        A("- ... and %d more." % (len(disagree) - 40))
    A("")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Classify fetched sps_web board documents by kind (task C2).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--era", choices=["wp", "blackboard", "legacy", "archive"],
                   help="only (re)classify rows from this era; other eras' rows in an "
                        "existing documents_classified.jsonl are carried forward unchanged")
    p.add_argument("--limit", type=int, help="only process the first N matching rows")
    p.add_argument("--outdir", default=DEFAULT_OUTDIR, help=f"output root (default {DEFAULT_OUTDIR})")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    outdir = args.outdir
    manifest_path = os.path.join(outdir, "manifest", "documents.jsonl")
    out_path = os.path.join(outdir, "manifest", "documents_classified.jsonl")
    report_path = os.path.join(outdir, "qa", "classify_report.md")

    manifest_rows = read_jsonl(manifest_path)
    if not manifest_rows:
        print("no rows in %s" % manifest_path, file=sys.stderr)
        return 1

    existing = {r["doc_id"]: r for r in read_jsonl(out_path)}

    fetch_idx = build_fetch_index(outdir, args.era)
    text_idx = build_text_index(outdir, args.era)
    sharepoint_idx = build_sharepoint_names_index(outdir)

    rows = manifest_rows
    if args.era:
        rows = [r for r in rows if r["era"] == args.era]
    if args.limit:
        rows = rows[: args.limit]
    process_ids = {r["doc_id"] for r in rows}

    print("[manifest] %d rows total, %d selected for (re)classification (era=%s, limit=%s)"
          % (len(manifest_rows), len(rows), args.era or "all", args.limit or "all"))
    print("[index] %d fetched raw files, %d with extracted text, %d sharepoint names resolved"
          % (len(fetch_idx), len(text_idx), len(sharepoint_idx)))

    classified = {r["doc_id"]: classify_document(r, fetch_idx, text_idx, sharepoint_idx) for r in rows}

    out_rows = []
    for r in manifest_rows:
        doc_id = r["doc_id"]
        if doc_id in process_ids:
            out_rows.append(classified[doc_id])
        elif doc_id in existing:
            out_rows.append(existing[doc_id])
        else:
            out = dict(r)
            out.update(kind=None, confidence=None, signals=[],
                       resolved_filename=None, has_text=False, pages=None)
            out_rows.append(out)

    write_jsonl(out_path, out_rows)

    report = build_report(out_rows)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report)

    n_fetched = sum(1 for r in out_rows if r["kind"] is not None)
    print("[out] %s (%d rows, %d classified, %d not-yet-fetched)"
          % (out_path, len(out_rows), n_fetched, len(out_rows) - n_fetched))
    print("[report] %s" % report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
