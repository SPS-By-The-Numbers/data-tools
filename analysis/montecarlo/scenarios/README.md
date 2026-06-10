# scenarios/ — machine-readable scenario specs (Stage 9 inputs)

Each `*.json` file is one scenario: an ordered list of ops applied to a copy
of the 2024-25 baseline world by `scenarios.py`. These are INPUTS (tracked),
not pipeline outputs — evaluation results are returned in memory by
`run_scenario`; persisted Monte Carlo results live under `../simulate/<name>/`
(Stage 10 — see the README there).

```json
{
  "name": "...",            // optional; defaults to the filename stem
  "description": "...",
  "ops": [ { "op": "<kind>", ...params, "comment": "ignored" }, ... ]
}
```

Ops (see `scenarios.py` module docstring for semantics and defaults):

| op | params |
|---|---|
| `set_walk_threshold` | `level` (ES/MS/HS), `miles` |
| `scale_walkzone` | `school_id`, exactly one of `factor` / `miles` |
| `close_school` | `school_id`, optional `receivers` (list), `hcc_receiver` |
| `convert_option_to_neighborhood` | `school_id` (option school w/ geozone), optional `stay_rate` |
| `move_school` | `school_id`, `new_location` (`[x_ft, y_ft]` EPSG:2926 or `{lat, lon}`), optional `move_geozone` |
| `add_basic_service` | exactly one of `level` (ES/MS/HS — every open school of that level) / `school_ids`; grants basic yellow-bus service, walk zones untouched (compose with the walk ops) |

`school_id` everywhere is the 3-digit SPS site number (parse_shapes locations).

Usage:

```console
$ python3 -m analysis.montecarlo.scenarios                    # list + validate specs
$ python3 -m analysis.montecarlo.scenarios --validate         # empty == baseline check
$ python3 -m analysis.montecarlo.scenarios --run close_sacajawea
```

Files:
- `empty.json` — no ops; the M6 acceptance check (must reproduce baseline).
- `es_walk_1p5mi.json` — ES walk threshold 1.0 → 1.5 mi (calibrated buffers).
- `close_sacajawea.json` — close Sacajawea ES (268) with default receivers.
- `ms_walk_1mi.json` — MS walk threshold 2.0 → 1.0 mi (user scenario, s10).
- `hs_bussing.json` — re-add HS basic yellow-bus service, official walk zones
  kept (user scenario, s10; introduced the `add_basic_service` op).
- `hs_bussing_1mi.json` — HS bussing + HS walk threshold 2.0 → 1.0 mi
  (user scenario, s10).
- `close_option_a.json` — KUOW-reported SPS "well-resourced schools" plan:
  close 21 schools incl. most option/K-8s (user scenario, s10). Engine
  default relocation rules; ops in the article's NW→SW order.
- `close_option_b.json` — KUOW-reported SPS "choice" plan: close 17 schools
  incl. Thurgood Marshall, whose HCC service relocates to Beacon Hill
  International (205) per the plan (user scenario, s10). Other relocations
  default; same op order.
- `close_option_b_dearborn.json` — Option B variant with TM's HCC going to
  Dearborn Park (251), the other receiver the plan names.
- `close_fab4.json` — the "fab-4" plan: close North Beach, Sacajawea,
  Stevens, Sanislo, each consolidating into one named receiver (Viewlands,
  John Rogers, Montlake, Highland Park) instead of the 3-nearest default
  (user scenario, s10).
- `convert_optA_rand1.json` / `convert_optA_rand2.json` — convert 5 of the
  6 option schools on the Option A list to neighborhood schools, two random
  combos (seed 20260610; user scenario, s10). rand1 keeps Boren option,
  rand2 keeps Salmon Bay.
