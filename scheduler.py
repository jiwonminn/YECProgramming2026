import math


def car_window(car, hours):
    "Hours the car is parked: arrival <= h < departure."
    return [h for h in hours if car["arrival"] <= h < car["departure"]]


def spare_kwh(car, hours, biggest):
    "How much extra energy the car could get beyond what it needs. Lower = less flexible = schedule first."
    return len(car_window(car, hours)) * biggest - car["need"]


def assign(state, car, charger, hour, kw):
    """Record one charging slot and update the trackers."""
    kw = math.floor(kw * 1e6) / 1e6  # round down so we never go over a limit
    if kw <= 0:
        return
    state["rows"].append({"car": car["id"], "charger": charger["id"], "hour": hour, "kw": kw})
    state["cap_left"][hour] -= kw
    state["free"][hour].remove(charger)
    state["delivered"][car["id"]] += kw


def make_schedule(meta, chargers, cars, hours):
    # cost of 1 kWh in each hour = price + CO2 cost
    costs = {h: hours[h]["price"] + meta["carbon_price"] * hours[h]["co2"] for h in hours}
    biggest = max(c["max_kw"] for c in chargers)

    state = {
        "cap_left": {h: meta["building_cap_kw"] for h in hours},  # power left per hour
        "free": {h: list(chargers) for h in hours},               # unused chargers per hour
        "rows": [],
        "delivered": {c["id"]: 0 for c in cars},
    }

    # least spare_kwh first; each car takes its cheapest hours first
    for car in sorted(cars, key=lambda c: spare_kwh(c, hours, biggest)):
        for h in sorted(car_window(car, hours), key=lambda h: costs[h]):
            need = car["need"] - state["delivered"][car["id"]]
            if need <= 1e-9:
                break
            if not state["free"][h] or state["cap_left"][h] <= 1e-9:
                continue
            charger = max(state["free"][h], key=lambda c: c["max_kw"])
            kw = min(charger["max_kw"], state["cap_left"][h], need)
            assign(state, car, charger, h, kw)

    return state["rows"]