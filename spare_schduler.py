import math


def floor_to_6dp(x):
    "Round down to 6 decimals so we never exceed a limit."
    return math.floor(x * 1e6) / 1e6


def make_schedule(meta, chargers, cars, hours):
    carbon_price = meta["carbon_price"] # 
    building_cap = meta["building_cap_kw"]
    biggest = max(c["max_kw"] for c in chargers)

    def window(car):
        "Hours the car is parked."
        return [h for h in hours if car["arrival"] <= h < car["departure"]]

    def priority(car):
        "Spare kWh: lower = less flexible = goes first."
        return len(window(car)) * biggest - car["need"]

    cost = {h: hours[h]["price"] + carbon_price * hours[h]["co2"] for h in hours}
    cap_left = {h: building_cap for h in hours}
    free = {h: list(chargers) for h in hours}
    rows = []

    for car in sorted(cars, key=priority):
        need = car["need"]
        for h in sorted(window(car), key=lambda h: cost[h]):
            if need <= 1e-9:
                break
            if not free[h] or cap_left[h] <= 1e-9:
                continue
            ch = max(free[h], key=lambda c: c["max_kw"])
            kw = floor_to_6dp(min(ch["max_kw"], cap_left[h], need))
            if kw <= 0:
                continue
            rows.append({"car": car["id"], "charger": ch["id"], "hour": h, "kw": kw})
            free[h].remove(ch)
            cap_left[h] -= kw
            need -= kw

    return rows