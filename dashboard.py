#!/usr/bin/env python3
"""EV charging dashboard (BONUS): one self-contained HTML file, standard library only.

    python dashboard.py samples/s2_tight_cap                  # uses schedule.csv if present
    python dashboard.py samples/s2_tight_cap schedule.csv -o dashboard.html --open
    python dashboard.py samples/s2_tight_cap --priority accessible,on_call,none,visitor
    python dashboard.py samples/s2_tight_cap schedule.csv --serve --open   # live: http://127.0.0.1:8000

Shows: the schedule as a sortable table with CSV download, two charts (cars charging per hour,
CO2 kg per charger per hour), an hourly cost forecast (electricity + CO2 per kWh) and what-if scenarios.

Scenario "re-plan" uses a small cost-aware greedy planner built into this file (same idea as
tools/greedy_baseline.py but with per-hour caps). It is a stand-in so the what-ifs work today;
the schedule being analysed is always the one you pass in (e.g. from scheduler.py).
"""
from __future__ import annotations
import argparse
import dataclasses
import json
import math
import sys
import webbrowser
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.io_util import load_dir, load_schedule  # noqa: E402

EPS = 1e-6


# ----------------------------------------------------------------------------- scoring
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


def floor4(x):
    return math.floor(x * 1e4 + 1e-9) / 1e4


def replan(cars, hours, chargers, caps, cp, frozen=(), start=None, priority=None):
    """Cost-aware greedy: each car takes its cheapest hours (price + carbon). Hours < start are frozen."""
    hc = {h.hour: h.price_cad_per_kwh + cp * h.co2_kg_per_kwh for h in hours}
    remaining = {c.car_id: c.kwh_needed for c in cars}
    left, busy, out = dict(caps), set(), [dict(r) for r in frozen]
    for r in out:
        remaining[r["car_id"]] -= r["kW"]
        left[r["hour"]] -= r["kW"]
        busy.add((r["hour"], r["charger_id"]))
    order = sorted(chargers.items(), key=lambda kv: (-kv[1], kv[0]))
    rank = {f: i for i, f in enumerate(priority or [])}
    for car in sorted(cars, key=lambda c: (rank.get(c.flag, len(rank)), -remaining[c.car_id], c.car_id)):
        hs = [h for h in range(car.arrival_hour, car.departure_hour) if h in hc and (
            start is None or h >= start)]
        hs.sort(key=lambda h: (hc[h], h))
        for h in hs:
            if remaining[car.car_id] <= 1e-9:
                break
            if left[h] <= 1e-9:
                continue
            free = next(((cid, mx)
                        for cid, mx in order if (h, cid) not in busy), None)
            if free is None:
                continue
            kw = floor4(min(remaining[car.car_id], free[1], left[h]))
            if kw <= 1e-9:
                continue
            out.append(
                dict(car_id=car.car_id, charger_id=free[0], hour=h, kW=kw))
            busy.add((h, free[0]))
            remaining[car.car_id] -= kw
            left[h] -= kw
    return out


# ----------------------------------------------------------------------------- analysis
def money(x):
    return f"${x:,.2f}"


def build(folder, sched_path, priority):
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
    g0_rows = replan(cars, hours, chargers, caps, cp, priority=priority)
    g0 = evaluate(cars, hours, chargers, caps, cp, pen, g0_rows)

    # ---- chart data
    charging = {h: set() for h in hlist}
    co2 = {cid: {h: 0.0 for h in hlist} for cid in chargers}
    for r in base["legal"]:
        charging[r["hour"]].add(r["car_id"])
        co2[r["charger_id"]][r["hour"]] += r["kW"] * \
            hm[r["hour"]].co2_kg_per_kwh
    parked = {h: sum(1 for c in cars if c.arrival_hour <=
                     h < c.departure_hour) for h in hlist}
    hour_rows = [dict(h=h, price=hm[h].price_cad_per_kwh, co2=hm[h].co2_kg_per_kwh, charging=len(charging[h]),
                      parked=parked[h], load=round(base["load"].get(h, 0.0), 4), cap=cap) for h in hlist]
    order = sorted(chargers, key=lambda c: (-sum(co2[c].values()), c))
    co2_series = {cid: [round(co2[cid][h], 5) for h in hlist] for cid in order}

    # ---- table rows
    flag_of = {c.car_id: c.flag for c in cars}
    table = []
    for r, why in zip(sched.rows, base["reasons"]):
        hh = hm.get(r["hour"])
        price = hh.price_cad_per_kwh if hh else 0.0
        e = hh.co2_kg_per_kwh if hh else 0.0
        table.append(dict(car=r["car_id"], ch=r["charger_id"], h=r["hour"], kw=r["kW"],
                          flag=flag_of.get(r["car_id"], "?"), price=price, co2=r["kW"] * e,
                          cost=r["kW"] * (price + cp * e), ok=why is None, why=why or ""))
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

    # ---- scenarios
    drop_h = 15 if 15 in hm else hlist[len(hlist) * 5 // 8]
    big = max(chargers, key=lambda c: (chargers[c], c))
    scen = []

    def run(name, desc, ch=chargers, cp_=cp, caps_=caps, cars_=cars, start=None, kind="risk"):
        hold = evaluate(cars, hours, ch, caps_, cp_, pen, sched.rows)
        frozen = [r for r in base["legal"]
                  if start is not None and r["hour"] < start]
        plan = replan(cars_, hours, ch, caps_, cp_,
                      frozen=frozen, start=start, priority=priority)
        new = evaluate(cars_, hours, ch, caps_, cp_, pen, plan)
        scen.append(dict(name=name, desc=desc, kind=kind, hold=hold["combined"], hold_unmet=hold["unmet"],
                         plan=new["combined"], plan_unmet=new["unmet"], plan_co2=new["co2_kg"],
                         d_hold=hold["combined"] - base["combined"], d_plan=new["combined"] - base["combined"]))

    run(f"Power cap drops to 60% at {drop_h}:00", f"Building cap x0.6 from hour {drop_h}; re-plan keeps earlier hours fixed.",
        caps_={h: cap * (0.6 if h >= drop_h else 1) for h in hlist}, start=drop_h)
    run(f"Fastest charger ({big}) goes offline", "Valet can't use it all day; re-plan around the remaining chargers.",
        ch={k: v for k, v in chargers.items() if k != big})
    run("Carbon price doubles",
        f"${cp * 2:.2f}/kg instead of ${cp:.2f}/kg: cleaner hours matter more.", cp_=cp * 2)
    run("Building cap +25%", "Utility upgrade or load-sharing agreement.",
        caps_={h: cap * 1.25 for h in hlist}, kind="lever")
    fastest = max(chargers.values()) if chargers else 7.2
    run("Add one more charger", f"One extra {fastest:g} kW charger.", ch={
        **chargers, "NEW": fastest}, kind="lever")
    run("Drivers stay 1 hour longer", "Nudge: departure +1 h (capped at end of day).",
        cars_=[dataclasses.replace(c, departure_hour=min(c.departure_hour + 1, hlist[-1] + 1)) for c in cars], kind="lever")

    fl = [dict(flag=k, cars=v["cars"], need=round(v["need"], 2), got=round(v["got"], 2), unmet=round(v["unmet"], 2),
               pct=round(100 * v["got"] / v["need"], 1) if v["need"] else 100.0) for k, v in sorted(base["flags"].items())]
    peak = max(base["load"].values(), default=0.0)
    full = sum(1 for c in cars if base["delivered"].get(
        c.car_id, 0.0) + EPS >= c.kwh_needed)
    dropped = sum(1 for w in base["reasons"]
                  if w and "ignored" not in w) + len(sched.problems)
    kpis = [
        dict(label="Combined score", value=money(base["combined"]), sub=(
            f"best possible {money(ref)}" if ref is not None else f"greedy re-plan {money(g0['combined'])}")),
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
                problems=sched.problems[:5], kpis=kpis, hours=hour_rows, chargers=order, co2=co2_series, table=table,
                raw=raw, flags=fl, forecast=forecast, scenarios=scen)


# ----------------------------------------------------------------------------- page
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EV Charging Dashboard</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--mute:#5b6573;--line:#e3e7ee;--accent:#2563eb;--accent2:#7c3aed;--good:#0f7b4a;--bad:#c2301f;--warn:#b26a00;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0f1318;--card:#171c23;--ink:#e8ecf2;--mute:#97a2b3;--line:#262d38;--accent:#6ea0ff;--accent2:#b79bff;--good:#4cc38a;--bad:#ff7b6b;--warn:#f0b24a;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 56px}
header{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline;justify-content:space-between;margin-bottom:16px}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:0 0 4px}.mute{color:var(--mute)}.small{font-size:12px}
.grid{display:grid;gap:12px}.kpis{grid-template-columns:repeat(auto-fit,minmax(165px,1fr));margin-bottom:12px}
.two{grid-template-columns:1fr 1fr}@media (max-width:860px){.two{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;min-width:0}
.kpi .v{font-size:22px;font-weight:650;font-variant-numeric:tabular-nums}.kpi .l{color:var(--mute);font-size:12px}
section{margin-top:12px}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
button,input{font:inherit;color:inherit}button{background:var(--accent);color:#fff;border:0;border-radius:8px;padding:6px 12px;cursor:pointer}
button.ghost{background:transparent;color:var(--accent);border:1px solid var(--line)}button:focus-visible,input:focus-visible,th:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
input[type=search]{background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:6px 10px;min-width:260px}
.scroll{overflow:auto;max-height:340px;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{position:sticky;top:0;background:var(--card);cursor:pointer;user-select:none;font-weight:600}
td.n,th.n{text-align:right}tr.drop td{opacity:.5;text-decoration:line-through}
.chart{width:100%;height:290px}.chart svg{display:block;width:100%;height:100%}
.legend{display:flex;flex-wrap:wrap;gap:4px 8px;margin-top:6px}
.chip{border:1px solid var(--line);background:transparent;color:var(--ink);border-radius:999px;padding:2px 9px;font-size:12px;display:inline-flex;gap:6px;align-items:center}
.chip i{width:10px;height:10px;border-radius:3px;display:inline-block}.chip[aria-pressed=false]{opacity:.4}
.pos{color:var(--bad)}.neg{color:var(--good)}
#tip{position:fixed;pointer-events:none;background:#10141acc;color:#fff;padding:6px 9px;border-radius:8px;font-size:12px;display:none;z-index:9;max-width:260px;backdrop-filter:blur(4px)}
.warn{color:var(--warn)}
</style></head><body><main>
<header><div><h1>EV Charging Dashboard</h1><div class="mute small" id="meta"></div></div>
<div class="mute small">Lower combined score is better</div></header>
<div id="warn" class="warn small"></div>
<div class="grid kpis" id="kpis"></div>

<section class="card"><h2>Schedule</h2><div class="mute small">The schedule file as a table. Click a header to sort. Struck-through rows break a rule and don't count.</div>
<div class="bar"><input type="search" id="q" placeholder="Filter by car, charger, flag, hour" aria-label="Filter schedule">
<button id="dl">Download schedule.csv</button><button class="ghost" id="dl2">Download table with cost &amp; CO2</button><span class="mute small" id="count"></span></div>
<div class="scroll"><table id="tbl"><thead></thead><tbody></tbody></table></div></section>

<section class="grid two">
<div class="card"><h2>Cars charging by hour</h2><div class="mute small">Bars: cars receiving power. Line: cars parked (arrived, not yet departed).</div><div class="chart" id="c1"></div></div>
<div class="card"><h2>CO2 per charger by hour (kg)</h2><div class="mute small">Stacked by charger. Click a legend chip to hide a charger.</div><div class="chart" id="c2"></div><div class="legend" id="lg2"></div></div>
</section>

<section class="card"><h2>Forecast: cost of 1 kWh by hour</h2><div class="mute small">Electricity price plus the carbon cost of that hour's grid CO2. Outlined: the blue segment marks the cheapest hour, the grey segment the cleanest.</div>
<div class="chart" id="c3"></div><div class="legend" id="lg3"></div></section>

<section class="grid two">
<div class="card"><h2>Fairness: unmet energy by flag</h2><div class="scroll" style="max-height:none"><table id="flags"></table></div></div>
<div class="card"><h2>Key hours</h2><div class="mute small">Where to put charging if you can choose. Cost per kWh = electricity price + CO2 cost.</div>
<div class="scroll" style="max-height:none;margin-top:8px"><table id="keyhrs"></table></div></div>
</section>

<section class="card"><h2>What-if scenarios</h2><div class="mute small">Score change against the current schedule (+ is worse). "Hold" keeps the schedule as is; "Re-plan" reschedules with the changed conditions.</div>
<div class="scroll" style="max-height:none;margin-top:8px"><table id="scen"></table></div></section>
</main><div id="tip"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent),$=s=>document.querySelector(s),NS='http://www.w3.org/2000/svg';
const $$=x=>'$'+x.toFixed(2),sg=x=>(x>=0?'+':'-')+'$'+Math.abs(x).toFixed(2);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
$('#meta').textContent=`${D.title} | schedule: ${D.source} | generated ${D.made}`;
if(D.problems.length)$('#warn').textContent='Unreadable rows: '+D.problems.join(' | ');
$('#kpis').innerHTML=D.kpis.map(k=>`<div class="card kpi"><div class="l">${esc(k.label)}</div><div class="v">${esc(k.value)}</div><div class="l">${esc(k.sub)}</div></div>`).join('');
$('#flags').innerHTML='<thead><tr><th>Flag</th><th class="n">Cars</th><th class="n">Need</th><th class="n">Delivered</th><th class="n">Unmet</th><th class="n">% met</th></tr></thead><tbody>'+
 D.flags.map(f=>`<tr><td>${esc(f.flag)}</td><td class="n">${f.cars}</td><td class="n">${f.need.toFixed(1)}</td><td class="n">${f.got.toFixed(1)}</td><td class="n">${f.unmet.toFixed(1)}</td><td class="n">${f.pct.toFixed(1)}%</td></tr>`).join('')+'</tbody>';
const dl=(i,t)=>t.map(r=>`<td class="n ${i}">${r}</td>`);
$('#scen').innerHTML='<thead><tr><th>Scenario</th><th class="n">Hold plan</th><th class="n">Re-plan</th><th class="n">Unmet after re-plan</th><th>Takeaway</th></tr></thead><tbody>'+D.scenarios.map(s=>{
 const cl=x=>x>0.005?'pos':x<-0.005?'neg':'';
 const gain=s.d_hold-s.d_plan;
 const take=s.kind==='lever'?(s.d_plan<-0.005?`Saves ${$$(-s.d_plan)}`:'No gain'):(gain>0.005?`Re-planning saves ${$$(gain)}`:gain<-0.005?`Holding beats re-plan by ${$$(-gain)}`:'Hold is fine');
 return `<tr><td><b>${esc(s.name)}</b><div class="mute small">${esc(s.desc)}</div></td><td class="n ${cl(s.d_hold)}">${$$(s.hold)}<div class="small">${sg(s.d_hold)}</div></td><td class="n ${cl(s.d_plan)}">${$$(s.plan)}<div class="small">${sg(s.d_plan)}</div></td><td class="n">${s.plan_unmet.toFixed(1)} kWh</td><td>${take}</td></tr>`}).join('')+'</tbody>';

/* tooltip */
const tip=$('#tip');
function showTip(e,html){tip.innerHTML=html;tip.style.display='block';const w=tip.offsetWidth;tip.style.left=Math.min(innerWidth-w-8,e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px'}
function hideTip(){tip.style.display='none'}
document.addEventListener('mouseover',e=>{const t=e.target.closest('[data-tip]');t?showTip(e,t.dataset.tip):0});
document.addEventListener('mousemove',e=>{if(e.target.closest('[data-tip]'))showTip(e,e.target.closest('[data-tip]').dataset.tip)});
document.addEventListener('mouseout',e=>{if(e.target.closest('[data-tip]'))hideTip()});

/* table */
let sortK=null,dir=1,filt='';
const cols=[['car','Car'],['ch','Charger'],['h','Hour',1],['kw','kW',1],['flag','Flag'],['price','$/kWh',1],['co2','CO2 kg',1],['cost','Cost $',1]];
$('#tbl thead').innerHTML='<tr>'+cols.map(c=>`<th tabindex="0" role="button" class="${c[2]?'n':''}" data-k="${c[0]}">${c[1]}</th>`).join('')+'</tr>';
function rows(){let r=D.table.map((x,i)=>({...x,i}));if(filt){const f=filt.toLowerCase();r=r.filter(x=>[x.car,x.ch,x.flag,x.h].join(' ').toLowerCase().includes(f))}
 if(sortK)r.sort((a,b)=>(a[sortK]>b[sortK]?1:a[sortK]<b[sortK]?-1:a.i-b.i)*dir);return r}
function drawTable(){const r=rows();$('#tbl tbody').innerHTML=r.map(x=>`<tr class="${x.ok?'':'drop'}" ${x.ok?'':`title="${esc(x.why)}"`}><td>${esc(x.car)}</td><td>${esc(x.ch)}</td><td class="n">${x.h}</td><td class="n">${x.kw}</td><td>${esc(x.flag)}</td><td class="n">${x.price.toFixed(4)}</td><td class="n">${x.co2.toFixed(3)}</td><td class="n">${x.cost.toFixed(3)}</td></tr>`).join('');
 $('#count').textContent=`${r.length} of ${D.table.length} rows`}
const sortBy=th=>{const k=th.dataset.k;dir=sortK===k?-dir:1;sortK=k;drawTable()};
$('#tbl thead').addEventListener('click',e=>{const t=e.target.closest('th');t&&sortBy(t)});
$('#tbl thead').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){const t=e.target.closest('th');if(t){e.preventDefault();sortBy(t)}}});
$('#q').addEventListener('input',e=>{filt=e.target.value.trim();drawTable()});
function save(name,text){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));a.download=name;document.body.appendChild(a);a.click();a.remove()}
$('#dl').onclick=()=>save('schedule.csv',D.raw);
$('#dl2').onclick=()=>save('schedule_table.csv','car_id,charger_id,hour,kW,flag,price_cad_per_kwh,co2_kg,cost_cad,counts\n'+rows().map(x=>[x.car,x.ch,x.h,x.kw,x.flag,x.price,x.co2.toFixed(5),x.cost.toFixed(5),x.ok?'yes':'no'].join(',')).join('\n')+'\n');
drawTable();

/* charts */
function el(t,a,p,txt){const n=document.createElementNS(NS,t);for(const k in a)n.setAttribute(k,a[k]);if(txt!=null)n.textContent=txt;p&&p.appendChild(n);return n}
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function niceStep(raw,int){const p=Math.pow(10,Math.floor(Math.log10(raw||1)));for(const m of [1,2,2.5,5,10]){const s=m*p;if(s>=raw&&(!int||Number.isInteger(s)))return s}return Math.ceil(raw)}
function frame(host,maxV,int,unit){host.innerHTML='';const W=host.clientWidth||600,H=host.clientHeight||290,m={l:44,r:10,t:10,b:30};
 const s=el('svg',{viewBox:`0 0 ${W} ${H}`,role:'img'},host);const ph=H-m.t-m.b,pw=W-m.l-m.r;
 const step=niceStep((maxV||1)/4,int),top=step*Math.max(1,Math.ceil((maxV||1)/step)),y=v=>m.t+ph-ph*v/top;
 for(let v=0;v<=top+1e-9;v+=step){el('line',{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:css('--line')},s);el('text',{x:m.l-6,y:y(v)+4,'text-anchor':'end','font-size':11,fill:css('--mute')},s,+v.toFixed(3))}
 const n=D.hours.length,bw=pw/n,x=i=>m.l+bw*i,every=bw<24?(bw<14?3:2):1;
 D.hours.forEach((h,i)=>{if(i%every===0)el('text',{x:x(i)+bw/2,y:H-10,'text-anchor':'middle','font-size':11,fill:css('--mute')},s,h.h)});
 el('text',{x:12,y:m.t+ph/2,transform:`rotate(-90 12 ${m.t+ph/2})`,'text-anchor':'middle','font-size':11,fill:css('--mute')},s,unit);
 return {s,m,W,H,ph,pw,y,x,bw,n}}
function hover(f,html){D.hours.forEach((h,i)=>{const r=el('rect',{x:f.x(i),y:f.m.t,width:f.bw,height:f.ph,fill:'transparent'},f.s);r.dataset.tip=html(h,i)})}
function chart1(){const h=D.hours,f=frame($('#c1'),Math.max(...h.map(a=>Math.max(a.charging,a.parked)),1),true,'cars');
 h.forEach((a,i)=>{const bh=f.ph-(f.y(a.charging)-f.m.t);el('rect',{x:f.x(i)+f.bw*.15,y:f.y(a.charging),width:f.bw*.7,height:Math.max(bh,0),rx:2,fill:css('--accent')},f.s)});
 el('polyline',{points:h.map((a,i)=>`${f.x(i)+f.bw/2},${f.y(a.parked)}`).join(' '),fill:'none',stroke:css('--accent2'),'stroke-width':2,'stroke-dasharray':'5 3'},f.s);
 hover(f,a=>`<b>${a.h}:00</b><br>Charging: ${a.charging}<br>Parked: ${a.parked}<br>Load: ${a.load.toFixed(1)} / ${a.cap} kW<br>Price: $${a.price.toFixed(4)}/kWh`)}
const hid=new Set(),colr=i=>`hsl(${(i*137.5+215)%360} 58% ${matchMedia('(prefers-color-scheme:dark)').matches?60:48}%)`;
function chart2(){const vis=D.chargers.filter(c=>!hid.has(c)),tot=D.hours.map((_,i)=>vis.reduce((s,c)=>s+D.co2[c][i],0)),f=frame($('#c2'),Math.max(...tot,0.01),false,'kg CO2');
 D.hours.forEach((_,i)=>{let acc=0;D.chargers.forEach((c,k)=>{if(hid.has(c))return;const v=D.co2[c][i];if(v<=0)return;const y0=f.y(acc+v),hh=f.y(acc)-y0;acc+=v;el('rect',{x:f.x(i)+f.bw*.15,y:y0,width:f.bw*.7,height:hh,fill:colr(k),stroke:css('--card'),'stroke-width':.6},f.s)})});
 hover(f,(a,i)=>`<b>${a.h}:00</b> | ${tot[i].toFixed(3)} kg<br>`+(D.chargers.filter(c=>!hid.has(c)&&D.co2[c][i]>0).map(c=>`${esc(c)}: ${D.co2[c][i].toFixed(3)} kg`).join('<br>')||'none charging')+`<br>Grid: ${a.co2.toFixed(3)} kg/kWh`);
 $('#lg2').innerHTML=D.chargers.map((c,k)=>`<button class="chip" aria-pressed="${!hid.has(c)}" data-c="${esc(c)}"><i style="background:${colr(k)}"></i>${esc(c)}</button>`).join('')}
$('#lg2').addEventListener('click',e=>{const b=e.target.closest('[data-c]');if(!b)return;hid.has(b.dataset.c)?hid.delete(b.dataset.c):hid.add(b.dataset.c);chart2()});

/* forecast: stacked cost of 1 kWh by hour */
function chartF(){const F=D.forecast,R=F.hours,f=frame($('#c3'),Math.max(...R.map(r=>r.total),0.01)*1.3,false,'$ per kWh');
 const tags={};[[F.best,'best overall',css('--ink')],[F.cleanest,'cleanest',css('--mute')],[F.cheapest,'cheapest',css('--accent')]].forEach(([h,t,c])=>(tags[h]=tags[h]||[]).push([t,c]));
 R.forEach((r,i)=>{const x=f.x(i)+f.bw*.15,w=f.bw*.7,y0=f.y(0),yp=f.y(r.price),yt=f.y(r.total);
  const a=el('rect',{x,y:yp,width:w,height:Math.max(y0-yp,0),fill:css('--accent')},f.s);
  const g=el('rect',{x,y:yt,width:w,height:Math.max(yp-yt,0),fill:css('--mute')},f.s);
  if(r.h===F.cheapest)a.setAttribute('style',`stroke:${css('--ink')};stroke-width:1.5`);
  if(r.h===F.cleanest)g.setAttribute('style',`stroke:${css('--ink')};stroke-width:1.5`);
  (tags[r.h]||[]).forEach(([t,c],k)=>el('text',{x:i===0?x:i===R.length-1?x+w:x+w/2,y:yt-6-12*k,'text-anchor':i===0?'start':i===R.length-1?'end':'middle','font-size':10,'font-weight':700,fill:c},f.s,t))});
 hover(f,(_,i)=>{const r=R[i];return `<b>${r.h}:00</b> | $${r.total.toFixed(4)}/kWh<br>Electricity: $${r.price.toFixed(4)}<br>CO2 cost: $${r.co2_cost.toFixed(4)} (${r.co2.toFixed(3)} kg/kWh)`});
 $('#lg3').innerHTML=`<span class="chip"><i style="background:${css('--accent')}"></i>Electricity price</span><span class="chip"><i style="background:${css('--mute')}"></i>CO2 cost ($${F.carbon_price.toFixed(2)}/kg)</span>`}
const keyRow=(l,h,v,sub)=>`<tr><td>${l}</td><td class="n">${h}:00</td><td class="n">${v}</td><td class="mute">${sub}</td></tr>`;
(function(){const F=D.forecast,at=h=>F.hours.find(r=>r.h===h);const b=at(F.best),c=at(F.cheapest),n=at(F.cleanest);
 $('#keyhrs').innerHTML='<thead><tr><th>Title</th><th class="n">Hour</th><th class="n">$/kWh total</th><th>Why</th></tr></thead><tbody>'+
 keyRow('Best overall',b.h,'$'+b.total.toFixed(4),`lowest price + CO2 cost`)+
 keyRow('Cheapest',c.h,'$'+c.total.toFixed(4),`lowest price: $${c.price.toFixed(4)}/kWh`)+
 keyRow('Cleanest',n.h,'$'+n.total.toFixed(4),`lowest CO2: ${n.co2.toFixed(3)} kg/kWh`)+'</tbody>'})();
if(D.live){$('#meta').textContent+=' | LIVE: refreshes when the schedule file changes';let last=null;setInterval(async()=>{try{const t=await(await fetch('/mtime',{cache:'no-store'})).text();if(last!==null&&t!==last)location.reload();last=t}catch(e){}},2000)}
const draw=()=>{chart1();chart2();chartF()};draw();new ResizeObserver(draw).observe($('#c1'));matchMedia('(prefers-color-scheme:dark)').addEventListener('change',draw);
</script></body></html>
"""


def render(folder, sched, priority, live=False):
    data = build(folder, sched, priority)
    data["live"] = live
    return PAGE.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))


def serve(folder, sched, priority, port, open_browser):
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
                    return self._send(render(folder, sched, priority, live=True))
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
    ap.add_argument("-o", "--output", default="dashboard.html")
    ap.add_argument("--priority", default="",
                    help="comma-separated flag order for re-plans, e.g. accessible,on_call,none,visitor")
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
    prio = [f for f in a.priority.split(",") if f]
    if a.serve:
        return serve(folder, sched, prio, a.port, a.open)
    Path(a.output).write_text(render(folder, sched, prio), encoding="utf-8")
    print(f"wrote {a.output} from {sched}")
    if a.open:
        webbrowser.open(Path(a.output).resolve().as_uri())


if __name__ == "__main__":
    main()
