"""
e2_merge.py -- Task E2 merge step (extractors/sps_web/PLAN.md, Section 3,
card E2): collect the LLM subagents' batch outputs, validate every row with
the E1 validator plus LLM-specific checks, and merge regex + LLM rows into
the final extracted.jsonl.

Usage (from the repo root)::

    venv/bin/python3 -m extractors.sps_web.e2_merge --batches out_sps_web/contracts/batches --round 1
    venv/bin/python3 -m extractors.sps_web.e2_merge --batches out_sps_web/contracts/batches --round 2

Inputs (read-only):
* ``<batches>/NNN.jsonl``     -- E1's residual batch input (one row per item;
  see extract.py's residual.jsonl for the field set). A batch may have no
  matching ``.out.jsonl`` yet -- that is reported as 100% missing, not an
  error, PROVIDED at least one other batch in the same dir has output. If
  *none* of the batches under ``--batches`` have a ``.out.jsonl`` at all (the
  common round-2 case: rerun/ was just written, the LLM hasn't run yet),
  the whole run is a no-op -- it prints a warning and leaves every output
  file untouched, rather than recording every item as missing.
* ``<batches>/NNN.out.jsonl`` -- an LLM subagent's output for that batch, one
  row per item keyed by ``(meeting_id, item_no, char_start)``, Section 2 row
  schema fields. Lines may be malformed JSON or duplicate keys (last wins).
* ``out_sps_web/contracts/regex_rows.jsonl`` / ``residual.jsonl`` -- E1's
  full output (paths overridable with ``--regex-rows``/``--residual`` so
  tests can point at a scratch corpus).

Outputs (rewritten from scratch every run; ``--out-root`` relocates all of
them, default ``out_sps_web``):
* ``contracts/llm_rows.jsonl``      -- the latest attempt for every item ever
  processed, keyed, tagged ``valid``/``reasons``/``round``/``attempts``
  (``attempts`` counts every round-2+ pass, including ones where the item
  was missing from the output); carried forward so a later round only needs
  to touch the items that still need work.

Idempotent across rounds: before looking at a key's row in the current
batch, ``_already_settled()`` checks ``llm_rows.jsonl``. A key already valid
at a round >= the current one, or recorded at a round *strictly later* than
the current one (valid or not), is left completely alone -- not
re-validated, not added to rerun/manual_review, not overwritten. This makes
it safe to re-run an old round (e.g. ``--round 1`` over ``batches/`` again
after adding new batches) without regressing fixes a later round already
made; only genuinely new keys or keys whose best stored attempt is invalid
get re-evaluated. Skipped counts show up in the per-batch report.
* ``contracts/rerun/NNN.jsonl``     -- round <= 1 only: failed + missing
  items, 100/file, with ``prior_attempt_reasons``, ready for round 2.
* ``contracts/manual_review.jsonl`` -- recomputed from scratch every run (not
  merged with what was there before): a key appears only if its *latest*
  entry in llm_rows.jsonl is not valid and that latest attempt was round >=
  2 or ``attempts`` >= 2. A key that later validates simply drops out.
* ``contracts/extracted.jsonl``     -- one row per admitted item: the regex
  row where regex was valid and complete, else the valid LLM row, else nulls
  with ``extractor="none"``. Sorted by meeting_date, item_no. Every row also
  carries the item's identity fields -- ``item_text``, ``title``,
  ``section``, ``board_action``, ``vote``, ``item_code``, ``era``,
  ``residual_category`` -- so link.py can pair on more than ``title``.
  Residual-derived rows (llm or none) get these from the batch/residual.jsonl
  row (keyed by ``(meeting_id, item_no, char_start)``, since the LLM's own
  ``.out.jsonl`` rows carry only the key + extracted fields); regex-complete
  rows get them from ``regex_rows.jsonl``, which does not carry
  ``item_text``/``residual_category`` -- those two are null on that branch.
* ``qa/e2_report.md``               -- per-batch counts, fill rates on the
  residual by era, and regex+LLM combined coverage by era. Also printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

from . import extract as ex

IDENTITY_FIELDS = ("meeting_id", "meeting_date", "item_no", "item_code",
                    "char_start", "era", "section", "title", "item_text",
                    "residual_category", "board_action", "vote")
SECTION2_FIELDS = ("vendor_raw", "vendor_name", "action_type", "amount", "amount_kind",
                    "prior_total", "revised_total", "contract_id", "po_number",
                    "term_start", "term_end", "department", "program_or_project",
                    "immediate_action",
                    # multi-vendor structure added by extract.py (2026-08-25)
                    "co_vendors", "co_vendors_raw", "group_total", "group_total_kind")

_MONEY_TEXT_RE = re.compile(
    r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(million|mil|billion|bil|thousand|[kmb])?\b",
    re.I)
_SUF_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mil": 1e6, "million": 1e6,
             "b": 1e9, "bil": 1e9, "billion": 1e9}
AMOUNT_BOUND = 2_000_000_000  # 2B: larger than the district's whole budget


def read_jsonl_tolerant(path):
    rows, n_bad = [], 0
    if not os.path.exists(path):
        return rows, n_bad
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                n_bad += 1
    return rows, n_bad


def _key(d):
    cs = d.get("char_start")
    try:
        cs = int(cs)
    except (TypeError, ValueError):
        pass
    return (d.get("meeting_id"), d.get("item_no"), cs)


def _text_money_values(text):
    vals = []
    for m in _MONEY_TEXT_RE.finditer(text):
        try:
            v = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if m.group(2):
            v *= _SUF_MULT.get(m.group(2).lower(), 1)
        vals.append(v)
    return vals


def validate_llm_row(row, batch_item, doc_pages):
    """E1's ``validate()`` plus the E2-specific checks: amount fields must
    appear in the source text (normalizing $/K/M/million/billion forms, exact
    after normalization -- no percentage tolerance), no amount may exceed
    AMOUNT_BOUND (the source has typos like "$4,352,000 million" an LLM can
    faithfully mis-convert into the trillions), citation pages must stay
    inside the source item's page range, and extractor must say "llm".
    """
    fake_item = {"title": batch_item.get("title") or "",
                 "body": batch_item.get("item_text") or ""}
    _, base_reasons = ex.validate(row, fake_item, doc_pages)
    reasons = list(base_reasons)

    text_vals = _text_money_values(ex._text_of(fake_item))
    for fld in ("amount", "prior_total", "revised_total"):
        v = row.get(fld)
        if not isinstance(v, (int, float)):
            continue
        if v > AMOUNT_BOUND:
            reasons.append(f"{fld}_implausible")
        elif not any(abs(v - tv) < 0.01 for tv in text_vals):
            reasons.append(f"{fld}_not_in_text")

    bcit, cit = batch_item.get("citation") or {}, row.get("citation") or {}
    ps, pe = cit.get("page_start"), cit.get("page_end")
    bps, bpe = bcit.get("page_start"), bcit.get("page_end")
    if None not in (ps, pe, bps, bpe) and (ps < bps or pe > bpe):
        reasons.append("citation_page_out_of_source_range")
    if row.get("extractor") != "llm":
        reasons.append("extractor_not_llm")

    # A deliberate null amount is correct when the model explains it: the
    # printed figure is malformed (column bleed like "$2,345,2922,361,532")
    # or the item is not a contract at all. E1's validator can't see that.
    notes = row.get("extractor_notes") or ""
    if row.get("amount") is None and ("malformed_amount:" in notes or "not_a_contract:" in notes):
        reasons = [r for r in reasons if r != "amount_missing_though_text_has_money"]

    seen, uniq = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            uniq.append(r)
    return (not uniq), uniq


def load_doc_pages(out_root):
    rows, _ = read_jsonl_tolerant(os.path.join(out_root, "manifest", "documents_classified.jsonl"))
    return {r["doc_id"]: r.get("pages") for r in rows if "doc_id" in r}


def _already_settled(stored, round_n):
    """True when ``stored`` (this key's current llm_rows.jsonl record, or
    None) means this round must leave the key alone: it is already valid at
    a round >= this one, or it was recorded at a round strictly later than
    this one (a stale/older batch must never regress a newer record, valid
    or not -- e.g. a re-run of round 1 after round 2 already ran).
    """
    if stored is None:
        return False
    if stored.get("round", 0) > round_n:
        return True
    return bool(stored.get("valid")) and stored.get("round", 0) >= round_n


def process_batches(batches_dir, round_n, documents, prior):
    """Load every NNN.jsonl/NNN.out.jsonl pair; validate; return per-batch
    stats, this round's validated records keyed by item, and the (key, item,
    reasons) list that still needs another round. ``prior`` is the current
    llm_rows.jsonl content keyed by item -- idempotency: a key already
    settled per ``_already_settled`` is left untouched (not re-validated,
    not added to rerun/manual_review), so re-running an old round over an
    unchanged batches/ directory can never regress a later round's fix.
    """
    batch_files = sorted(f for f in os.listdir(batches_dir) if re.match(r"^\d+\.jsonl$", f))
    batch_stats, round_records, rerun_items = [], {}, []
    for fn in batch_files:
        bid = fn[:-len(".jsonl")]
        items, _ = read_jsonl_tolerant(os.path.join(batches_dir, fn))
        items_by_key = {_key(it): it for it in items}
        raw_rows, n_bad = read_jsonl_tolerant(os.path.join(batches_dir, bid + ".out.jsonl"))
        rows_by_key, n_dupe = {}, 0
        for r in raw_rows:
            k = _key(r)
            n_dupe += k in rows_by_key
            rows_by_key[k] = r  # keep the last
        n_valid = n_invalid = n_missing = n_skipped = 0
        reasons_ctr = Counter()
        for key, item in items_by_key.items():
            if _already_settled(prior.get(key), round_n):
                n_skipped += 1
                n_valid += 1
                continue
            row = rows_by_key.get(key)
            if row is None:
                n_missing += 1
                reasons = ["missing_from_output"]
                round_records[key] = {"row": {}, "item": item, "valid": False,
                                       "reasons": reasons, "batch": bid, "round": round_n}
                rerun_items.append((key, item, reasons))
                continue
            doc_pages = documents.get((row.get("citation") or {}).get("doc_id"))
            valid, reasons = validate_llm_row(row, item, doc_pages)
            round_records[key] = {"row": row, "item": item, "valid": valid,
                                   "reasons": reasons, "batch": bid, "round": round_n}
            if valid:
                n_valid += 1
            else:
                n_invalid += 1
                reasons_ctr.update(reasons)
                rerun_items.append((key, item, reasons))
        batch_stats.append({"batch": bid, "items": len(items), "rows_returned": len(raw_rows),
                             "bad_json": n_bad, "duplicates": n_dupe, "missing": n_missing,
                             "valid": n_valid, "invalid": n_invalid, "skipped": n_skipped,
                             "reasons": reasons_ctr})
    return batch_stats, round_records, rerun_items


def _flatten(rec):
    out = dict(rec["row"])
    for f in ("meeting_id", "item_no", "char_start", "meeting_date"):
        out[f] = rec["item"].get(f)
    out["valid"], out["reasons"], out["round"], out["batch"] = (
        rec["valid"], rec["reasons"], rec["round"], rec["batch"])
    return out


def write_rerun(rerun_dir, rerun_items):
    os.makedirs(rerun_dir, exist_ok=True)
    for f in os.listdir(rerun_dir):
        if f.endswith(".jsonl"):
            os.remove(os.path.join(rerun_dir, f))
    rerun_items = sorted(rerun_items, key=lambda t: t[0])
    for i in range(0, len(rerun_items), 100):
        with open(os.path.join(rerun_dir, f"{i // 100:03d}.jsonl"), "w") as fh:
            for _key_, item, reasons in rerun_items[i:i + 100]:
                row = dict(item)
                row["prior_attempt_reasons"] = reasons
                fh.write(json.dumps(row) + "\n")


def compute_manual_review(combined, residual_by_key):
    """Pure recomputation, every run: a key belongs here only if its latest
    attempt (in ``combined`` / llm_rows.jsonl) is not valid AND that latest
    attempt was round >= 2 or it has been attempted twice. Nothing is loaded
    from a prior manual_review.jsonl -- a key that later validates simply
    stops appearing.
    """
    rows = []
    for key, rec in combined.items():
        if rec.get("valid"):
            continue
        if rec.get("round", 0) < 2 and rec.get("attempts", 0) < 2:
            continue
        row = dict(rec)
        res = residual_by_key.get(key)
        for f in ("title", "item_text", "section", "residual_category"):
            row[f] = res.get(f) if res else None
        rows.append(row)
    rows.sort(key=_key)
    return rows


def _trim_citation(cit):
    cit = cit or {}
    return {"doc_id": cit.get("doc_id"), "page_start": cit.get("page_start"),
            "page_end": cit.get("page_end")}


def _regex_out(row):
    sec2 = {f: row.get(f) for f in SECTION2_FIELDS}
    sec2.update(fund=None, funding_source_text=None, procurement_method=None,
                llm_confidence=None, citation=_trim_citation(row.get("citation")),
                extractor="regex", extractor_notes=row.get("extractor_notes"))
    return {**{k: row.get(k) for k in IDENTITY_FIELDS}, **sec2}


def _llm_out(llm_row, identity_src):
    sec2 = {f: llm_row.get(f) for f in SECTION2_FIELDS}
    sec2.update(fund=llm_row.get("fund"), funding_source_text=llm_row.get("funding_source_text"),
                procurement_method=llm_row.get("procurement_method"),
                llm_confidence=llm_row.get("llm_confidence"),
                citation=_trim_citation(llm_row.get("citation")),
                extractor="llm", extractor_notes=llm_row.get("extractor_notes"))
    return {**{k: identity_src.get(k) for k in IDENTITY_FIELDS}, **sec2}


def _null_out(identity_src):
    sec2 = {f: None for f in SECTION2_FIELDS}
    sec2.update(fund=None, funding_source_text=None, procurement_method=None,
                llm_confidence=None, citation=_trim_citation(identity_src.get("citation")),
                extractor="none", extractor_notes=None)
    return {**{k: identity_src.get(k) for k in IDENTITY_FIELDS}, **sec2}


def build_extracted(regex_rows, residual_by_key, llm_by_key):
    out = []
    for row in regex_rows:
        key = _key(row)
        res = residual_by_key.get(key)
        if res is None:
            out.append(_regex_out(row))
            continue
        rec = llm_by_key.get(key)
        if rec and rec.get("valid"):
            out.append(_llm_out(rec["row"], res))
        else:
            out.append(_null_out(res))
    out.sort(key=lambda r: (r.get("meeting_date") or "", str(r.get("item_no") or "")))
    return out


def write_report(path, batch_stats, residual_rows, extracted_rows, regex_rows):
    L = []
    A = L.append
    A("# E2 residual-extraction merge report\n")
    A("## Per batch\n")
    A("| batch | items | rows_returned | bad_json | dup_keys | missing | valid | invalid | "
      "skipped (already settled) | top reasons |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    tot = Counter()
    for b in batch_stats:
        for k in ("items", "rows_returned", "bad_json", "duplicates", "missing", "valid",
                  "invalid", "skipped"):
            tot[k] += b[k]
        top = ", ".join(f"{k}:{v}" for k, v in b["reasons"].most_common(4))
        A(f"| {b['batch']} | {b['items']} | {b['rows_returned']} | {b['bad_json']} | "
          f"{b['duplicates']} | {b['missing']} | {b['valid']} | {b['invalid']} | "
          f"{b['skipped']} | {top} |")
    A(f"| **all** | {tot['items']} | {tot['rows_returned']} | {tot['bad_json']} | "
      f"{tot['duplicates']} | {tot['missing']} | {tot['valid']} | {tot['invalid']} | "
      f"{tot['skipped']} | |")

    A("\n## Fill rates on the residual, by era\n")
    A("| era | items | vendor filled | amount filled | action_type filled |")
    A("|---|---|---|---|---|")
    by_era = defaultdict(list)
    for r in residual_rows:
        by_era[r.get("era") or "unknown"].append(_key(r))
    ex_by_key = {_key(r): r for r in extracted_rows}
    for era, keys in sorted(by_era.items()):
        n = len(keys)
        v = sum(1 for k in keys if (ex_by_key.get(k) or {}).get("vendor_raw"))
        a = sum(1 for k in keys if (ex_by_key.get(k) or {}).get("amount") is not None)
        t = sum(1 for k in keys if (ex_by_key.get(k) or {}).get("action_type") not in (None, "other"))
        A(f"| {era} | {n} | {v / n:.1%} | {a / n:.1%} | {t / n:.1%} |")

    A("\n## Combined regex+LLM coverage, by era\n")
    A("| era | admitted | resolved | coverage |")
    A("|---|---|---|---|")
    adm_by_era = Counter(r.get("era") or "unknown" for r in regex_rows)
    res_by_era = Counter(r.get("era") or "unknown" for r in extracted_rows if r.get("extractor") != "none")
    for era in sorted(adm_by_era):
        n, c = adm_by_era[era], res_by_era.get(era, 0)
        A(f"| {era} | {n} | {c} | {c / n:.1%} |")

    text = "\n".join(L) + "\n"
    with open(path, "w") as fh:
        fh.write(text)
    print(text)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    ap.add_argument("--batches", required=True, help="dir with NNN.jsonl + NNN.out.jsonl")
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--out-root", default=os.path.join(os.getcwd(), "out_sps_web"))
    ap.add_argument("--regex-rows", help="override path to regex_rows.jsonl")
    ap.add_argument("--residual", help="override path to residual.jsonl")
    args = ap.parse_args(argv)

    contracts_dir = os.path.join(args.out_root, "contracts")
    qa_dir = os.path.join(args.out_root, "qa")
    os.makedirs(contracts_dir, exist_ok=True)
    os.makedirs(qa_dir, exist_ok=True)
    regex_rows_path = args.regex_rows or os.path.join(contracts_dir, "regex_rows.jsonl")
    residual_path = args.residual or os.path.join(contracts_dir, "residual.jsonl")
    llm_rows_path = os.path.join(contracts_dir, "llm_rows.jsonl")

    if not os.path.isdir(args.batches) or not any(
            re.match(r"^\d+\.jsonl$", f) and
            os.path.exists(os.path.join(args.batches, f[:-len(".jsonl")] + ".out.jsonl"))
            for f in (os.listdir(args.batches) if os.path.isdir(args.batches) else [])):
        print(f"warning: no .out.jsonl files found under {args.batches} -- "
              f"nothing to merge, state left unchanged", file=sys.stderr)
        return 0

    documents = load_doc_pages(args.out_root)
    prior = {_key(r): r for r in read_jsonl_tolerant(llm_rows_path)[0]}
    batch_stats, round_records, rerun_items = process_batches(args.batches, args.round, documents, prior)

    combined = dict(prior)
    for key, rec in round_records.items():
        flat = _flatten(rec)
        flat["attempts"] = (prior.get(key, {}).get("attempts") or 0) + 1
        combined[key] = flat
    with open(llm_rows_path, "w") as fh:
        for key in sorted(combined):
            fh.write(json.dumps(combined[key]) + "\n")

    if args.round <= 1:
        write_rerun(os.path.join(contracts_dir, "rerun"), rerun_items)
    # round >= 2 failures go straight to manual_review (below), computed fresh
    # from combined every run -- nothing to write into rerun/, and critically
    # nothing to delete there either: --batches for round >= 2 normally *is*
    # contracts/rerun/, so clearing it here would destroy the very batch this
    # run just read, breaking a second pass over the same round-2 batch.

    regex_rows, _ = read_jsonl_tolerant(regex_rows_path)
    residual_rows, _ = read_jsonl_tolerant(residual_path)
    residual_by_key = {_key(r): r for r in residual_rows}
    llm_by_key = {k: {"row": v, "valid": v.get("valid")} for k, v in combined.items()}

    manual_review = compute_manual_review(combined, residual_by_key)
    with open(os.path.join(contracts_dir, "manual_review.jsonl"), "w") as fh:
        for r in manual_review:
            fh.write(json.dumps(r) + "\n")

    extracted = build_extracted(regex_rows, residual_by_key, llm_by_key)
    with open(os.path.join(contracts_dir, "extracted.jsonl"), "w") as fh:
        for r in extracted:
            fh.write(json.dumps(r) + "\n")

    write_report(os.path.join(qa_dir, "e2_report.md"), batch_stats, residual_rows, extracted, regex_rows)

    n_valid = sum(b["valid"] for b in batch_stats)
    n_invalid = sum(b["invalid"] for b in batch_stats)
    n_missing = sum(b["missing"] for b in batch_stats)
    print(f"round={args.round} batches={len(batch_stats)} valid={n_valid} "
          f"invalid={n_invalid} missing={n_missing} rerun_items={len(rerun_items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
