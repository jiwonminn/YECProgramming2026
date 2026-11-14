#!/usr/bin/env python3
"""Validate a schedule.csv against an instance. Exit 0 if fully valid (warnings OK).

The scorer uses the same rules (legal_rows below), so VALID here means every row will count.
"""
from __future__ import annotations
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from io_util import FLAGS, load_dir, load_schedule

EPS = 1e-6

def legal_rows(inst, rows):
    """Check rows top to bottom. Returns (legal, errors).

    A row that breaks a rule is dropped. For the per-hour limits (one car per charger,
    one charger per car, charger max, building cap) the row that would break the limit is
    the one dropped, so earlier rows in the file win.
    """
    charger_max = {c.charger_id: c.max_kw for c in inst.chargers}
    cars = {c.car_id: c for c in inst.cars}
    hours = {h.hour for h in inst.hours}

    charger_kw = defaultdict(float)   # (hour, charger) -> kW
    building_kw = defaultdict(float)  # hour -> kW
    car_on = {}                       # (hour, car) -> charger
    charger_has = {}                  # (hour, charger) -> car
    legal, errors = [], []

    for row in rows:
        loc = f"schedule.csv line {row['line']}"
        car_id, ch, h, kw = row["car_id"], row["charger_id"], row["hour"], row["kW"]
        if car_id not in cars:
            errors.append(f"{loc}: unknown car_id {car_id!r}")
            continue
        if ch not in charger_max:
            errors.append(f"{loc}: unknown charger_id {ch!r}")
            continue
        if h not in hours:
            errors.append(f"{loc}: hour {h} not in hours data")
            continue
        if kw < 0:
            errors.append(f"{loc}: negative kW")
            continue
        if kw == 0:
            continue  # harmless no-op, doesn't occupy the charger
        car = cars[car_id]
        if not (car.arrival_hour <= h < car.departure_hour):
            errors.append(
                f"{loc}: car {car_id} cannot charge at hour {h} "
                f"(window [{car.arrival_hour}, {car.departure_hour}))"
            )
            continue
        if car_on.get((h, car_id), ch) != ch:
            errors.append(f"{loc}: car {car_id} already on charger {car_on[(h, car_id)]} at hour {h}")
            continue
        if charger_has.get((h, ch), car_id) != car_id:
            errors.append(f"{loc}: charger {ch} already serving car {charger_has[(h, ch)]} at hour {h}")
            continue
        if charger_kw[(h, ch)] + kw - charger_max[ch] > EPS:
            errors.append(f"{loc}: charger {ch} would draw {charger_kw[(h, ch)] + kw:.6f} kW at hour {h}, max {charger_max[ch]}")
            continue
        if building_kw[h] + kw - inst.meta.building_cap_kw > EPS:
            errors.append(
                f"{loc}: building would draw {building_kw[h] + kw:.6f} kW at hour {h}, cap {inst.meta.building_cap_kw}"
            )
            continue
        car_on[(h, car_id)] = ch
        charger_has[(h, ch)] = car_id
        charger_kw[(h, ch)] += kw
        building_kw[h] += kw
        legal.append(row)
    return legal, errors

def validate(inst, sched):
    """sched is a ScheduleFile from io_util.load_schedule."""
    legal, errors = legal_rows(inst, sched.rows)
    errors = sched.problems + errors
    warnings = []
    energy = defaultdict(float)
    for row in legal:
        energy[row["car_id"]] += row["kW"]  # 1-hour slots, so kWh = kW
    for car in inst.cars:
        if car.flag not in FLAGS:
            errors.append(f"input: car {car.car_id} has unknown flag {car.flag!r}")
        delivered = energy.get(car.car_id, 0.0)
        if delivered + EPS < car.kwh_needed:
            warnings.append(f"car {car.car_id} ({car.flag}): delivered {delivered:.2f} / {car.kwh_needed:g} kWh")
        elif delivered - car.kwh_needed > EPS:
            warnings.append(
                f"car {car.car_id}: overcharged {delivered:.2f} > {car.kwh_needed:g} kWh "
                "(extra energy still counts toward cost/CO2)"
            )
    return errors, warnings

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", help="input folder or input.csv")
    ap.add_argument("schedule", help="schedule.csv")
    args = ap.parse_args()
    inst = load_dir(Path(args.data))
    errors, warnings = validate(inst, load_schedule(Path(args.schedule)))
    for w in warnings:
        print("WARN:", w)
    for e in errors:
        print("ERROR:", e)
    if errors:
        print(f"INVALID: {len(errors)} error(s), {len(warnings)} warning(s). Rows with errors score as if they weren't there.")
        sys.exit(1)
    print(f"VALID: 0 errors, {len(warnings)} warning(s)")
    sys.exit(0)

if __name__ == "__main__":
    main()
