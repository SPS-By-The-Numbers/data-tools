"""Reorganize the flat data/fiscal/ corpus into a report_type / year / org tree.

Run dry-run first:
    python3 -m extractors.fiscal.reorg

Execute moves (in-place inside data/fiscal/):
    python3 -m extractors.fiscal.reorg --execute

Resulting layout (all directory names lowercase + underscores; leaf filenames preserved verbatim):

    data/fiscal/
      apportionment/{yyyy-yyyy}/district/{ccddd}_{slug}/{leaf}
      apportionment/{yyyy-yyyy}/esd/{esd_code}_{slug}/{ccddd}_{slug}|{slug}/{leaf}
      apportionment/{yyyy-yyyy}/college/{code}_{slug}/{leaf}
      apportionment/{yyyy-yyyy}/state_agency/{code}_{slug}/{leaf}
      fiscal/{yyyy-yyyy}/{ccddd}_{slug}/{leaf}
      state_institutions/{yyyy-yyyy}/{leaf}
      esd_allocations/{yyyy-yyyy}/{leaf}
      county_treasurer/{yyyy-yyyy}/{leaf}
      state_agencies_schools_colleges/{yyyy-yyyy}/{leaf}
      technical_colleges/{yyyy-yyyy}/{leaf}

Canonical name table: per (kind, code), pick the name observed in the most recent
school year present in the corpus. Apportionment-District (ccddd -> name) is also
used to backfill CCDDDs onto ESD member-district directory names by exact match.
"""

import argparse
import os
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

REPORT_DIRS = {
    "Apportionment": "apportionment",
    "Apportionments": "apportionment",
    "Fiscal": "fiscal",
    "State Institutions": "state_institutions",
    "ESD Allocations": "esd_allocations",
    "County Treasurer": "county_treasurer",
    "State Agencies, Schools & Colleges": "state_agencies_schools_colleges",
    "Technical Colleges": "technical_colleges",
}

APPORTIONMENT_ORG_TYPE_DIRS = {
    "District (CCDDD)": "district",
    "ESD": "esd",
    "College": "college",
    "State Agency": "state_agency",
}

YEAR_RE = re.compile(r"^\d{4}-\d{4}$")
ORG_LABEL_RE = re.compile(r"^(.*?)\s*\(([^)]+)\)\s*$")
LEADING_CODE_RE = re.compile(r"^(\d{5})\s+(.*)$")


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def parse_org_label(label: str):
    """`Name (code)` -> (name, code) ; otherwise (label, None)."""
    m = ORG_LABEL_RE.match(label)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return label.strip(), None


def classify(name: str):
    """Return dict describing target placement, or None if unparseable."""
    parts = name.split(" - ")
    if len(parts) < 3 or not YEAR_RE.match(parts[0]):
        return None
    year = parts[0]
    rtype = parts[1]
    if rtype not in REPORT_DIRS:
        return None

    if rtype in ("Apportionment",):
        if len(parts) < 5:
            return None
        org_type = parts[2]
        if org_type == "ESD" and len(parts) >= 6:
            esd_name, esd_code = parse_org_label(parts[3])
            member = parts[4]
            leaf = " - ".join(parts[5:])
            return {
                "kind": "apportionment_esd",
                "year": year, "rtype": rtype,
                "esd_code": esd_code, "esd_name": esd_name,
                "member_name": member, "leaf": leaf,
            }
        if org_type in ("District (CCDDD)", "College", "State Agency") and len(parts) >= 5:
            org_name, code = parse_org_label(parts[3])
            leaf = " - ".join(parts[4:])
            kind = {
                "District (CCDDD)": "apportionment_district",
                "College": "apportionment_college",
                "State Agency": "apportionment_state_agency",
            }[org_type]
            return {
                "kind": kind, "year": year, "rtype": rtype,
                "code": code, "name": org_name, "leaf": leaf,
            }
        return None

    if rtype == "Apportionments":
        # Singleton typo case: "2023-2024 - Apportionments - 27931 Bates Technical College - Quarterly Funding Report.pdf"
        if len(parts) >= 4:
            m = LEADING_CODE_RE.match(parts[2])
            if m:
                code, org_name = m.group(1), m.group(2).strip()
                leaf = " - ".join(parts[3:])
                # Bates is a technical/community college -- bucket under college.
                return {
                    "kind": "apportionment_college", "year": year, "rtype": rtype,
                    "code": code, "name": org_name, "leaf": leaf,
                }
        return None

    if rtype == "Fiscal":
        if len(parts) >= 5 and parts[2] == "District (CCDDD)":
            org_name, code = parse_org_label(parts[3])
            leaf = " - ".join(parts[4:])
            return {
                "kind": "fiscal_district", "year": year, "rtype": rtype,
                "code": code, "name": org_name, "leaf": leaf,
            }
        return None

    # Flat report types: year / leaf
    leaf = " - ".join(parts[2:])
    flat_kinds = {
        "State Institutions": "state_institutions_flat",
        "ESD Allocations": "esd_allocations_flat",
        "County Treasurer": "county_treasurer_flat",
        "State Agencies, Schools & Colleges": "state_agencies_flat",
        "Technical Colleges": "technical_colleges_flat",
    }
    if rtype in flat_kinds:
        return {"kind": flat_kinds[rtype], "year": year, "rtype": rtype, "leaf": leaf}
    return None


CANONICAL_KEYS = {
    "apportionment_district": "district",
    "fiscal_district": "district",
    "apportionment_college": "college",
    "apportionment_state_agency": "state_agency",
    "apportionment_esd": "esd",
}


def build_canonical(infos):
    """(category, code) -> name from the most recent year that has it."""
    canonical = {}
    for info in infos:
        kind = info["kind"]
        if kind not in CANONICAL_KEYS:
            continue
        if kind == "apportionment_esd":
            code = info["esd_code"]
            name = info["esd_name"]
        else:
            code = info.get("code")
            name = info.get("name")
        if not code or not name:
            continue
        key = (CANONICAL_KEYS[kind], code)
        prev = canonical.get(key)
        if prev is None or info["year"] > prev[0]:
            canonical[key] = (info["year"], name)
    return {k: v[1] for k, v in canonical.items()}


def build_district_name_to_ccddd(infos, canonical):
    """Used only to backfill CCDDDs onto ESD member-district directories.

    Picks one CCDDD per district name based on the most recent year. If the
    same district name maps to multiple CCDDDs across years (very rare), the
    later year wins.
    """
    by_name = {}  # name -> (year, ccddd)
    for info in infos:
        if info["kind"] != "apportionment_district":
            continue
        code = info.get("code")
        if not code:
            continue
        # Use canonical name when available so historical name drift collapses.
        name = canonical.get(("district", code), info["name"])
        prev = by_name.get(name)
        if prev is None or info["year"] > prev[0]:
            by_name[name] = (info["year"], code)
        # Also index the original (non-canonical) name so ESD-branch labels
        # that match a historical (now-renamed) form still resolve.
        if info["name"] != name:
            prev2 = by_name.get(info["name"])
            if prev2 is None or info["year"] > prev2[0]:
                by_name[info["name"]] = (info["year"], code)
    return {n: c for n, (_, c) in by_name.items()}


def target_path(info, canonical, name_to_ccddd, base: Path):
    year = info["year"]
    leaf = info["leaf"]
    rtype = info["rtype"]
    rt_dir = REPORT_DIRS[rtype]
    kind = info["kind"]

    if kind == "apportionment_district":
        code = info["code"]
        name = canonical.get(("district", code), info["name"])
        return base / "apportionment" / year / "district" / f"{code}_{slugify(name)}" / leaf
    if kind == "apportionment_college":
        code = info["code"]
        name = canonical.get(("college", code), info["name"])
        return base / "apportionment" / year / "college" / f"{code}_{slugify(name)}" / leaf
    if kind == "apportionment_state_agency":
        code = info["code"]
        name = canonical.get(("state_agency", code), info["name"])
        return base / "apportionment" / year / "state_agency" / f"{code}_{slugify(name)}" / leaf
    if kind == "apportionment_esd":
        esd_code = info["esd_code"]
        esd_name = canonical.get(("esd", esd_code), info["esd_name"])
        member = info["member_name"]
        ccddd = name_to_ccddd.get(member)
        if ccddd:
            canonical_member = canonical.get(("district", ccddd), member)
            member_dir = f"{ccddd}_{slugify(canonical_member)}"
        else:
            member_dir = slugify(member)
        return (base / "apportionment" / year / "esd"
                / f"{esd_code}_{slugify(esd_name)}" / member_dir / leaf)
    if kind == "fiscal_district":
        code = info["code"]
        name = canonical.get(("district", code), info["name"])
        return base / "fiscal" / year / f"{code}_{slugify(name)}" / leaf
    # Flat kinds:
    return base / rt_dir / year / leaf


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, default=Path("data/fiscal"),
                    help="Source directory (default: data/fiscal).")
    ap.add_argument("--execute", action="store_true",
                    help="Actually perform moves. Default is dry-run.")
    ap.add_argument("--sample", type=int, default=8,
                    help="How many sample paths to print in dry-run output.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after N moves (debugging). 0 = no limit.")
    args = ap.parse_args()

    src = args.source.resolve()
    if not src.is_dir():
        sys.exit(f"Source not a directory: {src}")

    # Refuse to (re-)run if any of the target top-level dirs already exists --
    # implies a previous in-place run left state behind and a re-run could fight it.
    existing = [d for d in REPORT_DIRS.values() if (src / d).exists()]
    if existing and args.execute:
        sys.exit(f"Refusing to execute: these target dirs already exist in {src}: {existing}\n"
                 f"Either resume manually or move them aside first.")

    print(f"Scanning {src}...")
    files = []
    for entry in os.scandir(src):
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        files.append(Path(entry.path))
    print(f"  found {len(files):,} top-level files")

    parsed = []
    unparsed = []
    for p in files:
        info = classify(p.name)
        if info is None:
            unparsed.append(p)
        else:
            info["src"] = p
            parsed.append(info)

    print(f"  parsed:   {len(parsed):,}")
    print(f"  unparsed: {len(unparsed):,}")
    if unparsed:
        print("  first few unparsed:")
        for p in unparsed[:10]:
            print(f"    {p.name}")

    canonical = build_canonical(parsed)
    name_to_ccddd = build_district_name_to_ccddd(parsed, canonical)
    print(f"  canonical names: {len(canonical):,} (district/college/state_agency/esd)")
    print(f"  district-name -> ccddd lookup: {len(name_to_ccddd):,} entries")

    moves = []
    for info in parsed:
        tgt = target_path(info, canonical, name_to_ccddd, src)
        moves.append((info["src"], tgt, info["kind"]))

    # Per-kind summary
    by_kind = defaultdict(int)
    for _, _, k in moves:
        by_kind[k] += 1
    print("Planned moves per kind:")
    for k in sorted(by_kind, key=lambda x: -by_kind[x]):
        print(f"  {by_kind[k]:>7,d}  {k}")

    # Collisions
    target_sources = defaultdict(list)
    for s, t, _ in moves:
        target_sources[t].append(s)
    collisions = {t: srcs for t, srcs in target_sources.items() if len(srcs) > 1}
    if collisions:
        print(f"WARNING: {len(collisions)} target collision(s):")
        for t, srcs in list(collisions.items())[:5]:
            print(f"  {t.relative_to(src)}")
            for s in srcs:
                print(f"    <- {s.name}")

    # Samples per kind
    print(f"\nSample target paths ({args.sample} per kind):")
    by_kind_samples = defaultdict(list)
    for s, t, k in moves:
        if len(by_kind_samples[k]) < args.sample:
            by_kind_samples[k].append((s, t))
    for k in sorted(by_kind_samples):
        print(f"  [{k}]")
        for s, t in by_kind_samples[k]:
            print(f"    {s.name}")
            print(f"      -> {t.relative_to(src)}")

    if not args.execute:
        print("\nDry-run only. Re-run with --execute to perform moves.")
        return

    if unparsed:
        sys.exit(f"\nRefusing to execute with {len(unparsed)} unparsed files. "
                 f"Fix classifier or stash them aside first.")
    if collisions:
        sys.exit(f"\nRefusing to execute with {len(collisions)} collisions.")

    print(f"\nExecuting {len(moves):,} moves...")
    moved = 0
    last_dir = None
    for s, t, _ in moves:
        if t.parent != last_dir:
            t.parent.mkdir(parents=True, exist_ok=True)
            last_dir = t.parent
        os.rename(s, t)
        moved += 1
        if moved % 5000 == 0:
            print(f"  ... {moved:,}/{len(moves):,}")
        if args.limit and moved >= args.limit:
            print(f"  (stopped at --limit {args.limit})")
            break
    print(f"Done. Moved {moved:,} files.")


if __name__ == "__main__":
    main()
