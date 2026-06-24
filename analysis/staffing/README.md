# analysis/staffing

Teaching-staffing analysis for Seattle Public Schools (ccddd 17001) from S-275 payroll, enrollment, and
school attendance areas. **Read [`../../STAFFING_ANALYSIS_GUIDE.md`](../../STAFFING_ANALYSIS_GUIDE.md)
first** — it documents every data source, the join keys, and the non-obvious gotchas (G1-G15).

## Run

```console
$ ./run_all.sh            # from repo root: extract -> plots -> HTML report
```

Or step by step (use the venv interpreter; run from this directory):

```console
$ ../../venv/bin/python3 extract.py            # one pass over AVRO/CSV/XLSX -> build/staffing.pkl
$ ../../venv/bin/python3 plot_ratios.py        # per-duty + basic-ed ratio graphs
$ ../../venv/bin/python3 plot_program_ratios.py# program-matched (basic-ed/non-sped, sped/sped)
$ ../../venv/bin/python3 plot_experience.py    # experience-by-school scatter + salary-vs-experience curve
$ ../../venv/bin/python3 gen_report.py         # seattle_s275_salary_by_duty.html (figures embedded)
```

## Files

| File | Purpose |
|---|---|
| `common.py` | paths, constants (duty/program codes, MINFTE, level restrictions), the shared faceted-scatter plotter |
| `extract.py` | reads `safs_prod/s275/*.avro`, `data/enrollment/...csv`, `data/safs/spsbtn/...xlsx`; writes `build/staffing.pkl` (the only cache) |
| `plot_ratios.py` | 8 per-duty + 4 Basic-Education-only student:FTE ratio graphs |
| `plot_program_ratios.py` | non-SpecEd:Basic-Ed-teacher and SpecEd:SpecEd-teacher (caseload) ratios |
| `plot_experience.py` | teacher experience distribution by school + the salary schedule curve |
| `gen_report.py` | recomputes salary/FTE tables from the cache and assembles the HTML report |

## Outputs (written to repo root, git-ignored as working data)

`seattle_s275_salary_by_duty.html` plus `seattle_ratio_*.jpg`, `seattle_school_experience_scatter.jpg`,
`seattle_teacher_salary_experience.png`. `build/` (the pickle cache) is git-ignored.

## Conventions

Facet by middle-school attendance area (`ms_assignment_code`); x = school; per-year dot bands oldest→newest
left-to-right; **plasma** colormap by year; black per-school mean line; linear y capped near the 98th
percentile; facets ordered by the most-recent-year (2024-25) value.
