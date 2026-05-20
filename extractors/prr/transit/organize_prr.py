#!python3
"""Organize the transit PRR tree into prr_transportation/ by topic.

Reads:
  - data/transit/manifest.csv (one row per file in the source tree)
  - prr_transportation/_all_emails.csv (unified email index, with bodies)
  - data/transit/chunks/*.chunks.csv (bundle chunks)

Writes:
  - prr_transportation/<NN_topic>/<YYYY-MM-DD_HHMM_from_subject>.{pdf,eml,msg}
    Each entry is a symlink (default) or hard copy back to the source file.
  - prr_transportation/<NN_topic>/README.md  — topic explanation + callouts.
  - prr_transportation/README.md             — top-level index.

Topic assignment uses keyword rules in priority order. The first matching
rule wins. The taxonomy is hand-tuned around the user's stated research
questions about the RFP102112 → RFP022242 cancellation and Hunter
(Michael) Maltais's involvement.
"""

import argparse
import csv
import email
import email.policy
import logging
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pdfplumber

from .split_bundle import detect_email_header

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Portable-mode converters: turn .eml/.msg into universally-readable .txt
# files (with optional sibling attachment directories). Everything else
# (PDFs, docx, xlsx, zip) is copied verbatim because those are already
# universally readable.
# ----------------------------------------------------------------------

def _safe_attachment_name(name, fallback):
    if not name:
        return fallback
    name = re.sub(r"[\\/:\"*?<>|\r\n\t]+", "_", str(name))
    name = name.strip("._ ") or fallback
    return name[:120]


def convert_eml_to_txt(src_path, dest_txt_path, attach_dir=None):
    """Parse an .eml file and write a plain-text rendering plus
    attachments. Returns the list of attachment filenames written."""
    with open(src_path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=email.policy.default)

    # Pick a body: prefer text/plain, fall back to a stripped text/html.
    body_text = ""
    body_html = ""
    attachments_info = []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                try:
                    payload = part.get_payload(decode=True) or b""
                    fname = _safe_attachment_name(
                        part.get_filename(),
                        f"attachment_{len(attachments_info)+1}",
                    )
                    attachments_info.append((fname, payload, ct))
                except Exception as e:
                    logger.warning("eml attachment skip in %s: %s", src_path, e)
                continue
            if ct == "text/plain" and not body_text:
                try:
                    body_text = part.get_content()
                except Exception:
                    pass
            elif ct == "text/html" and not body_html:
                try:
                    body_html = part.get_content()
                except Exception:
                    pass
    else:
        ct = msg.get_content_type()
        if ct.startswith("text/"):
            try:
                body_text = msg.get_content()
            except Exception:
                pass

    if not body_text and body_html:
        # Quick-and-dirty HTML strip: replace <br>/<p>/<div> with newline
        # then drop the remaining tags.
        h = re.sub(r"(?i)<br\s*/?>", "\n", body_html)
        h = re.sub(r"(?i)</(p|div|tr|h[1-6])>", "\n", h)
        h = re.sub(r"<[^>]+>", "", h)
        body_text = h

    # Write the .txt.
    lines = []
    lines.append(f"Date:    {msg.get('Date', '')}")
    lines.append(f"From:    {msg.get('From', '')}")
    lines.append(f"To:      {msg.get('To', '')}")
    if msg.get("Cc"):
        lines.append(f"Cc:      {msg.get('Cc')}")
    if msg.get("Bcc"):
        lines.append(f"Bcc:     {msg.get('Bcc')}")
    lines.append(f"Subject: {msg.get('Subject', '')}")
    if msg.get("Message-ID"):
        lines.append(f"Message-ID: {msg.get('Message-ID')}")
    if msg.get("In-Reply-To"):
        lines.append(f"In-Reply-To: {msg.get('In-Reply-To')}")
    if attachments_info:
        names = ", ".join(a[0] for a in attachments_info)
        lines.append(f"Attachments ({len(attachments_info)}): {names}")
    lines.append("")
    lines.append("-" * 72)
    lines.append("")
    lines.append(body_text or "(no body)")

    dest_txt_path.parent.mkdir(parents=True, exist_ok=True)
    dest_txt_path.write_text("\n".join(lines), encoding="utf-8")

    # Write attachments.
    written_names = []
    if attachments_info:
        if attach_dir is None:
            attach_dir = dest_txt_path.with_suffix("").with_name(
                dest_txt_path.stem + "__attachments")
        attach_dir.mkdir(parents=True, exist_ok=True)
        for fname, payload, _ct in attachments_info:
            target = attach_dir / fname
            # Avoid collisions
            i = 2
            while target.exists():
                stem, dot, ext = fname.rpartition(".")
                target = attach_dir / (
                    f"{stem}_{i}.{ext}" if dot else f"{fname}_{i}")
                i += 1
            target.write_bytes(payload)
            written_names.append(target.name)
    return written_names


def convert_msg_to_txt(src_path, dest_txt_path, attach_dir=None):
    """Parse a .msg file via extract_msg and write a plain-text rendering
    plus attachments."""
    import extract_msg
    m = extract_msg.Message(str(src_path))

    body_text = m.body or ""
    if not body_text and getattr(m, "htmlBody", None):
        h = m.htmlBody
        if isinstance(h, bytes):
            try:
                h = h.decode("utf-8", errors="replace")
            except Exception:
                h = h.decode("latin-1", errors="replace")
        h = re.sub(r"(?i)<br\s*/?>", "\n", h)
        h = re.sub(r"(?i)</(p|div|tr|h[1-6])>", "\n", h)
        h = re.sub(r"<[^>]+>", "", h)
        body_text = h

    lines = []
    lines.append(f"Date:    {m.date.isoformat() if m.date else ''}")
    lines.append(f"From:    {m.sender or ''}")
    lines.append(f"To:      {m.to or ''}")
    if m.cc:
        lines.append(f"Cc:      {m.cc}")
    lines.append(f"Subject: {m.subject or ''}")
    if m.messageId:
        lines.append(f"Message-ID: {m.messageId}")
    if m.inReplyTo:
        lines.append(f"In-Reply-To: {m.inReplyTo}")
    if m.attachments:
        names = ", ".join(
            _safe_attachment_name(
                getattr(a, "longFilename", None) or getattr(a, "shortFilename", None),
                f"attachment_{i+1}")
            for i, a in enumerate(m.attachments)
        )
        lines.append(f"Attachments ({len(m.attachments)}): {names}")
    lines.append("")
    lines.append("-" * 72)
    lines.append("")
    lines.append(body_text or "(no body)")

    dest_txt_path.parent.mkdir(parents=True, exist_ok=True)
    dest_txt_path.write_text("\n".join(lines), encoding="utf-8")

    written_names = []
    if m.attachments:
        if attach_dir is None:
            attach_dir = dest_txt_path.with_suffix("").with_name(
                dest_txt_path.stem + "__attachments")
        attach_dir.mkdir(parents=True, exist_ok=True)
        for i, a in enumerate(m.attachments):
            fname = _safe_attachment_name(
                getattr(a, "longFilename", None) or getattr(a, "shortFilename", None),
                f"attachment_{i+1}")
            try:
                payload = a.data
            except Exception as e:
                logger.warning("msg attachment extract failed %s: %s",
                               src_path, e)
                continue
            if payload is None:
                continue
            target = attach_dir / fname
            j = 2
            while target.exists():
                stem, dot, ext = fname.rpartition(".")
                target = attach_dir / (
                    f"{stem}_{j}.{ext}" if dot else f"{fname}_{j}")
                j += 1
            if isinstance(payload, bytes):
                target.write_bytes(payload)
            else:
                target.write_bytes(bytes(payload))
            written_names.append(target.name)
    return written_names


def probe_pdf_header(pdf_path):
    """Open the first 2 pages of a PDF and try to parse an email header.

    Returns a dict with keys {from, to, subject, body} where body is the
    extracted first-2-pages text (used as the body for topic matching even
    when no header is found). Returns None if pdfplumber can't open it or
    no text was extractable.
    """
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            if not pdf.pages:
                return None
            text_parts = []
            for page in pdf.pages[:2]:
                try:
                    text_parts.append(page.extract_text() or "")
                except Exception:
                    pass
            text = "\n".join(text_parts)
    except Exception as e:
        logger.warning("pdf probe failed %s: %s", pdf_path, e)
        return None
    if len(text) < 20:
        return None
    hdr = detect_email_header(text) or {}
    return {
        "from": hdr.get("from", "") or "",
        "to": hdr.get("to", "") or "",
        "subject": hdr.get("subject", "") or "",
        "body": text,
    }

csv.field_size_limit(1 << 28)


# ----------------------------------------------------------------------
# Topic taxonomy. Each topic has a priority (lower = checked first), a
# slug used for the directory name, and match rules that operate on a
# search "haystack" (subject + from + to + body) plus path-based rules.
# ----------------------------------------------------------------------

class Topic:
    def __init__(self, slug, title, body_regexes=None, path_regexes=None,
                 subject_regexes=None, description=""):
        self.slug = slug
        self.title = title
        self.body_regexes = [re.compile(p, re.IGNORECASE)
                             for p in (body_regexes or [])]
        self.path_regexes = [re.compile(p, re.IGNORECASE)
                             for p in (path_regexes or [])]
        self.subject_regexes = [re.compile(p, re.IGNORECASE)
                                for p in (subject_regexes or [])]
        self.description = description

    def matches_email(self, rec):
        sub = rec.get("subject", "") or ""
        for rx in self.subject_regexes:
            if rx.search(sub):
                return True
        haystack = " ".join([
            rec.get("subject", "") or "",
            rec.get("from", "") or "",
            rec.get("to", "") or "",
            rec.get("body", "") or "",
        ])
        for rx in self.body_regexes:
            if rx.search(haystack):
                return True
        return False

    def matches_path(self, path_str):
        for rx in self.path_regexes:
            if rx.search(path_str):
                return True
        return False


TOPICS = [
    Topic(
        "01_rfp_cancellation_and_reissue",
        "RFP cancellation (RFP102112) and reissue (RFP022242)",
        subject_regexes=[
            r"\bRFP0?22242\b",
            r"\bnew transportation project\b",
            r"\b(cancel|withdraw|rescind|reissue|re-?issue)\b.*\b(RFP|transportation|102112)\b",
            r"\bcanceled?:.*RFP102112\b",
            r"\bnew RFP\b",
            r"\b022242\b",
        ],
        body_regexes=[
            r"\bRFP0?22242\b",
            r"\bcancel(?:lation)?\b.*\bRFP\s*0?102112\b",
            r"\b(reissue|re-?issue|re-?bid)\b.*\b(transportation|RFP)\b",
        ],
        description=(
            "Emails and documents tracing the cancellation of RFP102112 "
            "(the original transportation services RFP, Oct 2021 - Feb 2022) "
            "and its re-issue as RFP022242 (Feb-Apr 2022). Includes the "
            "DJC legal-advertisement invoice that formally re-advertised "
            "the new RFP."
        ),
    ),
    Topic(
        "02_attorney_client_priv",
        "Attorney-client-privileged emails (A/C PRIV)",
        subject_regexes=[r"\bA[/-]C\s+PRIV\b"],
        description=(
            "Emails explicitly marked attorney-client-privileged. The Feb "
            "1, 2022 'Transportation bids - status?' A/C PRIV thread "
            "between Enlow, Maltais, and Kongsaeng is the densest cluster "
            "of internal decision-making correspondence in this PRR drop."
        ),
    ),
    Topic(
        "03_zum_protest_and_legal_response",
        "Zum bid protest and SPS/legal response",
        subject_regexes=[
            r"\bprotest\b.*\bZ[uū]m\b",
            r"\bZ[uū]m\b.*\bprotest\b",
        ],
        body_regexes=[
            r"\bO'?Melveny\b|\bomm\.com\b",
            r"\bpacificalawgroup\b",
            r"\bprotest letter\b",
        ],
        description=(
            "Zūm Services, Inc.'s formal bid-protest letter (Feb 17-18, "
            "2022), supporting documentation from O'Melveny & Myers (their "
            "outside counsel), and SPS's internal response coordination "
            "(involving Pacifica Law Group / John Parnass). This protest "
            "immediately preceded the RFP cancellation."
        ),
    ),
    Topic(
        "04_maltais_personnel_and_role",
        "Hunter (Michael) Maltais — role, evaluations, departure",
        subject_regexes=[
            r"\b(Maltais|Hunter)\b.*(transition|resignation|departure|"
            r"last day|leaving|farewell|position|role|review|sign[- ]off)",
            r"\b(transition|resignation|departure|last day|leaving|farewell)"
            r"\b.*\b(Maltais|Hunter)\b",
        ],
        path_regexes=[
            r"Evaluation Team Sign-off_(Hunter|Maltais)",
            r"PRO_CON Form_hm",
            r"_hm\b",
            r"_HM\b",
            r"Maltais",
        ],
        description=(
            "Hunter (legal name Michael H.) Maltais was SPS's transportation "
            "director and a key evaluator on the RFP102112 panel. He "
            "advocated against First Student's continued performance. "
            "This directory holds artifacts naming him directly: his "
            "evaluation team sign-off, his pro/con form, his scoring "
            "sheets, and any emails about his role, evaluations, or "
            "departure from SPS. **General correspondence he was on but "
            "that isn't about him** lives in the other topical folders."
        ),
    ),
    Topic(
        "05_scoring_pricing_evaluation",
        "Scoring, pricing comparisons, and evaluation",
        subject_regexes=[
            r"\bpricing\b", r"\bprice comparison\b", r"\bscoring\b",
            r"\bpro[/_ ]?con\b", r"\bevaluation\b", r"\bbest[- ]and[- ]final\b",
        ],
        body_regexes=[
            r"\bFinal Evaluation Points\b",
            r"\bPreliminary Scores?\b",
            r"\bTwo-?Tier Pricing\b", r"\bThree-?Tier Pricing\b",
            r"\bPrice Comparison\b",
            r"\bevaluation team sign\b",
        ],
        path_regexes=[
            r"/Scoring/", r"/Updated pricing/", r"/Updated Pricing/",
            r"Price Comparison", r"Preliminary Scores", r"Final Scoring",
            r"Pros & Cons", r"PRO_CON", r"/Evaluations/", r"/References/",
            r"Evaluation Team Sign-off", r"Proposal Evaluation",
            r"Project Owner Checklist", r"Reference Check",
        ],
        description=(
            "Score sheets, pricing comparisons between Zum and First "
            "Student, pro/con forms, and the 'best and final offer' "
            "(BAFO) materials. Includes individual reviewer score sheets "
            "and aggregate spreadsheets."
        ),
    ),
    Topic(
        "06_award_decision_and_board_comms",
        "Award decision and board/public communication",
        subject_regexes=[
            r"\baward\b.*\b(RFP|transportation|First Student|Zum)\b",
            r"\bboard\b.*\b(transportation|contract)\b",
            r"\b(recommend(ation)?|selection|select(ed)?)\b.*"
            r"\b(transportation|RFP|First Student|Zum)\b",
        ],
        description=(
            "Award decision, board action items, public communications "
            "about contractor selection. Includes any community/journalist "
            "outreach about the RFP outcome."
        ),
    ),
    Topic(
        "07_rfp102112_lifecycle",
        "RFP102112 lifecycle (original RFP, Oct 2021 - Feb 2022)",
        subject_regexes=[
            r"\bRFP\s*0?102112\b",
            r"\baddend(um|a)\b.*\bRFP\b",
        ],
        path_regexes=[
            r"RFP102112_",
            r"/Public Records Request/RFP/",
            r"/Addenda/",
            # Catchall for the 20220520 clean tree -- anything under "Public
            # Records Request/" that didn't match a more specific topic
            # above is part of the original-RFP lifecycle.
            r"/Public Records Request/",
        ],
        description=(
            "Original RFP102112 release (Oct 2021), addenda 1-3 "
            "(Oct-Nov 2021), questions and answers, evaluation sign-offs, "
            "and the initial bid lifecycle through ~Feb 2022 when the "
            "cancellation was decided."
        ),
    ),
    Topic(
        "08_rfp022242_lifecycle",
        "RFP022242 lifecycle (re-issued RFP)",
        subject_regexes=[r"\bRFP\s*0?22242\b"],
        path_regexes=[r"022242"],
        description=(
            "The re-issued RFP022242 (Feb-Apr 2022 onward): question "
            "submissions, document distribution, the new bid timeline."
        ),
    ),
    Topic(
        "09_first_student_submittal",
        "First Student bid submittal and clarifications",
        path_regexes=[
            r"/Submittals/First Student/",
            r"First Student_confidentiality",
            r"FIRST STUDENT/",
            r"First Student/Updated",
        ],
        body_regexes=[
            r"\bFirst Student\b.*\b(proposal|submittal|response|pricing)\b",
        ],
        description=(
            "First Student's full RFP102112 submittal (~186 pages), "
            "confidentiality waivers, and pricing clarification responses."
        ),
    ),
    Topic(
        "10_zum_submittal",
        "Zum bid submittal and clarifications",
        path_regexes=[
            r"/Submittals/Zum/",
            r"Zum_Confidentiality",
            r"ZUM/",
            r"ZUM Response",
        ],
        body_regexes=[
            r"\bZ[uū]m\b.*\b(proposal|submittal|response|pricing)\b",
        ],
        description=(
            "Zum's full RFP102112 submittal (~149 pages), confidentiality "
            "waivers, and pricing clarification responses."
        ),
    ),
    Topic(
        "11_ops_committee_minutes",
        "Board Operations Committee minutes (2122-144)",
        path_regexes=[r"/2122-144/", r"OpsCmte"],
        description=(
            "Seattle Public Schools Board Operations Committee meeting "
            "minutes (2018-2021). Came in via PRR 2122-144 alongside the "
            "main transportation request. Context for what the board "
            "knew/discussed before the RFP102112 selection."
        ),
    ),
    Topic(
        "12_pra_administration",
        "PRR/PRA administration and internal handling",
        subject_regexes=[
            r"\bPRA\b.*\brequest", r"\bpublic records\b",
            r"\brecords request\b",
        ],
        path_regexes=[r"Public Records Request Form", r"Email Notification"],
        description=(
            "Meta-emails about handling the public records requests "
            "themselves: how SPS coordinated responses, redaction process, "
            "request volume tracking."
        ),
    ),
    Topic(
        "13_calendar_invites",
        "Calendar invites",
        description=(
            "Outlook calendar invites collected with the email "
            "correspondence. Several show meetings that were created or "
            "**cancelled** during the RFP timeline (e.g., the Zum "
            "Debrief)."
        ),
    ),
    Topic(
        "14_redaction_logs",
        "Redaction logs (one per installment)",
        path_regexes=[r"Redaction Log"],
        description=(
            "Metadata PDFs that accompany each installment, listing what "
            "was redacted from the released documents and the legal basis "
            "for each redaction (RCW citations). Helpful for understanding "
            "what's missing from the released material."
        ),
    ),
    Topic(
        "98_other_correspondence",
        "Other RFP correspondence",
        description=(
            "Emails and documents that touch the RFP but don't fall "
            "cleanly into the topical buckets above."
        ),
    ),
    Topic(
        "99_unclassified_files",
        "Unclassified source files",
        description="Non-email files that didn't match a topic rule.",
    ),
]

TOPIC_BY_SLUG = {t.slug: t for t in TOPICS}


# ----------------------------------------------------------------------

def safe_filename(s, maxlen=80):
    """Make a string safe for use as a filename component."""
    s = s.strip() if s else ""
    s = re.sub(r"[\\/:\"*?<>|\r\n\t]+", "_", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("._ ")
    return s[:maxlen]


def short_from(s):
    """Pull out a short display form of a 'From' header."""
    if not s:
        return "unknown"
    m = re.search(r"<([^>]+)>", s)
    if m:
        local = m.group(1).split("@", 1)[0]
        return safe_filename(local, 30)
    s = s.split(",", 1)[0].split("<", 1)[0]
    return safe_filename(s, 30)


def topic_for_email(rec):
    """Pick the highest-priority topic for an email record."""
    for t in TOPICS:
        if t.slug in ("98_other_correspondence", "99_unclassified_files"):
            continue
        if t.slug == "13_calendar_invites":
            if rec.get("classification") == "calendar":
                return t.slug
            continue
        if t.matches_email(rec):
            return t.slug
    return "98_other_correspondence"


def topic_for_file(path_str, file_ext):
    """Pick the highest-priority topic for a non-email file (by path)."""
    for t in TOPICS:
        if t.slug in ("98_other_correspondence", "99_unclassified_files",
                       "13_calendar_invites"):
            continue
        if t.matches_path(path_str):
            return t.slug
    return "99_unclassified_files"


# ----------------------------------------------------------------------

def chunk_pdf_path(bundle_slug, chunk_idx, start_page, end_page,
                   chunks_root):
    """Return the materialized chunk PDF path."""
    fname = (f"chunk_{int(chunk_idx):04d}_p{int(start_page):04d}-"
             f"p{int(end_page):04d}.pdf")
    return chunks_root / bundle_slug / fname


def materialize_entry(src_path, dest_dir, dest_name, mode="symlink",
                      repo_root=None):
    """Create dest_dir/dest_name pointing at src_path.

    Modes:
      - symlink: relative symlink (default).
      - copy:    plain file copy.
      - portable: copy + convert .eml/.msg to .txt sidecars with
        extracted attachments. PDFs, docx, xlsx are copied verbatim.

    Returns the actual destination path used (so callers can record the
    filename for READMEs).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / dest_name
    if dest.exists() or dest.is_symlink():
        dest.unlink()

    if mode == "portable":
        ext = Path(dest_name).suffix.lower()
        # Re-name eml/msg destinations to .txt so the file extension
        # matches the actual format on disk.
        if ext == ".eml":
            txt_dest = dest.with_suffix(".txt")
            if txt_dest.exists() or txt_dest.is_symlink():
                txt_dest.unlink()
            try:
                convert_eml_to_txt(src_path, txt_dest)
            except Exception as e:
                logger.warning("eml conversion failed %s: %s — copying raw",
                               src_path, e)
                shutil.copy2(src_path, dest)
                return dest
            return txt_dest
        if ext == ".msg":
            txt_dest = dest.with_suffix(".txt")
            if txt_dest.exists() or txt_dest.is_symlink():
                txt_dest.unlink()
            try:
                convert_msg_to_txt(src_path, txt_dest)
            except Exception as e:
                logger.warning("msg conversion failed %s: %s — copying raw",
                               src_path, e)
                shutil.copy2(src_path, dest)
                return dest
            return txt_dest
        # All other formats: copy as-is (PDFs, docx, xlsx, zip, etc.).
        shutil.copy2(src_path, dest)
        return dest

    if mode == "copy":
        shutil.copy2(src_path, dest)
        return dest

    # Default: relative symlink.
    rel = os.path.relpath(src_path, start=dest_dir)
    os.symlink(rel, dest)
    return dest


def write_topic_readme(topic_dir, topic, entries, callouts):
    """Write README.md for a topic directory."""
    lines = []
    lines.append(f"# {topic.title}\n\n")
    lines.append(topic.description.strip() + "\n\n")

    if callouts:
        lines.append("## Callouts\n\n")
        for c in callouts:
            lines.append(f"- {c}\n")
        lines.append("\n")

    lines.append(f"## Entries ({len(entries)}, chronological)\n\n")
    lines.append("| Date | From | Subject / File | Source |\n")
    lines.append("|------|------|---------------|--------|\n")
    for e in entries:
        date = e.get("date") or "(undated)"
        frm = e.get("from", "") or ""
        sub = e.get("subject_or_title", "") or ""
        src = e.get("source_label", "")
        # Markdown table-safe
        frm = frm.replace("|", "\\|")[:60]
        sub = sub.replace("|", "\\|")[:90]
        lines.append(f"| {date} | {frm} | [{sub}]({e['filename']}) | {src} |\n")

    (topic_dir / "README.md").write_text("".join(lines), encoding="utf-8")


# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/transit/manifest.csv")
    parser.add_argument("--emails", default="prr_transportation/_all_emails.csv")
    parser.add_argument("--chunks-root", default="data/transit/chunks")
    parser.add_argument("--out", default="prr_transportation")
    parser.add_argument(
        "--mode", choices=("symlink", "copy", "portable"),
        default="symlink",
        help="symlink (default): relative symlinks back into data/. "
             "copy: plain file copies. "
             "portable: copy + convert .eml/.msg to readable .txt "
             "sidecars with attachments extracted to a sibling dir. "
             "Use portable when zipping the tree for sharing.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    out_root = Path(args.out)
    chunks_root = Path(args.chunks_root)
    manifest_path = Path(args.manifest)
    emails_path = Path(args.emails)

    # --- load source data ----------------------------------------------
    with open(emails_path) as f:
        emails = list(csv.DictReader(f))
    with open(manifest_path) as f:
        manifest = list(csv.DictReader(f))
    logger.info("loaded %d emails, %d manifest rows", len(emails), len(manifest))

    # Index manifest by full_path so we can look up canonical-vs-duplicate.
    manifest_by_path = {r["full_path"]: r for r in manifest}

    # --- assign topics to emails ---------------------------------------
    topic_entries = defaultdict(list)
    topic_callouts = defaultdict(list)
    counts_by_kind = Counter()
    unique_emails = [e for e in emails if not e["dup_of_id"]]
    logger.info("unique emails after dedupe: %d", len(unique_emails))

    skipped_chunk_missing = 0
    for rec in unique_emails:
        topic = topic_for_email(rec)

        kind = rec["source_kind"]
        counts_by_kind[(topic, kind)] += 1

        # Resolve a source path for symlinking.
        if kind == "bundle":
            bundle_slug = rec["bundle"]
            try:
                src_path = chunk_pdf_path(
                    bundle_slug, rec["chunk_idx"],
                    rec["start_page"], rec["end_page"], chunks_root)
            except Exception:
                src_path = None
            if src_path is None or not src_path.exists():
                skipped_chunk_missing += 1
                continue
            src_path = src_path.resolve()
        else:
            src_path = Path(rec["source_path"]).resolve() if rec["source_path"] else None
            if src_path is None or not src_path.exists():
                continue

        # Build a chronological filename.
        date_iso = rec["date_iso"]
        date_label = date_iso[:16].replace("T", "_").replace(":", "") if date_iso else "0000-00-00_0000"
        frm = short_from(rec.get("from", ""))
        sub = safe_filename(rec.get("subject", "") or rec.get("classification", ""), 70)
        ext = src_path.suffix
        if kind == "bundle":
            suffix_tag = f"__{bundle_slug.replace('2122-501_Installment_', 'inst').replace('Installment_', 'inst')[:18]}_ch{int(rec['chunk_idx']):03d}"
        elif kind == "msg":
            suffix_tag = "__msg"
        else:
            suffix_tag = "__eml"
        filename = f"{date_label}_{frm}_{sub}{suffix_tag}{ext}"
        filename = safe_filename(filename, 200)

        topic_dir = out_root / topic
        actual_dest = materialize_entry(
            src_path, topic_dir, filename, mode=args.mode)
        actual_name = actual_dest.name if actual_dest else filename

        topic_entries[topic].append({
            "date": date_iso[:16].replace("T", " ") if date_iso else "",
            "from": rec.get("from", ""),
            "subject_or_title": rec.get("subject", "") or "(no subject)",
            "filename": actual_name,
            "source_label": (
                f"{kind} {('('+bundle_slug+' chunk '+str(rec['chunk_idx'])+')') if kind == 'bundle' else ''}".strip()
            ),
            "_rec": rec,
        })

    logger.info("skipped %d chunk emails whose chunk PDF wasn't materialized",
                skipped_chunk_missing)

    # --- assign topics to remaining (non-email) files ------------------
    # Use the manifest rows that are ORIGINAL_SOURCE, REDACTION_LOG, or
    # ARCHIVE -- but not the bundle PDFs (those are already handled via
    # chunks) and not NOISE.
    placed_paths = set()
    # Include ALL native eml/msg paths (canonical and duplicate). Dup paths
    # were already represented in the index by their canonical, so don't
    # re-link them through the manifest pass.
    for rec in emails:
        if rec["source_kind"] in ("eml", "msg") and rec["source_path"]:
            placed_paths.add(str(Path(rec["source_path"]).resolve()))

    DOC_PDF_RE = re.compile(r"^DOC\d+", re.IGNORECASE)
    for m in manifest:
        if m["container_class"] in ("NOISE", "EMAIL_DROP_BUNDLED"):
            continue
        if m["duplicate_of_sha256"]:
            continue  # skip redundant copies of files we already include
        if m["full_path"] in placed_paths:
            continue
        ext = m["ext"]
        src = Path(m["full_path"]).resolve()
        if not src.exists():
            continue

        # For DOC0000NNN.pdf files in decomposed drops, peek at the first
        # couple pages to harvest subject/from/body so they route to the
        # right topic (printed emails, letters, scoring sheets all need
        # different handling than a path-based heuristic alone).
        topic = None
        probed_subject = None
        probed_from = None
        if ext == ".pdf" and DOC_PDF_RE.match(m["basename"]):
            hdr = probe_pdf_header(src)
            if hdr:
                fake_rec = {
                    "subject": hdr.get("subject", ""),
                    "from": hdr.get("from", ""),
                    "to": hdr.get("to", ""),
                    "body": hdr.get("body", "")[:8000],
                }
                cand = topic_for_email(fake_rec)
                if cand != "98_other_correspondence":
                    topic = cand
                probed_subject = hdr.get("subject", "")
                probed_from = hdr.get("from", "")
        if topic is None:
            topic = topic_for_file(m["rel_path"], ext)
        date_iso = ""
        try:
            mt = int(m["mtime"]) if m["mtime"] else 0
            if mt:
                date_iso = datetime.fromtimestamp(mt).isoformat()[:16]
        except Exception:
            pass
        date_label = (
            date_iso[:16].replace("T", "_").replace(":", "")
            if date_iso else "0000-00-00_0000"
        )
        basename = safe_filename(m["basename"], 120)
        # If we probed a subject from the PDF, embed a short slug in the
        # filename so chronological browsing shows what each doc is.
        sub_slug = ""
        if probed_subject:
            sub_slug = "_" + safe_filename(probed_subject, 60)
        filename = f"{date_label}_FILE_{basename[:-len(ext)]}{sub_slug}{ext}"
        filename = safe_filename(filename, 200)
        topic_dir = out_root / topic
        actual_dest = materialize_entry(
            src, topic_dir, filename, mode=args.mode)
        actual_name = actual_dest.name if actual_dest else filename
        topic_entries[topic].append({
            "date": date_iso.replace("T", " ") if date_iso else "(undated)",
            "from": probed_from or "",
            "subject_or_title": probed_subject or m["basename"],
            "filename": actual_name,
            "source_label": f"file ({m['container_class']})",
            "_rec": {"file": True, "manifest_row": m},
        })

    # --- callouts -------------------------------------------------------
    # Targeted findings to highlight in each topic README.

    callouts = defaultdict(list)
    callouts["01_rfp_cancellation_and_reissue"] = [
        "**The 6-day decision window:** the Zum Debrief meeting was "
        "cancelled at 2022-02-17 21:37 PT ('will reschedule after the "
        "protest process is complete'). Six days later, on 2022-02-24 "
        "11:02 PT, Fallen Kongsaeng told Nancy Milgate: *'I gave this "
        "project a new # RFP022242. I labeled the folder RFP022242 "
        "Student Transportation_NEW so we can tell the difference "
        "between the two. For RFP102112 it wouldn't let me add cancelled "
        "to the folder name.'* — that's the moment the new project "
        "number was assigned. **The written justification for "
        "cancellation appears to have been made between Feb 18 and Feb "
        "24, 2022.** No email in this PRR drop directly states the "
        "rationale; it may be in (a) an attorney-client privileged "
        "exchange that was withheld under RCW 42.56.290 attorney-work-"
        "product exemption (see the redaction logs), or (b) verbal "
        "discussion not memorialized.",
        "**Actual drafting of RFP022242 began Mar 3.** Milgate sent the "
        "first draft package to Podesta/Maltais/Davies on 2022-03-03 "
        "23:49 PT with attachments: Attach 1 Scope of Work (3-3-22 hm), "
        "Attach 3 Pricing for Six-Hour Daily Rate (3-2-22 hm), Attach 7 "
        "Contractor Questionnaire, Attach 8 Sample Contract. Note: 'hm' "
        "suffixes show Maltais was annotating these drafts. **Maltais "
        "was therefore still actively involved through Mar 4, 2022** "
        "('RE: Edits to Scope of Work').",
        "**Formal re-advertisement** by Daily Journal of Commerce: AD# "
        "403750 invoice dated 2022-03-14 ('FW: DJC Invoice and Affidavit "
        "for AD# 403750; BCSB:STUDENT TRANSPORT').",
        "**Who was driving:** Nancy Milgate (Contracting Services "
        "Manager) handled mechanics; Fred Podesta (COO) approved scope; "
        "Maltais (Transportation Manager) edited scope; Mary Cauffman "
        "(Podesta's office) highlighted changes; Randall Enlow (Public "
        "Records Officer / Office of Legal Counsel) handled disclosure "
        "questions but does not appear to have driven the cancel/reissue "
        "decision in any unredacted email here.",
        "**Process drag into July 2022:** Even after re-advertisement, "
        "the new RFP022242 had Q&A and submittal cycles running through "
        "April 2022 ('FW: RFP022242: Student Transportation Services for "
        "2022-2025 and Succeeding Years', 2022-04-20). The Apr 18 "
        "Public Records Request thread shows new external requests still "
        "arriving — see also 12_pra_administration/.",
        "**Compare scope changes:** the Mar 3 RFP022242 attachments are "
        "named with revision dates that diverge from the original Oct "
        "2021 RFP102112 attachments (in 07_rfp102112_lifecycle/). "
        "Diffing them is the most direct way to see what was changed.",
    ]
    callouts["02_attorney_client_priv"] = [
        "**Don't be misled by this folder.** The 2022-02-01 "
        "'Transportation bids - status?' thread is about **public-records "
        "compliance** (whether SPS could legally withhold bid documents "
        "pending award under PRA), not about the RFP cancellation. Karen "
        "Stambaugh (Office of Legal Counsel) explains in the thread that "
        "RCW 39.26.030(2) lets *state* agencies withhold, but *local* "
        "agencies like SPS have no such authority and must release. "
        "Maltais's reply ('We're not releasing these records yet, is "
        "that correct? The intent to award has not been made yet') is "
        "him asking whether they had to release pre-award.",
        "**Implication:** the cancellation/reissue justification is "
        "likely missing from this PRR drop entirely — either because it "
        "was claimed under attorney-work-product exemption (see "
        "14_redaction_logs/ for what was withheld) or because it was "
        "done verbally. Worth filing a follow-up PRR specifically for "
        "any 2022-02-17 through 2022-02-24 emails involving Podesta, "
        "Milgate, Enlow, or general counsel discussing RFP102112 "
        "outcome or cancellation, including those previously withheld.",
    ]
    callouts["03_zum_protest_and_legal_response"] = [
        "**Zum protest letter:** Feb 17, 2022, from Vanessa Guerrero "
        "(O'Melveny & Myers, vguerrero@omm.com).",
        "**Supporting documentation** delivered Feb 17-18 with thread "
        "carrying ~46 hits on protest keywords.",
        "**SPS legal coordination** via Pacifica Law Group (John "
        "Parnass) — see Milgate's 2022-02-18 'FW: Zūm Services, Inc. "
        "Protest Letter Supporting Documentation' to Berge, Podesta, "
        "Maltais, Davies, Narver.",
        "**The Zum Debrief meeting was cancelled** (calendar invite "
        "'Canceled: Zum Debrief - RFP102112'). The debrief is normally a "
        "post-decision conversation with the losing bidder — its "
        "cancellation suggests the original decision was being unwound.",
    ]
    callouts["04_maltais_personnel_and_role"] = [
        "Maltais's name appears in **168 unique records** (out of 386 "
        "total) — he was a central participant. This folder collects "
        "artifacts *about him by name* (sign-offs, evaluations, scoring "
        "sheets). His correspondence-as-participant is distributed "
        "across the topical folders.",
        "**Title:** 'Transportation Manager' (per his email signature, "
        "not 'Director'). Office (206) 252-0943, Cell (206) 794-2148, "
        "email mhmaltais@seattleschools.org. He signs as 'Hunter' but "
        "appears in directories as Michael H. Maltais.",
        "**Last email authored by Maltais in this PRR drop: 2022-03-29 "
        "20:57 PT — 'Transportation RFP022242 Price Comparison.'** Last "
        "email he was on (any direction): 2022-04-01 00:15. Of 16 "
        "RFP-related emails dated *after* 2022-04-01 in this drop, "
        "**only 1** has Maltais on any line. The 'Accepted: "
        "Transportation RFP022242 Review' meeting acceptances on Apr 5 "
        "from Milgate and Johnson — but not Maltais — suggest he had "
        "stopped being invited.",
        "**This is consistent with (but does not prove) the hypothesis "
        "that he was pushed out of the process in early-to-mid April "
        "2022.** Caveats: (a) absence in this PRR drop ≠ absence in "
        "SPS's actual record (the PRR scope may have filtered later "
        "Maltais correspondence); (b) leave, illness, reassignment, and "
        "termination all produce the same email pattern. A follow-up "
        "PRR specifically for personnel actions related to Maltais "
        "between 2022-03-29 and 2022-12-31 would be the most direct "
        "way to confirm.",
        "**Right before he goes quiet, he was leading the price "
        "comparison work for the new RFP** (Mar 29 'Transportation "
        "RFP022242 Price Comparison'). The cancellation/reissue had "
        "already happened by then — so whatever caused his departure "
        "must have arisen *during* RFP022242, not before. If the user's "
        "hypothesis is right, it would have been triggered by the "
        "RFP022242 outcome or by his continued advocacy against First "
        "Student during that round.",
    ]
    callouts["05_scoring_pricing_evaluation"] = [
        "**Preliminary scoring** finished Dec 2021 — see the "
        "'Preliminary Scores' spreadsheets and individual reviewer "
        "score sheets in 'Public Records Request/Scoring/'.",
        "**Best-and-final pricing comparison** in January 2022 led to "
        "Zum winning on points (see Milgate 2022-01-18 'FW: RFP102112: "
        "Student Transportation Services for 2022-2025 - Fi...').",
        "**Maltais owned the pro/con form** ('PRO_CON Form_hm.docx').",
    ]
    callouts["07_rfp102112_lifecycle"] = [
        "RFP102112 was released 10/28/2021. Three addenda followed "
        "(10/29, 11/22, 11/29), with the major three-tier pricing "
        "tables introduced in Addendum 3.",
        "Submittals were received by year-end 2021; scoring through "
        "Jan 2022; the protest landed Feb 17, 2022; the RFP was "
        "cancelled and reissued (see 01_rfp_cancellation_and_reissue/) "
        "rather than awarded.",
    ]
    callouts["09_first_student_submittal"] = [
        "First Student's full submittal is 186 pages and exists in 3 "
        "duplicate copies across the PRR drops (33.7 MB redundant "
        "storage). The canonical copy is symlinked here.",
    ]
    callouts["10_zum_submittal"] = [
        "Zum's full submittal is 149 pages and exists in 3 duplicate "
        "copies (128.8 MB redundant). The canonical copy is symlinked "
        "here.",
    ]

    # --- write per-topic READMEs and the top-level index ---------------
    for topic in TOPICS:
        entries = topic_entries.get(topic.slug, [])
        entries.sort(
            key=lambda e: (e["date"] or "9999-99-99", e["filename"])
        )
        if not entries:
            # Skip directories we never populated.
            continue
        topic_dir = out_root / topic.slug
        topic_dir.mkdir(parents=True, exist_ok=True)
        write_topic_readme(topic_dir, topic, entries, callouts[topic.slug])
        logger.info("topic %-45s %d entries", topic.slug, len(entries))

    # Top-level index
    index_lines = ["# Transit / Transportation PRR — Organized Index\n\n"]
    index_lines.append(
        "This tree is a topical re-organization of the public-records "
        "response files in `data/transit/2122-501 _ Transit RFP/`. "
        "Every entry inside a topic folder is a symlink back to either "
        "the original artifact in `data/transit/...` or to a "
        "materialized per-email chunk PDF in "
        "`data/transit/chunks/<bundle>/`.\n\n"
        "Files within each topic are named `YYYY-MM-DD_HHMM_<from>_"
        "<subject>__<src>.<ext>` so that `ls` sorts chronologically.\n\n"
    )
    index_lines.append(
        "**Source preference for deduplicated copies:** native `.eml` > "
        "native `.msg` > bundle chunk. The unified index "
        "(`_all_emails.csv`) has the full dedupe map.\n\n"
    )
    index_lines.append("## Research questions this layout targets\n\n")
    index_lines.append(
        "- **Why was RFP102112 cancelled and reissued?** See "
        "`01_rfp_cancellation_and_reissue/` and "
        "`02_attorney_client_priv/` (the A/C PRIV thread on 2022-02-01 "
        "is the highest-density internal decision-making cluster).\n"
        "- **Who was driving the cancellation?** Reference the From/To "
        "fields in the 01/02/03 folder READMEs.\n"
        "- **Why did the process drag into July?** See the post-March "
        "2022 entries in `01_rfp_cancellation_and_reissue/` and "
        "`08_rfp022242_lifecycle/`.\n"
        "- **Hunter (Michael) Maltais's role and departure:** "
        "`04_maltais_personnel_and_role/`. General correspondence he "
        "was on but isn't about him lives in the topical folders by "
        "subject.\n\n"
    )
    index_lines.append("## Folders\n\n")
    for topic in TOPICS:
        n = len(topic_entries.get(topic.slug, []))
        if n == 0:
            continue
        index_lines.append(f"- **[{topic.slug}/]({topic.slug}/)** "
                           f"— {topic.title}  ({n} entries)\n")
    index_lines.append("\n")
    index_lines.append(
        "## Generated from\n\n"
        "- `data/transit/manifest.csv` — file inventory.\n"
        "- `prr_transportation/_all_emails.csv` — unified email index "
        "(eml + msg + bundle chunks, with dedupe).\n"
        "- `data/transit/chunks/*.chunks.csv` — per-bundle chunk splits.\n"
        "- `data/transit/ocr/Installment_{5,6,7,9,11}/page_NNNN.txt` — "
        "Tesseract OCR sidecars for image pages.\n\n"
        "Regenerate with:\n\n"
        "```bash\n"
        "python3 -m extractors.prr.transit.organize_prr\n"
        "```\n"
    )
    (out_root / "README.md").write_text("".join(index_lines),
                                        encoding="utf-8")
    logger.info("wrote top-level %s/README.md", out_root)

    # Final summary
    total = sum(len(v) for v in topic_entries.values())
    logger.info("organized %d artifacts into %d topics",
                total, sum(1 for v in topic_entries.values() if v))


if __name__ == "__main__":
    main()
