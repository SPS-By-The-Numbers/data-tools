# Repository Reorganization Plan

Goal: make the repo layout understandable at a glance. Today the root holds ~150
loose working files (CSVs, PNGs, logs, scratch scripts) mixed in with real source
code, and human-reference material (`input/`, `olddata/`, `analysis/`, scratch
files) is interleaved with pipeline sources. After this plan executes:

- **All source code** lives in `extractors/`, `marts/`, `tools/`, `scripts/`,
  `bigquery/`, `docs/`. `bigsheet.py` — a key feature that joins all per-school
  data into one wide analysis sheet — is promoted out of the root into `marts/`.
- **`data/` is untouched and treated as read-only** — it is the tree that syncs
  to GCS, and nothing may be moved into it, created in it, or renamed within it.
  Root files that look like raw data are parked in `attic/` or `reference/` for
  the owner to place into `data/` (and sync) themselves if they choose.
- **Human reference material** (`input/`, `olddata/`, `regress/`, `stats/`,
  `analysis/`, root `scratch_*` files) lives under a single gitignored
  `reference/` directory — kept on disk, out of git.
- **Generated outputs** (`safs_prod/`, `output/`, `out_*/`) are gitignored in
  place, with a recorded TODO to later consolidate them under one output root.
- **Everything unclassifiable** is parked (not deleted) in `attic/` for the owner
  to review later.
- The repo root contains only: `README.md`, `CLAUDE.md`, `LICENSE`,
  `requirements.txt`, `.gitignore`, `Reorganize.md`, and directories.

This is a plan only. Execute the phases in order; each phase ends with a commit.

---

## Guardrails (read before doing anything)

1. **Never delete anything.** Files that look like junk (`foo.csv`, `tmp.csv`,
   logs) get *moved* to `attic/`, never `rm`'d. The owner deletes later.
2. **Move-as-a-unit only** for reference material: `input/`, `olddata/`,
   `regress/`, `stats/`, `analysis/`, and root `scratch_*` files are moved into
   `reference/` in a single `mv` each — never open, edit, reorganize, or clean
   their contents. They are unclean working messes by the owner's own account.
3. **Do not touch at all** (contents or location):
   - `out_fiscal/`, `out_stars/`, `out_enrollment/`, `out_stars.zip`, `output/`,
     `safs_prod/`, `SEA_Analysis/`
   - `venv/`, `.git/`, `.claude/`, `.pytest_cache/`, `__pycache__/`, `.DS_Store`
   These are handled only via `.gitignore` entries in Phase 5.
4. **Tracked vs untracked:** before moving any file, run
   `git ls-files --error-unmatch <path>` — if tracked, use `git mv`; if
   untracked, use plain `mv`. Never use `git add -A` or `git add .`; stage
   explicit paths only. Exception: `analysis/` is tracked but is being *removed
   from git on purpose* (Phase 3 explains the `git rm -r --cached` dance).
5. **Pre-existing dirty state:** `CLAUDE.md` and `docs/index.html` have
   uncommitted modifications that predate this reorg. Phase 0 checkpoints them
   so reorg commits stay clean.
6. **Collisions:** when moving a file into a destination where a same-named file
   already exists, compare with `cmp -s`. If identical, move the *source* copy to
   `attic/dupes/` instead. If different, move it with a `-2` suffix and record it
   in `attic/MANIFEST.md`.
7. **`data/` is read-only.** Move NOTHING into `data/`, create no files there
   (not even a README), rename nothing inside it. It mirrors the GCS bucket, and
   the sync scripts would propagate any stray addition to cloud storage. This
   also protects the pipeline: `load_safs.sh` picks inputs by glob
   (`data/safs/f195/*.accdb`, `data/safs/f196/*.csv`, ...), so any file dropped
   into `data/` could silently change pipeline input.
8. Moves are same-filesystem renames — even the 800 MB files are instant. Do not
   copy-then-delete.
9. After Phases 1, 2, 3, and 5, run the "quick check" subset of Phase 6 before
   committing.

---

## Target layout

```
data-tools/
├── README.md, CLAUDE.md, LICENSE, requirements.txt, Reorganize.md
├── extractors/          # ETL source code (unchanged internally, adopts strays)
│   ├── safs/  fiscal/  stars/  budget/  purplebook/  odata/  prr/
│   ├── enrollment_reports.py        # moved from root
│   └── p223_pdf_batch.py, p223_pdf_to_csv.py, ...
├── bigquery/            # legacy pre-SAFS loaders (unchanged; documented as legacy)
├── marts/               # downstream joined datasets ("data marts")
│   ├── __init__.py
│   ├── bigsheet.py      # KEY FEATURE: joins ALL per-school data into one wide sheet
│   └── README.md        # inputs, invocation, output contract
├── scripts/             # shell entry points
│   ├── load_safs.sh  do_assessment.sh  load_one_odata_by_code.sh
│   ├── pull_data_from_gcs.sh  push_data_to_gcs.sh
├── tools/               # ad-hoc analysis/CLI python (not part of the pipeline)
│   ├── analyze.py  plot.py  scatter.py  boxplot.py
│   ├── to_boss.py  odd_salary.py  avro_to_csv.py
├── docs/                # GitHub Pages site + dev guides
│   ├── index.html  montecarlo/  contentscripts/
│   └── guides/          # STAFFING_ANALYSIS_GUIDE.md, ENROLLMENT_HANDOFF.md
├── data/                # raw source data; syncs to gs://sps-btn-data-all-data/raw/
│   │                    # UNTOUCHED by this reorg — read-only, nothing moves in
│   ├── safs/  fiscal/  stars/  sps/  sqss/  assessment/  census/  map/
│   └── enrollment/  transit/
├── reference/           # gitignored — human reference, moved as-is, never cleaned
│   ├── analysis/  input/  olddata/  regress/  stats/  scratch/
│   └── prr/             # public-records-request document sets (moved from root)
├── attic/               # gitignored parking lot for unclassified root files
├── safs_prod/           # generated AVRO output (gitignored in place)
├── output/, out_*/      # generated (gitignored in place; see TODO below)
├── SEA_Analysis/        # gitignored in place, untouched
└── ...
```

**TODO (recorded, not executed now):** consolidate all generated output —
`safs_prod/`, `output/`, `out_fiscal/`, `out_stars/`, `out_enrollment/` — under
a single output root (e.g. `out/safs_prod`, `out/fiscal`, ...) and update
`load_safs.sh --outdir`, `extractors/fiscal/build_sources.py` defaults, the
`out_fiscal/` paths in ~40 `extractors/fiscal/extract_*.py` and
`extractors/stars/` docstrings, and README/CLAUDE.md/fiscal guides. Too much
path churn to bundle into this reorg; tracked in Follow-ups and as a TODO note
in README.

Deliberate non-move: `bigquery/` stays where it is (small, tracked, referenced
in CLAUDE.md); documented as legacy.

---

## Phase 0 — Checkpoint

1. `git status --porcelain > /tmp/reorg_before.txt` and
   `find data -maxdepth 2 | sort > /tmp/reorg_data_before.txt` (kept as proof
   that `data/` is never touched — see Phase 6).
2. Commit the pre-existing modifications as-is:
   ```
   git add CLAUDE.md docs/index.html
   git commit -m "Checkpoint: pre-reorg WIP in CLAUDE.md and docs/index.html"
   ```
3. Create the new directories:
   `mkdir -p scripts tools docs/guides reference/scratch reference/prr attic/dupes attic/logs attic/data-candidates`
4. Create `attic/MANIFEST.md` with a header line; append one line per file moved
   to attic in later phases (`- <original path> — <one-line guess at what it is>`).

## Phase 1 — Source code moves (mostly `git mv`)

### 1a. Shell entry points → `scripts/`
`git mv` (all tracked): `load_safs.sh`, `load_one_odata_by_code.sh`,
`pull_data_from_gcs.sh`, `push_data_to_gcs.sh`. Plain `mv` (untracked, then
`git add`): `do_assessment.sh`.

All of these assume they run from repo root (they use relative `data/...` paths
and `python3 -m extractors...`). Add this as the first non-shebang line of each:
```bash
cd "$(dirname "$0")/.." || exit 1
```
Keep them executable (`chmod +x scripts/*.sh`).

### 1b. Promote `bigsheet.py` → `marts/` (key feature, NOT a one-off)
`bigsheet.py` joins ALL per-school data — vitals, MAP scores (hc/non-hc), BEX
building condition/utilization/income, S-275 staffing churn, assessments, and
SQSS — into one wide per-school sheet for analysis. It is a proper pipeline
stage (a data mart built on extractor outputs), so it gets its own package:

```
mkdir -p marts && touch marts/__init__.py
git mv bigsheet.py marts/bigsheet.py
git add marts/__init__.py
```

It has no repo-internal imports, so both `venv/bin/python3 -m marts.bigsheet`
and `venv/bin/python3 marts/bigsheet.py` work unchanged — but it must run from
the repo root because it hard-codes relative input paths.

Write `marts/README.md` (~25 lines) documenting the contract as read from the
code — do not change the code:
- CLI inputs: `--vitals` (per-school vitals CSV), `--assessment` (assessment
  CSV), `-o` output CSV. Recent copies of these inputs sat at the repo root
  (`vitals.csv`, `assessment.csv`) and will be in `attic/` after Phase 4 —
  say so, since Phase 7 uses them as the ground-truth contract when rewiring
  these two inputs to BigQuery.
- Hard-coded inputs (all under the GCS-synced tree):
  `data/sps/map/map-score-2017-2024-average-{hc,nonhc}.csv`,
  `data/sps/building/{bex-vi-historic-building-scores,utilization_condition,income_by_school}.csv`,
  `data/sps/s275/building_transitions.csv`, `data/sps/sqss/sqss.csv`.
- Invocation example, and the join keys (`school_code`, `class_of`).

### 1c. Ad-hoc analysis python → `tools/`
Move: `analyze.py`, `plot.py`, `scatter.py`, `boxplot.py`, `to_boss.py`,
`odd_salary.py`, `avro_to_csv.py`. (`analyze.py` and `plot.py` are tracked →
`git mv`; check each of the rest per Guardrail 4, and `git add` the untracked
ones after moving so `tools/` is fully tracked.)

Note in `tools/README.md` (create it, ~5 lines): these are ad-hoc scripts that
operate on pipeline outputs; some reference input CSVs by root-relative name
that may now live in `attic/` — fix paths on next use, don't chase them now.

### 1d. Extractor strays
- `mv enrollment_reports.py extractors/enrollment_reports.py && git add extractors/enrollment_reports.py`
  (it is a finished extractor per `ENROLLMENT_HANDOFF.md`; it should be tracked).
- `git mv extractors/FISCAL_HANDOFF.md extractors/fiscal/HANDOFF.md`
- `foo_stars_analysis.py`, `foo_stars_join.py`, `foo.py` are scratch → `attic/`
  (Phase 4 covers them; fine to do now).

### 1e. Dev guides → `docs/guides/`
- `STAFFING_ANALYSIS_GUIDE.md` is tracked:
  `git mv STAFFING_ANALYSIS_GUIDE.md docs/guides/`
- `mv ENROLLMENT_HANDOFF.md docs/guides/ && git add docs/guides/ENROLLMENT_HANDOFF.md`

### 1f. Update references
Grep and fix every reference to the moved paths:
```
grep -rn "load_safs.sh\|bigsheet\|STAFFING_ANALYSIS_GUIDE\|ENROLLMENT_HANDOFF\|FISCAL_HANDOFF\|enrollment_reports.py" \
  README.md CLAUDE.md docs extractors marts tools scripts --include='*.md' --include='*.py' --include='*.sh' --include='*.html'
```
Expected touch points: `CLAUDE.md` (commands section: `./scripts/load_safs.sh`,
`tools/` script list; also **remove `bigsheet.py` from the "ad-hoc analysis
scripts" list** and describe `marts/bigsheet.py` as a first-class stage that
joins all per-school data), `README.md`, `docs/guides/ENROLLMENT_HANDOFF.md`
(references `enrollment_reports.py` by path), `extractors/fiscal/*.md`.
Do NOT edit anything under `analysis/` or other reference material.

### 1g. Verify + commit
`venv/bin/pytest` must pass; `bash -n scripts/*.sh` must pass;
`venv/bin/python3 -m extractors.safs.from_raw_file --help` and
`venv/bin/python3 -m marts.bigsheet --help` must run.
```
git commit -m "Reorg: promote bigsheet to marts/, shell entry points to scripts/, ad-hoc analysis to tools/, guides to docs/guides/"
```

## Phase 2 — Park root data-like files (NOTHING moves into `data/`)

Several root files look like raw source data, but per Guardrail 7 they must NOT
be placed into `data/` — the owner will triage them into `data/` and sync to
GCS themselves later, if they choose. Park them in `attic/data-candidates/`
(flat; one `attic/MANIFEST.md` line each noting the likely `data/` destination):

| File(s) | Manifest note (suggested eventual home — do NOT move there) |
|---|---|
| `2023-2024-purple-book.txt`, `2024-2025-purple-book.txt`, `2025-2026-purple-book-2-26.pdf/.txt`, `2024-2025-recommended-budget.pdf/.txt` | likely `data/sps/budget/` |
| `AF1952526.accdb` | name suggests the 2025-26 F195 SAFS database; would join `data/safs/f195/` and the `load_safs.sh` globs — owner decision |
| `2023-2024-sqss.avro` | likely `data/sqss/` (a similar file may already exist there) |
| `apportionment.mhtml` | likely `data/fiscal/` |
| `Student Transportation Allocation (STARS) Reports _ OSPI.mhtml` | likely `data/stars/` |

The PRR document sets are curated human-reference collections (they have their
own READMEs/FINDINGS) → `reference/prr/`:
```
mv prr_transportation reference/prr/transportation
mv prr_transportation.zip reference/prr/transportation.zip
mv prr_pricing_extract reference/prr/pricing_extract
mv prr_pricing_extract.zip reference/prr/pricing_extract.zip
```
Then check nothing in code hard-codes the old names:
`grep -rn "prr_transportation\|prr_pricing_extract" extractors marts tools scripts --include='*.py' --include='*.sh'`
— `extractors/prr/transit/` scripts take paths as CLI args, but fix any
defaults/docstrings found.

No commit — every path touched here is untracked and becomes gitignored in
Phase 5. Sanity check before moving on: `ls data` output is byte-identical to
what it was in `/tmp/reorg_before.txt`-time (`git status` never lists `data/`
anyway; use `find data -maxdepth 1 | sort` before and after Phase 2 to prove
`data/` was not touched).

## Phase 3 — Quarantine human-reference material into `reference/`

These are kept for human reference only — per the owner, unclean messes. Move
each **as a single unit** (Guardrail 2); do not look inside or tidy them.

```
mv input    reference/input
mv olddata  reference/olddata
mv regress  reference/regress
mv stats    reference/stats
mv scratch_* reference/scratch/        # all root scratch_* files
```

`analysis/` is special: its files are **tracked**, and the owner wants it out of
git (it becomes gitignored reference material). Remove it from the index while
keeping the files on disk, then move it:
```
git rm -r -q --cached analysis
mv analysis reference/analysis
git commit -m "Reorg: untrack analysis/ and move human-reference dirs (analysis, input, olddata, regress, stats, scratch_*) under reference/"
```
This commit records the deletion of `analysis/*` from the repo — that is
intended; full history remains reachable via git. The working files live on
untouched at `reference/analysis/`.

Reference fixups (text edits only, outside `reference/`):
- `CLAUDE.md` mentions `analysis/` paths (e.g. `analysis/map_rit_scatter.py`,
  working-directory list) — update to `reference/` or drop in Phase 5c.
- Claude memory index (outside the repo, skip silently if absent): in
  `/Users/albert/.claude/projects/-Users-albert-src-sps-data-tools/memory/`,
  `ridership-montecarlo-project.md` points at `analysis/montecarlo/` →
  `reference/analysis/montecarlo/`; `teaching-staffing-analysis.md` points at
  `STAFFING_ANALYSIS_GUIDE.md` (root) → `docs/guides/`;
  `enrollment-report-ingestion.md` points at `ENROLLMENT_HANDOFF.md` →
  `docs/guides/`.

## Phase 4 — Attic sweep of the remaining root files

Everything still loose at the root that is not in the keep-list below goes to
`attic/` (flat, keep original filename; logs into `attic/logs/`), with one
manifest line each.

**Keep at root:** `README.md`, `CLAUDE.md`, `LICENSE`, `requirements.txt`,
`.gitignore`, `Reorganize.md`, `.DS_Store`, `out_stars.zip` (out_* family,
untouched), and all directories.

**Known attic-bound inventory** (not exhaustive — apply the rule above as the
source of truth, since the root has drifted before):

- Derived CSVs: `assessment*.csv`, `assal_outliers.csv`, `tfinsal_outliers.csv`,
  `attend.csv`, `boss.csv`, `dict.csv`, `district_office_transitions.csv`,
  `map_rit_delta_stats*.csv`, `outlier.csv`, `output.csv`, `sofg_goals-*.csv`,
  `vitals.csv`, `wide.csv`, `tmp.csv`, `foo.csv`, `moo.csv`,
  `x-district-exp.csv`, `x-district-rev.csv`, `transit-expenditures.csv`,
  `address-mapping.csv`, `stranger-endorsement.csv`, `time-endorsement.csv`
- Images/plots/reports: `ela.png`, `math.png`, `my_plot.png`, `map_rit_*.png`,
  `map_rit_delta_report.pdf`, `expenditures.svg`, `revenues.svg`,
  `seattle_*.jpg/.png/.html`, `sps_*.png/.html`, `stranger.svg`,
  `stranger.afdesign`, `times.svg`, `seattle_purchased_services_review.html`
- Data blobs of unknown provenance: `pdc` (803 MB AVRO), `expenditures.avro`,
  `moo.json`, `SjuasQNeIKA.json`
- Scratch code/text: `foo`, `foo.py`, `foo.txt`, `foo_stars_analysis.py`,
  `foo_stars_join.py`, `only`, `raw_info`, `top.columns`, `s275_schemas.txt`,
  `test.txt`, `dumptypes.c`, `dumptypes.h`, `types.h`
- Logs → `attic/logs/`: `latest_load.log`, `run.log`, `s275.log`, `load_all`
  (despite the name, it is a log of a pipeline run)

No commit content here beyond the manifest — `attic/` gets gitignored in
Phase 5, so just verify the root listing is clean: `ls -p | grep -v /` should
show only the keep-list files.

## Phase 5 — `.gitignore`, sync scripts, top-level docs

### 5a. `.gitignore`
Replace the current tail section (the lines from `# This directory should be in
gcs.` down) with:
```gitignore
# macOS
.DS_Store

# Raw source data — synced to GCS, never committed, read-only for tooling
data/

# Generated pipeline outputs — reproducible from data/ + extractors/.
# TODO: consolidate these under a single output root (e.g. out/) and update
# load_safs.sh --outdir, extractors/fiscal + extractors/stars output paths,
# and the docs that reference safs_prod/ and out_fiscal/. See Reorganize.md.
safs_prod/
output/
out_*
out_*/

# Human reference material (old inputs, old analyses, scratch) — kept on disk only
reference/

# Parked clutter pending owner triage
attic/
SEA_Analysis/
*.log

*.sw[op]
```
(Drop the now-obsolete `input/`, `output/`, `data/`, `out_stars/` lines being
replaced; keep everything above that section — Python boilerplate and
`.claude/settings.local.json` — unchanged. `out_*` without the slash also
covers `out_stars.zip`.) Verify no tracked file becomes ignored:
`git ls-files -i -c --exclude-standard` must print nothing.

### 5b. GCS sync scripts
Today `push_data_to_gcs.sh`/`pull_data_from_gcs.sh` only sync `data/safs` and
`data/sps` to `gs://sps-btn-data-all-data/raw/{safs,sps}`. Per the owner,
**everything in `data/` should sync**. Rewrite both around a shared subdir
loop, preserving the existing `raw/<subdir>` layout:

```bash
#!/bin/bash
# push_data_to_gcs.sh — mirror local data/ to GCS. Pass subdir names to limit,
# e.g. ./scripts/push_data_to_gcs.sh safs sps
# NOTE: first full push is ~150 GB (data/fiscal alone is ~142 GB) — run deliberately.
cd "$(dirname "$0")/.." || exit 1
BUCKET=gs://sps-btn-data-all-data/raw
subdirs=("$@")
[ ${#subdirs[@]} -eq 0 ] && subdirs=($(cd data && ls -d */ | tr -d /))
for d in "${subdirs[@]}"; do
  gcloud storage rsync "data/$d" "$BUCKET/$d" --recursive
done
```
`pull_data_from_gcs.sh` is the mirror image (`rsync "$BUCKET/$d" "data/$d"`),
with the subdir list defaulting to `gcloud storage ls "$BUCKET/"` when no args
are given. **Do not run the push** — the first full sync is an owner decision;
flag it in the final report.

### 5c. `README.md` and `CLAUDE.md`
Add/refresh a "Repository layout" section in both matching the tree in this
plan (top-level dirs, one line each), including one line each for `marts/`
("joined per-school datasets; `bigsheet.py` merges everything we have per
school"), `reference/` ("human reference only, gitignored, never cleaned by
tooling"), and `attic/` ("pending owner triage"). Since no README may be
created inside `data/`, document the `data/` tree in the top-level README
instead: one line per subtree (`safs`, `fiscal`, `stars`, `sps`, `sqss`,
`assessment`, `census`, `map`, `enrollment`, `transit`), approximate sizes
(`data/fiscal` is ~142 GB), the GCS bucket mapping (5b), and the rule that
`data/` holds raw source only, is read-only for tooling, and only the owner
adds to it. Update all command examples:
`./scripts/load_safs.sh`, `./scripts/push_data_to_gcs.sh`, `tools/plot.py`,
etc. Carry the **single-output-directory TODO** into README verbatim (short
form: "TODO: `safs_prod/`, `output/`, `out_*` should move under one output
root; requires coordinated updates to `load_safs.sh` and fiscal/stars extractor
paths"). In README, note `bigquery/` is a legacy pre-SAFS loader kept for
reference. In CLAUDE.md, update the "Working in this repo" bullet that lists
working directories (`input/`, `olddata/`, `regress/`, `stats/`, `analysis/`
are now under `reference/`; `attic/` holds parked root clutter) and remove or
update any `analysis/` path mentions.

### 5d. Optional but recommended: pin pytest collection
Create `pytest.ini` at root so pytest never wanders into `reference/`, `attic/`,
or `data/`:
```ini
[pytest]
testpaths = extractors marts
```

### 5e. Commit
```
git add .gitignore scripts/push_data_to_gcs.sh scripts/pull_data_from_gcs.sh README.md CLAUDE.md pytest.ini
git commit -m "Reorg: gitignore data/, generated outputs, reference/, attic/; sync all of data/ with GCS; document layout"
```
(Note: `git add` must touch nothing under `data/` — there is nothing trackable
there by design.)

## Phase 6 — Verification

Quick check (also run mid-plan as noted):
1. `venv/bin/pytest` — all tests pass.
2. `bash -n scripts/*.sh` — all parse.
3. `venv/bin/python3 -m extractors.safs.from_raw_file --help`,
   `venv/bin/python3 -m extractors.fiscal.build_sources --help`, and
   `venv/bin/python3 -m marts.bigsheet --help` run from repo root.

Full check:
4. `ls -p | grep -v /` shows only: `README.md CLAUDE.md LICENSE requirements.txt Reorganize.md out_stars.zip` (plus `.DS_Store`).
5. `git status --porcelain` is empty (no unexpected deletions, no stray
   untracked files — everything is either committed or ignored).
6. `git ls-files -i -c --exclude-standard` prints nothing.
7. `git ls-files | grep '^analysis/'` prints nothing (analysis fully untracked),
   and `ls reference/analysis/montecarlo/NOTES.md` still exists on disk.
8. Grep for stale references:
   `grep -rn "olddata\|^input/\|analysis/\|prr_transportation\|\./load_safs" README.md CLAUDE.md docs extractors tools scripts --include='*.md' --include='*.py' --include='*.sh'`
   — anything found must either be fixed or be a deliberate historical mention.
9. **`data/` untouched:** `find data -maxdepth 2 | sort | diff /tmp/reorg_data_before.txt -`
   produces no output. This is a hard requirement — any diff means Guardrail 7
   was violated and must be reverted before finishing.
10. Do **not** run `./scripts/load_safs.sh` end-to-end (needs local Postgres and
    GCP credentials, and rewrites BigQuery tables). The `--help` smoke tests plus
    pytest are the bar.
11. Report to the owner: files parked in `attic/` (point at `attic/MANIFEST.md`),
    any Guardrail-6 collisions, the `attic/data-candidates/` items awaiting
    owner placement into `data/` (notably `AF1952526.accdb`), confirmation that
    `analysis/` was untracked and moved to `reference/analysis/` intact, proof
    that `data/` was not modified (check 9), and that the expanded GCS push has
    NOT been run.

## Phase 7 — `marts/bigsheet.py`: read vitals + assessment from BigQuery

Separate from the reorg on purpose: Phases 0–6 must be committed and verified
first, so this redesign can fail or be reverted without touching the reorg.
This phase changes behavior; everything before it was move-only.

**Intent (from the owner):** the `--vitals` and `--assessment` flags currently
take pre-baked CSVs whose derivation is recorded nowhere in this repo. They
should instead pull from BigQuery, making the bigsheet reproducible end-to-end.

### 7a. Facts already established (do not re-derive)
- BigQuery project `sps-btn-data`; table ids follow
  `sps-btn-data.<bq_dataset>.<table>` (`extractors/safs/gcloud_load_tables.py:46`).
  `assessment`/`sqss` land in dataset `ospi` (tables `rc_assessment`,
  `rc_sqss`); other pipeline datasets land in `safs_<name>`
  (`safs_enrollment.enrollment`, `safs_f19x.*`, `safs_s275.*`, `safs_domains.*`).
- `google-cloud-bigquery==3.31.0` is already in `requirements.txt`. **Gotcha:**
  `QueryJob.to_dataframe()` additionally requires the `db-dtypes` package — add
  it to `requirements.txt` and `venv/bin/pip install` it.
- Auth is Application Default Credentials. If a query fails with an auth error,
  stop and tell the owner to run `! gcloud auth application-default login` —
  do not attempt other credential mechanisms.
- `ospi.rc_assessment` (see `extractors/safs/schemas/assessment.py`) has
  `school_code`, `school_year`, `grade_level`, `test_subject`,
  `test_administration`, `student_group`, `pct_noscore`, `pct_alternative`,
  `pct_met_standard`, ... — but **not** `class_of`,
  `pct_met_standard_numeric`, or `pct_met_standard_numeric_nodat`. Those are
  derived columns that exist only in the pre-baked CSVs.

### 7b. Recover the input contracts
Read the headers plus ~50 sample rows of `attic/assessment.csv` and
`attic/vitals.csv` (also compare `attic/assessment-1-2-5-6.csv` etc. — pick the
file whose columns match what `marts/bigsheet.py` consumes:
`select_assessments()` needs `class_of, school_code, grade_level,
test_administration, test_subject, student_group, pct_noscore, pct_alternative,
pct_met_standard_numeric, pct_met_standard_numeric_nodat`; the vitals path
needs `school_code, class_of, school_name, type, region, is_regular,
ms_assignment_code, all_students, spend_*_per_pupil,
class_teacher_* / num_class_teachers* / asst_principal_fte /
other_teacher_fte` — confirm the full list from the code, not this summary).
Record both contracts (column, dtype, example) in `marts/README.md`.

### 7c. Reconstruct each input as a BigQuery query
Work one input at a time, validating against the attic CSV as ground truth:

- **assessment** (expected to be tractable): base table `ospi.rc_assessment`.
  Derive `class_of` from `school_year` + `grade_level` and
  `pct_met_standard_numeric` from `pct_met_standard` (suppression markers
  cast to NULL; the `_nodat` variant differs in how no-data rows are treated).
  Do NOT trust those formula sketches — determine the actual rules by fitting
  against `attic/assessment.csv` rows and prove them: recompute the CSV from
  the query and require exact agreement on the overlapping year range (BQ may
  simply contain newer years; extra rows are fine, contradicting rows are not).
- **vitals** (may not be reconstructible): candidate sources are
  `safs_enrollment.enrollment` (enrollment counts), `safs_f19x.*` (per-school
  spend → the `spend_*_per_pupil` columns), `safs_s275.*` (teacher counts, FTE,
  experience percentiles — heed the FTE gotcha: sum `fte_in_assignment`, not
  `assignment_fte`), `safs_domains.*` (school directory: name/type/region).
  Some columns (`region`, `ms_assignment_code`) may exist nowhere in BQ.

**Stop rule:** if a column of either contract cannot be reproduced from BQ with
a verifiable match against the attic CSV, do NOT guess or silently drop it.
Implement what verifies, keep the CSV path working for the rest, and report
exactly which columns resisted reconstruction and why. A partially-migrated
bigsheet with an honest README beats a fully-migrated one with quietly wrong
numbers.

### 7d. CLI redesign
Keep the join/pivot logic untouched; change only input acquisition:
- `--vitals` / `--assessment` become optional. When omitted, fetch from
  BigQuery via the queries from 7c (store each query as a named constant or a
  `.sql` file under `marts/`). When given a CSV path, behave exactly as today
  (offline/fallback mode).
- Add `--bq-project` defaulting to `sps-btn-data`.
- Structure: `def load_vitals(args) -> DataFrame` / `def load_assessment(args)
  -> DataFrame` that branch on flag presence; `main()` otherwise unchanged.

### 7e. Verify + commit
1. `venv/bin/python3 -m marts.bigsheet --vitals attic/vitals.csv --assessment attic/assessment.csv -o /tmp/sheet_csv.csv` — CSV mode still works.
2. `venv/bin/python3 -m marts.bigsheet -o /tmp/sheet_bq.csv` — BQ mode runs.
3. Compare the two outputs: identical column sets; on the shared
   `(school_code, class_of)` rows, values agree (allow BQ-side extra rows from
   newer data; report any disagreement instead of papering over it).
4. Update `marts/README.md` (both modes, the queries, any unreconstructed
   columns) and commit:
   `git add marts requirements.txt && git commit -m "Marts: bigsheet reads vitals/assessment from BigQuery, CSV flags become offline fallback"`

---

## Follow-ups (out of scope — do not do these now)

- **Single output directory (recorded TODO):** move `safs_prod/`, `output/`,
  `out_fiscal/`, `out_stars/`, `out_enrollment/` under one root (e.g. `out/`),
  updating `scripts/load_safs.sh` (`--outdir`), `extractors/fiscal/build_sources.py`
  `--out-dir` default, the `out_fiscal/` paths in the ~40
  `extractors/fiscal/extract_*.py` docstrings and their `extractors/stars/`
  counterparts, and README/CLAUDE.md/`extractors/fiscal/*.md` references.
- **`marts/bigsheet.py` further hardening** (beyond Phase 7): turn the
  hard-coded `data/sps/...` input paths into CLI flags with those defaults, and
  resolve any columns Phase 7 could not reconstruct from BigQuery (owner may
  know their provenance — e.g. `region`/`ms_assignment_code` look hand-curated).
- `extractors/purplebook.py` coexists with the `extractors/purplebook/` package;
  the package shadows the module on import, so the `.py` is likely dead. Needs
  owner confirmation before renaming/removing.
- **Owner-only:** triage `attic/data-candidates/` into `data/` (notably
  `AF1952526.accdb` — name suggests the 2025-26 F195 database, which would join
  the `load_safs.sh` globs) and sync; likewise review whether anything in
  `reference/input` or `reference/olddata` is irreplaceable raw data that
  belongs in `data/` (and therefore GCS).
- Review and empty the rest of `attic/`.
- The first full `push_data_to_gcs.sh` run (~150 GB).
