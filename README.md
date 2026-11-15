# EV Charging Scheduler and Dashboard

This project reads EV charging instances from a folder or a single `input.csv`, builds a charging schedule, validates it, and then prints a score summary. The core logic is split across the scheduler, report, validation, and dashboard scripts.

## Project layout

- [main.py](main.py): command-line entry point for generating a schedule from an input folder and writing a CSV file.
- [scheduler.py](scheduler.py): builds a schedule using a greedy strategy plus a repair step and chooses the best rule by score.
- [report.py](report.py): writes a schedule CSV and prints a summary of electricity cost, CO2, unmet energy, and the combined score.
- [dashboard.py](dashboard.py): reads a schedule and renders a single HTML dashboard using a template and embedded JSON data.
- [tools/io_util.py](tools/io_util.py): input/output helpers for loading instance data and reading schedule files.
- [tools/validate.py](tools/validate.py): checks whether schedule rows are legal under the instance constraints.
- [tools/score.py](tools/score.py): computes a cost-based score from a schedule and reports validation counts.
- [tools/greedy_baseline.py](tools/greedy_baseline.py): a simple baseline scheduler that charges by cheapest hours.

## What the code reads

The project works with an input instance in one of two forms:

1. A directory with these files:
   - `meta.csv`
   - `chargers.csv`
   - `cars.csv`
   - `hours.csv`
2. A single `input.csv` file containing rows tagged by `record_type` values like `META`, `CHARGER`, `CAR`, and `HOUR`.

The loader in [tools/io_util.py](tools/io_util.py) normalizes both forms into a dataclass-based `Instance` object containing:

- `Meta`: `building_cap_kw`, `carbon_price_cad_per_kg`, `unmet_penalty_cad_per_kwh`
- `Charger`: `charger_id`, `max_kw`
- `Car`: `car_id`, `arrival_hour`, `departure_hour`, `kwh_needed`, `flag`
- `Hour`: `hour`, `price_cad_per_kwh`, `co2_kg_per_kwh`

The loader is called via `load_dir(path)`, which accepts either a directory or a file path.

## Main scheduler entry point

[main.py](main.py) does the following:

1. `load_dir(input_path)` loads the instance.
2. `make_best_schedule(instance)` is called with the instance.
3. The selected rule is printed as `Selected rule: ...`.
4. The scheduler rows are converted to the plain dictionary format expected by [report.py](report.py).
5. `write_schedule(rows, output_path)` writes the schedule CSV.
6. `summarize(rows, meta, hours, cars)` prints the summary.

The default output filename is `schedule.csv` when no output path is passed.

Usage:

```bash
python3 main.py <input> [output.csv]
```

Example:

```bash
python3 main.py samples/s1_basic
python3 main.py samples/s2_tight_cap out.csv
```

## Scheduler behavior

[scheduler.py](scheduler.py) implements a greedy charging scheduler and evaluates multiple priority rules.

The rule list is:

- `spare_kwh`
- `edf`

The scheduler repeatedly tries each rule, builds a schedule for that rule, scores the result, and keeps the best one. The score is computed as:

- electricity cost
- CO2 cost based on `carbon_price_cad_per_kg`
- unmet energy penalty based on `unmet_penalty_cad_per_kwh`

The schedule is built with a repair step that tries to move charging away from congested hours when a car remains short. The returned object is a pair of:

- `rows`: list of schedule rows
- `rule`: rule name that was selected as best

The score compares rows by:

1. total score
2. unmet energy by flag in the order: `accessible`, `on_call`, `visitor`, `none`

This is done through `make_best_schedule(inst, verbose=True)`.

## Schedule row format

The generated schedule rows use fields like:

```python
{"car": car_id, "charger": charger_id, "hour": hour, "kw": kW}
```

This is the internal format used by [scheduler.py](scheduler.py).

Before writing or summarizing, [main.py](main.py) converts them to the report format:

```python
{"car_id": ..., "charger_id": ..., "hour": ..., "kW": ...}
```

This is the format expected by [report.py](report.py) and the schedule validators.

## Report output

[report.py](report.py) provides two functions used by the CLI:

- `write_schedule(rows, path="schedule.csv")`: writes a CSV with the columns `car_id,charger_id,hour,kW`.
- `summarize(rows, meta, hours, cars)`: prints a summary showing:
  - electricity cost
  - CO2 emitted and CO2 cost
  - unmet energy and unmet penalty
  - combined score
  - per-flag totals for car count, energy needed, delivered, unmet, and percent met

The `summarize` function expects plain dictionaries, not dataclass instances. It uses the meta values and a mapping of hour to `(price_cad_per_kwh, co2_kg_per_kwh)` and car-to-`(kwh_needed, flag)` data.

## Validation and scoring utilities

The `tools` folder contains utilities that read, validate, and score schedule files: [tools/io_util.py](tools/io_util.py), [tools/validate.py](tools/validate.py), [tools/score.py](tools/score.py), and [tools/greedy_baseline.py](tools/greedy_baseline.py).

- `load_dir(path)` reads an instance folder or single `input.csv` and returns an `Instance` object.
- `load_schedule(path)` reads a schedule CSV into a `ScheduleFile` with `rows` and `problems`.
- `legal_rows(inst, rows)` filters rows to the ones that are legal under the hour/charger/building constraints.
- `validate(inst, sched)` checks the schedule and warns for under-delivery or overcharging.
- `score(inst, sched)` computes the cost-based score from legal rows and reports validation counts.
- `greedy_baseline.py` is a simple, reproducible baseline that assigns each car to the cheapest available hours.

## Dashboard

[dashboard.py](dashboard.py) builds a single-page HTML dashboard from a schedule and the original input folder.

It does the following:

- loads the scenario instance
- loads the schedule file with `load_schedule`
- validates the rows and filters out illegal ones before building the dashboard metrics
- builds summary KPI cards, CO2 data, hourly load data, forecast data, and a raw schedule dump
- writes a finished HTML page to `dashboard_report.html` unless `--serve` is used

Usage:

```bash
python3 dashboard.py samples/s2_tight_cap
python3 dashboard.py samples/s2_tight_cap schedule.csv --open
python3 dashboard.py samples/s2_tight_cap schedule.csv --serve --open
```

When using `--serve`, it starts a local HTTP server at `http://127.0.0.1:8000` and serves the dashboard dynamically.

The template is [dashboard.html](dashboard.html). The script reads it, injects JSON data where the `__DATA__` placeholder appears, and writes the final page without modifying the template file itself.

## Results from the sample scenarios

These numbers were produced by running the actual project entry point and the actual scoring utility on each sample.

| Scenario | Command | Combined score | Notes |
| --- | --- | ---: | --- |
| `samples/s1_basic` | `python3 main.py samples/s1_basic` then `python3 tools/score.py samples/s1_basic schedule.csv` | 8.0298 | all cars fully served; no unmet energy |
| `samples/s2_tight_cap` | `python3 main.py samples/s2_tight_cap` then `python3 tools/score.py samples/s2_tight_cap schedule.csv` | 56.4595 | tight building cap; 46.2 kWh unmet |
| `samples/s3_evening_rush` | `python3 main.py samples/s3_evening_rush` then `python3 tools/score.py samples/s3_evening_rush schedule.csv` | 16.6328 | all cars fully served; no unmet energy |

Baseline and best-possible references are taken from the files in each sample directory:

| Scenario | Baseline | Best possible (reference.csv) | Notes |
| --- | ---: | ---: | --- |
| `samples/s1_basic` | 8.0298 | 8.0298 | baseline and reference match; all demand served |
| `samples/s2_tight_cap` | 56.4595 | 56.4595 | same schedule at the current solver output |
| `samples/s3_evening_rush` | 16.6328 | 16.6328 | same schedule at the current solver output |

The `reference.csv` values are read by the dashboard when present and shown as the “best possible” comparison, but the measured project output above is the actual output of the current solver.

## Fairness

The scheduler’s tie-breaker prefers less unmet energy for `accessible` cars before `on_call`, then `visitor`, then `none` when the total score is tied. This is implemented in [scheduler.py](scheduler.py) via `TIE_BREAK_ORDER` and `unmet_by_flag()`.

The reason is practical: `accessible` drivers have the most constrained access in the scheduling model, and `on_call` drivers are treated as a priority group when there is a score tie. The tie-break therefore preserves the most constrained groups before choosing among otherwise equal-cost schedules.

## Testing

The project is tested by running the project entry point and the scoring utilities against the included sample scenarios:

```bash
python3 main.py samples/s1_basic
python3 main.py samples/s2_tight_cap
python3 main.py samples/s3_evening_rush

python3 tools/score.py samples/s1_basic schedule.csv
python3 tools/score.py samples/s2_tight_cap schedule.csv
python3 tools/score.py samples/s3_evening_rush schedule.csv
```

The score output should stay at roughly the values in the table above, and the `validate errors=0` check should pass for the generated schedule files.

## Credits

This project includes utility scripts in the `tools/` directory from GDG on Campus York University.

## Notes

- The code uses the standard library only for its entry points and helper logic.
- The optimization logic and validation logic are intentionally separated.
- The project is structured around reading an input instance, generating a valid schedule, validating/scoring it, and optionally rendering a dashboard.
