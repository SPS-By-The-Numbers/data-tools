# Rural/urban indicator + input interactions

**Script:** `stars_rural_interaction.py`

## Purpose
Ask the structural question: do rural and urban districts have **different cost
structures**? Add a rural/urban dummy and interact it with every continuous input
so each slope (elasticity) can differ, then joint-F-test the interaction block.

## Method
Rural = bottom 50% by density (`basic_program/land_area`), split per year. Model
adds `rural` + `rural × {land_area, average_distance, destinations, basic_program,
special_program}`. Dependent = F-196 cost. `a4` = negative control.

## Key findings
Cost target, jointly significant in **4 of 6** non-COVID years (ΔR² 0.0009–0.0045).

**Critical caveat — trust ΔR², not the F-test:** the `a4` negative control is
"significant" at p<1e-5 in **7/7** years *despite ΔR² ≈ 0*. When base R² ≈ 0.9998,
residual variance is so tiny that microscopic curvature reads as highly
significant. By the honest metric, cost gains ~0.3–0.45% — **~30× the control** —
so it's real but small.

Interpretable slope differences (2018-19):
| interaction | coef | p | meaning |
|---|---|---|---|
| rural × land_area | +0.100 | 0.023 | land area drives cost rurally, ~nil urban |
| rural × destinations | +0.017 | 0.012 | destinations matter more rurally |
| rural × special_program | −0.117 | 0.020 | special-ed scales less steeply rurally |

Geography is the cost driver in rural districts; ridership counts dominate urban.

## Takeaway
A genuine but **small** structural difference (<0.5% added R²) — it won't move the
coefficient-recovery floor. The policy-relevant consequence (the single statewide
formula's residuals are biased by district identity) is pursued in
`stars_credibility.md` and `stars_mixed.md`.

## Run
```
python3 analysis/stars_rural_interaction.py
python3 analysis/stars_rural_interaction.py --dep a4   # negative control
```
