# Repo-wide backlog

Open cross-cutting work items. Per-dataset open items live in
`extractors/fiscal/TODO.md` and `extractors/stars/TODO.md`; durable
coverage-gap catalogs live in the neighboring `COVERAGE.md` files.
(Extracted from the retired `Reorganize.md` plan; see git history for the
full executed reorg plan.)

- **Single output directory:** move `safs_prod/`, `output/`, `out_fiscal/`,
  `out_stars/`, `out_enrollment/` under one root (e.g. `out/`), updating
  `scripts/load_safs.sh` (`--outdir`), `extractors/{fiscal,stars}/build_sources.py`
  `--out-dir` defaults, the `Family.out_dir` values in
  `extractors/{fiscal,stars}/registry.py`, the `out_fiscal/` paths in the ~40
  `extractors/fiscal/extract_*.py` docstrings and their stars counterparts,
  and README/CLAUDE.md/doc references.
- **Fiscal/stars incremental re-parse path:** the bqload pipeline is
  seed-first (loads existing CSVs). Parsing only new/changed PDFs after a
  `data/` rsync — per-source-file manifest, delete-then-insert into the
  Postgres staging tables — is designed (see git history of the bqload plan)
  but not built.
- **Enrollment → BigQuery:** load `out_enrollment/` CSVs (see
  `docs/guides/ENROLLMENT_GUIDE.md`) via a bqload family; optional canonical
  school-id reconciliation for Section-4 names.
- **Bigsheet input provenance:** `region`/`ms_assignment_code` in
  `safs_domains.d_school` look hand-curated and are not reconstructable from
  OSPI sources; document or automate their derivation. (The bigsheet
  generator itself migrated to the website repo; `marts/` is a pointer.)
- **`extractors/purplebook.py` vs `extractors/purplebook/` package:** the
  package shadows the module on import, so the `.py` is likely dead. Needs
  owner confirmation before removing.
- **Owner-only:** triage `attic/data-candidates/` into `data/` (notably
  `AF1952526.accdb`, the probable 2025-26 F-195 database that would join the
  `load_safs.sh` globs); review `reference/input` / `reference/olddata` for
  irreplaceable raw data; empty the rest of `attic/`.
- **First full `push_data_to_gcs.sh` run** (~150 GB).
- **SAFS item-dictionary completion:** load the F-196 `*item_dictionary.xlsx`
  sidecars + multi-year fallback (plan in
  `extractors/fiscal/DATA_SOURCE_DIVERGENCE.md` § Item domain completion).
