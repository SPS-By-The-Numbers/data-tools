# Scenario breakdown: `close_sacajawea`

Close Sacajawea ES (268, a school on SPS's real consolidation candidate lists). Receivers default to the 3 nearest open neighborhood elementaries; displaced kids split per residence area by the receivers' existing draw.

*Generated 2026-06-10 from the 2024-25 baseline. All rider figures are rides/day (AM+PM boardings). Expected-value (EV) columns are the deterministic model; the MC column is the mean Δ and 95% interval over the saved paired draws.*

## Resolved assumptions

**op[0] `close_school`** — close **Sacajawea** (268); its 196 assigned students stay where they live and re-assign to the **engine-default receivers** (3 nearest open same-level neighborhood schools, split per residence area in proportion to existing draw).

Receiving schools (all displacements combined):

| receiver | kids received | share |
|---|---|---|
| Olympic View (262) | 146.5 | 74% |
| Wedgwood (279) | 39.2 | 20% |
| Rogers (266) | 11.1 | 6% |

Evaluation invariants (all scenarios): district enrollment is conserved per grade band (kids change schools, never leave); walk zones change only where an op touches them; the ride-propensity model keeps the baseline-calibrated scale and covariate centering, so changes in rides come only from the re-assignment (who is bus-eligible, and at what distance and school demographics); the gifted program moves only when an HCC pathway site is touched.

## Per-school deltas (basic program)

| school | role | enrolled base→scen (Δ) | bus-eligible base→scen (Δ) | EV rides/day base→scen (Δ) | MC Δ rides [95% CI] |
|---|---|---|---|---|---|
| Sacajawea (268) | closed | 196 → 0 (-196) | 110 → 0 (-110) | 104.4 → 0.0 (-104.4) | -104.2 [-107.7, -99.8] |
| Rogers (266) | receiver | 248 → 259 (+11) | 106 → 112 (+6) | 84.2 → 88.5 (+4.4) | +4.4 [+4.1, +4.7] |
| Wedgwood (279) | receiver | 333 → 372 (+39) | 106 → 145 (+39) | 46.4 → 63.3 (+16.9) | +16.9 [+14.3, +19.9] |
| Olympic View (262) | receiver | 347 → 494 (+147) | 187 → 286 (+99) | 142.6 → 218.3 (+75.7) | +75.9 [+71.0, +81.4] |
| **district total** | | | | **10,008.5 → 10,000.9 (-7.6)** | |

Gifted program: unchanged (no HCC pathway site is touched).

## Reading the table

- **enrolled** — students assigned to the school (IPF column marginal, all grade bands); a receiver's gain is its share of a closed/converted school's students.
- **bus-eligible** — assigned students living outside the school's walk zone; the gap between Δenrolled and Δeligible is the (approximate) count landing inside the walk zone.
- **EV rides/day** — expected rides at the baseline-calibrated propensity; “affected” rows move because the propensity tilt re-centers as the eligible pool shifts.
- **MC Δ** — mean and 95% interval over the paired Monte Carlo draws (population + behavioral-parameter uncertainty).
