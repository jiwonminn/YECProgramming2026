#!/usr/bin/env python3
"""Greedy baseline: each car in turn takes its cheapest hours, one car per charger per hour.

Strategy (simple, reproducible):
1. Process cars biggest kwh_needed first, then by car_id.
2. For each car, sort its hours in [arrival, departure) by (price + carbon_price * co2), then by hour.
3. In each hour, take the free charger with the highest max_kw and fill as much as the
   charger max, the building cap and the car's remaining need allow.
"""
from __future__ import annotations
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from io_util import SCHEDULE_COLUMNS, _open, load_dir

def run(inst):
    hour_cost = {
        h.hour: h.price_cad_per_kwh + inst.meta.carbon_price_cad_per_kg * h.co2_kg_per_kwh
        for h in inst.hours
    }
    remaining = {c.car_id: c.kwh_needed for c in inst.cars}
    build_left = {h.hour: inst.meta.building_cap_kw for h in inst.hours}
    busy = set()  # (hour, charger_id) already serving a car
    chargers = sorted(inst.chargers, key=lambda c: (-c.max_kw, c.charger_id))
    schedule = []

    for car in sorted(inst.cars, key=lambda c: (-c.kwh_needed, c.car_id)):
        hours = [h for h in range(car.arrival_hour, car.departure_hour) if h in hour_cost]
        hours.sort(key=lambda h: (hour_cost[h], h))
        for h in hours:
            if remaining[car.car_id] <= 1e-9:
                break
            if build_left[h] <= 1e-9:
                continue
            free = next((c for c in chargers if (h, c.charger_id) not in busy), None)
            if free is None:
                continue
            kw = round(min(remaining[car.car_id], free.max_kw, build_left[h]), 4)
            if kw <= 1e-9:
                continue
            schedule.append({"car_id": car.car_id, "charger_id": free.charger_id, "hour": h, "kW": kw})
            busy.add((h, free.charger_id))
            remaining[car.car_id] -= kw
            build_left[h] -= kw
    schedule.sort(key=lambda r: (r["hour"], r["charger_id"]))
    return schedule

def write_schedule(schedule, path):
    with _open(path, "w") as f:
        w = csv.DictWriter(f, fieldnames=SCHEDULE_COLUMNS)
        w.writeheader()
        w.writerows(schedule)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", help="input folder or input.csv")
    ap.add_argument("-o", "--output", default="schedule.csv")
    args = ap.parse_args()
    schedule = run(load_dir(Path(args.data)))
    write_schedule(schedule, args.output)
    print(f"wrote {args.output} ({len(schedule)} rows)")

if __name__ == "__main__":
    main()
