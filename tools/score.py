#!/usr/bin/env python3
"""Score a schedule.csv. Illegal or unreadable rows are dropped and that energy counts as unmet."""
from __future__ import annotations
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from io_util import ScheduleFile, load_dir, load_schedule
from validate import legal_rows, validate

def score(inst, sched: ScheduleFile):
    errors, warnings = validate(inst, sched)
    legal, _ = legal_rows(inst, sched.rows)
    hours = {h.hour: h for h in inst.hours}

    delivered = defaultdict(float)
    elec_cost = 0.0
    co2_kg = 0.0
    for row in legal:
        h = hours[row["hour"]]
        kw = row["kW"]
        delivered[row["car_id"]] += kw
        elec_cost += kw * h.price_cad_per_kwh
        co2_kg += kw * h.co2_kg_per_kwh

    unmet_by_flag = defaultdict(float)
    unmet_total = 0.0
    for car in inst.cars:
        unmet = max(0.0, car.kwh_needed - delivered.get(car.car_id, 0.0))
        unmet_total += unmet
        unmet_by_flag[car.flag] += unmet

    co2_cost = co2_kg * inst.meta.carbon_price_cad_per_kg
    unmet_penalty = unmet_total * inst.meta.unmet_penalty_cad_per_kwh
    return {
        "electricity_cost_cad": elec_cost,
        "co2_kg": co2_kg,
        "co2_cost_cad": co2_cost,
        "unmet_kwh": unmet_total,
        "unmet_penalty_cad": unmet_penalty,
        "combined_score": elec_cost + co2_cost + unmet_penalty,
        "unmet_by_flag": dict(unmet_by_flag),
        "validate_errors": len(errors),
        "validate_warnings": len(warnings),
        "legal_rows": len(legal),
        "raw_rows": len(sched.rows) + len(sched.problems),
    }

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data", help="input folder or input.csv")
    ap.add_argument("schedule")
    ap.add_argument("--baseline-schedule", help="optional baseline schedule.csv to compare against")
    args = ap.parse_args()
    inst = load_dir(Path(args.data))
    result = score(inst, load_schedule(Path(args.schedule)))
    print(f"electricity_cost_cad: {result['electricity_cost_cad']:.4f}")
    print(f"co2_kg: {result['co2_kg']:.4f}")
    print(f"co2_cost_cad: {result['co2_cost_cad']:.4f}")
    print(f"unmet_kwh: {result['unmet_kwh']:.4f}")
    print(f"unmet_penalty_cad: {result['unmet_penalty_cad']:.4f}")
    print(f"combined_score (lower better): {result['combined_score']:.4f}")
    print("unmet_by_flag:", {k: round(v, 4) for k, v in result["unmet_by_flag"].items()})
    print(f"rows: {result['legal_rows']}/{result['raw_rows']} legal; validate errors={result['validate_errors']}")
    if args.baseline_schedule:
        base = score(inst, load_schedule(Path(args.baseline_schedule)))
        print(f"baseline_combined: {base['combined_score']:.4f}")
        print(f"improvement_vs_baseline (higher better): {base['combined_score'] - result['combined_score']:.4f}")

if __name__ == "__main__":
    main()
