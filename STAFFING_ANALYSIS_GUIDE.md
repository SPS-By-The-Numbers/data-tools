# Teaching Staffing Analysis — Data Guide & Gotchas

Reference for analyzing Seattle Public Schools (SPS) teaching staffing from S-275 payroll +
enrollment + school metadata. Load this before starting analysis. Everything here was verified
against the actual files in this repo (Dec 2025 pipeline run, data through school year 2024-25).

**District of interest:** `ccddd = 17001` = Seattle Public Schools.

---

## 0. Environment

- Use the venv interpreter directly: `venv/bin/python3` (don't bother activating). Needs `fastavro`,
  `openpyxl`, `numpy`, `matplotlib`.
- The big AVRO files are read by **streaming** (`fastavro.reader`) — `assignment.avro` is ~100 MB and
  `private_assignment.avro` ~360 MB. One streaming pass + a dict is the pattern; don't load to a DataFrame blindly.
- Avoid `Date.now()`-style nondeterminism only matters for the Workflow tool, not normal scripts.

---

## 1. Where the data is

### S-275 staff/payroll — `safs_prod/s275/*.avro`
One row per the grain below. `private_*` tables hold the salary/PII columns; non-private hold structure.

| File | Grain | Key columns |
|---|---|---|
| `report.avro` | one per district-year | `report_id`, `school_year`, `ccddd`, `report_type`, `district` |
| `report_employee.avro` | one per person-year | `report_employee_id`, `report_id`, `employee_id`, **`experience_years`**, `highest_degree`, `highest_degree_year` |
| `private_report_employee.avro` | one per person-year | `report_employee_id`, **`total_final_salary`**, `insurance`, `benefits`, `other_salary` |
| `employee.avro` | one per person-year | `employee_id`, **`obfuscated_id`** (stable cross-year person key), `c_*` cached cols |
| `assignment.avro` | one per assignment (a person has many) | `assignment_id`, `report_employee_id`, **`report_id`**, `school_code`, **`program_code`**, `activity_code`, **`duty_root_code`**, `duty_suffix_code`, `grade`, **`fte_in_assignment`**, `is_major` |
| `assignment_fte.avro` | per fte profile | `assignment_fte_id`, `fte_hours`, `fte_days`, `certificated_fte`, `classified_fte`, `is_certificated` |
| `private_assignment.avro` | one per assignment | `assignment_id`, `assignment_salary`, `c_pct_of_assignments`, `c_est_total_final_salary` (per-assignment apportioned salary) |
| `private_assignment_comp_base.avro` | comp base | `certificated_base`, `classified_base` |

### Domains — `safs_prod/domains/*.avro`
- `d_duty_root.avro` — `duty_root`, `duty_name`, `duty_name_category`. **Job titles.** (see §4)
- `d_duty_suffix.avro` — `duty_suffix`, `duty_contract_type`. (see gotcha G8)
- `d_school.avro` — `school_code`, `school` (name), `type` (Elementary/Middle/High/…), `is_regular`,
  `region`, **`ms_assignment_code`**, **`is_district_office`**.
- `d_program.avro` — `program_code`, `program`, `per_pupil_program`. (see §5)

### Enrollment — `data/enrollment/rc_enrollment_17001.csv`
Per (school_year, school, grade). Columns include `all_students`, **`students_with_disabilities`**,
`low_income`, `english_language_learners`, `highly_capable`, race/gender breakdowns.
- "District Total" rows (blank `school_code`) aggregate by grade; per-school rows have a real `school_code`.
- Grade `All Grades` = sum of grades **including PK**. Use `school_name=='District Total' & grade=='All Grades'`
  for district totals, or `school_code present & grade=='All Grades'` for per-school totals.
- ⚠️ School-year format is `2014-15` here vs `2014-2015` in S-275 — convert: `y[:4]+'-20'+y[5:7]`.

### School metadata / attendance areas — `data/safs/spsbtn/9998-9999-spsbtn.xlsx`
The **`schools`** tab: columns `ccddd, school_code, school_and_district, type, is_regular, region, ms_assignment_code`.
`ms_assignment_code` = the **middle-school attendance area** (the middle school a school feeds into; a
middle school points to itself). 12 areas for Seattle. Read with `openpyxl` (`data_only=True`).
(Other tabs: programs, activities, object, nces, funds, duty_root, duty_suffix, purpleschool.)

---

## 2. How to join

```
report (ccddd==17001)                 # pick Seattle, report_id -> school_year (12 yrs: 2013-14..2024-25)
  └─ report_id ─────────────┐
report_employee             │         # one row per person-year; has experience_years
  ├─ report_employee_id ──┐ │
  ├─ employee_id ──> employee.obfuscated_id   # STABLE person id across years
  └─ report_id ───────────┼─┘
private_report_employee     │         # total_final_salary  (join on report_employee_id)
  └─ report_employee_id ──┘
assignment                            # duty + school + program + FTE; one person has many
  ├─ report_employee_id  -> link to the person/salary
  ├─ report_id           -> school_year  (assignment carries report_id directly — no need to go via report_employee)
  ├─ duty_root_code      -> d_duty_root
  ├─ program_code        -> d_program
  └─ school_code         -> d_school / enrollment.school_code / spsbtn.school_code
```

Key facts that make joins clean:
- **`assignment.report_id` is populated**, so you can get school_year per assignment without the report_employee join.
- **Every employee has exactly one `is_major == True` assignment** → use it as the person's "primary duty/school."
- **`obfuscated_id`** (in `employee`) is the only stable person key across years (`employee_id`/`report_employee_id`
  are per-year). Use it for cohort/transition analysis (e.g. did a person change duty between years).

### Minimal recipe (per-employee salary by primary duty, one year)
```python
import fastavro
from collections import defaultdict

YEAR_REPORT_ID = 3619  # 2024-2025 Seattle; map via report.avro

re_ids=set()
for r in fastavro.reader(open('safs_prod/s275/report_employee.avro','rb')):
    if r['report_id']==YEAR_REPORT_ID: re_ids.add(r['report_employee_id'])

sal={}
for r in fastavro.reader(open('safs_prod/s275/private_report_employee.avro','rb')):
    if r['report_employee_id'] in re_ids:
        v=r['total_final_salary']; sal[r['report_employee_id']]=float(v) if v is not None else None

major_duty={}; emp_fte=defaultdict(float)
for a in fastavro.reader(open('safs_prod/s275/assignment.avro','rb')):
    if a['report_employee_id'] not in re_ids: continue
    emp_fte[a['report_employee_id']]+=float(a['fte_in_assignment'] or 0)   # total FTE across assignments
    if a['is_major']: major_duty[a['report_employee_id']]=a['duty_root_code']
# salary per FTE = sal[re]/emp_fte[re]; group by major_duty[re]
```

Seattle `report_id` → year: 93=2013-14, 398=2014-15, 707=2015-16, 1025=2016-17, 1342=2017-18,
1661=2018-19, 1984=2019-20, 2306=2020-21, 2631=2021-22, 2959=2022-23, 3288=2023-24, 3619=2024-25.
(Or just read `report.avro` and filter `str(ccddd)=='17001'`.)

---

## 3. GOTCHAS & surprising interpretations  (read this section twice)

**G1 — Salary is per-PERSON, duty/FTE is per-ASSIGNMENT.** `total_final_salary` lives on
`private_report_employee` (one per person-year). Duty and FTE live on `assignment` (many per person).
To attribute salary to a duty, classify each person by their `is_major` assignment's duty. Don't try to
average salary at the assignment grain unless you use `private_assignment.c_est_total_final_salary`
(the apportioned per-assignment estimate).

**G2 — `total_final_salary` is NOT FTE-normalized.** It's the actual amount paid. Roles differ wildly in
FTE: teachers ~0.9-1.0, **aides average ~0.69 FTE**. For apples-to-apples comparisons compute
`sum(salary)/sum(emp_fte)` (salary per 1.0 FTE). Raw average aide salary (~$58k) ≈ $84k/FTE.

**G3 — Duty 91 "Aide" is classified staff, but the domain tags its category as `teacher`.** Don't treat
the `duty_name_category=='teacher'` filter as "certificated teachers." The real classroom teacher duties
are **31, 32, 33, 34**. Aide (91) is paraeducators.

**G4 — 2015-16 reclassification: Elementary Specialist (34) was carved out of Elementary Homeroom (31).**
Duty 34 has ZERO rows before 2015-16; ~79% of the first specialists were duty-31 the prior year. For any
elementary-teacher trend, **combine 31+34** (pool at the employee level, don't average the two means).
Using 31 alone overstates the decline (−26% vs −15% combined, 2013-14→2024-25).

**G5 — 2018-19 coding artifact: duty 31 spiked while duty 33 ("Other Teacher") collapsed** that single year
(teachers miscoded between 31 and 33). Trust *combined* teacher totals, not 31-vs-33 year-over-year deltas.

**G6 — New duty codes appear mid-series.** Elementary Specialist (34) starts 2015-16; Substitute Teacher
(52) only becomes meaningful from 2020-21. "Growth from zero" for these is reclassification, not hiring.

**G7 — `experience_years` is a certificated-staff field. Classified aides report 0** (median AND mean = 0).
Only meaningful for teachers (median ~9-11 yrs). Don't compute aide experience.

**G8 — `duty_suffix_code` distinguishes base vs supplemental contracts.** 0 = certificated base / all
classified (this is where the real FTE lives); 1-3 = supplemental contracts, often `fte_in_assignment==0`.
The `is_major` assignment is always a suffix-0 row in practice.

**G9 — District Office detection: `d_school.is_district_office`** flags school codes ~1000-1500
("District Office"). ~22-28% of Seattle staff-years are based there. To get school-based staff only,
exclude employees whose `is_major` assignment `school_code` is in that set. This drops the superintendent,
directors/supervisors, most central "Professional"/"Other Support" staff; teachers/aides/principals survive.

**G10 — Special-education teachers are ~92% coded as duty 33 "Other Teacher"** (5,259 of 5,735 FTE), with
duty 34 at ZERO special-ed. So you CANNOT meaningfully split special-ed teaching by the 31/32/33/34 duty
distinction — sum teacher duties (31-34) when slicing by special-ed program. (Basic-ed teaching, by
contrast, IS spread across 31/32/34.)

**G11 — Program filtering.** `assignment.program_code` is the program. Basic Education = **`program_code 1`**
("Regular Instruction"); variants 2 (Alternative Learning Experience) and 3 (Dropout Reengagement) are
also "Basic Education -" but usually excluded. Special Education = **programs 21-29** (21 Supplemental-State
and 24 Supplemental-Federal are the bulk; 22/25 are Infants & Toddlers, rare at regular schools).
Basic-ed is ~70% of teacher FTE; the other ~30% is sped/bilingual/LAP/highly-capable/etc.

**G12 — For per-FTE *ratios*, drop sub-0.5-FTE points.** A stray 0.1-FTE "secondary teacher" at an
elementary yields students/FTE in the thousands and destroys any scale. Require `fte >= 0.5` for a
(school, year, duty) point to count. Also: restrict level-specific duties to their level (Elementary
Homeroom/Specialist → elementary schools; Secondary → middle/high) so off-level noise doesn't appear.

**G13 — Enrollment "All Grades" includes PK**, and `students_with_disabilities` (SWD) is the special-ed
student count. Non-sped students = `all_students - students_with_disabilities`. Sped students are ~16-18%
of enrollment and rising. ⚠️ Most SWD students are taught largely in general-ed classrooms, so
"SWD ÷ sped-teacher-FTE" is a *caseload of dedicated sped staff*, not a true class size.

**G14 — Sentinels.** Numeric code columns that can hold rare non-numeric values use negative-range
sentinels; NULLs use `_NULL_NUMBER = -931415926`. These are unwound to real nulls on AVRO export, so the
files here are clean — but if you ever read staging Postgres directly, watch for them.

**G15 — Year coverage.** S-275 has 12 Seattle years (2013-14 → 2024-25); enrollment has 11 (2014-15 →
2024-25). Overlap for ratio work = 11 years. Enrollment peaked 2019-20 (56,051), fell to ~51,200 (−9%).

---

## 4. Duty root code reference (`d_duty_root`)

Teaching-relevant:
| code | name | notes |
|---|---|---|
| 31 | Elementary Homeroom Teacher | elementary classroom; combine with 34 (see G4) |
| 32 | Secondary Teacher | middle/high |
| 33 | Other Teacher | catch-all; **where special-ed teachers live** (G10) |
| 34 | Elementary Specialist Teacher | created 2015-16 from 31 |
| 52 | Substitute Teacher | sparse before 2020-21 |
| 91 | Aide | **classified** paraeducators (G3); exp=0 (G7) |

Other categories present: 11-13 admin, 21-25 principals/vice-principals, 40 Other Support, 41 Library
Media, 42 Counselor, 43 OT, 44 Social Worker, 45 SLP, 46 Psychologist, 47 Nurse, 48 PT, 94 Office/Clerical,
96 Professional, 97 Service Worker, 99 Director/Supervisor. (`duty_name_category` groups these, but note G3.)

---

## 5. Program code reference (`d_program`) — staffing-relevant

- **1** Basic Education (Regular Instruction) ← "basic ed"
- 2 Basic Ed – Alternative Learning Experience; 3 Basic Ed – Dropout Reengagement
- **21** Special Ed – Supplemental, State; **24** Special Ed – Supplemental, Federal (bulk of sped)
- 22/25 Special Ed – Infants & Toddlers; 23 ARP-IDEA; 26 Institutions; 29 Special Ed – Other Federal
- 55 LAP; 64 Limited English Proficiency; 74 Highly Capable; 51 ESEA Disadvantaged; 97 Districtwide Support

---

## 6. Established findings (context, so you don't re-derive)

- 7,156 staff-years in Seattle 2024-25; ~39k teacher records (duties 31-34) across all years.
- Per-1.0-FTE teacher salary rose ~63% 2013-14→2024-25 (e.g. Elem Homeroom $69.5k→$113.1k). Big jumps
  2018-19 (+10%, post-McCleary) and 2022-23 (+8%, COLA).
- **Aides surged**: headcount 873→1,469 (+68%), FTE 598→1,012 (+69%), while teacher FTE was flat/down →
  teacher:aide FTE ratio compressed 4.79:1 → 2.92:1.
- Student:teacher FTE ratio ~17:1 and stable; student:aide ratio fell 78→51 (more aide coverage per student).
- Basic-ed is ~70% of teacher FTE; sped teaching is ~92% duty-33.

---

## 7. Outputs from the prior session (this analysis)

- `seattle_s275_salary_by_duty.html` — the big self-contained report (salary tables, enrollment/ratios,
  per-duty by-school ratio scatters, program-matched ratios, teacher salary-by-experience, teacher
  experience-by-school). ~13 MB (figures base64-embedded).
- `seattle_ratio_duty_*.jpg`, `seattle_ratio_basiced_*.jpg`, `seattle_ratio_*_teacher_*.jpg`,
  `seattle_school_experience_scatter.jpg`, `seattle_teacher_salary_experience.png` — the figures.
- ⚠️ The Python that built these lived in the session **scratchpad (ephemeral)** — not committed. If you
  want them persisted into `analysis/`, ask and they can be reconstructed (the recipes above + this guide
  are enough to rebuild any of it).

Plot conventions used (if you continue the visual style): facet by middle-school attendance area
(`ms_assignment_code`), x=school, dots in per-year bands oldest→newest left-to-right, **plasma** colormap
by year, black per-school mean line, linear y capped near the 98th percentile, facets ordered by the
most-recent-year (2024-25) value.
