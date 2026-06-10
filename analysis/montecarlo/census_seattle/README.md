# census_seattle — ACS + synthetic population intermediates

Tracked intermediates for Stage 4 (`acs_population.py`) and Stage 5 (`synth_population.py`).

Built from gitignored raw data in `data/census/` via:

    python3 -m analysis.montecarlo.acs_population --build
    python3 -m analysis.montecarlo.synth_population --build

ACS vintage: 2023 5-year estimates. Geography: King County (FIPS 53033) block groups
with any overlap with the SPS territory (union of attendance + option-zone layers).

## Files

### block_groups.csv (558 rows)

One row per block group intersecting SPS territory.

| Column | Description |
|---|---|
| GEOID | 12-digit block-group GEOID (state+county+tract+bg) |
| geoid_tract | 11-digit tract GEOID |
| area_sqft | Total BG area (EPSG:2926 sq ft) |
| sps_area_sqft | Area within SPS boundary |
| sps_frac | sps_area_sqft / area_sqft — used to area-weight partial-overlap BGs |
| centroid_lat / centroid_lon | WGS84 centroid of intersection |
| geometry_wkt | WKT of the SPS-clipped BG polygon (EPSG:2926) |

488 of 558 block groups are fully inside SPS territory (sps_frac > 99%).
70 partially overlap the SPS boundary.

### acs_age.csv (558 rows)

B01001 (Sex by Age) at block-group level — male + female summed.

| Column | Description |
|---|---|
| GEOID | join key |
| age_5_9 | Children 5-9 years |
| age_10_14 | Children 10-14 years |
| age_15_17 | Children 15-17 years |
| age_5_17 | Total school-age children |

Totals in SPS territory: 30,488 (5-9) + 29,281 (10-14) + 16,705 (15-17) = **76,474**.

### acs_enrollment.csv (558 rows)

B14003 (Sex by School Enrollment by Type by Age) at **tract level**, joined to
each block group within the tract. This table is suppressed at block-group
resolution in the ACS, so we use tract-level estimates.

| Column | Description |
|---|---|
| GEOID | 12-digit BG GEOID (key) |
| geoid_tract | 11-digit tract (source of enrollment counts) |
| pub_5_9 / priv_5_9 | Enrolled in public / private school, ages 5-9 (tract total) |
| pub_10_14 / priv_10_14 | Ages 10-14 |
| pub_15_17 / priv_15_17 | Ages 15-17 |
| pub_frac_5_9 | pub / (pub+priv) for 5-9; NaN if both are zero |
| pub_frac_10_14 | Ages 10-14 |
| pub_frac_15_17 | Ages 15-17 |

District-wide public fraction: 75.7% (ES 75%, MS 76%, HS 80%).

### synth_pop.csv (558 rows)

Stage 5 output — estimated public school children per block group × grade band.

| Column | Description |
|---|---|
| GEOID | 12-digit BG GEOID |
| geoid_tract | 11-digit tract |
| sps_frac | from block_groups.csv |
| n_age_5_9 / n_age_10_14 / n_age_15_17 | sps_frac-weighted ACS age counts |
| n_pub_es | Expected public ES children (K-5) |
| n_pub_ms | Expected public MS children (6-8) |
| n_pub_hs | Expected public HS children (9-12) |
| n_pub_total | Sum of above three |
| alpha_es / alpha_ms / alpha_hs | Dirichlet α = n_pub + 0.5 (for MC sampling) |

Age-to-grade-band split:
- 5-9 years → 100% ES
- 10-14 years → 20% ES + 60% MS + 20% HS
- 15-17 years → 100% HS

District total: **52,904** expected vs 49,765 SPS enrollment (1.06x ACS over-count).
Grade split: ES 46.8%, MS 23.2%, HS 30.0%.

The over-count is expected: some children in the SPS territory attend public
school outside SPS (non-existent given SPS boundaries, but a few outliers),
and ACS estimates have survey noise. The IPF stage (Stage 6) calibrates to
actual per-school enrollment as column marginals.

## Monte Carlo sampling

```python
from analysis.montecarlo.synth_population import sample_synth_pop
import numpy as np

rng = np.random.default_rng(seed)
pop = sample_synth_pop(rng)
# pop has columns: GEOID, n_es, n_ms, n_hs
```

The sampler draws grade-band *fractions* (per block group) from
Dirichlet(alpha_es, alpha_ms, alpha_hs) and multiplies by n_pub_total.
District-wide total is preserved by construction; variance is in the
within-block-group and across-block-group spatial distribution.
