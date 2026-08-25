"""
totext.py -- extracts plain text from SPS board documents fetched by fetch.py.

Usage (from repo root):
    $ venv/bin/python3 -m extractors.sps_web.totext
    $ venv/bin/python3 -m extractors.sps_web.totext --era archive
    $ venv/bin/python3 -m extractors.sps_web.totext --era wp --limit 200
    $ venv/bin/python3 -m extractors.sps_web.totext --force --workers 8

For every content file under <outdir>/raw/<era>/<date>/ with a sibling
<file>.prov.json (raw/ is fetch.py's output, treated read-only here;
.prov.json files and any *.tmp/.tmp-* leftovers are skipped as inputs),
writes:
    <outdir>/text/<era>/<date>/<stem>.txt
    <outdir>/text/<era>/<date>/<stem>.textmeta.json

<stem>.txt is the extracted text verbatim, including page breaks as \\f
wherever pdftotext/OCR produced them -- downstream page numbers come from
counting \\f, so nothing here strips or renormalizes them.

<stem>.textmeta.json schema:
    {
      "doc_id": str | null,        # from the sibling .prov.json
      "source_file": str,          # raw file path, relative to <outdir>
      "sha256": str | null,        # from .prov.json; used to detect staleness
      "pages": int | null,
      "chars": int,
      "chars_per_page": float | null,
      "method": "pdftotext" | "ocr" | "docx" | "doc" | "image" | "none",
      "ocr_pages": int,            # >0 only when method == "ocr"
      "extracted_at": str,         # UTC ISO8601
      "error": str | null
    }

Idempotence: skipped (rerun is a no-op) when <stem>.textmeta.json already
exists and its "sha256" matches the raw file's current .prov.json sha256,
unless --force. Safe to rerun while fetch.py's crawl is still filling in
raw/ -- a rerun just picks up files that are new or changed.

PDF: `pdftotext -layout <pdf> -` (poppler; \\f per page, incl. the last --
verified against `pdfinfo` page counts). If under OCR_MIN_CHARS_PER_PAGE
chars/page on average (image-only scan -- common 2005-2011, also a few
image-heavy WP-era slide decks), OCR is attempted: (1) `ocrmypdf --skip-text
--output-type pdf` then pdftotext again, if ocrmypdf is on PATH; else
(2) `pdftoppm -r 200 -png` to rasterize pages + `tesseract <page> -` per
page joined with \\f, if tesseract+pdftoppm are on PATH (skipped, with
error="ocr_skipped_too_large", past OCR_MAX_PAGES_TESSERACT pages -- the
per-page loop is O(pages) subprocess calls and would otherwise stall a
worker for a huge scanned exhibit); else (3) method="none",
error="ocr_unavailable" (the thin pdftotext text, if any, is still kept in
the .txt -- nothing is discarded). OCR intermediates live under
tempfile.TemporaryDirectory(), removed per file.

.docx: unzipped with stdlib zipfile; word/document.xml's <w:p> paragraphs
become \\n-joined lines. No page concept -> pages/chars_per_page null.
.doc: `textutil -convert txt -stdout` (macOS); else method="none" +
error="textutil_unavailable".
Images (.jpg/.jpeg/.png/.gif): method="image" always; text via
`tesseract <file> -` if available, else empty.
Anything else: method="none", no error.

Per-file failures (exceptions, missing tools, non-zero subprocess exit)
never abort the run -- caught, recorded in the file's own .textmeta.json
"error", and appended to <outdir>/qa/text_failures.jsonl (JSONL,
run_id-tagged, append-only across runs).

Summary (stdout + <outdir>/qa/text_report.md), per era: files seen,
extracted this run, skipped (up to date), counts by method, OCR count,
failures, and chars/page distribution (min/p10/median) so scanned-but-
not-yet-OCR'd documents stay visible.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

DEFAULT_OUTDIR = "out_sps_web"
OCR_MIN_CHARS_PER_PAGE = 50
OCR_DPI = 200
OCR_MAX_PAGES_TESSERACT = 60  # per-page tesseract loop is O(pages); ocrmypdf has no such cap
SUBPROCESS_TIMEOUT = 900
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif")


def detect_tools():
    names = ("pdftotext", "ocrmypdf", "tesseract", "pdftoppm", "textutil")
    return {name: shutil.which(name) for name in names}


def count_pages(text):
    """Pages = number of form-feed page separators pdftotext emits (one per
    page, including the last, verified empirically). Falls back to 1 for
    non-empty text with no separator (rare, e.g. single unusual page)."""
    if not text:
        return 0
    ff = text.count("\f")
    return ff if ff else 1


def pdftotext_stdout(pdf_path, timeout=SUBPROCESS_TIMEOUT):
    r = subprocess.run(["pdftotext", "-layout", pdf_path, "-"], capture_output=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"pdftotext rc={r.returncode}: {r.stderr.decode('utf-8', errors='replace')[:300]}")
    return r.stdout.decode("utf-8", errors="replace")


def _page_num_key(fname):
    m = re.search(r"-(\d+)\.png$", fname)
    return int(m.group(1)) if m else 0


def _ocr_via_ocrmypdf(path, timeout=SUBPROCESS_TIMEOUT):
    with tempfile.TemporaryDirectory(prefix="totext-ocrmypdf-") as tmpd:
        out_pdf = os.path.join(tmpd, "ocr.pdf")
        r = subprocess.run(
            ["ocrmypdf", "--skip-text", "--output-type", "pdf", path, out_pdf],
            capture_output=True, timeout=timeout,
        )
        if r.returncode != 0:
            raise RuntimeError(f"ocrmypdf rc={r.returncode}: {r.stderr.decode('utf-8', errors='replace')[:300]}")
        text = pdftotext_stdout(out_pdf, timeout=timeout)
        return text, count_pages(text)


def _ocr_via_tesseract(path, dpi=OCR_DPI, timeout=SUBPROCESS_TIMEOUT):
    with tempfile.TemporaryDirectory(prefix="totext-tess-") as tmpd:
        prefix = os.path.join(tmpd, "page")
        r = subprocess.run(["pdftoppm", "-r", str(dpi), "-png", path, prefix], capture_output=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError(f"pdftoppm rc={r.returncode}: {r.stderr.decode('utf-8', errors='replace')[:300]}")
        page_files = sorted(glob.glob(prefix + "-*.png"), key=_page_num_key)
        if not page_files:
            raise RuntimeError("pdftoppm produced no page images")
        texts = []
        for pf in page_files:
            rt = subprocess.run(["tesseract", pf, "-"], capture_output=True, timeout=180)
            if rt.returncode != 0:
                raise RuntimeError(f"tesseract rc={rt.returncode} on {os.path.basename(pf)}: {rt.stderr.decode('utf-8', errors='replace')[:300]}")
            texts.append(rt.stdout.decode("utf-8", errors="replace"))
        text = "\f".join(texts) + "\f"
        return text, len(page_files)


def extract_pdf(path, tools):
    """Returns (text, pages, method, ocr_pages, error)."""
    text = pdftotext_stdout(path)
    pages = count_pages(text)
    cpp = (len(text) / pages) if pages else 0.0
    if cpp >= OCR_MIN_CHARS_PER_PAGE:
        return text, pages, "pdftotext", 0, None

    if tools.get("ocrmypdf"):
        try:
            ocr_text, ocr_pages = _ocr_via_ocrmypdf(path)
            return ocr_text, ocr_pages, "ocr", ocr_pages, None
        except Exception as e:  # noqa: BLE001 - never let one bad file kill the run
            return text, pages, "none", 0, f"ocrmypdf_failed: {e}"
    if tools.get("tesseract") and tools.get("pdftoppm"):
        if pages > OCR_MAX_PAGES_TESSERACT:
            # Per-page tesseract is O(pages) subprocess calls; a several-hundred-
            # page scanned exhibit would otherwise dominate a worker for many
            # minutes. Leave it un-OCR'd (thin pdftotext text kept) and flag it
            # for a manual/batch OCR pass instead of stalling this run.
            return text, pages, "none", 0, f"ocr_skipped_too_large: {pages} pages > {OCR_MAX_PAGES_TESSERACT}"
        try:
            ocr_text, ocr_pages = _ocr_via_tesseract(path)
            return ocr_text, ocr_pages, "ocr", ocr_pages, None
        except Exception as e:  # noqa: BLE001
            return text, pages, "none", 0, f"tesseract_failed: {e}"
    return text, pages, "none", 0, "ocr_unavailable"


def extract_docx(path):
    import zipfile
    from xml.etree import ElementTree as ET

    W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        with z.open("word/document.xml") as f:
            tree = ET.parse(f)
    paragraphs = []
    for p in tree.getroot().iter(f"{W_NS}p"):
        paragraphs.append("".join(node.text or "" for node in p.iter(f"{W_NS}t")))
    return "\n".join(paragraphs), None, "docx", 0, None


def extract_doc(path, tools):
    if not tools.get("textutil"):
        return "", None, "none", 0, "textutil_unavailable"
    r = subprocess.run(["textutil", "-convert", "txt", "-stdout", path], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"textutil rc={r.returncode}: {r.stderr.decode('utf-8', errors='replace')[:300]}")
    return r.stdout.decode("utf-8", errors="replace"), None, "doc", 0, None


def extract_image(path, tools):
    if not tools.get("tesseract"):
        return "", None, "image", 0, None
    r = subprocess.run(["tesseract", path, "-"], capture_output=True, timeout=180)
    if r.returncode != 0:
        return "", None, "image", 0, f"tesseract_failed: {r.stderr.decode('utf-8', errors='replace')[:300]}"
    return r.stdout.decode("utf-8", errors="replace"), None, "image", 0, None


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


class FailureLog:
    """Append-only across runs so failure history survives reruns; every
    row carries run_id (this run's UTC start timestamp)."""

    def __init__(self, path, run_id):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._lock = threading.Lock()
        self._run_id = run_id
        self._fh = open(path, "a")

    def write(self, doc_id, source_file, method, error):
        row = {"run_id": self._run_id, "doc_id": doc_id, "source_file": source_file, "method": method, "error": error}
        with self._lock:
            self._fh.write(json.dumps(row) + "\n")
            self._fh.flush()

    def close(self):
        self._fh.close()


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, max(0, round(p * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.seen, self.extracted, self.skipped, self.ocr, self.failed = {}, {}, {}, {}, {}
        self.methods, self.cpp = {}, {}

    def see(self, era):
        with self.lock:
            self.seen[era] = self.seen.get(era, 0) + 1

    def skip_existing(self, era):
        with self.lock:
            self.skipped[era] = self.skipped.get(era, 0) + 1

    def record(self, era, method, error, cpp):
        with self.lock:
            self.extracted[era] = self.extracted.get(era, 0) + 1
            m = self.methods.setdefault(era, {})
            m[method] = m.get(method, 0) + 1
            if method == "ocr":
                self.ocr[era] = self.ocr.get(era, 0) + 1
            if error:
                self.failed[era] = self.failed.get(era, 0) + 1
            if cpp is not None:
                self.cpp.setdefault(era, []).append(cpp)

    def report(self):
        eras = sorted(set(self.seen) | set(self.extracted) | set(self.skipped))
        lines = ["| era | seen | extracted | skipped-existing | ocr | failed | methods |",
                  "|---|---|---|---|---|---|---|"]
        for era in eras:
            methods = self.methods.get(era, {})
            method_str = ", ".join(f"{k}={v}" for k, v in sorted(methods.items())) or "-"
            lines.append(f"| {era} | {self.seen.get(era, 0)} | {self.extracted.get(era, 0)} | "
                         f"{self.skipped.get(era, 0)} | {self.ocr.get(era, 0)} | {self.failed.get(era, 0)} | {method_str} |")
        lines.append("")
        lines.append("| era | chars/page min | p10 | median | n |")
        lines.append("|---|---|---|---|---|")
        for era in eras:
            vals = sorted(self.cpp.get(era, []))
            if vals:
                lines.append(f"| {era} | {vals[0]:.1f} | {percentile(vals, 0.10):.1f} | {percentile(vals, 0.50):.1f} | {len(vals)} |")
            else:
                lines.append(f"| {era} | - | - | - | 0 |")
        return "\n".join(lines)


def iter_raw_files(outdir, era=None):
    raw_root = os.path.join(outdir, "raw")
    if not os.path.isdir(raw_root):
        return
    eras = [era] if era else sorted(d for d in os.listdir(raw_root) if os.path.isdir(os.path.join(raw_root, d)))
    for e in eras:
        era_dir = os.path.join(raw_root, e)
        if not os.path.isdir(era_dir):
            continue
        for date in sorted(os.listdir(era_dir)):
            date_dir = os.path.join(era_dir, date)
            if not os.path.isdir(date_dir):
                continue
            for name in sorted(os.listdir(date_dir)):
                if name.endswith(".prov.json") or name.endswith(".tmp") or name.startswith(".tmp-"):
                    continue
                path = os.path.join(date_dir, name)
                if not os.path.isfile(path):
                    continue
                prov_path = path + ".prov.json"
                if os.path.isfile(prov_path):
                    yield e, date, path, prov_path


def process_one(era, date, raw_path, prov_path, outdir, tools, force, stats, failure_log):
    stats.see(era)
    source_file = os.path.relpath(raw_path, outdir)
    try:
        with open(prov_path) as f:
            prov = json.load(f)
    except Exception as e:  # noqa: BLE001
        failure_log.write(None, source_file, "none", f"bad_prov: {e}")
        stats.record(era, "none", f"bad_prov: {e}", None)
        return

    doc_id, raw_sha = prov.get("doc_id"), prov.get("sha256")
    name = os.path.basename(raw_path)
    stem, ext = os.path.splitext(name)
    ext = ext.lower()

    text_dir = os.path.join(outdir, "text", era, date)
    txt_path = os.path.join(text_dir, stem + ".txt")
    meta_path = os.path.join(text_dir, stem + ".textmeta.json")

    if not force and os.path.isfile(meta_path):
        try:
            with open(meta_path) as f:
                old_meta = json.load(f)
            if old_meta.get("sha256") == raw_sha:
                stats.skip_existing(era)
                return
        except Exception:  # noqa: BLE001 - stale/corrupt meta: fall through and reprocess
            pass

    try:
        if ext == ".pdf":
            text, pages, method, ocr_pages, error = extract_pdf(raw_path, tools)
        elif ext == ".docx":
            text, pages, method, ocr_pages, error = extract_docx(raw_path)
        elif ext == ".doc":
            text, pages, method, ocr_pages, error = extract_doc(raw_path, tools)
        elif ext in IMAGE_EXTS:
            text, pages, method, ocr_pages, error = extract_image(raw_path, tools)
        else:
            text, pages, method, ocr_pages, error = "", None, "none", 0, None
    except Exception as e:  # noqa: BLE001 - a single bad file must never abort the run
        text, pages, method, ocr_pages, error = "", None, "none", 0, f"exception: {e}"

    chars = len(text)
    cpp = (chars / pages) if pages else None

    try:
        atomic_write(txt_path, text.encode("utf-8", errors="replace"))
        meta = {
            "doc_id": doc_id, "source_file": source_file, "sha256": raw_sha,
            "pages": pages, "chars": chars, "chars_per_page": cpp,
            "method": method, "ocr_pages": ocr_pages,
            "extracted_at": datetime.now(timezone.utc).isoformat(), "error": error,
        }
        atomic_write(meta_path, json.dumps(meta, indent=2).encode("utf-8"))
    except Exception as e:  # noqa: BLE001
        failure_log.write(doc_id, source_file, method, f"write_failed: {e}")
        stats.record(era, "none", f"write_failed: {e}", None)
        return

    stats.record(era, method, error, cpp)
    if error:
        failure_log.write(doc_id, source_file, method, error)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--era", choices=["wp", "blackboard", "legacy", "archive"], help="only process this era")
    p.add_argument("--limit", type=int, help="only process the first N matching files")
    p.add_argument("--workers", type=int, default=4, help="thread pool size (default 4)")
    p.add_argument("--force", action="store_true", help="reprocess even if a matching-sha256 .textmeta.json exists")
    p.add_argument("--outdir", default=DEFAULT_OUTDIR, help=f"output root (default {DEFAULT_OUTDIR})")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    tools = detect_tools()
    tool_line = ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in tools.items())
    print(f"[tools] {tool_line}")

    candidates = list(iter_raw_files(args.outdir, args.era))
    if args.limit:
        candidates = candidates[: args.limit]
    print(f"[files] {len(candidates)} candidates" + (f" (era={args.era})" if args.era else ""))

    run_id = datetime.now(timezone.utc).isoformat()
    print(f"[run_id] {run_id}")

    stats = Stats()
    failure_log = FailureLog(os.path.join(args.outdir, "qa", "text_failures.jsonl"), run_id)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = [
                ex.submit(process_one, era, date, raw_path, prov_path, args.outdir, tools, args.force, stats, failure_log)
                for era, date, raw_path, prov_path in candidates
            ]
            for f in as_completed(futures):
                f.result()
    finally:
        failure_log.close()

    report = stats.report()
    print("\n" + report)
    report_path = os.path.join(args.outdir, "qa", "text_report.md")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w") as fh:
        fh.write(f"# Text extraction report\n\ntools: {tool_line}\n\n" + report + "\n")
    print(f"\n[report] {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
