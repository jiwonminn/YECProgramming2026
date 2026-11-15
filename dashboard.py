#!/usr/bin/env python3
"""EV charging dashboard (BONUS). Python builds the data; the page layout lives in dashboard.html.

    python dashboard.py samples/s2_tight_cap                         # uses schedule.csv if present
    python dashboard.py samples/s2_tight_cap schedule.csv --open     # writes dashboard_report.html
    python dashboard.py samples/s2_tight_cap schedule.csv --serve --open   # live: http://127.0.0.1:8000

Shows: headline numbers, report.py's summary with a schedule.csv download,
two charts (cars charging per hour, CO2 kg per charger per hour as a heatmap) and the hourly cost forecast
(electricity + CO2 per kWh).

dashboard.html is the TEMPLATE. Edit it freely (Bootstrap, layout, text), but keep the
__DATA__ placeholder: this script swaps it for the JSON data. The finished page is written to
dashboard_report.html so the template is never overwritten.
"""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from tools.io_util import load_dir, load_schedule  # noqa: E402
from report import summarize  # noqa: E402
from main import _as_report_meta  # noqa: E402

EPS = 1e-6
TEMPLATE = ROOT / "dashboard.html"


# ----------------------------------------------------------------------------- scoring (unchanged)
def check_rows(cars, hours, chargers, caps, rows):
    """Mirror tools/validate.legal_rows with per-hour building caps. Returns a reason (or None) per row."""
    car_by = {c.car_id: c for c in cars}
    hset = {h.hour for h in hours}
    ch_kw, b_kw = defaultdict(float), defaultdict(float)
    car_on, ch_has = {}, {}
    out = []
    for r in rows:
        cid, ch, h, kw = r["car_id"], r["charger_id"], r["hour"], r["kW"]
        why = None
        if cid not in car_by:
            why = "unknown car"
        elif ch not in chargers:
            why = "unknown charger"
        elif h not in hset:
            why = "hour not in data"
        elif kw < 0:
            why = "negative kW"
        elif kw == 0:
            why = "zero kW (ignored)"
        elif not (car_by[cid].arrival_hour <= h < car_by[cid].departure_hour):
            why = "outside car window"
        elif car_on.get((h, cid), ch) != ch:
            why = "car on two chargers"
        elif ch_has.get((h, ch), cid) != cid:
            why = "charger already in use"
        elif ch_kw[(h, ch)] + kw - chargers[ch] > EPS:
            why = "over charger max"
        elif b_kw[h] + kw - caps.get(h, 0.0) > EPS:
            why = "over building cap"
        if why is None:
            car_on[(h, cid)], ch_has[(h, ch)] = ch, cid
            ch_kw[(h, ch)] += kw
            b_kw[h] += kw
        out.append(why)
    return out


def evaluate(cars, hours, chargers, caps, cp, penalty, rows):
    reasons = check_rows(cars, hours, chargers, caps, rows)
    legal = [r for r, w in zip(rows, reasons) if w is None]
    hm = {h.hour: h for h in hours}
    delivered, load = defaultdict(float), defaultdict(float)
    elec = co2 = 0.0
    for r in legal:
        h = hm[r["hour"]]
        delivered[r["car_id"]] += r["kW"]
        load[r["hour"]] += r["kW"]
        elec += r["kW"] * h.price_cad_per_kwh
        co2 += r["kW"] * h.co2_kg_per_kwh
    flags = defaultdict(lambda: dict(cars=0, need=0.0, got=0.0, unmet=0.0))
    unmet = 0.0
    for c in cars:
        got = delivered.get(c.car_id, 0.0)
        u = max(0.0, c.kwh_needed - got)
        unmet += u
        f = flags[c.flag]
        f["cars"] += 1
        f["need"] += c.kwh_needed
        f["got"] += min(got, c.kwh_needed)
        f["unmet"] += u
    return dict(reasons=reasons, legal=legal, elec=elec, co2_kg=co2, co2_cost=co2 * cp, unmet=unmet,
                penalty=unmet * penalty, combined=elec + co2 * cp + unmet * penalty,
                flags=dict(flags), load=dict(load), delivered=dict(delivered))


# ----------------------------------------------------------------------------- report.py summary
def report_summary(inst, legal_rows):
    """Run report.summarize() exactly as main.py does and capture what it prints.

    report.py's logic is not touched: we only read its printed lines. The per-flag table it prints
    after the blank line is skipped on purpose (the dashboard no longer shows fairness by flag).
    Legal rows only, so rows the scorer would drop don't count here either.
    """
    meta, hours, cars = _as_report_meta(inst)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            summarize(legal_rows, meta, hours, cars)
    except Exception as e:  # never let the summary break the whole dashboard
        return [dict(metric="report.py error", value=f"{type(e).__name__}: {e}")]
    totals = buf.getvalue().split("\n\n")[0]
    out = []
    for line in totals.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out.append(dict(metric=k.strip(), value=" ".join(
                v.split()).replace("$ ", "$")))
    return out


# ----------------------------------------------------------------------------- analysis
def money(x):
    return f"${x:,.2f}"


def build(folder, sched_path):
    inst = load_dir(folder)
    sched = load_schedule(sched_path)
    cars, hours = inst.cars, sorted(inst.hours, key=lambda h: h.hour)
    chargers = {c.charger_id: c.max_kw for c in inst.chargers}
    m = inst.meta
    cap, cp, pen = m.building_cap_kw, m.carbon_price_cad_per_kg, m.unmet_penalty_cad_per_kwh
    caps = {h.hour: cap for h in hours}
    hm = {h.hour: h for h in hours}
    hlist = [h.hour for h in hours]

    base = evaluate(cars, hours, chargers, caps, cp, pen, sched.rows)
    ref = None
    ref_file = Path(folder) / "reference.csv"
    if ref_file.exists():
        try:
            ref = float(ref_file.read_text(
                encoding="utf-8-sig").splitlines()[1].split(",")[0])
        except (ValueError, IndexError):
            ref = None

    # ---- chart data
    charging = {h: set() for h in hlist}
    co2 = {cid: {h: 0.0 for h in hlist} for cid in chargers}
    for r in base["legal"]:
        charging[r["hour"]].add(r["car_id"])
        co2[r["charger_id"]][r["hour"]] += r["kW"] * \
            hm[r["hour"]].co2_kg_per_kwh
    # which car / how many kW each charger delivered in each hour (for the heatmap tooltip)
    detail = {cid: {} for cid in chargers}
    for r in base["legal"]:
        d = detail[r["charger_id"]].setdefault(
            r["hour"], dict(car=r["car_id"], kw=0.0))
        d["kw"] = round(d["kw"] + r["kW"], 4)
    parked = {h: sum(1 for c in cars if c.arrival_hour <=
                     h < c.departure_hour) for h in hlist}
    hour_rows = [dict(h=h, price=hm[h].price_cad_per_kwh, co2=hm[h].co2_kg_per_kwh, charging=len(charging[h]),
                      parked=parked[h], load=round(base["load"].get(h, 0.0), 4), cap=cap) for h in hlist]
    order = sorted(chargers, key=lambda c: (-sum(co2[c].values()), c))
    co2_series = {cid: [round(co2[cid][h], 5) for h in hlist] for cid in order}

    raw = Path(sched_path).read_bytes().decode("utf-8-sig", errors="replace")

    # ---- forecast: cost of 1 kWh by hour = electricity price + CO2 cost (logic from forecast.py)
    f_price = [hm[h].price_cad_per_kwh for h in hlist]
    f_co2 = [hm[h].co2_kg_per_kwh for h in hlist]
    f_co2_cost = [x * cp for x in f_co2]
    f_total = [p + c for p, c in zip(f_price, f_co2_cost)]
    # cheapest = lowest price, cleanest = lowest CO2, best = lowest total (price + CO2 cost)
    cheapest = min(hlist, key=lambda h: hm[h].price_cad_per_kwh)
    cleanest = min(hlist, key=lambda h: hm[h].co2_kg_per_kwh)
    best = hlist[f_total.index(min(f_total))]
    forecast = dict(
        hours=[dict(h=h, price=round(p, 5), co2=round(e, 5), co2_cost=round(c, 5), total=round(t, 5))
               for h, p, e, c, t in zip(hlist, f_price, f_co2, f_co2_cost, f_total)],
        cheapest=cheapest, cleanest=cleanest, best=best, carbon_price=cp)

    peak = max(base["load"].values(), default=0.0)
    full = sum(1 for c in cars if base["delivered"].get(
        c.car_id, 0.0) + EPS >= c.kwh_needed)
    dropped = sum(1 for w in base["reasons"]
                  if w and "ignored" not in w) + len(sched.problems)
    kpis = [
        dict(label="Combined score", value=money(base["combined"]), sub=(
            f"best possible {money(ref)}" if ref is not None else "lower is better")),
        dict(label="Electricity", value=money(
            base["elec"]), sub=f"{sum(base['delivered'].values()):.1f} kWh delivered"),
        dict(label="CO2", value=f"{base['co2_kg']:.2f} kg",
             sub=f"{money(base['co2_cost'])} at ${cp:.2f}/kg"),
        dict(label="Unmet", value=f"{base['unmet']:.1f} kWh",
             sub=f"{money(base['penalty'])} penalty"),
        dict(label="Cars fully charged", value=f"{full} / {len(cars)}",
             sub=f"{len(base['legal'])} legal rows" + (f", {dropped} dropped" if dropped else "")),
        dict(label="Peak building load",
             value=f"{peak:.1f} kW", sub=f"cap {cap:g} kW"),
    ]
    return dict(title=Path(folder).name or str(folder), source=str(sched_path), made=datetime.now().strftime("%Y-%m-%d %H:%M"),
                problems=sched.problems[:5], kpis=kpis, report=report_summary(
                    inst, base["legal"]),
                hours=hour_rows, chargers=order, co2=co2_series, raw=raw, forecast=forecast, detail=detail)


# ----------------------------------------------------------------------------- page
def render(folder, sched, live=False):
    page = TEMPLATE.read_text(encoding="utf-8")
    if "__DATA__" not in page:
        sys.exit(f"{TEMPLATE.name} is missing the __DATA__ placeholder")
    data = build(folder, sched)
    data["live"] = live
    return page.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))


def serve(folder, sched, port, open_browser):
    """Tiny local web server. Rebuilds the dashboard on every page load; the page polls /mtime and reloads itself."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _send(self, body, ctype="text/html; charset=utf-8", code=200):
            b = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            path = self.path.split("?")[0]
            try:
                if path == "/mtime":
                    return self._send(str(sched.stat().st_mtime_ns), "text/plain")
                if path == "/schedule.csv":
                    return self._send(sched.read_bytes().decode("utf-8-sig", errors="replace"), "text/csv; charset=utf-8")
                if path in ("/", "/index.html"):
                    return self._send(render(folder, sched, live=True))
                self._send("not found", "text/plain", 404)
            except Exception as e:  # keep serving, show the problem in the browser
                self._send(f"<pre>Dashboard error: {e}</pre>", code=500)

        def log_message(self, *args):
            pass

    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        sys.exit(f"Port {port} is busy. Try: --port {port + 1}")
    url = f"http://127.0.0.1:{port}/"
    print(
        f"Live dashboard at {url}  (Ctrl+C to stop). Reloads when {sched} changes.")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", help="input folder (or input.csv)")
    ap.add_argument("schedule", nargs="?",
                    help="schedule.csv (default: ./schedule.csv, else the folder's schedule_baseline.csv)")
    ap.add_argument("-o", "--output", default="dashboard_report.html")
    ap.add_argument("--open", action="store_true",
                    help="open the dashboard in a browser")
    ap.add_argument("--serve", action="store_true",
                    help="serve a live dashboard on localhost instead of writing a file")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    folder = Path(a.data)
    sched = Path(a.schedule) if a.schedule else next(
        (p for p in (Path("schedule.csv"), folder / "schedule_baseline.csv") if p.exists()), None)
    if sched is None or not sched.exists():
        sys.exit(
            "No schedule found. Pass one: python dashboard.py <input_folder> schedule.csv")
    if a.serve:
        return serve(folder, sched, a.port, a.open)
    if Path(a.output).resolve() == TEMPLATE:
        sys.exit(
            "Output would overwrite the dashboard.html template. Pick another name with -o.")
    Path(a.output).write_text(render(folder, sched), encoding="utf-8")
    print(f"wrote {a.output} from {sched}")
    if a.open:
        webbrowser.open(Path(a.output).resolve().as_uri())


if __name__ == "__main__":
    main()
