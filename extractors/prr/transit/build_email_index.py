#!python3
"""Build a unified index of every email-like artifact in the transit PRR tree.

Pulls together:
  - native .eml files (RFC822, parsed via stdlib email module)
  - native .msg files (Outlook, parsed via extract_msg)
  - bundle chunks from the .chunks.csv files (printed-Outlook PDFs that
    were split by split_bundle.py)

For each record we capture: source_kind, source_path (or bundle + page
range), from, to, cc, subject, normalized_subject (RE:/FW: stripped),
date (best-effort parsed via dateutil), message_id, in_reply_to,
references, attachments_summary, body_text (where available).

Then we dedupe across (normalized_from, normalized_subject, date_minute),
preferring native > bundle (and within natives, preferring the canonical
sha256 copy over duplicates).

Output: prr_transportation/_all_emails.csv
"""

import argparse
import csv
import email
import email.policy
import glob
import logging
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime, getaddresses
from pathlib import Path

import dateutil.parser
import extract_msg

logger = logging.getLogger(__name__)

# Limit CSV cell sizes so a misbehaving body doesn't blow up the file.
csv.field_size_limit(1 << 28)


SUBJECT_PREFIX_RE = re.compile(
    r"^(?:\s*(?:RE|FW|FWD|R|Re|Fw|Fwd|Antwort|AW|TR|VS|Sv|VL|VB)\s*[:\[]\s*\[?[^\]]*\]?\s*)+",
    re.IGNORECASE,
)


def normalize_subject(s):
    """Strip leading RE:/FW:/FWD: chains. Returns lower-cased, whitespace-
    collapsed, no leading prefixes."""
    if not s:
        return ""
    out = s
    for _ in range(8):
        stripped = SUBJECT_PREFIX_RE.sub("", out).strip()
        if stripped == out:
            break
        out = stripped
    return re.sub(r"\s+", " ", out).strip().lower()


def normalize_address(s):
    """Take 'Doe, Jane <jdoe@x.com>' -> 'jdoe@x.com' (lowercased) for
    matching. If no @ present, return the lowercased displayed name."""
    if not s:
        return ""
    addrs = getaddresses([s])
    if addrs:
        name, addr = addrs[0]
        if addr:
            return addr.lower().strip()
        if name:
            return re.sub(r"\s+", " ", name).strip().lower()
    return re.sub(r"\s+", " ", s).strip().lower()


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    # First try RFC822 (eml headers)
    try:
        d = parsedate_to_datetime(s)
        if d is not None:
            return d
    except (TypeError, ValueError):
        pass
    # Fallback: dateutil (handles printed-Outlook formats)
    try:
        return dateutil.parser.parse(s, fuzzy=True)
    except (ValueError, OverflowError, dateutil.parser.ParserError):
        return None


def parse_eml(path):
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=email.policy.default)
    body = ""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                if ct == "text/plain":
                    try:
                        body = part.get_content()
                        break
                    except Exception:
                        pass
            if not body:
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        try:
                            body = part.get_content()
                        except Exception:
                            pass
                        break
        else:
            body = msg.get_content() if msg.get_content_type().startswith("text/") else ""
    except Exception as e:
        logger.warning("body extraction failed on %s: %s", path, e)
    return {
        "from": msg.get("From", ""),
        "to": msg.get("To", ""),
        "cc": msg.get("Cc", ""),
        "subject": msg.get("Subject", "") or "",
        "date": msg.get("Date", ""),
        "message_id": (msg.get("Message-ID", "") or "").strip(),
        "in_reply_to": (msg.get("In-Reply-To", "") or "").strip(),
        "references": (msg.get("References", "") or "").strip(),
        "body": body or "",
    }


def parse_msg(path):
    m = extract_msg.Message(str(path))
    refs = ""
    try:
        if m.header is not None:
            refs = m.header.get("References") or ""
    except Exception:
        pass
    return {
        "from": m.sender or "",
        "to": m.to or "",
        "cc": m.cc or "",
        "subject": m.subject or "",
        "date": m.date.isoformat() if m.date else "",
        "message_id": (m.messageId or "").strip(),
        "in_reply_to": (m.inReplyTo or "").strip(),
        "references": refs,
        "body": m.body or "",
    }


def chunk_to_record(row, bundle_name):
    """Turn a chunks.csv row into a record matching the eml/msg shape."""
    subject = row.get("header_subject") or row.get("cal_start") or ""
    date_str = row.get("header_sent") or row.get("header_date") or ""
    classification = row.get("classification", "")
    return {
        "from": row.get("header_from", ""),
        "to": row.get("header_to", ""),
        "cc": row.get("header_cc", ""),
        "subject": subject,
        "date": date_str,
        "message_id": "",
        "in_reply_to": "",
        "references": "",
        "body": "",  # body would need pdftotext on the chunk PDF; defer
        "_classification": classification,
        "_bundle": bundle_name,
        "_chunk_idx": int(row.get("chunk_idx", -1)),
        "_start_page": int(row.get("start_page", 0)),
        "_end_page": int(row.get("end_page", 0)),
        "_n_pages": int(row.get("n_pages", 0)),
        "_n_image_pages": int(row.get("n_image_pages", 0)),
        "_n_ocr_pages": int(row.get("n_ocr_pages") or 0),
        "_attachments": row.get("header_attachments", ""),
    }


def build_record(parsed, source_kind, source_path, extra=None):
    d = parse_date(parsed["date"])
    rec = {
        "source_kind": source_kind,
        "source_path": str(source_path) if source_path else "",
        "from": parsed["from"],
        "from_addr": normalize_address(parsed["from"]),
        "to": parsed["to"],
        "cc": parsed["cc"],
        "subject": parsed["subject"],
        "norm_subject": normalize_subject(parsed["subject"]),
        "date_raw": parsed["date"],
        "date_iso": d.isoformat() if d else "",
        "date_sort": d.replace(tzinfo=timezone.utc).timestamp() if (d and d.tzinfo is None) else (d.timestamp() if d else 0),
        "message_id": parsed.get("message_id", ""),
        "in_reply_to": parsed.get("in_reply_to", ""),
        "references": parsed.get("references", ""),
        "attachments": (extra or {}).get("_attachments", parsed.get("attachments", "")) if extra else parsed.get("attachments", ""),
        "bundle": (extra or {}).get("_bundle", ""),
        "chunk_idx": (extra or {}).get("_chunk_idx", ""),
        "start_page": (extra or {}).get("_start_page", ""),
        "end_page": (extra or {}).get("_end_page", ""),
        "n_pages": (extra or {}).get("_n_pages", ""),
        "n_image_pages": (extra or {}).get("_n_image_pages", ""),
        "n_ocr_pages": (extra or {}).get("_n_ocr_pages", ""),
        "classification": (extra or {}).get("_classification", "email"),
        "body": parsed.get("body", "")[:32000],  # cap body size in CSV
    }
    return rec


def dedupe(records):
    """Group records that look like the same email. Within each group,
    prefer source_kind native > bundle. Marks duplicates with `dup_of_id`.

    Match key: (from_addr, norm_subject, date_minute_string). For chunks
    with no parseable date, falls back to (from_addr, norm_subject) and
    matches against any native record with same subject and from.
    """
    # Assign stable IDs
    for i, r in enumerate(records):
        r["id"] = f"E{i:05d}"

    def keymin(r):
        d = r["date_iso"][:16]  # YYYY-MM-DDTHH:MM
        return (r["from_addr"], r["norm_subject"], d)

    by_key = defaultdict(list)
    for r in records:
        if r["date_iso"]:
            by_key[keymin(r)].append(r)

    # Native-source preference
    rank = {"eml": 0, "msg": 0, "bundle": 1}
    n_dup = 0
    for k, group in by_key.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda r: (rank.get(r["source_kind"], 9), r["id"]))
        canonical = group[0]
        for dup in group[1:]:
            dup["dup_of_id"] = canonical["id"]
            n_dup += 1

    # Fuzzy bundle→native pass: chunks without a date_iso try to match by
    # (from_addr, norm_subject) only.
    natives_by_subject_from = defaultdict(list)
    for r in records:
        if r["source_kind"] in ("eml", "msg") and not r.get("dup_of_id"):
            natives_by_subject_from[(r["from_addr"], r["norm_subject"])].append(r)
    for r in records:
        if r.get("dup_of_id"):
            continue
        if r["source_kind"] != "bundle":
            continue
        if r["date_iso"]:
            continue  # already attempted
        natives = natives_by_subject_from.get((r["from_addr"], r["norm_subject"]))
        if natives:
            r["dup_of_id"] = natives[0]["id"]
            n_dup += 1

    return n_dup


FIELDS = [
    "id", "source_kind", "source_path",
    "date_iso", "date_sort", "date_raw",
    "from", "from_addr", "to", "cc",
    "subject", "norm_subject",
    "message_id", "in_reply_to", "references",
    "attachments",
    "bundle", "chunk_idx", "start_page", "end_page",
    "n_pages", "n_image_pages", "n_ocr_pages",
    "classification",
    "dup_of_id",
    "body",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data/transit/2122-501 _ Transit RFP")
    parser.add_argument("--chunks-glob",
                        default="data/transit/chunks/*.chunks.csv")
    parser.add_argument("--ocr-root", default="data/transit/ocr",
                        help="optional: dir of OCR sidecars per bundle. "
                        "Used to backfill chunk body text.")
    parser.add_argument("--out-csv", default="prr_transportation/_all_emails.csv")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    root = Path(args.root)
    records = []

    # 1) Native .eml
    eml_paths = sorted(root.rglob("*.eml"))
    logger.info("parsing %d .eml files", len(eml_paths))
    for p in eml_paths:
        try:
            parsed = parse_eml(p)
            records.append(build_record(parsed, "eml", p))
        except Exception as e:
            logger.warning("eml parse failed %s: %s", p, e)

    # 2) Native .msg
    msg_paths = sorted(root.rglob("*.msg"))
    logger.info("parsing %d .msg files", len(msg_paths))
    for p in msg_paths:
        try:
            parsed = parse_msg(p)
            records.append(build_record(parsed, "msg", p))
        except Exception as e:
            logger.warning("msg parse failed %s: %s", p, e)

    # 3) Bundle chunks (preserve OCR sidecar text for bodies if available)
    ocr_root = Path(args.ocr_root) if args.ocr_root else None
    for csv_path in sorted(glob.glob(args.chunks_glob)):
        bundle_name = Path(csv_path).name.replace(".chunks.csv", "")
        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        logger.info("merging %d chunks from %s", len(rows), bundle_name)

        # Find the OCR sidecar dir whose name best matches this bundle.
        sidecar_dir = None
        if ocr_root and ocr_root.is_dir():
            # Try plain "Installment_N" matching first.
            m = re.search(r"Installment[_ ](\d+)", bundle_name)
            if m:
                cand = ocr_root / f"Installment_{m.group(1)}"
                if cand.is_dir():
                    sidecar_dir = cand

        for row in rows:
            extra = chunk_to_record(row, bundle_name)
            # If we have OCR sidecars, pull body text spanning the chunk's
            # page range so downstream search can find keywords in OCR.
            if sidecar_dir:
                body_parts = []
                for p_num in range(extra["_start_page"], extra["_end_page"] + 1):
                    sc = sidecar_dir / f"page_{p_num:04d}.txt"
                    if sc.exists():
                        body_parts.append(sc.read_text(
                            encoding="utf-8", errors="replace"))
                body = "\n".join(body_parts)
            else:
                body = ""
            parsed = {
                "from": extra.pop("_classification") == "calendar" and "" or row.get("header_from", ""),
                "to": row.get("header_to", ""),
                "cc": row.get("header_cc", ""),
                "subject": row.get("header_subject") or row.get("cal_start") or "",
                "date": row.get("header_sent") or row.get("header_date") or "",
                "message_id": "",
                "in_reply_to": "",
                "references": "",
                "body": body,
            }
            # Restore classification key for build_record
            extra["_classification"] = row.get("classification", "")
            # parsed["from"] above tries to be clever about calendar items;
            # actually just use the raw header_from for everything.
            parsed["from"] = row.get("header_from", "") or row.get(
                "cal_organizer", "")
            records.append(build_record(parsed, "bundle", "", extra=extra))

    logger.info("total records: %d", len(records))
    n_dup = dedupe(records)
    logger.info("duplicate groups marked: %d", n_dup)

    out_path = Path(args.out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in records:
            r.setdefault("dup_of_id", "")
            w.writerow(r)
    logger.info("wrote %d rows to %s", len(records), out_path)


if __name__ == "__main__":
    main()
