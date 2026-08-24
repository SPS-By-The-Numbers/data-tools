# S-275 salary skyline — every SPS employee, one bar each

A chart of `total_final_salary` for every Seattle Public Schools employee in one
S-275 report — 7,156 bars for 2024–25 — grouped by OSPI duty title and sorted
highest to lowest inside each group. Built August 2026. Two renderings from one
data pull and one band definition:

| | file | shape |
|---|---|---|
| wide | `out_salary_skyline/salary_skyline.html` | interactive; vertical bars, ~14,500px-wide scroller, sticky $-axis, draggable minimap, per-bar hover, grouped stats table |
| tall | `out_salary_skyline/salary_skyline_tall.svg` / `.png` | static; axes flipped, horizontal bars, 1560 × 16,858px, self-contained (fonts inlined) |

Everything under `out_salary_skyline/` is generated and gitignored. The scripts
in `tools/salary_skyline/` are the durable part.

---

## 1. Reproduce

```console
$ python3 tools/salary_skyline/fetch_fonts.py            # once per checkout (needs network)
$ bq query --project_id=sps-btn-data --use_legacy_sql=false \
      --max_rows=20000 --format=csv \
      --parameter=ccddd:INT64:17001 \
      --parameter=school_year:STRING:2024-2025 \
      "$(cat tools/salary_skyline/query.sql)" > out_salary_skyline/staff.csv
$ python3 tools/salary_skyline/build_salary_skyline.py        # wide interactive HTML
$ python3 tools/salary_skyline/build_salary_skyline_tall.py   # tall standalone SVG
$ python3 tools/salary_skyline/wrap_page.py                   # SVG -> responsive HTML page
$ tools/salary_skyline/render_png.sh                          # SVG -> PNG
```

All paths are relative to the repo root; run from there. No venv needed — the
generators are stdlib-only.

`query.sql` is parameterized on `ccddd` and `school_year`, so another district
or year is a flag change. `report_type = "final"` is hardcoded: preliminary
reports carry a different meaning for `total_final_salary`.

## 2. Where the data comes from

`sps-btn-data.safs_s275.*` — see [DATA_DICTIONARY.md](../DATA_DICTIONARY.md)
for the full column list and
[STAFFING_ANALYSIS_GUIDE.md](STAFFING_ANALYSIS_GUIDE.md) for the S-275 joins
and gotchas generally. What this chart specifically depends on:

- **Salary is per person, not per assignment.**
  `private_report_employee.total_final_salary` is one value per employee per
  report, set by payroll rather than by the October 1 snapshot. Do not sum
  `private_assignment.assignment_salary` to get it and do not prorate it by
  FTE — `pct100_fte_in_assignment` explicitly disclaims that use.
- **Assignments are many per person**, keyed by
  school × program × activity × duty × grade. So the duty title has to be
  *chosen*. `query.sql` picks the duty root of the employee's **major**
  assignment (`is_major`), breaking ties on summed `fte_in_assignment`, then on
  assignment salary, then on the duty code itself for determinism.
- **FTE is `SUM(assignment.fte_in_assignment)`.** Not
  `assignment_fte.certificated_fte` / `classified_fte` — those are per-employee
  markers repeated across assignment rows and over-count roughly 5×.
- `safs_domains.d_duty_root` supplies `duty_name`. Note its `school_year` is
  the sentinel `9998-9999`, so **do not** join it on year — an equality join
  against a real school year returns zero rows, silently.

Output CSV columns: `cat, duty, duty_name, salary, fte`. `cat` is a legacy band
id left at 0 and ignored by both generators; `duty` (the OSPI duty **root**) is
the real grouping key.

## 3. The banding — `tools/salary_skyline/salary_bands.py`

One module defines both levels and the palette; both generators import it.
Changing a group, moving a duty code, or renaming a band is a single edit there
followed by a re-run of the two build scripts.

**Classified status is inferred from the duty code, not from
`assignment_fte.is_classified`.** Roots 90–99 are the OSPI classified series.
Three of them are deliberately grouped away from the rest:

- **99** Director or Supervisor → *Central administration + central office staff*
- **96** Professional → *Central administration + central office staff*

The work is administrative and professional rather than support, and the S-275
duty series alone puts them with custodians and paraeducators, which is
misleading in a payroll chart.

Groups, in plot order (left→right wide, top→bottom tall). Within each band,
highest paid first:

| group | bands | duty roots | staff | payroll | % |
|---|---|---|---|---|---|
| Central administration + central office staff | District administration; Classified directors & supervisors; Classified professional | 11–13, 99, 96 | 441 | $60.9M | 8.9% |
| School administration | Principals & school administration | 21–25 | 197 | $36.9M | 5.4% |
| Teachers | Teachers; Substitute teachers | 31–34, 52 | 3,172 | $346.1M | 50.6% |
| Certificated support | Counselors & social workers; Health & therapy services; Librarians & other certificated support | 39–49, 63–64 | 754 | $82.9M | 12.1% |
| Classified support | Classified technical; Office & clerical; Paraeducators & aides; Crafts, trades & operators; Service workers | 91–95, 97–98 | 2,576 | $155.5M | 22.7% |
| Other | Extracurricular & leave | 51, 61, 90 | 16 | $1.8M | 0.3% |

Any duty root not listed falls into the trailing catch-all band rather than
being dropped — check band 15's count after changing years. Roots 49 (Behavior
Analyst) and 93 (Laborer) exist in the domain table but had no SPS staff in
2024–25.

### Palette

Four categorical hues plus neutral, from the validated default palette
(blue / orange / aqua / yellow, assigned in slot order so chart adjacency
matches palette adjacency). The two administration groups share the blue hue at
two steps of the sequential ramp — central office `#184f95`, school
administration `#2a78d6` — so the central-office/school split reads without
spending a fifth hue. Aqua and yellow sit below 3:1 on the light surface, which
obligates the visible band labels and the table view; both ship.

## 4. Headline numbers, 2024–25 final

| | |
|---|---|
| Employees | 7,156 |
| Total FTE | 6,148.6 |
| Total final salary | $684.0M |
| Median | $91,456 |
| 10th–90th percentile | $50,873 – $140,002 |
| Highest paid | $356,800 (Superintendent) |

Things that came out of the grouping and are worth knowing before re-cutting it:

- The top **classified director** is paid **$289,385** — more than any principal
  in the district ($219,692), and within **$2** of the second-highest-paid
  district administrator ($289,387).
- Teachers are half the payroll (50.6%) and their band is nearly flat from
  ~$130k to ~$90k — the salary schedule showing through — then falls off a cliff
  at the low end, which is partial-year staff, not low-paid staff.
- Paraeducators & aides are the second-largest headcount (1,469, median
  $57,783).
- **Bar length is not FTE-adjusted.** `total_final_salary` is what payroll paid,
  so part-time and partial-year employees sit short by design. Substitutes,
  leave/buy-back and extracurricular base contracts are real payroll with little
  or no FTE. If you need rate-of-pay rather than amount-paid, this is the wrong
  measure.
- Salary excludes insurance, mandatory benefits, and supplemental/TRI contracts
  — those are separate columns on `private_report_employee`.

## 5. Published artifacts

Both live pages were published from this data. **Republishing must pass the
existing URL** (`url=`), because the output files have since moved to
`out_salary_skyline/` and publishing a new path would mint a separate artifact:

- wide — `https://claude.ai/code/artifact/db416f16-b441-4c05-9fe8-9465589e368b`
- tall — `https://claude.ai/code/artifact/51309130-dacb-446a-9a2c-63f9c77a3c95`

## 6. Rendering notes

- The tall SVG inlines Zilla Slab, Public Sans and IBM Plex Mono as base64
  woff2 (~106 KB) so it renders identically offline and in tools without
  network access. It also carries a `prefers-color-scheme` block, so opening it
  in a dark browser flips the whole palette; the PNG bakes the light theme.
- There is no `rsvg-convert`, `cairosvg`, `inkscape` or ImageMagick in this
  checkout. `render_png.sh` uses headless Chrome, which is the only thing on
  hand that handles a 1560 × 16,858 canvas. Set `CHROME=` to override the path.
- The wide chart draws 7,156 SVG `<rect>`s and hit-tests hover by binary search
  on bar x, rather than attaching listeners per bar.

## 7. "Who (or what) would you axe? 🪓" — the redistribution game

`out_salary_skyline/admin_game.html`, built from the same `staff.csv` pull.
One bubble per central-office employee (area = `total_final_salary`); click or
sweep-drag a bubble — or its bar in the skyline row — to cross positions out,
and their payroll is redistributed live to SEA-represented staff. Published
artifact (republish must pass this URL):
`https://claude.ai/code/artifact/23cdfc74-68ed-476a-ad49-34e9790a1f23`.

```console
$ bq query --project_id=sps-btn-data --use_legacy_sql=false \
      --max_rows=1000 --format=csv \
      --parameter=ccddd:INT64:17001 \
      --parameter=school_year:STRING:2024-2025 \
      < tools/salary_skyline/services_query.sql > out_salary_skyline/services.csv
$ python3 tools/salary_skyline/build_admin_game.py     # from the repo root
```

(The main `staff.csv` pull is in §1 — note both queries must be fed via
stdin: their leading `--` comment lines get eaten as flags if passed as an
argument.)

- `tools/salary_skyline/sea_units.py` defines both sides of the game:
  **CUTTABLE** components (district admin 11–13, classified dir/sup 99,
  classified professional 96, and school admin 21–25 as an off-by-default
  option) and **RECIPIENTS** (teachers 31–34, subs 52, certificated support
  39–49 + 63–64, paraeducators 91, office & clerical 94 — 5,743 people in
  2024–25, an approximation of SEA's three bargaining units from duty codes).
  The two sets are disjoint; crafts/custodial/service (92–93, 95, 97–98)
  belong to other unions and appear on neither side.
- Distribution math: with total removed *T* and per-person weight *w_g*, each
  member of group *g* gets `T·w_g / Σ(n_h·w_h)`. The headline stat
  (per ×1-weighted member) is also the marginal rate — each extra dollar cut
  adds `1/Σn·w` per member.
- **Deficit waterfall (added 2026-08-22):** before anything reaches staff, the
  freed money fills two holes, in order and each toggleable: the
  **$23,706,321 recurring budget deficit** (GF expenditures over revenues +
  other financing in the latest F-196 *actuals*, 2024-25 — switched from the
  budget book's $21.25M budgeted figure 2026-08-23; update the constant when
  2025-26 actuals land) and the **Economic Stabilization Fund refill** ($0
  committed per Budget Book PDF p.21; 3% floor on the $1,338,853,189 GF
  expenditure budget = $40,165,596, refilled at a chosen $/yr pace). Framing:
  the game shows recurring yearly cash flow, NOT a one-time year. Constants
  live in `build_admin_game.py` next to the F-196 numbers. The controls sit in a
  highlighted band at the literal top of the page (non-sticky — it scrolls
  off): a "Fill budget deficit first" checkbox and a checkbox + "Refill
  Economic Stabilization Fund by $[x]M/yr" number input (default = the 3%
  floor ÷ 5, i.e. ~$8.0M/yr simulating a 5-year fill; unchecking disables
  the input and skips the refill). Edits retarget the waterfall,
  resize/relabel the hole-bar segment, and raise a slim info alert in the
  band stating how many years the chosen annual amount takes to reach the 3%
  floor; the alert appears only on a genuinely new value and auto-dismisses
  after 3 s. The hole is drawn *inside*
  the skyline as a "The hole" section between the block and SEA staff: two
  area-true rectangles (deficit, ESF) whose height is pinned to the max SEA
  salary and whose width = dollars ÷ max_sea in person-widths — so their
  footprint is directly comparable to the salary bars — filling bottom-up as
  money is cut (green when full). The ESF rect resizes with the $[x]M/yr
  input inside a slot reserved at the 3%-floor width; the per-person `step`
  accounts for the slot. With the benefits toggle on, the chopping-block cluster SVGs scale
  by √1.3265 so bubble *area* grows by exactly the multiplier (the skyline
  bars do not scale — they sit on a real $ axis). Notable result: cutting
  all 441 central-office staff (salary only) fills the deficit but leaves the
  ESF $475k short — staff get $0; with the benefits toggle on there is a
  $19.4M surplus (~$3,382/member).
- **Benefits are always on and F-196-derived** (the toggle was removed
  2026-08-23): every staff dollar in the game — bubble areas, EMP values,
  skyline bars/silhouettes, medians, freed money — is total compensation =
  salary × 1.3265, baked in by the generator (`rg_salaries`/`rg_split`/
  component items are multiplied up front; purchased services are exempt).
  Tooltips show the split ("$357k sal + $117k ben"). Constants in
  `build_admin_game.py` hold SPS 2024–25 actuals from
  `safs_f19x.general_fund_expenditures`: Object 4 (benefits + payroll taxes)
  $240.9M, Objects 2+3 (salaries) $737.7M. Object 4 is attributed to S-275
  salaries by the ratio Σ`total_final_salary` / Σ(obj 2+3), which reduces to
  Object4/Objects23 = **32.65¢ per salary dollar**, so the toggle multiplies
  every cut by ×1.3265. Re-query the constants when changing year/district.
- **Combined skyline** lives in the dashboard: one SVG in a band that sticks
  just below the stat tiles on wide screens (its `top` is set from the tile
  strip's measured height); under 1020px — or viewports shorter than 820px —
  it drops out of the sticky stack (min-width 660px, horizontal scroll).
  It is **three stacked rows** — On the block / The hole / SEA staff — each
  full-width on its own line, all sharing one dollar scale and one
  per-person bar width, so row *lengths* compare headcounts (638 cuttable
  positions vs 5,743 SEA staff) and heights compare pay; each row carries
  its own $100k gridlines. Left section: per-position
  bars (sub-pixel wide; cut bars grey out), then two SEA program sections —
  **Basic ed + other** and **Special education** — each holding that
  program's recipient-group step-silhouettes with the redistributed amount
  stacked on top in central-office blue (cap paths carry `data-cap=<group>`
  so one translate per group moves every one of its silhouettes). The SEA
  side is rendered as **two toggleable layers** sharing the same per-person
  step: the default combined view, and a program-split view behind the
  "Show program splits" checkbox (default off) with five sections —
  **Basic ed + other**, **LAP** (program 55), **Title I** (51–53), **MLL**
  (multilingual learners, 64+65), **Special education** (21+24, combined per
  the psychologist recode) — assigned by FTE *plurality* per person via
  `query.sql`'s 5-bucket `pgroup` column (ties → basic; zero-FTE staff use
  row plurality; `SEC_BUCKETS` maps buckets → chart sections). 2024–25
  SEA-side counts: 3,408 basic / 97 LAP / 53 Title I / 357 MLL / 1,828
  special ed. Sliver sections keep their labels via greedy placement.
- **Body Count** (button beside Restore): a lightbox tabulating current cuts
  by duty title in three columns — Special education / Basic / LAP + Title I
  + MLL — from a per-item body-count bucket baked into EMP (`PG2BC` in the
  generator; services map by partition). Close via ×, backdrop, or Esc.
- Gotcha fixed 2026-08-22: the info alert's `display:flex` overrode the
  `hidden` attribute, so it never visually dismissed — `.alert[hidden]
  {display:none}` is load-bearing. Test visibility with computed style, not
  the `hidden` property. The stack is a duplicate silhouette with a
  2,000-unit skirt below the baseline, translated up by the per-person amount
  and clipped to the plot — one `transform` update per group animates 5,743
  "bars" at once.
- Touch: cluster SVGs use `touch-action: pan-y` AND pointerdown never calls
  `preventDefault()` for touch pointers — Safari treats a cancelled
  pointerdown like a cancelled touchstart and kills native scrolling for the
  whole gesture, which froze the page on phones (bubbles cover the screen).
  A touch is instead held pending: mostly-horizontal drag commits a
  sweep-cut, vertical drag falls through to native scroll, a clean tap
  toggles on pointerup, pointercancel abandons it. Don't reintroduce either
  `touch-action: none` or an unconditional preventDefault.
- **Purchased-services chopping block:** two extra cuttable clusters (violet)
  from F-196 General Fund Object 7 actuals via `services_query.sql` —
  special-ed partition (programs 21+24, 10 NCES classes, $44.3M in 2024–25)
  vs everything else (34 classes, $135.2M; contracted student transportation
  alone is $59.7M). One bubble per NCES class, same dollars-per-area scale as
  the salary bubbles. Services are benefits-exempt (`svc` flag in COMPS) and
  **always on** — the "What's on the block?" component checkboxes were
  removed 2026-08-23; all six components (4 staff incl. school admin + 2
  service partitions) are permanently enabled. In the skyline block row each partition is an
  area-true violet rect at the block row's AVERAGE comp height, greying
  bottom-up with the cut fraction (`svcut-` JS); the hole tanks likewise use
  the SEA row's average comp as their height — synthetic blocks read as
  "N average people" wide. The SpEd
  cluster carries an owner-directed warning callout: cuts there impact
  vulnerable students and may just decrease revenue (SpEd services are
  substantially reimbursement-funded), leading to no deficit impact.
- Cut feedback: an axe emoji (per-bubble deterministic tilt, baked into the
  SVG) replaces the earlier red X, and cutting sparks a capped burst of
  flying-money emoji via the Web Animations API (`spawnBills` in the
  template; skipped under `prefers-reduced-motion`, ≤420 concurrent).
- Clusters are circle-packed at build time (a Python port of d3
  `packSiblings` in `build_admin_game.py`), so showing/hiding a component
  never re-lays-out; the page itself is a static template
  (`admin_game_template.html`) with vanilla JS state.
- The output is artifact-shaped (no doctype/html/body wrapper) and loads
  Zilla Slab / Public Sans / IBM Plex Mono from Google Fonts; opening the raw
  file locally renders in quirks mode, which is fine for a look but the
  artifact is the canonical rendering.
