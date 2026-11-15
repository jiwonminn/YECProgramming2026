#!/usr/bin/env python3
"""Run the EV scheduler from the command line."""

import sys
from pathlib import Path

# Find tools/ relative to main.py, not the current working directory.
BASE_DIR = Path(__file__).resolve().parent
TOOLS_DIR = BASE_DIR / "tools"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import io_util
from report import summarize, write_schedule
from scheduler import make_best_schedule


def main():
    if len(sys.argv) not in (2, 3):
        print(
            f"Usage: python3 {Path(sys.argv[0]).name} <input> [output.csv]",
            file=sys.stderr,
        )
        return 2

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2]) if len(sys.argv) == 3 else Path("schedule.csv")

    # Load the input and find the best schedule.
    instance = io_util.load_dir(input_path)
    rows, rule = make_best_schedule(instance)

    print(f"Using rule: {rule}")

    # scheduler.py uses car/charger/kw, while report.py expects
    # car_id/charger_id/kW.
    report_rows = [
        {
            "car_id": row["car"],
            "charger_id": row["charger"],
            "hour": row["hour"],
            "kW": row["kw"],
        }
        for row in rows
    ]

    # Write the output CSV.
    write_schedule(report_rows, output_path)
    print(f"Wrote {len(report_rows)} rows to {output_path}\n")

    # summarize() expects plain dicts rather than the dataclasses
    # returned by io_util.load_dir().
    meta = {
        "building_cap_kw": instance.meta.building_cap_kw,
        "carbon_price_cad_per_kg": instance.meta.carbon_price_cad_per_kg,
        "unmet_penalty_cad_per_kwh": instance.meta.unmet_penalty_cad_per_kwh,
    }

    hours = {
        hour.hour: (
            hour.price_cad_per_kwh,
            hour.co2_kg_per_kwh,
        )
        for hour in instance.hours
    }

    cars = {
        car.car_id: (
            car.kwh_needed,
            car.flag or "none",
        )
        for car in instance.cars
    }

    summarize(report_rows, meta, hours, cars)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())