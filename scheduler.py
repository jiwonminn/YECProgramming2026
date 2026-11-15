import copy
import math


def car_window(car, hours):
    """Hours the car is parked: arrival <= h < departure."""
    return [h for h in hours if car.arrival_hour <= h < car.departure_hour]


# ---------- priority (lower = goes first) ----------

RULES = ["spare_kwh", "edf"]   # the priority rules we try; add new ones here

# Fairness policy (tie-break only): if two rules give the same score, keep the one that
# leaves these groups least short, in this order.
# accessible: can't easily use another space or come back later.
# on_call: may be called away (e.g. hospital) and must leave with charge.
TIE_BREAK_ORDER = ["accessible", "on_call", "visitor", "none"]


def priority(car, hours, biggest, rule):
    """How urgent a car is under the given rule. Lower = goes first."""
    if rule == "spare_kwh":
        # extra energy the car could get beyond what it needs: least flexible first
        return len(car_window(car, hours)) * biggest - car.kwh_needed
    if rule == "edf":
        # Earliest Deadline First: the car leaving soonest goes first
        return car.departure_hour
    raise ValueError(f"unknown rule {rule}")


def assign(state, car, charger, hour, kw):
    """Record one charging slot and update the trackers."""
    kw = math.floor(kw * 1e6 + 1e-6) / 1e6  # round down to 6 decimals (the +1e-6 keeps 1.2 as 1.2, not 1.199999)
    if kw <= 0:
        return
    state["rows"].append({"car": car.car_id, "charger": charger.charger_id, "hour": hour, "kw": kw})
    state["cap_left"][hour] -= kw
    state["free"][hour].remove(charger)
    state["delivered"][car.car_id] += kw


# ---------- repair step helpers ----------

def row_at(state, car_id, hour):
    """The booking for this car in this hour, or None."""
    for r in state["rows"]:
        if r["car"] == car_id and r["hour"] == hour:
            return r
    return None


def room(state, car, hour, charger_max):
    """How many more kW this car could get in this hour right now."""
    r = row_at(state, car.car_id, hour)
    if r:                                    # already has a charger here: top it up
        space = charger_max[r["charger"]] - r["kw"]
    elif state["free"][hour]:                # needs a free charger
        space = max(c.max_kw for c in state["free"][hour])
    else:
        return 0
    return max(0, min(space, state["cap_left"][hour]))


def add(state, car, hour, kw, charger_max):
    """Give a car kw more in this hour (top up its booking, or book a new charger)."""
    kw = math.floor(kw * 1e6 + 1e-6) / 1e6
    if kw <= 0:
        return 0
    r = row_at(state, car.car_id, hour)
    if r:
        r["kw"] += kw
        state["cap_left"][hour] -= kw
        state["delivered"][car.car_id] += kw
    else:
        charger = max(state["free"][hour], key=lambda c: c.max_kw)
        assign(state, car, charger, hour, kw)
    return kw


def take_away(state, row, kw, chargers):
    """Remove kw from a booking; if it drops to 0, delete it and free the charger."""
    row["kw"] -= kw
    state["cap_left"][row["hour"]] += kw
    state["delivered"][row["car"]] -= kw
    if row["kw"] <= 1e-9:
        state["rows"].remove(row)
        state["free"][row["hour"]].append(chargers[row["charger"]])


def repair(state, inst, costs, hours, rule, max_rounds=20):
    """Help cars that are still short: move other cars to quieter hours to make room."""
    chargers = {c.charger_id: c for c in inst.chargers}
    charger_max = {c.charger_id: c.max_kw for c in inst.chargers}
    cars = {c.car_id: c for c in inst.cars}
    biggest = max(charger_max.values())

    def short(car):
        return car.kwh_needed - state["delivered"][car.car_id]

    for _ in range(max_rounds):
        changed = False
        for s in sorted(inst.cars, key=lambda c: priority(c, hours, biggest, rule)):
            for h in sorted(car_window(s, hours), key=lambda h: costs[h]):
                if short(s) <= 1e-9:
                    break

                # 1. easy case: there is still room in this hour
                if add(state, s, h, min(room(state, s, h, charger_max), short(s)), charger_max) > 0:
                    changed = True
                    continue

                # 2. hour is full: try moving another car o to a different hour h2
                others = [r["car"] for r in state["rows"] if r["hour"] == h and r["car"] != s.car_id]
                for o_id in others:
                    o = cars[o_id]
                    for h2 in sorted(car_window(o, hours), key=lambda x: costs[x]):
                        if h2 == h or short(s) <= 1e-9:
                            continue
                        o_row = row_at(state, o_id, h)       # always look it up fresh
                        if o_row is None:
                            break
                        move = min(room(state, o, h2, charger_max), o_row["kw"], short(s))
                        if move <= 1e-9:
                            continue
                        backup = copy.deepcopy(state)
                        take_away(state, o_row, move, chargers)
                        add(state, o, h2, move, charger_max)
                        gained = add(state, s, h, min(room(state, s, h, charger_max), short(s)), charger_max)
                        if gained > 1e-9:
                            changed = True
                        else:                                # didn't help s: undo the move
                            state.clear()
                            state.update(backup)
        if not changed:
            break


def make_schedule(inst, rule):
    """Greedy + repair using the given priority rule. Returns a list of schedule rows."""
    if not inst.chargers or not inst.cars:
        return []      # nothing can charge (e.g. the only charger broke)
    # cost of 1 kWh in each hour = price + CO2 cost
    costs = {h.hour: h.price_cad_per_kwh + inst.meta.carbon_price_cad_per_kg * h.co2_kg_per_kwh
             for h in inst.hours}
    hours = list(costs)
    biggest = max(c.max_kw for c in inst.chargers)

    state = {
        "cap_left": {h: inst.meta.building_cap_kw for h in hours},  # power left per hour
        "free": {h: list(inst.chargers) for h in hours},            # unused chargers per hour
        "rows": [],
        "delivered": {c.car_id: 0 for c in inst.cars},
    }

    # cars in priority order; each car takes its cheapest hours first
    for car in sorted(inst.cars, key=lambda c: priority(c, hours, biggest, rule)):
        for h in sorted(car_window(car, hours), key=lambda h: costs[h]):
            need = car.kwh_needed - state["delivered"][car.car_id]
            if need <= 1e-9:
                break
            if not state["free"][h] or state["cap_left"][h] <= 1e-9:
                continue
            charger = max(state["free"][h], key=lambda c: c.max_kw)
            kw = min(charger.max_kw, state["cap_left"][h], need)
            assign(state, car, charger, h, kw)

    repair(state, inst, costs, hours, rule)

    # clean up: drop leftover scraps from moving power around (< 0.001 kW), round down to 6 decimals
    return [dict(r, kw=math.floor(r["kw"] * 1e6 + 1e-6) / 1e6) for r in state["rows"] if r["kw"] >= 1e-3]


# ---------- try every priority, keep the lowest score ----------

def score(rows, inst):
    """Same formula as the official scorer: electricity + CO2 cost + unmet penalty."""
    hours = {h.hour: h for h in inst.hours}
    delivered = {c.car_id: 0 for c in inst.cars}
    cost = 0
    for r in rows:
        h = hours[r["hour"]]
        cost += r["kw"] * (h.price_cad_per_kwh + inst.meta.carbon_price_cad_per_kg * h.co2_kg_per_kwh)
        delivered[r["car"]] += r["kw"]
    unmet = sum(max(0, c.kwh_needed - delivered[c.car_id]) for c in inst.cars)
    return cost + unmet * inst.meta.unmet_penalty_cad_per_kwh


def unmet_by_flag(rows, inst):
    """kWh each group did NOT get, in tie-break order: (accessible, on_call, visitor, none)."""
    delivered = {c.car_id: 0 for c in inst.cars}
    for r in rows:
        delivered[r["car"]] += r["kw"]
    short = {f: 0.0 for f in TIE_BREAK_ORDER}
    for c in inst.cars:
        short[c.flag if c.flag in short else "none"] += max(0, c.kwh_needed - delivered[c.car_id])
    return tuple(round(short[f], 6) for f in TIE_BREAK_ORDER)


def make_best_schedule(inst, verbose=True):
    """Run the scheduler once per priority rule and keep the best one.

    Best = lowest score. If two rules tie on score, our fairness policy decides:
    least short for accessible drivers first, then on-call, then visitors, then everyone else.
    Returns (rows, rule).
    """
    best = None
    for rule in RULES:
        rows = make_schedule(inst, rule)
        short = unmet_by_flag(rows, inst)
        key = (round(score(rows, inst), 6),) + short    # compare score first, then each group in order
        if verbose:
            print(f"  {rule:10s} score: {key[0]:.4f}   short (kWh) accessible {short[0]:.1f}, "
                  f"on_call {short[1]:.1f}, visitor {short[2]:.1f}, none {short[3]:.1f}")
        if best is None or key < best[0]:
            best = (key, rows, rule)
    return best[1], best[2]