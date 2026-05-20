#!python3
"""Build a manifest CSV of the transit/transportation PRR data tree.

Walks the tree under --root, one row per file, with provenance parsed from
the path (PRR case, installment, delivery date), file stats, sha256, and --
for PDFs -- page count and a per-page char-count profile extracted via
pdfplumber so each PDF can be classified as text / scanned / mixed.

After collecting rows, a second pass groups by sha256 and marks duplicates.

Usage:
    python3 -m extractors.prr.transit.build_manifest \\
        --root 'data/transit/2122-501 _ Transit RFP' \\
        --out  data/transit/manifest.csv
"""

import argparse
import csv
import hashlib
import logging
import os
import re
import statistics
import sys
import time
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


CASE_RE = re.compile(r"\b(2122-\d{3})\b")
INSTALLMENT_RE = re.compile(r"Installment\s+(\d+)", re.IGNORECASE)
DATE_DIR_RE = re.compile(r"^(\d{8})\b")
UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
DOC_BATES_RE = re.compile(r"^DOC\d{6,}", re.IGNORECASE)
REDACTION_LOG_RE = re.compile(r"Redaction Log", re.IGNORECASE)

# Default case for files whose path doesn't name a sub-case (the top-level
# folder is "2122-501 _ Transit RFP").
DEFAULT_CASE = "2122-501"

# CSV column order.
FIELDS = [
    "full_path",
    "rel_path",
    "prr_case",
    "installment",
    "delivery_date",
    "basename",
    "ext",
    "size_bytes",
    "sha256",
    "mtime",
    "container_class",
    "pdf_page_count",
    "pdf_text_chars_total",
    "pdf_chars_per_page_median",
    "pdf_pages_with_text",
    "extract_class",
    "duplicate_of_sha256",
    "notes",
]


def parse_provenance(rel_parts):
    """Extract (prr_case, installment, delivery_date) from path components.

    rel_parts: tuple of path segments relative to the root, e.g.
    ('20220802 PRR', '2122-349', 'DOC0000001.eml').
    """
    delivery_date = None
    installment = None
    case = DEFAULT_CASE

    for part in rel_parts:
        m = DATE_DIR_RE.match(part)
        if m and delivery_date is None:
            delivery_date = m.group(1)
        m = CASE_RE.search(part)
        if m:
            case = m.group(1)
        m = INSTALLMENT_RE.search(part)
        if m and installment is None:
            installment = int(m.group(1))

    return case, installment, delivery_date


def classify_container(path, rel_parts, basename, ext, size):
    """Coarse 5-bucket classification from path + filename + size."""
    name = basename
    lower = name.lower()

    if name == ".DS_Store" or size == 0 or UUID_RE.match(name):
        return "NOISE"

    if REDACTION_LOG_RE.search(name):
        return "REDACTION_LOG"

    if ext == ".zip":
        # If a sibling "(Unzipped Files)" dir already exists, the zip is
        # redundant; still emit it but call it NOISE so dedupe doesn't double
        # count both the zip and its expansion.
        unzipped_sibling = path.with_name(name + " (Unzipped Files)")
        if unzipped_sibling.is_dir():
            return "NOISE"
        return "ARCHIVE"

    # Bundle PDFs: the big concatenated installment PDFs that need splitting.
    if ext == ".pdf" and INSTALLMENT_RE.search(name) and size > 1_000_000:
        return "EMAIL_DROP_BUNDLED"

    # Decomposed email drops: files in directories dominated by DOC0000NNN
    # bates-stamped artifacts, or that themselves carry that pattern.
    if DOC_BATES_RE.match(name):
        return "EMAIL_DROP_DECOMPOSED"

    # Anything else (RFP attachments, submittals, scoring sheets, meeting
    # minutes extracted from zips, delivery-notification emails, the bare
    # RFP xlsx at root, etc.) is original source content — not a bundle
    # that needs splitting, not a container, not noise.
    return "ORIGINAL_SOURCE"


def classify_extract(ext, pdf_page_count, pdf_chars_per_page_median,
                     pdf_pages_with_text):
    """Per-row extraction-strategy hint."""
    if ext == ".eml":
        return "email_native_eml"
    if ext == ".msg":
        return "email_native_msg"
    if ext in (".docx", ".xlsx", ".xlsm", ".xlsb"):
        return "office_text"
    if ext == ".zip":
        return "archive"
    if ext == ".pdf":
        if pdf_page_count is None or pdf_page_count == 0:
            return "pdf_unreadable"
        frac_text = (pdf_pages_with_text or 0) / pdf_page_count
        # Scanned: almost no pages produced text via pdfplumber.
        if frac_text < 0.10:
            return "pdf_scanned"
        # Text: nearly every page has substantial text.
        if frac_text >= 0.90 and (pdf_chars_per_page_median or 0) >= 200:
            return "pdf_text"
        # Everything in between is mixed — the bundles where some pages are
        # printed-Outlook text and others are scanned attachments. These are
        # what need per-page classification before splitting.
        return "pdf_mixed"
    return "other"


def sha256_of(path, block_size=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(block_size):
            h.update(chunk)
    return h.hexdigest()


def pdf_stats(path):
    """Return (page_count, total_chars, median_chars_per_page, pages_with_text).

    Uses pdfplumber. Pages from which extract_text returns None are treated
    as zero-char pages (typical for image-only scans).
    """
    try:
        with pdfplumber.open(str(path)) as pdf:
            chars_per_page = []
            for page in pdf.pages:
                try:
                    text = page.extract_text() or ""
                except Exception as e:
                    logger.warning("pdfplumber page error in %s: %s", path, e)
                    text = ""
                chars_per_page.append(len(text))
        if not chars_per_page:
            return 0, 0, None, 0
        total = sum(chars_per_page)
        median = int(statistics.median(chars_per_page))
        with_text = sum(1 for c in chars_per_page if c > 20)
        return len(chars_per_page), total, median, with_text
    except Exception as e:
        logger.warning("pdfplumber failed on %s: %s", path, e)
        return None, None, None, None


def iter_files(root):
    """Yield Path objects for every regular file under root, sorted."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            yield Path(dirpath) / name


def build_row(root, path, do_pdf=True):
    rel_parts = path.relative_to(root).parts
    basename = path.name
    ext = path.suffix.lower()
    stat = path.stat()
    size = stat.st_size

    case, installment, delivery_date = parse_provenance(rel_parts)

    notes = []
    pdf_pages = pdf_chars = pdf_median = pdf_with_text = None
    if ext == ".pdf" and do_pdf and size > 0:
        t0 = time.time()
        pdf_pages, pdf_chars, pdf_median, pdf_with_text = pdf_stats(path)
        elapsed = time.time() - t0
        if elapsed > 30:
            notes.append(f"pdf_stats_slow={elapsed:.1f}s")

    container = classify_container(path, rel_parts, basename, ext, size)
    extract = classify_extract(ext, pdf_pages, pdf_median, pdf_with_text)

    digest = "" if size == 0 else sha256_of(path)

    return {
        "full_path": str(path),
        "rel_path": str(path.relative_to(root)),
        "prr_case": case,
        "installment": "" if installment is None else installment,
        "delivery_date": delivery_date or "",
        "basename": basename,
        "ext": ext,
        "size_bytes": size,
        "sha256": digest,
        "mtime": int(stat.st_mtime),
        "container_class": container,
        "pdf_page_count": "" if pdf_pages is None else pdf_pages,
        "pdf_text_chars_total": "" if pdf_chars is None else pdf_chars,
        "pdf_chars_per_page_median": "" if pdf_median is None else pdf_median,
        "pdf_pages_with_text": "" if pdf_with_text is None else pdf_with_text,
        "extract_class": extract,
        "duplicate_of_sha256": "",
        "notes": ";".join(notes),
    }


def mark_duplicates(rows):
    """Group rows by sha256; for each group of size > 1, mark all but the
    canonical (lexicographically first rel_path) with duplicate_of_sha256."""
    by_hash = {}
    for r in rows:
        h = r["sha256"]
        if not h:
            continue
        by_hash.setdefault(h, []).append(r)
    dup_groups = 0
    dup_files = 0
    for h, group in by_hash.items():
        if len(group) < 2:
            continue
        dup_groups += 1
        group.sort(key=lambda r: r["rel_path"])
        canonical = group[0]
        for r in group[1:]:
            r["duplicate_of_sha256"] = h
            dup_files += 1
        canonical["notes"] = ";".join(
            filter(None, [canonical["notes"], f"canonical_of={len(group)}"])
        )
    logger.info(
        "duplicate groups: %d; redundant copies: %d", dup_groups, dup_files
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True,
                        help="root directory of the transit PRR tree")
    parser.add_argument("--out", default="-",
                        help="output CSV path (default: stdout)")
    parser.add_argument("--no-pdf", action="store_true",
                        help="skip pdfplumber stats (fast smoke test)")
    parser.add_argument("--limit", type=int, default=None,
                        help="stop after N files (for testing)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"--root {root} is not a directory")

    files = list(iter_files(root))
    if args.limit:
        files = files[: args.limit]
    logger.info("walking %d files under %s", len(files), root)

    rows = []
    t0 = time.time()
    for i, path in enumerate(files, 1):
        try:
            rows.append(build_row(root, path, do_pdf=not args.no_pdf))
        except Exception as e:
            logger.exception("failed on %s: %s", path, e)
            rows.append({
                **{f: "" for f in FIELDS},
                "full_path": str(path),
                "rel_path": str(path.relative_to(root)),
                "basename": path.name,
                "ext": path.suffix.lower(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
                "container_class": "ERROR",
                "extract_class": "error",
                "notes": f"build_row_error={e!r}",
            })
        if i % 25 == 0:
            elapsed = time.time() - t0
            logger.info("processed %d/%d files (%.1fs elapsed)",
                        i, len(files), elapsed)

    mark_duplicates(rows)

    out = sys.stdout if args.out == "-" else open(args.out, "w", newline="")
    try:
        writer = csv.DictWriter(out, fieldnames=FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    finally:
        if out is not sys.stdout:
            out.close()

    logger.info("wrote %d rows in %.1fs", len(rows), time.time() - t0)


if __name__ == "__main__":
    main()
