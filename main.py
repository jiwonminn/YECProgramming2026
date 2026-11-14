"""Read an input folder, build a schedule, write schedule.csv.

Usage:  python main.py samples/s1_basic -o schedule.csv
"""
import argparse
import csv
from pathlib import Path

from tools.io_util import SCHEDULE_COLUMNS, load_dir
from scheduler import make_schedule


def to_scheduler_inputs(inst):
    """Convert reader.py's dataclasses into the plain dicts scheduler.py expects."""
    meta = {
        "building_cap_kw": inst.meta.building_cap_kw,
        "carbon_price": inst.meta.carbon_price_cad_per_kg,
        "unmet_penalty": inst.meta.unmet_penalty_cad_per_kwh,
    }
    chargers = [{"id": c.charger_id, "max_kw": c.max_kw} for c in inst.chargers]
    cars = [
        {"id": c.car_id, "arrival": c.arrival_hour, "departure": c.departure_hour,
         "need": c.kwh_needed, "flag": c.flag}
        for c in inst.cars
    ]
    hours = {h.hour: {"price": h.price_cad_per_kwh, "co2": h.co2_kg_per_kwh} for h in inst.hours}
    return meta, chargers, cars, hours


def write_schedule(rows, path):
    """Write rows in the exact format the scorer wants: car_id,charger_id,hour,kW (plain UTF-8)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(SCHEDULE_COLUMNS)
        for r in sorted(rows, key=lambda r: (r["hour"], r["charger"])):
            w.writerow([r["car"], r["charger"], r["hour"], r["kw"]])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", help="input folder (or input.csv)")
    ap.add_argument("-o", "--output", default="schedule.csv")
    args = ap.parse_args()

    inst = load_dir(Path(args.data))
    rows = make_schedule(*to_scheduler_inputs(inst))
    write_schedule(rows, args.output)
    print(f"wrote {args.output} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
