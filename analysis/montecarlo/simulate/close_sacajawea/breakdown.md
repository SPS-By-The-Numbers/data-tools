# Scenario breakdown: `close_sacajawea`

Close Sacajawea ES (268, a school on SPS's real consolidation candidate lists). Default closure semantics: displaced students may enroll anywhere with no enrollment cap - each residence area's students redistribute across all open schools pro-rata to the area's existing draw (revealed choice, dominated by distance).

*Generated 2026-06-11 from the 2024-25 baseline. All rider figures are rides/day (AM+PM boardings). Expected-value (EV) columns are the deterministic model; the MC column is the mean Δ and 95% interval over the saved paired draws.*

## Resolved assumptions

**op[0] `close_school`** — close **Sacajawea** (268); its 196 assigned students stay where they live and re-assign to **any open school, pro-rata to their residence area's existing draw** (revealed choice, dominated by distance; no enrollment caps).

Receiving schools (all displacements combined):

| receiver | kids received | share |
|---|---|---|
| Hazel Wolf (292) | 93.3 | 48% |
| Olympic View (262) | 20.6 | 11% |
| Cascadia (971) | 17.4 | 9% |
| Cedar Park (210) | 16.7 | 9% |
| McDonald (247) | 10.9 | 6% |
| Olympic Hills (261) | 10.0 | 5% |
| Thornton Creek (977) | 6.4 | 3% |
| Wedgwood (279) | 4.6 | 2% |
| Rogers (266) | 3.9 | 2% |
| Stanford (241) | 2.7 | 1% |
| TOPS (935) | 1.8 | 1% |
| Bryant (209) | 1.6 | 1% |
| Bagley (204) | 0.9 | 0% |
| View Ridge (277) | 0.9 | 0% |
| Green Lake (229) | 0.8 | 0% |
| Greenwood (230) | 0.8 | 0% |
| Gatzert (226) | 0.8 | 0% |
| Viewlands (276) | 0.7 | 0% |
| Decatur (287) | 0.5 | 0% |

Evaluation invariants (all scenarios): district enrollment is conserved per grade band (kids change schools, never leave); walk zones change only where an op touches them; the ride-propensity model keeps the baseline-calibrated scale and covariate centering, so changes in rides come only from the re-assignment (who is bus-eligible, and at what distance and school demographics); the gifted program moves only when an HCC pathway site is touched.

## Per-school deltas (basic program)

| school | role | enrolled base→scen (Δ) | bus-eligible base→scen (Δ) | EV rides/day base→scen (Δ) | propensity base→scen (marginal) | MC Δ rides [95% CI] |
|---|---|---|---|---|---|---|
| Sacajawea (268) | closed | 196 → 0 (-196) | 110 → 0 (-110) | 104.4 → 0.0 (-104.4) | 0.95 → — (marg 0.95) | -104.2 [-108.5, -100.7] |
| Gatzert (226) | receiver | 371 → 372 (+1) | 259 → 260 (+1) | 165.7 → 164.2 (-1.5) | 0.64 → 0.63 (marg -1.14) | -1.5 [-2.1, -0.9] |
| Cascadia (971) | receiver | 534 → 551 (+17) | 0 → 0 (+0) | 0.0 → 0.0 (+0.0) | — → — | — |
| Decatur (287) | receiver | 190 → 191 (+1) | 0 → 0 (+0) | 0.0 → 0.0 (+0.0) | — → — | — |
| Bryant (209) | receiver | 476 → 478 (+2) | 149 → 149 (+0) | 52.1 → 52.3 (+0.1) | 0.35 → 0.35 | +0.1 [+0.1, +0.2] |
| Viewlands (276) | receiver | 270 → 271 (+1) | 151 → 151 (+0) | 73.4 → 73.6 (+0.2) | 0.49 → 0.49 | +0.2 [+0.2, +0.2] |
| Greenwood (230) | receiver | 332 → 333 (+1) | 110 → 111 (+0) | 74.2 → 74.5 (+0.2) | 0.67 → 0.67 | +0.2 [+0.2, +0.3] |
| View Ridge (277) | receiver | 294 → 295 (+1) | 127 → 127 (+1) | 82.2 → 82.6 (+0.4) | 0.65 → 0.65 | +0.4 [+0.4, +0.5] |
| Green Lake (229) | receiver | 364 → 365 (+1) | 252 → 252 (+1) | 205.0 → 205.4 (+0.4) | 0.81 → 0.81 | +0.4 [+0.4, +0.5] |
| Bagley (204) | receiver | 337 → 338 (+1) | 177 → 179 (+1) | 125.0 → 125.7 (+0.7) | 0.70 → 0.70 (marg 0.64) | +0.7 [+0.6, +0.7] |
| Stanford (241) | receiver | 422 → 425 (+3) | 385 → 387 (+3) | 130.6 → 131.4 (+0.8) | 0.34 → 0.34 (marg 0.30) | +0.8 [+0.7, +0.9] |
| TOPS (935) | receiver | 450 → 452 (+2) | 438 → 440 (+2) | 304.8 → 305.7 (+0.9) | 0.70 → 0.70 (marg 0.50) | +0.9 [+0.8, +1.0] |
| Rogers (266) | receiver | 248 → 252 (+4) | 106 → 108 (+2) | 84.2 → 85.4 (+1.3) | 0.79 → 0.79 (marg 0.79) | +1.3 [+1.2, +1.4] |
| Wedgwood (279) | receiver | 333 → 338 (+5) | 106 → 109 (+3) | 46.4 → 47.8 (+1.4) | 0.44 → 0.44 (marg 0.43) | +1.4 [+1.2, +1.7] |
| McDonald (247) | receiver | 443 → 454 (+11) | 370 → 381 (+11) | 124.4 → 127.6 (+3.1) | 0.34 → 0.34 (marg 0.29) | +3.1 [+2.6, +3.8] |
| Thornton Creek (977) | receiver | 370 → 376 (+6) | 238 → 244 (+6) | 177.9 → 182.2 (+4.4) | 0.75 → 0.75 (marg 0.71) | +4.4 [+4.0, +4.7] |
| Cedar Park (210) | receiver | 226 → 243 (+17) | 193 → 209 (+16) | 81.6 → 88.2 (+6.6) | 0.42 → 0.42 (marg 0.40) | +6.6 [+5.6, +7.6] |
| Olympic Hills (261) | receiver | 439 → 449 (+10) | 173 → 182 (+9) | 157.7 → 165.4 (+7.7) | 0.91 → 0.91 (marg 0.89) | +7.7 [+7.0, +8.3] |
| Olympic View (262) | receiver | 347 → 368 (+21) | 187 → 199 (+12) | 142.6 → 152.0 (+9.4) | 0.76 → 0.76 (marg 0.77) | +9.5 [+8.9, +10.0] |
| Hazel Wolf (292) | receiver | 663 → 756 (+93) | 564 → 628 (+64) | 325.9 → 364.2 (+38.3) | 0.58 → 0.58 (marg 0.60) | +38.4 [+35.9, +40.7] |
| **district total** | | | | **10,008.5 → 9,979.3 (-29.2)** | | |

Gifted program: unchanged (no HCC pathway site is touched).

## State funding (EXAL) change

Each term of the STARS Expected Allocation formula contributes a multiplicative factor; the factors multiply exactly to the scenario reimbursement at the mean-draw inputs.

| term | input base → scen | factor on EXAL |
|---|---|---|
| BasicRiders | 9,195 → 9,166 | ×0.9979 |
| SpecialRiders | 4,256 → 4,256 | ×1.0000 |
| Destinations | 105.75 → 104.75 | ×0.9849 |
| AvgDistance (mi) | 2.16 → 2.16 | ×1.0002 |
| **EXAL** | **$36.68M → $36.05M** | **×0.9830** |

MC mean Δ revenue: -0.62 [-0.64, -0.61] $M/yr (differs slightly from the factor product — EXAL is nonlinear across draws). Destinations deltas are vs the any-program served set: only never-served schools count as additions; closures count even if the model carried no rides there.

## Reading the table

- **enrolled** — students assigned to the school (IPF column marginal, all grade bands); a receiver's gain is its share of a closed/converted school's students.
- **bus-eligible** — assigned students living outside the school's walk zone; the gap between Δenrolled and Δeligible is the (approximate) count landing inside the walk zone.
- **EV rides/day** — expected rides at the baseline-calibrated propensity; “affected” rows move because the propensity tilt re-centers as the eligible pool shifts.
- **propensity** — rides/day per bus-eligible student (school level, base → scen); the parenthesized marginal rate is Δrides ÷ Δeligible — the expected uptake of the NEWLY eligible (or newly ineligible) students at this school. A both-ways rider counts 2, so 0.60 ≈ between 30% riding both ways and 60% riding one way; the theoretical max is 2.
- **MC Δ** — mean and 95% interval over the paired Monte Carlo draws (population + behavioral-parameter uncertainty).
