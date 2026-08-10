# School vs District Office compensation split — reconstruction from BigQuery

How the "Cracking the Budget" compensation split (Teaching / Student Support /
Building Support / Other, School vs District Office) is computed, what it
found, and how to reproduce it. Rebuilt August 2026 from the author's workbook
`Medium #3 = Cracking thd Budget Part 1.xlsx` (Summary sheet), replacing its
hardcoded values with database pulls wherever the database can supply them.

Scripts (run from repo root; both cache query results under `./out_summary/`,
gitignored — delete a CSV to force a re-pull):

```console
$ venv/bin/python3 tools/bb_summary_from_db.py      # the Budget Book chain
$ venv/bin/python3 tools/pb_actuals_reconcile.py    # school-side S-275 cross-check
```

Data: `sps-btn-data.safs_f19x.general_fund_expenditures` (F-195 budget +
F-196 actuals), `safs_s275.*` (staff/payroll), `safs_domains.*` (code tables).
All Seattle Public Schools (`ccddd = 17001`), General Fund, compensation =
objects 2 (certificated salaries), 3 (classified salaries), 4 (benefits).

---

## 1. The four activity buckets

OSPI activity codes, as the workbook groups them (note: these differ from the
post #2 chart scripts' buckets — see §7):

| Bucket | Activities |
|---|---|
| Teaching Related | 27 Teaching, 28 Extracurricular, 34 Professional Learning–State |
| Student Support | 84 Principal (debt; $0 comp), 23 Principal's Office, 24 Guidance & Counseling, 25 Pupil Mgmt & Safety, 26 Health & Related, 35 Pupil Safety |
| Building Support | 62 Grounds, 63 Operations of Buildings, 64 Maintenance, 65 Utilities, 74 Warehousing, 44 Operations–Food Service, 67 Building & Property Security |
| Other comp | everything else (residual) |

## 2. Primary-material inputs (the only hardcoded numbers)

Five values per pair of years cannot come from OSPI data and are transcribed
from primary documents. **F-195 budget rows carry no school codes, so "how
much was allocated to schools" is fundamentally absent from the database** —
the Budget Book total is the irreducible external input.

| Input | 2023-24 | 2024-25 | Source |
|---|---:|---:|---|
| School Allocated Comp | 634,579,723 | 660,376,817 | Budget Book school-allocation section |
| Non-grant School Allocated Comp | 585,466,859 | 607,948,098 | same (reported, unused in chain) |
| PB Teaching+Librarian+Other | 510,496,137 | 511,623,813 | Purple Book |
| PB Principal's Office | 66,478,371 | 68,213,544 | Purple Book |
| PB Guidance & Counseling | 21,038,425 | 20,660,973 | Purple Book |

Everything else in the workbook — object totals, per-activity budget comp,
the chronic-underspend constants, the 2016-2024 medians — is reproduced by
the database to within rounding (object literals match to ~$2k).

## 3. The budget-side chain (Purple Book carve)

The Budget Book gives one school-allocated comp total with no activity split.
The Purple Book carves it: its Principal's Office allocation ≈ the whole of
activity 23, its Guidance allocation is the school-allocated slice of
activity 24, and Teaching absorbs the residual (including Seattle Ed Levy
money that never passes through the PB process):

    school Teaching        = BB total − PB Principal's Office − PB Guidance
    school Student Support = PB Principal's Office + PB Guidance
    school Building/Other  = 0 (by construction)
    DO (non-school) bucket = bucket's total budget comp − its school piece

The PB could be dropped by substituting F-196 school-coded actuals for
activities 23+24 — Principal's Office substitutes within $2M, but Guidance
actuals run ~$14M above the PB allocation (program-funded counselors), so the
substitution shifts ~$12M between Teaching and Student Support and blurs the
allocated-vs-spent reading. **Decision: keep the PB/Budget-Book version.**

## 4. Chronic underspend (budget − actuals, all objects)

The workbook's constants are rounded copies of true variances; the DB
recomputes them. Corrections found:

- **Supervision-Instruction "3.7M" is a transcription error** — the actual
  2023-24 variance is $5.35M (likely copied from the Principal's Office line).
  Knock-on: the pie graphic's "8.7% Other Staff" is 8.5% corrected.
- Two formula off-by-ones in the workbook reference empty cells: `C129`
  (2024 total, misses Building's $1.7M) and `C150` (median total, misses
  Building's $1.3M). Downstream Δ-rows compute independently and are correct.
- Median(2016-2024) recomputed: Teaching $48.7M (vs $50M), Principal's
  Office $1.7M (vs $1.4M), Building $1.3M (exact), Other $4.8M (vs $4.7M).
  Construction: per-activity medians summed, Teaching pooling 27+34 per year.

## 5. The actuals side needs no Purple Book

F-196 actuals carry building codes from 2019-20 on, so the school/DO split is
directly observable. Two conventions:

- **Parked pools count as District Office ("Centrally Managed Teaching").**
  `c_in_school_allocated_staff` (set in `extractors/safs/transforms/f19x.py`)
  flags comp at building 1002 in activities 27/23/24/84: school-serving staff
  never allocated to a specific school — $55.1M (2023-24) / $61.5M (2024-25),
  composition ~1/3 special-ed itinerants, ~1/4 a central bilingual pool
  (strikingly, ~60% the size of all school-side bilingual spend), rest
  levy/Title/pilot/basic-ed pools. 94% of central Teaching actuals is this.
- S-275 and F-196 disagree on where support staff sit: custodians/food
  service are at central codes in S-275 but charged to school buildings in
  F-196. The S-275 duty×activity cross-check (`pb_actuals_reconcile.py`,
  methods A/B/C) confirms S-275 duty and activity coding agree internally
  (off-diagonals ~$9M of ~$499M) and that the Purple-Book-comparable school
  comp is best computed as F-196 school comp in activities 22/23/24/27 with
  within-activity duty shares (strips substitutes, which the PB does not
  allocate).

## 6. The reconciled table (2024-25; both columns tie to objects 2+3+4 to the dollar)

| Category | Side | Xlsx row | Budget $M | Actuals $M |
|---|---|---|---:|---:|
| Teaching Related | School | 51 | 571.5 | 571.6 |
| Student Support | School | 52+53 | 88.9 | 110.8 |
| Building Support | School | — | 0.0 | 22.6 |
| Other comp | School | — | 0.0 | 27.9 |
| Teaching Related | District Office | 115 | 113.4 | 54.9 |
| Student Support | District Office | 116 | 84.9 | 59.5 |
| Building Support | District Office | 117 | 66.7 | 39.7 |
| Other comp | District Office | 118 | 118.6 | 91.6 |
| **Total** | | | **1,044.0** | **978.6** |

Readings: the WSS teaching allocation was spent almost exactly (571.5 vs
571.6, closeness real, near-identity coincidence); schools run $70M of
non-allocated staff (health/safety, custodians, food service) who physically
sit at schools; every DO row underspends its budget-side estimate — the
$65.4M total gap is the 2024-25 comp underspend. On a like-for-like
role-and-activity basis, school-allocated actuals ≈ the Budget Book
allocation (+$0.0M in 2023-24, +$8.2M in 2024-25): **schools spend what they
are allocated; the surprises live in the parked pools and the underspend.**

## 7. Caveats

- The post #2 chart scripts (`build_charts.py` in the staffing scratch area)
  use different buckets: Teaching {27,28}, Student Support includes 67,
  Building {61-65,68}. Do not mix the two definitions in one figure.
- Workbook's BB school-allocs tab sums to $632.6M for 2023-24 where its
  Summary hardcodes $634.6M — small snapshot/definition gap in the primary
  source, unresolved.
- Budget school split only exists via the BB/PB carve; actuals school split
  only exists from 2019-20 (no school codes earlier, and none on budget rows).
