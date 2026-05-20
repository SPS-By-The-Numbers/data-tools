#!python3
"""Split a bundled "Installment N" PDF into per-email chunks.

The bundles are concatenated printouts of Outlook emails (plus calendar
invites and attachments). Each email starts with a header block:

    From: <name/address>
    To:   <recipients>
    Subject: <...>
    Date: <...>
    Attachments: <...>

We detect those header blocks at the top of a page and use them as chunk
boundaries. Calendar invites carry a similar block keyed on Subject/Start/
End/Meeting Status. Pages that pdfplumber can't extract text from are
flagged as IMAGE -- they're either image-only attachments embedded in a
prior email, or (in the case of fully-scanned bundles like Installment 11)
the whole bundle needs OCR before splitting can work reliably.

Output:
  - chunks CSV: one row per detected chunk with (start_page, end_page,
    n_pages, n_image_pages, classification, header fields).
  - optional per-chunk PDFs via qpdf (--write-chunks).

Usage:
    python3 -m extractors.prr.transit.split_bundle \\
        --bundle 'data/transit/.../Installment 7.pdf' \\
        --out-csv data/transit/chunks/Installment_7.chunks.csv \\
        [--write-chunks data/transit/chunks/Installment_7/]
"""

import argparse
import csv
import logging
import re
import subprocess
import sys
import time
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


# Header detection: look at first non-empty lines of a page. We require
# "From:" to be one of the very first lines (so we don't trip on inline
# forwarded quotes deeper in a body). A boundary is confirmed when one of
# To:/Sent:/Subject:/Cc: also appears within the next few lines.
RE_FROM = re.compile(r"^\s*From:\s*(.+?)\s*$")
RE_TO = re.compile(r"^\s*To:\s*(.+?)\s*$")
RE_SENT = re.compile(r"^\s*Sent:\s*(.+?)\s*$")
RE_CC = re.compile(r"^\s*Cc:\s*(.+?)\s*$")
RE_SUBJECT = re.compile(r"^\s*Subject:\s*(.+?)\s*$")
RE_DATE = re.compile(r"^\s*Date:\s*(.+?)\s*$")
RE_ATTACHMENTS = re.compile(r"^\s*Attachments:\s*(.+?)\s*$")
RE_START = re.compile(r"^\s*Start:\s*(.+?)\s*$")
RE_END = re.compile(r"^\s*End:\s*(.+?)\s*$")
RE_MEETING_STATUS = re.compile(r"^\s*Meeting Status:\s*(.+?)\s*$")
RE_SHOW_TIME = re.compile(r"^\s*Show Time As:\s*(.+?)\s*$")
RE_RECURRENCE = re.compile(r"^\s*Recurrence:\s*(.+?)\s*$")
RE_ORGANIZER = re.compile(r"^\s*Organizer:\s*(.+?)\s*$")

# Header field collection (joined across continuation lines).
HEADER_FIELDS = ["from", "to", "sent", "cc", "subject", "date", "attachments"]
CAL_FIELDS = ["subject", "start", "end", "show_time", "recurrence",
              "meeting_status", "organizer"]

# Minimum chars/page to consider a page text-extractable (anything below
# this we treat as IMAGE and flag for OCR).
IMAGE_THRESHOLD = 20


def first_non_empty_lines(text, k):
    """Return up to k leading non-empty stripped lines."""
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        out.append(s)
        if len(out) >= k:
            break
    return out


def detect_email_header(text):
    """If the page text looks like the top of a printed Outlook email,
    return a dict of parsed header fields. Otherwise return None.

    We require: a "From:" line within the first 3 non-empty lines, AND at
    least one of To:/Sent:/Subject:/Cc: in the first 8 non-empty lines.
    """
    lines = first_non_empty_lines(text, 12)
    if not lines:
        return None

    from_idx = None
    for i, line in enumerate(lines[:3]):
        if RE_FROM.match(line):
            from_idx = i
            break
    if from_idx is None:
        return None

    # Confirm with a second header line nearby.
    confirmed = False
    fields = {f: None for f in HEADER_FIELDS}
    fields["from"] = RE_FROM.match(lines[from_idx]).group(1)
    for i in range(from_idx + 1, min(len(lines), from_idx + 8)):
        ln = lines[i]
        for name, rx in [
            ("to", RE_TO), ("sent", RE_SENT), ("cc", RE_CC),
            ("subject", RE_SUBJECT), ("date", RE_DATE),
            ("attachments", RE_ATTACHMENTS),
        ]:
            m = rx.match(ln)
            if m:
                if name in ("to", "sent", "cc", "subject"):
                    confirmed = True
                if fields[name] is None:
                    fields[name] = m.group(1)
                break
    if not confirmed:
        return None
    return fields


def detect_calendar_header(text):
    """Outlook calendar-invite printouts have a different block (no From/To
    line at top, but Subject/Start/End/etc.). Detected separately."""
    lines = first_non_empty_lines(text, 12)
    if not lines:
        return None
    has_subject = any(RE_SUBJECT.match(l) for l in lines[:3])
    has_cal_marker = any(
        RE_START.match(l) or RE_END.match(l) or RE_MEETING_STATUS.match(l)
        or RE_SHOW_TIME.match(l)
        for l in lines[:8]
    )
    if not (has_subject and has_cal_marker):
        return None
    fields = {f: None for f in CAL_FIELDS}
    for ln in lines:
        for name, rx in [
            ("subject", RE_SUBJECT), ("start", RE_START), ("end", RE_END),
            ("show_time", RE_SHOW_TIME), ("recurrence", RE_RECURRENCE),
            ("meeting_status", RE_MEETING_STATUS),
            ("organizer", RE_ORGANIZER),
        ]:
            m = rx.match(ln)
            if m and fields[name] is None:
                fields[name] = m.group(1)
    return fields


def classify_pages(pdf, ocr_dir=None):
    """For each page, return (text, kind, header_dict_or_none).

    kind ∈ {EMAIL_HEADER, CAL_HEADER, TEXT, IMAGE, OCR_TEXT}.

    If ocr_dir is provided, pages where pdfplumber returns < threshold
    chars fall back to <ocr_dir>/page_NNNN.txt. The resulting page is
    classified normally and labeled OCR_TEXT (not IMAGE) if it now has
    extractable text.
    """
    rows = []
    for page in pdf.pages:
        try:
            text = page.extract_text() or ""
        except Exception as e:
            logger.warning("page %d extract_text failed: %s",
                           page.page_number, e)
            text = ""
        source = "pdf"
        if len(text) < IMAGE_THRESHOLD and ocr_dir is not None:
            sidecar = ocr_dir / f"page_{page.page_number:04d}.txt"
            if sidecar.exists():
                ocr_text = sidecar.read_text(encoding="utf-8", errors="replace")
                if len(ocr_text) >= IMAGE_THRESHOLD:
                    text = ocr_text
                    source = "ocr"
        if len(text) < IMAGE_THRESHOLD:
            rows.append((text, "IMAGE", None))
            continue
        h = detect_email_header(text)
        if h:
            rows.append(
                (text, "EMAIL_HEADER" if source == "pdf" else "EMAIL_HEADER",
                 h))
            continue
        c = detect_calendar_header(text)
        if c:
            rows.append((text, "CAL_HEADER", c))
            continue
        rows.append((text, "OCR_TEXT" if source == "ocr" else "TEXT", None))
    return rows


def assemble_chunks(page_rows):
    """Walk classified pages and emit chunks. A new chunk starts on every
    EMAIL_HEADER or CAL_HEADER page. IMAGE pages don't start chunks (they
    flow into whatever chunk they sit inside).

    If the bundle starts with non-header pages (e.g. Installment 7's first
    25 image-only pages), they form an initial PROLOGUE chunk.
    """
    chunks = []
    current = None
    for idx, (text, kind, header) in enumerate(page_rows):
        page_num = idx + 1  # 1-based
        is_image = kind == "IMAGE"
        is_ocr = kind == "OCR_TEXT"
        if kind in ("EMAIL_HEADER", "CAL_HEADER"):
            if current is not None:
                chunks.append(current)
            classification = "email" if kind == "EMAIL_HEADER" else "calendar"
            current = {
                "classification": classification,
                "start_page": page_num,
                "end_page": page_num,
                "n_pages": 1,
                "n_image_pages": 0,
                "n_ocr_pages": 0,
                "header": header,
            }
        else:
            if current is None:
                current = {
                    "classification": ("scanned_prologue" if is_image
                                       else "prologue"),
                    "start_page": page_num,
                    "end_page": page_num,
                    "n_pages": 1,
                    "n_image_pages": 1 if is_image else 0,
                    "n_ocr_pages": 1 if is_ocr else 0,
                    "header": None,
                }
            else:
                current["end_page"] = page_num
                current["n_pages"] += 1
                if is_image:
                    current["n_image_pages"] += 1
                elif is_ocr:
                    current["n_ocr_pages"] += 1
    if current is not None:
        chunks.append(current)
    return chunks


def write_chunks_csv(out_path, bundle_path, chunks):
    fields = [
        "bundle", "chunk_idx", "start_page", "end_page", "n_pages",
        "n_image_pages", "n_ocr_pages", "classification",
        "header_from", "header_to", "header_sent", "header_cc",
        "header_subject", "header_date", "header_attachments",
        "cal_start", "cal_end", "cal_meeting_status", "cal_organizer",
    ]
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, c in enumerate(chunks):
            h = c.get("header") or {}
            row = {
                "bundle": bundle_path.name,
                "chunk_idx": i,
                "start_page": c["start_page"],
                "end_page": c["end_page"],
                "n_pages": c["n_pages"],
                "n_image_pages": c["n_image_pages"],
                "n_ocr_pages": c.get("n_ocr_pages", 0),
                "classification": c["classification"],
                "header_from": h.get("from") or "",
                "header_to": h.get("to") or "",
                "header_sent": h.get("sent") or "",
                "header_cc": h.get("cc") or "",
                "header_subject": h.get("subject") or "",
                "header_date": h.get("date") or "",
                "header_attachments": h.get("attachments") or "",
                "cal_start": h.get("start") or "",
                "cal_end": h.get("end") or "",
                "cal_meeting_status": h.get("meeting_status") or "",
                "cal_organizer": h.get("organizer") or "",
            }
            w.writerow(row)


def write_chunk_pdfs(out_dir, bundle_path, chunks):
    """Use qpdf to extract page ranges into per-chunk PDFs."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(chunks):
        name = f"chunk_{i:04d}_p{c['start_page']:04d}-p{c['end_page']:04d}.pdf"
        out_path = out_dir / name
        cmd = [
            "qpdf", str(bundle_path),
            "--pages", str(bundle_path),
            f"{c['start_page']}-{c['end_page']}", "--",
            str(out_path),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error("qpdf failed on chunk %d (p%d-%d): %s",
                         i, c["start_page"], c["end_page"],
                         e.stderr.decode("utf-8", "replace"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True,
                        help="path to a bundled installment PDF")
    parser.add_argument("--out-csv", required=True,
                        help="output chunks CSV")
    parser.add_argument("--write-chunks",
                        help="if set, write per-chunk PDFs to this dir "
                        "(uses qpdf)")
    parser.add_argument("--ocr-dir",
                        help="directory of per-page OCR sidecars "
                        "(page_NNNN.txt). Used as fallback for pages "
                        "where pdfplumber returns no text.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    bundle = Path(args.bundle)
    if not bundle.is_file():
        sys.exit(f"--bundle {bundle} does not exist")

    ocr_dir = Path(args.ocr_dir) if args.ocr_dir else None
    if ocr_dir and not ocr_dir.is_dir():
        sys.exit(f"--ocr-dir {ocr_dir} is not a directory")

    t0 = time.time()
    with pdfplumber.open(str(bundle)) as pdf:
        logger.info("opened %s: %d pages%s",
                    bundle.name, len(pdf.pages),
                    f" (OCR fallback from {ocr_dir})" if ocr_dir else "")
        page_rows = classify_pages(pdf, ocr_dir=ocr_dir)
    chunks = assemble_chunks(page_rows)

    # Summary stats
    n_pages = len(page_rows)
    n_image = sum(1 for _, k, _ in page_rows if k == "IMAGE")
    n_ocr = sum(1 for _, k, _ in page_rows if k == "OCR_TEXT")
    by_class = {}
    for c in chunks:
        by_class[c["classification"]] = by_class.get(c["classification"], 0) + 1
    logger.info(
        "%d pages (%d image, %d ocr), %d chunks: %s",
        n_pages, n_image, n_ocr, len(chunks),
        ", ".join(f"{k}={v}" for k, v in sorted(by_class.items())),
    )

    out_csv = Path(args.out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    write_chunks_csv(out_csv, bundle, chunks)
    logger.info("wrote %s", out_csv)

    if args.write_chunks:
        out_dir = Path(args.write_chunks)
        write_chunk_pdfs(out_dir, bundle, chunks)
        logger.info("wrote %d chunk PDFs to %s", len(chunks), out_dir)

    logger.info("done in %.1fs", time.time() - t0)


if __name__ == "__main__":
    main()
