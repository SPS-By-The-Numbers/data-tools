"""Vendor normalization for the board-contracts pipeline (PLAN.md stage 6 / card F1).

Reads ``out_sps_web/contracts/extracted_filled.jsonl`` when it exists (E3,
``bar_fill.py``), else ``out_sps_web/contracts/extracted.jsonl`` (one row per admitted
contract-like item, from E1/E2) and produces a canonical vendor dimension:

    out_sps_web/contracts/vendors.jsonl        one row per canonical vendor
    out_sps_web/contracts/vendor_map.jsonl     vendor_raw -> vendor_id
    out_sps_web/contracts/vendors_review.csv   proposed merges for a human
    out_sps_web/qa/vendors_report.md           counts, top lists, leftovers

Run from the repo root::

    venv/bin/python3 -m extractors.sps_web.vendors

How a raw vendor string becomes a vendor
----------------------------------------
1. ``canonical_key()`` folds the string: strip the contract/bid-number prefixes
   E1 sometimes captures ("Contract D5050 to ..."), strip trailing project
   descriptors ("... for the John Rogers Elementary project"), casefold, drop
   punctuation and legal suffixes (Inc/LLC/Corp/Co/Ltd/PS/...), normalize
   abbreviations (Constr->Construction, Bldg->Building, Assn->Association,
   Dept->Department, Intl->International, Svcs->Services, Assoc->Associates),
   drop a leading "the", collapse whitespace.
2. The hand-maintained ``vendor_aliases.csv`` (same directory) maps a key to a
   canonical name and a ``vendor_class``. Alias rows are the ONLY judgement
   calls that are applied automatically besides exact key equality.
3. Everything else groups by exact canonical key. Near-duplicate keys are only
   *proposed*, never applied.

Where merge decisions live
--------------------------
``extractors/sps_web/vendor_merges.csv`` is the SYSTEM OF RECORD: in the repo,
hand-editable, read on every run. ``decision=y`` unions the two groups (the
larger survives, ``method="cluster"``); ``decision=n`` suppresses that pair from
ever being proposed again.

``out_sps_web/contracts/vendors_review.csv`` is a disposable worksheet listing
only the UNDECIDED proposals. Mark ``approve`` y/n there; the next run harvests
every non-empty mark into ``vendor_merges.csv`` (deduped on the unordered key
pair) and the row then drops out of the worksheet. Marking once is enough --
nothing is lost when the worksheet is regenerated, which is exactly the bug this
split fixes.

**``canonical_key()`` must stay stable.** ``vendor_merges.csv`` stores canonical
keys, so changing the folding rules silently orphans stored decisions. If you
must change it, re-key the CSV in the same commit. Orphaned keys are reported as
warnings on stderr, never a hard failure.

``vendor_class`` values: ``government``, ``cooperative``, ``contractor``,
``nonprofit``, ``school_placement``, ``unknown``, plus two extensions --
``labor_union`` (CBAs are a large slice of the corpus and are not contractors)
and ``not_a_vendor`` (Seattle Public Schools itself, project names, bid-number
labels and other E1 capture noise). ``not_a_vendor`` rows are kept in
``vendor_map.jsonl`` with ``vendor_id=null`` so downstream code can drop them,
and are listed in the QA report; they are excluded from ``vendors.jsonl``.

``total_amount_sum`` is a NAIVE sum of the non-null ``amount`` field over every
action for the vendor. Amounts mix not-to-exceed, revised-total, increase and
final values, and introduction/action rows are not yet paired (that is F2), so
the figure double-counts. It is a sort key, not a spend figure.
"""

from __future__ import annotations

import argparse
import collections
import csv
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALIAS_CSV = Path(__file__).resolve().parent / "vendor_aliases.csv"
MERGES_CSV = Path(__file__).resolve().parent / "vendor_merges.csv"
# Prefer E3's output (bar_fill.py) when it exists: it fills `vendor_raw` on
# rows whose minutes named no counterparty, from the linked Board Action
# Report. Those strings have to be normalised here or reconcile check 4 flags
# them as unmapped. Falls back to the plain E2 file when E3 has not run.
_FILLED = REPO_ROOT / "out_sps_web" / "contracts" / "extracted_filled.jsonl"
_PLAIN = REPO_ROOT / "out_sps_web" / "contracts" / "extracted.jsonl"
IN_EXTRACTED = _FILLED if _FILLED.exists() else _PLAIN
OUT_VENDORS = REPO_ROOT / "out_sps_web" / "contracts" / "vendors.jsonl"
OUT_MAP = REPO_ROOT / "out_sps_web" / "contracts" / "vendor_map.jsonl"
OUT_REVIEW = REPO_ROOT / "out_sps_web" / "contracts" / "vendors_review.csv"
OUT_REPORT = REPO_ROOT / "out_sps_web" / "qa" / "vendors_report.md"

NOT_A_VENDOR = "not_a_vendor"

# --------------------------------------------------------------------------
# canonical key
# --------------------------------------------------------------------------

# "Contract D5050 to X", "D-5041 to X", "Bid No. B06691 to X",
# "Alternates A-2 and B-1 to X" -- E1 swallowed the award clause.
_PREFIX_RES = [
    re.compile(r"^\s*alternates?\b.*?\bto\s+", re.I),
    re.compile(r"^\s*(?:public\s+work\s+)?contract\s+(?:no\.?\s*)?[A-Za-z]{0,2}[-\s]?\d{3,6}[A-Za-z]?\s+to\s+", re.I),
    re.compile(r"^\s*[A-Za-z]{0,2}[-\s]?\d{3,6}[A-Za-z]?\s+to\s+", re.I),
    re.compile(r"^\s*bid\s+no\.?\s*[A-Za-z0-9-]*\s+to\s+", re.I),
    re.compile(r"^\s*(?:award(?:ed)?|awarding)\s+to\s+", re.I),
]

# trailing project / scope descriptors captured with the name
_DESCRIPTOR_WORDS = (
    r"project|projects|modernization|upgrades?|replacements?|renovations?|"
    r"additions?|remodels?|improvements?|phase|elementary|middle school|"
    r"high school|k-?8|services|program|provision"
)
_TRAIL_RES = [
    # "... to Meany Middle School Phase II"
    re.compile(r"\s+to\s+.*?\b(?:" + _DESCRIPTOR_WORDS + r")\b.*$", re.I),
    # "... for the John Rogers Elementary project", "... for the Provision of X"
    re.compile(r"\s+for\s+(?:the\s+)?[^,]*?\b(?:" + _DESCRIPTOR_WORDS + r")\b.*$", re.I),
    # "... at Van Asselt Elementary School"
    re.compile(r"\s+at\s+(?:the\s+)?[A-Z][^,]*?\b(?:" + _DESCRIPTOR_WORDS + r")\b.*$", re.I),
]

_LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "llp", "lp", "plc", "pllc", "ps", "pc",
    "corp", "corporation", "co", "company", "companies", "ltd", "limited",
    "lc", "lllp",
}

_ABBREV = {
    "constr": "construction",
    "construc": "construction",
    "contr": "contracting",
    "bldg": "building",
    "bldgs": "buildings",
    "assn": "association",
    "assoc": "associates",
    "assocs": "associates",
    "associate": "associates",
    "dept": "department",
    "depts": "departments",
    "intl": "international",
    "intnl": "international",
    "svc": "services",
    "svcs": "services",
    "serv": "services",
    "servs": "services",
    "nw": "northwest",
    "mgmt": "management",
    "univ": "university",
    "dist": "district",
    "natl": "national",
    "cnty": "county",
    "arch": "architects",
    "architect": "architects",
    "architecture": "architects",
    "contractor": "contractors",
    "constructors": "construction",
    "us": "us",
    "usa": "us",
    "the": "the",
}

_DBA_RE = re.compile(r"\s+d\.?b\.?a\.?\s+", re.I)


def _fold_punctuation(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("’", "'").replace("‘", "'")
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    s = s.replace("&", " and ")
    s = s.replace("'", "")          # children's -> childrens, directors' -> directors
    s = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z]?\b)", "", s)   # P.S. -> PS, U.S. -> US
    s = re.sub(r"[^0-9a-zA-Z]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def canonical_key(name: str | None) -> str:
    """Fold a raw vendor string down to a comparison key. Empty if nothing survives."""
    if not name:
        return ""
    s = name.strip()
    # hyphenation artifacts from the PDF text layer: "Construc-tion" -> "Construction"
    s = re.sub(r"(?<=[a-z])-\s*\n?\s*(?=[a-z])", "", s)
    for rx in _PREFIX_RES:
        s = rx.sub("", s)
    # "X, Inc. dba Y" -> keep the legal name, Y gets an alias row if it matters
    s = _DBA_RE.split(s)[0]
    for rx in _TRAIL_RES:
        s = rx.sub("", s)
    s = _fold_punctuation(s).lower()
    if not s:
        return ""
    tokens = s.split()
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    tokens = [_ABBREV.get(t, t) for t in tokens]
    # drop legal suffixes wherever they land (they trail, but "Co, Inc." stacks)
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    tokens = [t for t in tokens if t not in _LEGAL_SUFFIXES] or tokens
    return " ".join(tokens).strip()


def slugify(name: str) -> str:
    s = _fold_punctuation(name).lower().replace(" ", "-")
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:60] or "vendor"


# --------------------------------------------------------------------------
# alias table
# --------------------------------------------------------------------------

VALID_CLASSES = {
    "government", "cooperative", "contractor", "nonprofit", "school_placement",
    "labor_union", NOT_A_VENDOR, "unknown",
}


def load_aliases(path: Path = ALIAS_CSV) -> dict[str, tuple[str, str, str]]:
    """key -> (canonical_name, vendor_class, note). Comment lines start with '#'."""
    out: dict[str, tuple[str, str, str]] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        rows = csv.DictReader(r for r in fh if not r.lstrip().startswith("#"))
        for i, row in enumerate(rows, start=2):
            alias = (row.get("alias_key") or "").strip()
            if not alias:
                continue
            canon = (row.get("canonical_name") or "").strip()
            klass = (row.get("vendor_class") or "unknown").strip() or "unknown"
            note = (row.get("note") or "").strip()
            if klass not in VALID_CLASSES:
                print(f"{path.name}:{i}: unknown vendor_class {klass!r}", file=sys.stderr)
                klass = "unknown"
            if klass == NOT_A_VENDOR and not canon:
                canon = alias
            key = canonical_key(alias)
            if not key:
                continue
            out[key] = (canon or alias, klass, note)
            # the canonical name itself must resolve to the same entity
            ckey = canonical_key(canon or alias)
            if ckey and ckey not in out:
                out[ckey] = (canon or alias, klass, note)
    return out


# --------------------------------------------------------------------------
# heuristic classification
# --------------------------------------------------------------------------

_CLASS_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("government", re.compile(
        r"\bcity of\b|\bcounty\b|\bstate of\b|\bport of\b|\bdepartment of\b|"
        r"\boffice of\b|\buniversity of\b|\bschool district\b|\bcommunity college\b|"
        r"\bpublic health\b|\bsound transit\b|\bospi\b|\beducational service district\b|"
        r"\bmunicipalit|\bhousing authority\b|\bu s (?:department|food|army|navy)\b|"
        r"\bfederal\b|\bconsulate\b|\bembassy\b", re.I)),
    ("cooperative", re.compile(
        r"\bdirectors association\b|\bkcda\b|\bnaspo\b|\bvaluepoint\b|"
        r"\bpurchasing cooperative\b|\brisk management pool\b|\bconsortium\b", re.I)),
    ("labor_union", re.compile(
        r"\bunion\b|\blocal \d|\bteamsters\b|\bfederation of teachers\b|"
        r"\btrades council\b|\bbargaining\b", re.I)),
    ("contractor", re.compile(
        r"\bconstruction\b|\bconstructors\b|\bcontracting\b|\bcontractors?\b|"
        r"\bbuilders?\b|\broofing\b|\belectric(?:al)?\b|\bmechanical\b|\bplumbing\b|"
        r"\bsheet metal\b|\barchitects?\b|\barchitecture\b|\bengineers?\b|"
        r"\bengineering\b|\blandscaping\b|\bearthworks\b|\bdemolition\b|\bmasonry\b|"
        r"\bflooring\b|\bpaving\b|\bglass\b|\bpainting\b|\bhvac\b|\bexcavat|"
        r"\bindustries\b|\bsystems\b|\btechnologies\b|\bsolutions\b|\bnetworks?\b|"
        r"\bsupply\b|\bequipment\b|\bfarms?\b|\bbakeries\b|\bfoodservice\b|"
        r"\bstaffing\b|\bconsulting\b|\bpartners\b", re.I)),
    ("school_placement", re.compile(
        r"\bacademy\b|\blearning center\b|\bschool for\b|\bday school\b|"
        r"\bcenter for children\b|\btherapy\b|\bbehavioral?\b", re.I)),
    ("nonprofit", re.compile(
        r"\bfoundation\b|\bymca\b|\bywca\b|\balliance\b|\bunited way\b|"
        r"\bsociety\b|\bcoalition\b|\bcouncil\b|\bchurch\b|\bboys and girls\b|"
        r"\bhospital\b|\bmedical center\b|\bmuseum\b|\binstitute\b|"
        r"\bassociation\b|\bnetwork\b", re.I)),
]


def classify(name: str) -> str:
    for klass, rx in _CLASS_RULES:
        if rx.search(name):
            return klass
    return "unknown"


# --------------------------------------------------------------------------
# review file
# --------------------------------------------------------------------------

REVIEW_FIELDS = [
    "approve", "rule", "ratio",
    "key_a", "canonical_a", "n_actions_a", "raw_forms_a", "example_a",
    "key_b", "canonical_b", "n_actions_b", "raw_forms_b", "example_b",
]
MERGE_FIELDS = ["key_a", "key_b", "decision", "canonical_a", "canonical_b", "note"]
_APPROVED = {"y", "yes", "1", "true", "t", "merge"}

MERGES_HEADER = """\
# Durable vendor merge decisions for extractors.sps_web.vendors (card F1).
# This file is the system of record: it is in the repo, hand-editable, and read on
# every run. out_sps_web/contracts/vendors_review.csv is a scratch worksheet that
# only ever lists UNDECIDED proposals; any approve mark written there is harvested
# into this file after the run and then disappears from the worksheet.
#
# key_a,key_b   canonical keys (vendors.canonical_key output), stored in sorted
#               order and matched unordered. They are only stable as long as
#               canonical_key() is stable -- see the module docstring. A key that
#               matches no current vendor group is warned about, not fatal.
# decision      y = merge the two groups (larger one survives)
#               n = never propose this pair again
# canonical_a/b display names at the time of the decision, for human context only
# note          why
"""


def _pair(a: str, b: str) -> tuple[str, str]:
    """Merge decisions are unordered: always key them on the sorted pair."""
    return (a, b) if a <= b else (b, a)


def _decide(value: str) -> str:
    return "y" if (value or "").strip().lower() in _APPROVED else "n"


def load_merges(path: Path = MERGES_CSV) -> dict[tuple[str, str], dict]:
    """Read the durable decision table. Comment lines start with '#'."""
    out: dict[tuple[str, str], dict] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(r for r in fh if not r.lstrip().startswith("#")):
            a, b = (row.get("key_a") or "").strip(), (row.get("key_b") or "").strip()
            if not a or not b:
                continue
            a, b = _pair(a, b)
            out[(a, b)] = {
                "key_a": a, "key_b": b, "decision": _decide(row.get("decision")),
                "canonical_a": (row.get("canonical_a") or "").strip(),
                "canonical_b": (row.get("canonical_b") or "").strip(),
                "note": (row.get("note") or "").strip(),
            }
    return out


def save_merges(decisions: dict[tuple[str, str], dict],
                path: Path = MERGES_CSV) -> None:
    rows = sorted(decisions.values(), key=lambda r: (r["decision"], r["key_a"], r["key_b"]))
    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(MERGES_HEADER)
        w = csv.DictWriter(fh, fieldnames=MERGE_FIELDS)
        w.writeheader()
        w.writerows(rows)


def harvest_review_marks(path: Path = OUT_REVIEW) -> dict[tuple[str, str], dict]:
    """Pull every non-empty `approve` mark out of the scratch worksheet."""
    out: dict[tuple[str, str], dict] = {}
    if not path.exists():
        return out
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            a, b = (row.get("key_a") or "").strip(), (row.get("key_b") or "").strip()
            mark = (row.get("approve") or "").strip()
            if not a or not b or not mark:
                continue
            ca, cb = (row.get("canonical_a") or ""), (row.get("canonical_b") or "")
            if a > b:
                a, b, ca, cb = b, a, cb, ca
            out[(a, b)] = {"key_a": a, "key_b": b, "decision": _decide(mark),
                           "canonical_a": ca, "canonical_b": cb,
                           "note": "from vendors_review.csv"}
    return out


def merge_decisions(stored: dict[tuple[str, str], dict],
                    harvested: dict[tuple[str, str], dict]) -> dict[tuple[str, str], dict]:
    """Harvested worksheet marks win over what is already stored."""
    out = dict(stored)
    for pair, row in harvested.items():
        prev = out.get(pair)
        if prev and prev["decision"] == row["decision"]:
            continue                     # unchanged; keep the original note
        if prev:
            row = dict(row, note=row["note"] + f" (was {prev['decision']})")
        out[pair] = row
    return out


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

class Group:
    """One canonical vendor under construction."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.raws: dict[str, int] = collections.Counter()
        self.methods: dict[str, str] = {}
        self.alias_name: str | None = None
        self.alias_class: str | None = None
        self.rows: list[dict] = []

    @property
    def n_actions(self) -> int:
        return len(self.rows)


def _pick_name(g: Group) -> str:
    if g.alias_name:
        return g.alias_name
    # most-used raw form; ties broken toward the longer (more complete) string
    return max(g.raws.items(), key=lambda kv: (kv[1], len(kv[0])))[0]


def _example(rows: list[dict]) -> str:
    if not rows:
        return ""
    r = rows[0]
    title = re.sub(r"\s+", " ", (r.get("title") or ""))[:110]
    return f"{r.get('meeting_date') or '?'} {title}"


def build(rows: list[dict], aliases: dict[str, tuple[str, str, str]],
          decisions: dict[tuple[str, str], dict],
          ) -> tuple[dict[str, Group], list[dict]]:
    """Group raw vendor strings into canonical vendors.

    `decisions` is the durable table from `vendor_merges.csv`: `y` pairs are
    unioned here, `y` and `n` pairs alike are suppressed from the proposals so
    the review worksheet only ever shows what a human has not ruled on.
    """
    # 1. raw -> key -> group
    groups: dict[str, Group] = {}
    raw_rows: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        raw = r.get("vendor_raw")
        if raw:
            raw_rows[raw].append(r)
        # E1 emits a structured `co_vendors` list on multi-vendor items, and
        # link.py explodes each entry into its own action row. Those names
        # need a vendor_id too, or reconcile check 4 reports them unmapped.
        for cv in (r.get("co_vendors") or []):
            cv_raw = cv.get("vendor_raw") if isinstance(cv, dict) else cv
            if cv_raw:
                raw_rows[cv_raw].append(r)

    raw_to_group: dict[str, str] = {}
    raw_method: dict[str, str] = {}
    for raw, rs in raw_rows.items():
        key = canonical_key(raw)
        if not key:
            key = "__unparsed__"
        hit = aliases.get(key)
        if hit:
            canon, klass, _ = hit
            gkey = canonical_key(canon) or key
            method = "alias" if gkey != key else "exact"
        else:
            canon = klass = None
            gkey, method = key, "exact"
        g = groups.get(gkey)
        if g is None:
            g = groups[gkey] = Group(gkey)
        if canon and g.alias_name is None:
            g.alias_name, g.alias_class = canon, klass
        g.raws[raw] += len(rs)
        g.rows.extend(rs)
        raw_to_group[raw] = gkey
        raw_method[raw] = method

    # 2. apply the durable human decisions (vendor_merges.csv)
    parent: dict[str, str] = {k: k for k in groups}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    approved = 0
    orphans: list[tuple[str, str]] = []
    for (a, b), row in decisions.items():
        missing = [k for k in (a, b) if k not in parent]
        if missing:
            # canonical_key() changed, or the vendor left the corpus. Warn only.
            orphans.append((a, b))
            continue
        if row["decision"] == "y":
            ra, rb = find(a), find(b)
            if ra != rb:
                # keep the larger group as the survivor
                if groups[ra].n_actions < groups[rb].n_actions:
                    ra, rb = rb, ra
                parent[rb] = ra
                approved += 1
    for a, b in orphans:
        print(f"vendor_merges.csv: no vendor group for {a!r} / {b!r} "
              f"(canonical_key changed, or the vendor left the corpus)",
              file=sys.stderr)
    if approved:
        merged: dict[str, Group] = {}
        for k, g in groups.items():
            root = find(k)
            tgt = merged.get(root)
            if tgt is None:
                tgt = merged[root] = Group(root)
                tgt.alias_name = groups[root].alias_name
                tgt.alias_class = groups[root].alias_class
            tgt.raws.update(g.raws)
            tgt.rows.extend(g.rows)
            if tgt.alias_name is None and g.alias_name:
                tgt.alias_name, tgt.alias_class = g.alias_name, g.alias_class
            if k != root:
                for raw in g.raws:
                    raw_to_group[raw] = root
                    raw_method[raw] = "cluster"
        groups = merged

    for g in groups.values():
        g.methods = {raw: raw_method[raw] for raw in g.raws}

    # 3. propose (never apply) near-duplicate merges among the survivors,
    #    minus every pair a human has already ruled on
    proposals = propose_merges(groups, decided=set(decisions))
    return groups, proposals


def _token_subset(a: str, b: str) -> bool:
    """True when the shorter key's tokens are all present in the longer one."""
    ta, tb = a.split(), b.split()
    if len(ta) > len(tb):
        ta, tb = tb, ta
    return len(ta) >= 2 and len(ta) < len(tb) and set(ta) <= set(tb)


def propose_merges(groups: dict[str, Group], hi: float = 0.92, lo: float = 0.85,
                   decided: set[tuple[str, str]] | None = None) -> list[dict]:
    """Conservative near-duplicate detection. Proposes only -- nothing is applied.

    Three rules, weakest last:
      ratio>=0.92                      difflib ratio on the canonical keys
      same-first-2-tokens+ratio>=0.85  same head, small tail drift
      token-subset                     one key's tokens contained in the other's
    """
    names = {k: _pick_name(g) for k, g in groups.items()}
    classes = {k: (g.alias_class or classify(names[k])) for k, g in groups.items()}
    keys = sorted(k for k, g in groups.items()
                  if classes[k] != NOT_A_VENDOR and k != "__unparsed__")
    out: list[dict] = []
    for i, a in enumerate(keys):
        sm = difflib.SequenceMatcher(b=a, autojunk=False)
        ta = a.split()[:2]
        for b in keys[i + 1:]:
            rule, ratio = None, 0.0
            if _token_subset(a, b):
                rule = "token-subset"
            if abs(len(a) - len(b)) <= max(len(a), len(b)) * 0.5:
                sm.set_seq1(b)
                if sm.real_quick_ratio() >= lo and sm.quick_ratio() >= lo:
                    ratio = sm.ratio()
                    if ratio >= hi:
                        rule = "ratio>=0.92"
                    elif len(ta) == 2 and b.split()[:2] == ta and ratio >= lo:
                        rule = rule or "same-first-2-tokens+ratio>=0.85"
            if rule is None or _pair(a, b) in (decided or ()):
                continue
            if not ratio:
                ratio = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
            ga, gb = groups[a], groups[b]
            out.append({
                "approve": "", "rule": rule, "ratio": f"{ratio:.3f}",
                "key_a": a, "canonical_a": names[a], "n_actions_a": ga.n_actions,
                "raw_forms_a": " | ".join(sorted(ga.raws)), "example_a": _example(ga.rows),
                "key_b": b, "canonical_b": names[b], "n_actions_b": gb.n_actions,
                "raw_forms_b": " | ".join(sorted(gb.raws)), "example_b": _example(gb.rows),
            })
    order = {"ratio>=0.92": 0, "same-first-2-tokens+ratio>=0.85": 1, "token-subset": 2}
    out.sort(key=lambda r: (order[r["rule"]], -float(r["ratio"]), r["key_a"]))
    return out


def emit(groups: dict[str, Group], proposals: list[dict], rows: list[dict],
         write: bool = True) -> dict:
    vendors: list[dict] = []
    mappings: list[dict] = []
    used_ids: set[str] = set()
    nonvendor_names: list[tuple[str, int]] = []

    ordered = sorted(groups.values(), key=lambda g: (-g.n_actions, g.key))
    for g in ordered:
        name = _pick_name(g)
        klass = g.alias_class or classify(name)
        if klass == NOT_A_VENDOR:
            nonvendor_names.append((name, g.n_actions))
            for raw in sorted(g.raws):
                mappings.append({"vendor_raw": raw, "vendor_id": None,
                                 "canonical_name": name, "vendor_class": klass,
                                 "method": g.methods.get(raw, "exact"),
                                 "n_actions": g.raws[raw]})
            continue
        vid = slugify(name)
        base, n = vid, 2
        while vid in used_ids:
            vid, n = f"{base}-{n}", n + 1
        used_ids.add(vid)

        dates = sorted(r["meeting_date"] for r in g.rows if r.get("meeting_date"))
        amounts = [r["amount"] for r in g.rows
                   if isinstance(r.get("amount"), (int, float))]
        vendors.append({
            "vendor_id": vid,
            "canonical_name": name,
            "vendor_class": klass,
            "canonical_key": g.key,
            "aliases": sorted(g.raws),
            "n_actions": g.n_actions,
            "first_seen": dates[0] if dates else None,
            "last_seen": dates[-1] if dates else None,
            "total_amount_sum": round(sum(amounts), 2) if amounts else None,
            "total_amount_sum_note": ("naive sum of non-null `amount` over all actions; "
                                      "mixes not_to_exceed/revised_total/increase and "
                                      "double-counts intro+action rows -- not spend"),
            "n_amounts": len(amounts),
            "by_action_type": dict(collections.Counter(
                r.get("action_type") or "null" for r in g.rows)),
            "by_era": dict(collections.Counter(r.get("era") or "null" for r in g.rows)),
        })
        for raw in sorted(g.raws):
            mappings.append({"vendor_raw": raw, "vendor_id": vid,
                             "canonical_name": name, "vendor_class": klass,
                             "method": g.methods.get(raw, "exact"),
                             "n_actions": g.raws[raw]})

    if write:
        OUT_VENDORS.parent.mkdir(parents=True, exist_ok=True)
        OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
        with OUT_VENDORS.open("w", encoding="utf-8") as fh:
            for v in vendors:
                fh.write(json.dumps(v, ensure_ascii=False) + "\n")
        with OUT_MAP.open("w", encoding="utf-8") as fh:
            for m in sorted(mappings, key=lambda m: m["vendor_raw"]):
                fh.write(json.dumps(m, ensure_ascii=False) + "\n")
        with OUT_REVIEW.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=REVIEW_FIELDS)
            w.writeheader()
            for p in proposals:
                w.writerow(p)
        OUT_REPORT.write_text(render_report(vendors, mappings, proposals,
                                            nonvendor_names, rows), encoding="utf-8")
    return {"vendors": vendors, "mappings": mappings,
            "not_a_vendor": nonvendor_names, "proposals": proposals}


def render_report(vendors, mappings, proposals, nonvendor_names, rows) -> str:
    n_rows = len(rows)
    n_with_raw = sum(1 for r in rows
                     if r.get("vendor_raw") or r.get("co_vendors"))
    raw_forms = {m["vendor_raw"] for m in mappings}
    by_method = collections.Counter(m["method"] for m in mappings)
    by_class = collections.Counter(v["vendor_class"] for v in vendors)
    unknown = [v for v in vendors if v["vendor_class"] == "unknown"]

    L: list[str] = []
    a = L.append
    a("# Vendor normalization (F1)\n")
    a(f"Source: `out_sps_web/contracts/extracted.jsonl` ({n_rows} rows, "
      f"{n_with_raw} with a `vendor_raw`, {n_rows - n_with_raw} without).\n")
    a("| metric | n |")
    a("|---|---|")
    a(f"| distinct raw vendor strings | {len(raw_forms)} |")
    a(f"| canonical vendors emitted | {len(vendors)} |")
    a(f"| raw strings judged not-a-vendor | {sum(1 for m in mappings if m['vendor_id'] is None)} |")
    a(f"| distinct not-a-vendor entities | {len(nonvendor_names)} |")
    a(f"| mapped by exact canonical key | {by_method['exact']} |")
    a(f"| mapped by hand-written alias | {by_method['alias']} |")
    a(f"| mapped by human-approved cluster | {by_method['cluster']} |")
    a(f"| undecided merges awaiting review | {len(proposals)} |")
    a("")
    a("Class mix: " + ", ".join(f"{k} {n}" for k, n in by_class.most_common()) + "\n")
    a("Nothing below `ratio>=0.92` (or identical first two tokens with "
      "`ratio>=0.85`) is ever merged automatically. Undecided proposals live in "
      "`out_sps_web/contracts/vendors_review.csv`; mark `approve` `y` or `n` and "
      "rerun. The mark is harvested into `extractors/sps_web/vendor_merges.csv` "
      "(the durable, in-repo system of record) and the row leaves the "
      "worksheet.\n")

    a("## Top 30 vendors by board actions\n")
    a("| # | vendor | class | actions | first | last | naive $ sum |")
    a("|---|---|---|---|---|---|---|")
    for i, v in enumerate(sorted(vendors, key=lambda v: -v["n_actions"])[:30], 1):
        amt = f"{v['total_amount_sum']:,.0f}" if v["total_amount_sum"] else ""
        a(f"| {i} | {v['canonical_name']} | {v['vendor_class']} | {v['n_actions']} | "
          f"{v['first_seen'] or ''} | {v['last_seen'] or ''} | {amt} |")
    a("")
    a("## Top 30 vendors by naive amount sum\n")
    a("Not spend: `amount` mixes not-to-exceed, revised-total and increase "
      "values and intro/action rows are still unpaired (F2).\n")
    a("| # | vendor | class | naive $ sum | actions w/ amount |")
    a("|---|---|---|---|---|")
    ranked = sorted((v for v in vendors if v["total_amount_sum"]),
                    key=lambda v: -v["total_amount_sum"])[:30]
    for i, v in enumerate(ranked, 1):
        a(f"| {i} | {v['canonical_name']} | {v['vendor_class']} | "
          f"{v['total_amount_sum']:,.0f} | {v['n_amounts']} |")
    a("")
    a(f"## Unclassified vendors ({len(unknown)})\n")
    a("`vendor_class=unknown` -- the heuristics found no signal and there is no "
      "alias row. Add them to `extractors/sps_web/vendor_aliases.csv`.\n")
    for v in sorted(unknown, key=lambda v: -v["n_actions"]):
        a(f"- {v['canonical_name']} ({v['n_actions']})")
    a("")
    a(f"## Raw strings excluded as not-a-vendor ({len(nonvendor_names)})\n")
    for name, n in sorted(nonvendor_names, key=lambda t: -t[1]):
        a(f"- {name} ({n})")
    a("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--extracted", type=Path, default=IN_EXTRACTED)
    ap.add_argument("--aliases", type=Path, default=ALIAS_CSV)
    ap.add_argument("--merges", type=Path, default=MERGES_CSV)
    ap.add_argument("--no-review-marks", action="store_true",
                    help="do not harvest approve marks from vendors_review.csv")
    ap.add_argument("--dry-run", action="store_true", help="do not write outputs")
    args = ap.parse_args(argv)

    rows = [json.loads(line) for line in args.extracted.open(encoding="utf-8") if line.strip()]
    aliases = load_aliases(args.aliases)

    # Harvest first, so a mark written in the worksheet takes effect this run and
    # is durable from now on even though the worksheet is about to be rewritten.
    stored = load_merges(args.merges)
    harvested = {} if args.no_review_marks else harvest_review_marks()
    decisions = merge_decisions(stored, harvested)
    if decisions != stored and not args.dry_run:
        save_merges(decisions, args.merges)

    groups, proposals = build(rows, aliases, decisions)
    res = emit(groups, proposals, rows, write=not args.dry_run)

    n_y = sum(1 for d in decisions.values() if d["decision"] == "y")
    print(f"rows={len(rows)} "
          f"raw_names={len({r['vendor_raw'] for r in rows if r.get('vendor_raw')})} "
          f"vendors={len(res['vendors'])} "
          f"not_a_vendor={len(res['not_a_vendor'])} "
          f"undecided_proposals={len(proposals)} "
          f"aliases_loaded={len(aliases)} "
          f"decisions={len(decisions)} (y={n_y}, n={len(decisions) - n_y}) "
          f"harvested={len(harvested)}")
    if not args.dry_run:
        for p in (OUT_VENDORS, OUT_MAP, OUT_REVIEW, OUT_REPORT):
            print(f"wrote {p.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
