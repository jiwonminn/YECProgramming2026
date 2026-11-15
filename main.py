#!/usr/bin/env python3

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scheduler import make_best_schedule
from report import summarize, write_schedule
from tools.io_util import load_dir


def _as_report_rows(schedule_rows):
    return [
        {
            "car_id": row["car"],
            "charger_id": row["charger"],
            "hour": int(row["hour"]),
            "kW": float(row["kw"]),
        }
        for row in schedule_rows
    ]


def _as_report_meta(instance):
    meta = {
        "building_cap_kw": instance.meta.building_cap_kw,
        "carbon_price_cad_per_kg": instance.meta.carbon_price_cad_per_kg,
        "unmet_penalty_cad_per_kwh": instance.meta.unmet_penalty_cad_per_kwh,
    }
    hours = {
        hour.hour: (hour.price_cad_per_kwh, hour.co2_kg_per_kwh)
        for hour in instance.hours
    }
    cars = {
        car.car_id: (car.kwh_needed, car.flag)
        for car in instance.cars
    }
    return meta, hours, cars


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) < 2:
        print(f"Usage: python3 {Path(argv[0]).name} <input> [output.csv]", file=sys.stderr)
        return 1

    input_path = Path(argv[1])
    output_path = Path(argv[2]) if len(argv) > 2 else Path("schedule.csv")

    instance = load_dir(input_path)
    schedule_rows, rule = make_best_schedule(instance, verbose=False)
    print(f"Selected rule: {rule}")

    report_rows = _as_report_rows(schedule_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_schedule(report_rows, str(output_path))
    meta, hours, cars = _as_report_meta(instance)
    summarize(report_rows, meta, hours, cars)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
