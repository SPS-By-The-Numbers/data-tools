# Ruralness density term

**Script:** `stars_ruralness.py`

## Purpose
Test whether a single "ruralness" indicator — population density
(`basic_program / land_area`) — adds explanatory power to the STARS model.

## Key modelling note
The base model already has `ln(land_area)` and `ln(basic_program)`, so adding
`ln(density) = ln(basic_program) − ln(land_area)` would be a **perfect linear
combination** of existing terms (singular). Density therefore must enter in
**level/ratio form** to carry new information.

## Key findings
Dependent = F-196 cost (real target):
- ΔR² ≈ **0.0001–0.0002** per year; density **never significant** (0/8 years,
  p ≥ 0.22); AIC mostly *worsens*.
- `a4` negative control: ΔR² ≈ 0 (as expected — `a4` is a pure function of the 7
  inputs), confirming the test is wired correctly.

## Takeaway
A single density term adds essentially nothing. Ruralness is already captured by
the inputs the formula has — `average_distance` (long routes = rural) plus the
size terms. This is a **null result**; the structural question (do rural and urban
districts have *different* cost structures?) is answered separately and more
usefully in `stars_rural_interaction.md`.

## Run
```
python3 analysis/stars_ruralness.py            # dep=cost
python3 analysis/stars_ruralness.py --dep a4   # negative control
```
