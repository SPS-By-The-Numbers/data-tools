# Duty title vs. state basic-education allocation

Answers "how much of each S-275 duty title is paid for by the state's basic
education allocation?" for one district and school year.

```console
$ venv/bin/python3 -m tools.duty_funding.build_duty_funding \
    --pdf "data/fiscal/apportionment/2024-2025/district/17001_seattle_public_schools/Final Apportionment Summary.pdf" \
    --ccddd 17001 --school-year 2024-2025 \
    -o output/duty_funding/sps_2024-25_duty_state_funding.csv \
    --items-out output/duty_funding/sps_2024-25_1191f_pages1-7.csv
```

Needs Application Default Credentials for `sps-btn-data` (it shells out to `bq`)
and `pdftotext`.

## Modules

- `s275_by_duty.sql` — per duty title, for one district/year `final` report.
- `s275_by_duty_program.sql` — per duty title **x program code**. This is the
  join key for apportionment: the state funds special education under Account
  4121, and the S-275 says which assignments sit in program 21.
- `f196_benefits.sql` — F-196 actual objects 2, 3 and 4. The S-275 reports
  salary with no benefits in it, so `object 4 / (object 2 + object 3)` is what
  scales a duty title's salary up to total compensation (SPS 2024-25:
  $240.9M / $737.7M = **32.65 cents per dollar of salary**). One districtwide
  ratio, applied to every title — the F-196 does not split object 4 between
  certificated and classified staff, so a per-class rate is not available.
- `f196_revenues.sql` + `f196_program_objects.sql` + `funding_sources.py` —
  every General Fund revenue line (F-196 actuals) grouped into six display
  segments, each scaled down to the part its program actually spends on people.
  Supersedes the earlier `apportionment_accounts.py`, which covered state
  apportionment only.
- `parse_bea_pages.py` — parses pages 1-7 of a 1191F Final Apportionment
  Summary. **These pages are not in `ospi_fiscal.fiscal_apportionment_final`** —
  `extractors/fiscal/extract_apportionment_final.py` keeps headline account
  totals only and skips the derivation by design (SPS 2024-25 has 20 rows there,
  exactly one from pages 1-7). Emits both the printed line items and the model
  drivers, recovered by zipping each `[Bracket Name]` formula against the
  numeric substitution printed under it.
- `build_duty_funding.py` — joins the two.

## The two joins

**By revenue line (the stacked budget bar).** Two corrections stand between a
revenue code and a job title, and both matter more than they sound.

*Scale by what the program spends on people.* Each F-196 revenue code names the
program its money is restricted to, and `f196_program_objects.sql` says what
share of that program's spending is objects 2 and 3 (salaries) plus 4 (benefits)
rather than contracted services, supplies or capital. Only that share is
attributable. Pupil transportation is the case that forces the issue: SPS
contracts its yellow bus service, so program 99 spends $63.5M of which just
**7.4%** is staff pay — $56.9M is object 7. Charging the whole $44M
transportation revenue stream against the 28 FTE coded to program 99 overstated
them roughly thirteenfold. Shares range from 7.4% (transportation) through 57%
(food service) and 63% (districtwide support) to 99.9% (bilingual); the
districtwide figure is 81.8%.

*Divide by payroll, not headcount.* Within a program, money is spread by each
duty title's share of `total_final_salary`, not its share of FTE. Pay between
duty titles varies better than two to one, so an FTE split over-credits the
cheaper title and under-credits the dearer one — it was what kept Service Worker
reading 1.87x after the transportation fix, and 1.13x after this one.

Unrestricted lines (program 0 — the levy, investment earnings, transfers,
private gifts) spread across all staff, as do lines whose program employs no
S-275 staff, so no dollar is lost. Account 3100 is treated as restricted to the
basic-education programs even though its revenue line is coded unrestricted.
SPS 2024-25:

### Staffing roles (`model_roles.py`, `f196_program_objects.sql` aside)

Report **1191EDF** — "Student Full Time Enrollment and Calculated Staff Unit
Report", pages 8-15 of the same PDF — builds the class totals one role at a
time. `parse_bea_pages.pages_for()` locates the sub-report by banner rather than
assuming a page range, since the 1191F's length varies by district. The roles
sum *exactly* to the three class totals, so the decomposition is the state's
own:

| | model FTE | actual FTE | allocated | actual pay |
|---|---|---|---|---|
| Classroom teachers | 2,327.8 | 2,951.6 | $292.7M | $454.9M |
| Guidance counselors | 152.8 | 109.7 | $19.2M | $17.4M |
| School nurses | 69.0 | 51.0 | $8.7M | $9.7M |
| Teacher librarians | 62.6 | 65.2 | $7.9M | $11.2M |
| Social workers | 24.7 | 47.1 | $3.1M | $7.0M |
| Psychologists | 8.3 | 41.4 | $1.0M | $8.7M |
| Principals and vice principals | 141.7 | 187.3 | $25.0M | $48.6M |
| Central administration (CAS) | 46.7 | 37.7 | $8.2M | $12.8M |
| Office support | 242.6 | 288.1 | $24.4M | $30.9M |
| Custodians and security | 208.7 | 492.8 | $21.0M | $41.0M |
| Central administration (CLS) | 136.8 | 383.6 | $13.8M | $68.3M |
| Teaching assistance and family involvement | 99.5 | 1,011.7 | $10.0M | $112.6M |
| Facilities, warehouse, maintenance | 97.0 | 115.0 | $9.8M | $15.3M |
| Technology | 28.4 | 54.0 | $2.9M | $6.4M |
| No basic education staff unit | 0 | 312.4 | $0 | $62.5M |
| **total** | **3,646.613** | **6,148.568** | **$447,636,901.82** | **$907.4M** |

Dollars follow FTE within a class, because that is how the model works — one
flat rate per staff unit — so both units reconcile to the same totals the 1191F
reports. Guidance counselors and school nurses are the only two roles the state
funds *more* generously than SPS staffs them.

A few 1191EDF lines have no clean S-275 counterpart, so `ROLES` merges them into
the nearest one and says so: teaching assistance with family involvement (both
duty 91), custodians with student and staff safety (both duty 97), facilities
with warehouse (duties 92/93/95). Duty roots the model funds nothing for —
therapists, speech pathologists, behaviour analysts, substitutes — collect in a
per-class "no staff unit" row rather than being dropped.

**"State apportionment" means the 1191F staff units, not a revenue-code proxy.**
Pages 1-7 fund a number of CIS, CAS and CLS staff units at a flat rate per
class, and `staff_units()` reassembles the three pots from the parsed drivers —
salary, insurance (a headcount pot, split CIS/CAS by FTE), payroll benefits (a
percentage of salary, split by salary), substitutes and professional learning
days (both instructional, so CIS). **Benefits are included** — $117.7M of the
$447.6M, 26% — which is what makes the comparison against S-275 salary plus the
F-196 benefit ratio like for like:

| | pot | share of pay |
|---|---|---|
| CIS certificated instructional | $332.6M | 58% |
| CAS certificated administrative | $33.2M | 54% |
| CLS classified | $81.8M | 30% |
| **all three** | **$447.6M** | **49%** |

That total is line III.A.7 plus III.B.9 plus substitutes and professional
learning days, to the penny. Because the money is counted there, the F-196
revenue lines for Account 3100 and the 3121 special-education transfer are
dropped rather than counted twice (`ENTITLEMENT_REVENUES`).

`attribute_staff_units()` spreads each class's pot **by FTE**, deliberately
unlike the revenue segments. The model buys staff units at a flat rate, so an
FTE split reproduces it and a title paid above its class rate covers less of its
pay than one paid below — 15% (Director or Supervisor) to 77% (Substitute
Teacher). Splitting by payroll instead would hand every title in a class the
identical percentage and hide exactly the difference the model creates.

The chart carries **two** series. CIS, CAS and CLS share one colour and one
segment: a duty title belongs to exactly one staff class, so the three never
appear in the same bar, and the chart is already faceted by class — splitting
them would spend two colours restating the section heading. State special
education (revenue 4121 and 4321) is the second, attributed by program 21 and
divided by payroll, since a lump sum per eligible student funds an actual
payroll rather than a headcount.

| source | pays people |
|---|---|
| State apportionment — CIS, CAS and CLS staff units | $447.6M |
| Special education — state | $114.2M |
| **The sources shown, paying people** | **$561.9M** |
| Not attributed: these sources buy things, not people | $22.5M |
| Not shown: LAP, bilingual, highly capable, transportation, food service, Title I, other federal, local levy, private gifts, transfers | $465.6M |
| **All General Fund revenue** | **$1,172.1M** |

Together they cover 62% of pay — 70% of CIS, 55% of CAS, 46% of CLS.

Everything is rendered server-side; the only script on the page is the hover
tooltip.

The shareable page leads with the roll-ups and works down to the detail, each
unit paired with its counterpart: staff class in dollars, staff class in FTE,
job title in dollars, job title in FTE. The headcount charts scale each title's
own FTE by the share of its pay the state covers — "how many of these people
does state money pay for" — so a title costing more per FTE than the state's
flat rate shows fewer funded people than it employs. The two roll-ups answer different halves of the same shortfall — a class
far over its unit count is short because of headcount the model never budgeted
for, while a class near its unit count is short because the state's flat rate is
below what SPS pays.

The end-to-end check runs the same method over *all* revenue: $973.6M of pay,
against $978.6M of actual F-196 spending on objects 2, 3 and 4 — a 0.5% gap,
reached from the revenue side independently.

The two basic-education segments come to the F-196's $551,918,642 for Account
3100 before scaling, which is deliberately *not* the apportionment paperwork's
figure: the 1191F final summary says $551,855,699 and the Statement of
Apportionment's annual allotment is $551,086,004. The F-196 is the district's
accrual-basis books, the allotment is a basis before adjustments, and the 1191F
was run in January 2026 with a prior-year adjustment folded in. Everything here
uses the F-196 so the segments sum to one real total.

Only the General Fund is covered. Capital projects, debt service, the
transportation vehicle fund and ASB are separate funds and are not staff payroll.

**By staff class (the FTE chart).** Pages 1-7 fund three staff classes at flat
per-FTE rates, and every S-275 duty root maps to exactly one (`DUTY_CLASS`):

| class | duty roots | 2024-25 SPS model FTE | salary pot |
|---|---|---|---|
| CIS certificated instructional | 31-64 | 2,645.197 | $244.1M |
| CAS certificated administrative | 11-25 | 188.451 | $25.8M |
| CLS classified | 90-99 | 812.965 | $53.8M |

Insurance is a headcount pot split CIS/CAS by FTE; payroll tax and mandatory
benefits are a percentage of salary, so they split by salary.

The CSV also keeps two older staff-class attributions, which answer a narrower
question than the account stack and no longer drive the charts:

- **`rate_*`** — class per-FTE rate × the duty title's actual S-275 FTE. "At
  state rates, what would these people cost?" Does not sum to the state pot.
- **`share_*`** — class pot × (duty FTE / district actual FTE in that class).
  Sums exactly to the pot ($323,753,375 salaries, $441,441,897 with benefits).

## Caveats

- The S-275 covers **all** staff regardless of funding source. SPS reports 6,149
  FTE and $684M final salary against a state model of 3,647 FTE and $324M, so
  district-wide only ~47% of salary is state basic-ed money. The rest is
  levy, federal, grants, and the separately-allocated accounts (special ed 4121,
  LAP 4174, transportation 4199) that live on later pages of the same PDF.
- Benefits use one districtwide F-196 ratio, so they scale every title
  identically; object 4 is not split between certificated and classified staff.
- CTE and Skills Center are inside the Account 3100 guaranteed entitlement
  (III.H) as lump sums rather than staff units, so within basic education they
  ride the same per-FTE distribution as everything else.
- `bq query` defaults to 100 rows — both queries pass `--max_rows`.
- `assignment_fte` is `SUM(assignment.fte_in_assignment)`. Do **not** use
  `assignment_fte.certificated_fte` / `classified_fte` — those are per-employee
  markers repeated on every assignment row and over-count roughly 5×.
- `total_final_salary` is `SUM(private_assignment.c_est_total_final_salary)`.
  The raw `total_final_salary` lives on the employee, not the assignment, so
  summing it per duty title would multi-count anyone with more than one duty.
- Supplemental-contract rows (duty suffix 1/2) carry salary but zero FTE, which
  is why per-FTE ratios exceed 100% for a few titles.

## Charts

`build_variance_charts.py` renders the join as two bullet-style budget/variance
charts — the state's prototypical model as the budget bar, the district's actual
overlaid on it.

```console
$ venv/bin/python3 -m tools.duty_funding.build_variance_charts \
    --data output/duty_funding/sps_2024-25_duty_state_funding.csv \
    -o output/duty_funding/sps_2024-25_variance.html
```

Standalone HTML — hover tooltips, table views, light and dark. Rasterize the
same way as `tools/salary_skyline`:

```console
$ "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless \
    --disable-gpu --hide-scrollbars --virtual-time-budget=8000 \
    --window-size=1240,2850 \
    --screenshot=output/duty_funding/sps_2024-25_variance.png \
    "file://$PWD/output/duty_funding/sps_2024-25_variance.html"
```

The dollar chart is faceted into the three staff classes on one shared dollar
scale, so bar lengths stay comparable across facets as well as within them. Its
budget bar is a stack of the six revenue segments; the actual is drawn over it
in neutral ink, the bullet-chart convention, so the measure never competes with
the six series colours. The actual is itself a two-part stack — salary solid,
benefits in a 45-degree hatch of the same ink. The stripes are explicit `<line>`
elements drawn inside each chart's own SVG, **not** an SVG `<pattern>`: a pattern
must be referenced as `fill="url(#id)"`, which silently fails wherever the
document carries a `<base>` tag, and `var()` colours inside pattern content do
not resolve in every engine because that content sits outside the element using
it. `hatch_lines()` trims each stripe to the segment box arithmetically, and
`cap_ears()` paints out the sliver that overhangs the rounded end so the
stripes run the full length — without it the tip is a solid block of ink that
reads as a separate mark. For the
same reason the stack's rounded end is drawn as geometry rather than a clip
path, so the charts carry **no `url(#id)` references at all** and render the
same wherever they are embedded. Tone-on-tone hatching keeps benefits
legible as part of the measure rather than reading as a seventh series, and
survives greyscale and CVD. The stack palette is the six validated
categorical slots — run
`node <dataviz-skill>/scripts/validate_palette.js` before changing them.

Chart 2 is per staff class, not per duty title: the 1191F prints the prototypical
FTE only as the three class aggregates, and OSPI report 1159 (which does break
staff units down further) stops after 2015-16.
