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
