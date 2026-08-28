# SEA chart critique

Builds `output/sea_chart_critique/index.html` — the SEA "Average Reported
Salaries by Job Category vs. State Funded Salaries by Staff Type" graphic
marked up with its errors, plus five replacement charts.

```console
$ venv/bin/python3 tools/sea_chart_critique/build.py
```

The first run issues two `bq` queries and caches them to
`output/sea_chart_critique/*.csv`; delete those files to re-query.
Everything else is read from `output/duty_funding/` (produced by
`tools/duty_funding/build_duty_funding.py`) and from `SEA- bad graph.png` at the
repo root, which is cropped and embedded as a data URI. The page is
self-contained: one HTML file, no external assets beyond a Google Fonts link.

| file | |
|---|---|
| `data.py` | 1191F rate derivation, S-275 rollup, duty→class map, group definitions |
| `build.py` | SVG chart renderers, page copy, assembly |
| `s275_by_duty_2425.sql` | duty-root rollup |
| `s275_admin_employees_2425.sql` | one row per administrator, for the bucket rebuild |

## The three bar values, reconstructed

Every rate is a statewide base salary figure × Seattle's 1.180 regionalization.
2025-26 is 2024-25 × the 2.5% salary inflator.

| bar | printed | 2024-25 | 2025-26 | matches |
|---|---|---|---|---|
| red — CAS | $136,988 | **$136,988.56** | $140,413.27 | 2024-25 |
| blue — CLS | $67,858 | $66,203.90 | **$67,859.00** | 2025-26 |
| yellow — CIS | $96,170 | $92,286.62 | $94,593.79 | neither |
| yellow + professional learning days | | $93,824.73 | **$96,170.35** | 2025-26 |

The professional-learning add-on is `School CIS PD Salary` $4,068,604.84 ÷
2,645.197 school-generated CIS units = $1,538.11/unit, × 1.025 = $1,576.56. It
is a certificated-instructional pot with no CAS or CLS analogue, so folding it
into the yellow bar and not the others is not a symmetric choice.

The chart carries no year label, so the red/blue mismatch cannot be resolved
from the graphic itself — hence the page argues it both ways rather than
asserting which year SEA meant.

## Rebuilding SEA's job categories

SEA's five buckets are not S-275 categories and it published no definitions.
S-275 carries **no employee names**, so the buckets are reconstructed by salary
tier and checked against headcounts from the SPS leadership pages as they stood
during 2024-25 (Wayback captures `20250322112434` for `/about/leadership/` and
`20250326041643` for `/departments/directors-of-schools/`):

| roster | n | S-275 tier | avg salary |
|---|---|---|---|
| Superintendent (Brent Jones) | 1 | duty 11 | $356,800 |
| Superintendent Senior Cabinet | 10 | ≥ $275,613, ex-superintendent | $278,370 |
| Regional Executive Directors of Schools | 5 | next 5 of duty 13 | $241,181 |
| Program directors — *a stated guess* | 143 | rest of duty 13 + 99 | $166,595 |

The cabinet tier falls out of the data on its own: exactly **ten** people are
paid $275,613 or more excluding the superintendent, and the next-highest is
$21,047 below them. That the tier size matches the roster is the check that
makes the whole reconstruction credible — and its average carried to 2025-26
($285,329) lands 0.3% from SEA's printed $284,518.

**Class mix matters more than the divisor for the cabinet.** Eight of the ten
are *classified* (duty 99, Director or Supervisor); only two carry a
certificated administrator code. Their blended benchmark is $80,361, not
$136,989 — so correcting it makes the cabinet multiple *worse* (3.46× vs 1.26×
for teachers). The rebuild is not a defense of administration.

**Program directors is where SEA's bar breaks.** Against all 143 remaining
district administrators and directors/supervisors the average is $166,595
($170,760 in 2025-26). SEA printed $230,970, which is reachable only from
roughly the top 25 of the 143 — an 82nd-percentile slice, overstated by about
$60,000 per position.

The year stays undetermined: the two administrator bars fit 2025-26 to within
0.3%, the teacher and para bars fit 2024-25 to within ~1%. No single year fits
all four within one percent.

## Charts 3 and 4 use different bases, deliberately

Both plot salary against "what the state pays", and they disagree. That is the
point, and the page says so in a callout.

| | state figure | teachers | reads as |
|---|---|---|---|
| Chart 3 | class rate x **FTE SPS employs** | 82% | a reductio |
| Chart 4, img1, img3 | class rate x **staff units the model funds** | 63% | coverage |

Chart 3 keeps the first because that is what SEA's premise implies — and the
premise is self-refuting: hire more people and the "state contribution" grows.
Everything framed as coverage uses the second, because the formula generates a
fixed unit count from enrollment that does not move when the district hires.

Across the eight groups: **$548.9M paid, $272.3M allocated, 50% covered**.
Coverage runs from 69% (office, cabinet) down to **8%** for instructional
aides, where the model funds 99.5 units against 1,012 FTE.

That aide figure carries a standing caveat, repeated in every chart that shows
it: basic-education staff units ignore the special-education and MLL money that
pays for most paraeducators, so their real support is higher than 8%.


## Standalone images for sharing

```console
$ venv/bin/python3 tools/sea_chart_critique/build_images.py   # -> img{1,2,3}.html
$ tools/sea_chart_critique/render_images.sh                   # -> img{1,2,3}.png @2x
```

Three flat PNGs that stand on their own outside the page — each carries its own
title, legend, and source line, light theme only. `render_images.sh` screenshots
via headless Chrome at `--force-device-scale-factor=2` and trims to the card.

| | what it is | size |
|---|---|---|
| `img1.png` | salary paid with the state's allocation overlaid, plus the per-FTE overage subtext | 2004 × 1670 |
| `img2.png` | all 14 1191EDF roles, funded units vs actual FTE, three class panels on one shared scale | 2004 × 2382 |
| `img3.png` | every SPS salary in those eight groups, one bar each, over six rows, with the state's unit rate and funded block drawn across each group's span | 2404 × 3801 |
| `img3_noline.png` | the same skyline with no rate overlay — `image3(..., rate_line=False)` | 2404 × 3657 |

Image 3's **x-axis is FTE, not headcount**. Bar width is a person's FTE and
height is their pay per FTE, so every area on the chart is dollars: a bar's
area is that person's salary, and the shaded block (funded units x class rate)
is the state's allocation, $272.3M across the eight groups.

That was not the first design, and the reason for the change is worth keeping.
With one equal-width slot per person, the funded-unit mark landed in the wrong
space — units are FTE, slots were people, and the two only coincide at 1.0 FTE
per person. The aide mark sat at slot 99 when the funding actually reaches 144
of those 1,469 people: **31% short**, on the row that is already the most
attackable in the set. Office staff were out by 21%, teachers by 3%. Putting
FTE on the axis makes the mark land exactly right and keeps area meaningful;
the cost is that a half-time employee is a half-width bar.

Rows hold roughly equal FTE (`_split_by_fte`): teachers over three, aides over
two, the six remaining groups together on a sixth. Bar pitch — pixels per FTE —
is constant across every row, set by the widest, so short rows are left short
rather than stretched to fit.

The low-FTE tail that would wreck a per-FTE axis does not exist here: only 3 of
5,585 people are below 0.2 FTE (0.6 FTE, $43k), and the highest pay per FTE in
the district is the superintendent at 1.0 FTE, so nothing overshoots the axis.

Narrow segments in the last row get a stacked label on its own step with a
dotted leader down to the bars. Rotated labels were tried first and collide as
soon as two thin groups sit side by side.

Image 3 needs the per-employee pull, which reuses the skyline query:

```console
$ bq query --project_id=sps-btn-data --use_legacy_sql=false --max_rows=20000 \
    --format=csv --parameter=ccddd:INT64:17001 \
    --parameter=school_year:STRING:2024-2025 \
    < tools/salary_skyline/query.sql > output/sea_chart_critique/staff_2425.csv
```

Pipe it on **stdin**. Passing it as `"$(cat query.sql)"` makes the shell re-expand
the `$(cat ...)` example inside the file's own comment header and silently
returns nothing.

That query assigns each person a single duty root (their major assignment), so
its group counts (5,585 charted) run slightly below the distinct counts in
`group_headcount.csv` (5,608), which count anyone holding *any* assignment in a
group's duties. Image 1 uses the distinct counts, since its FTE and salary come
from the additive duty rollup; image 3 uses major-duty, since it draws one bar
per person.

## Gotcha worth remembering

An earlier version of this page claimed SPS files its central administrators at
0.77 FTE and built a "divisor" correction on it. **That was wrong, and it was
our bug** — `extractors/safs/transforms/s275.py` collapsed assignment rows that
were identical except for `recno`, which are separate reported records whose
FTE must sum. Fixed 2026-08-25; see the `s275-assignment-dedup-bug` note.

The raw file is ground truth:

```console
$ mdb-export data/safs/s275/2024-2025_Final_S-275_Personnel_Database.accdb \
      2024-2025S-275FinalForPublic
```

It also carries `LastName` / `FirstName` / `MiddleName`, which the warehouse
strips — so the cabinet reconstruction above is verifiable by name, and checks
out exactly. Do not repeat the claim that "S-275 has no names."

What the fix moved, SPS 2024-25: district FTE 6,185.9 -> **6,362.0**; teachers
2,951.6 -> **3,035.2**; certificated central administration 37.7 -> **48.6**,
which turns that role from 0.81x (funded more generously than staffed) to
**1.04x**, near parity. Only guidance counselors and school nurses remain below
1.0. Class-level pay is untouched, so the 62% headline in
`docs/guides/DUTY_FUNDING.md` still holds.


## See also

- `docs/guides/DUTY_FUNDING.md` — the full method behind the coverage figures
  and the 1191EDF role mapping.
- `tools/duty_funding/` — parses the 1191F/1191EDF pages this depends on.
