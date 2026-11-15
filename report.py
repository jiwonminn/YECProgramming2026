import csv, os, sys
from collections import defaultdict
# (main.py calls write_schedule and summarize, so no scheduler import needed here)

def read_csv(folder, name):
    with open(os.path.join(folder, name), newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))
#this function is for reading csv for load_input function

def load_input(folder):
    meta = {r["key"]: float(r["value"]) for r in read_csv(folder, "meta.csv")}
    hours = {int(r["hour"]): (float(r["price_cad_per_kwh"]), float(r["co2_kg_per_kwh"]))
             for r in read_csv(folder, "hours.csv")}
    cars = {r["car_id"]: (float(r["kwh_needed"]), r["flag"] or "none")
            for r in read_csv(folder, "cars.csv")}
    return meta, hours, cars
#this function is reading:  meta: building_cap_kw, carbon_price_cad_per_kg, unmet_penalty_cad_per_kwh; 
#                           hours: hour, price_cad_per_kwh, co2_kg_per_kwh; 
#                           cars: car_id, kwh_needed, flag

def write_schedule(rows, path="schedule.csv"):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["car_id", "charger_id", "hour", "kW"])
        for r in rows:
            w.writerow([r["car_id"], r["charger_id"], int(r["hour"]), repr(float(r["kW"]))])
#open up a csv file and write the schedule to it, with columns: car_id, charger_id, hour, kW

def summarize(rows, meta, hours, cars):
    co2_price = meta["carbon_price_cad_per_kg"]
    penalty = meta["unmet_penalty_cad_per_kwh"]
#call the meta values for carbon price and unmet penalty, we know it is a fixed value for the whole simulation, so we can just call it once here

    elec = co2_kg = 0.0
    delivered = defaultdict(float)
    for r in rows:
        kw = float(r["kW"])
        price, co2 = hours[int(r["hour"])]
        elec += kw * price
        co2_kg += kw * co2
        delivered[r["car_id"]] += kw
#calculate the total electricity cost and CO2 emissions based on the schedule rows, and also keep track of how much energy was delivered to each car

    by_flag = defaultdict(lambda: [0, 0.0, 0.0, 0.0])
    unmet_total = 0.0
    for cid, (need, flag) in cars.items():
        got = delivered.get(cid, 0.0)
        unmet = max(0.0, need - got)
        unmet_total += unmet
        b = by_flag[flag]
        b[0] += 1; b[1] += need; b[2] += min(got, need); b[3] += unmet
#group the cars by their flag, and calculate the total unmet energy for each flag, as well as the total number of cars and total energy needed for each flag

    co2_cost = co2_kg * co2_price
    unmet_cost = unmet_total * penalty
    print(f"Electricity cost : ${elec:9.2f}")
    print(f"CO2              : {co2_kg:9.2f} kg   -> ${co2_cost:.2f}")
    print(f"Unmet energy     : {unmet_total:9.2f} kWh  -> ${unmet_cost:.2f}")
    print(f"Combined score   : ${elec + co2_cost + unmet_cost:9.2f}\n")
#print the total electricity cost, CO2 emissions and cost, unmet energy and cost, and the combined score

    print(f"  {'flag':<11}{'cars':>5}{'need':>9}{'delivered':>11}{'unmet':>8}{'% met':>8}")
    for flag in sorted(by_flag):
        n, need, got, unmet = by_flag[flag]
        pct = 100 * got / need if need else 100.0
        print(f"  {flag:<11}{n:>5}{need:>9.1f}{got:>11.1f}{unmet:>8.1f}{pct:>7.1f}%")
#print the summary statistics for each flag

def main():
    folder = sys.argv[1]
    rows = solve(folder)
    write_schedule(rows)
    print(f"Wrote {len(rows)} rows to schedule.csv\n")
    summarize(rows, *load_input(folder))
#main function to call every function in this python file

if __name__ == "__main__":
    main()
#this function is to call the main function when this file is run directly, and not when it is imported as a module