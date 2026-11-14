import os
import sys

# organizers' loader (tools/io_util.py) -- cite in slides
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
from io_util import load_dir

from edf_scheduler import make_schedule
from report import write_schedule, summarize

folder = sys.argv[1]
inst = load_dir(folder)
best_rows = make_schedule(inst)

# convert to the format report.py expects
rows = [{"car_id": r["car"], "charger_id": r["charger"], "hour": r["hour"], "kW": r["kw"]} for r in best_rows]
meta = {"carbon_price_cad_per_kg": inst.meta.carbon_price_cad_per_kg,
        "unmet_penalty_cad_per_kwh": inst.meta.unmet_penalty_cad_per_kwh}
hours = {h.hour: (h.price_cad_per_kwh, h.co2_kg_per_kwh) for h in inst.hours}
cars = {c.car_id: (c.kwh_needed, c.flag) for c in inst.cars}

write_schedule(rows, "schedule.csv")
print(f"Wrote {len(rows)} rows to schedule.csv\n")
summarize(rows, meta, hours, cars)