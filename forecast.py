import sys
import matplotlib.pyplot as plt

from report import load_input

folder = sys.argv[1]
#argv[1] is the folder containing the input files (meta.json, hours.csv, cars.csv)
meta, hours, cars = load_input(folder)
#the hours dict is {hour: (price, co2_kg_per_kWh)}

hs = sorted(hours)
price = [hours[h][0] for h in hs]
co2_cost = [hours[h][1] * meta["carbon_price_cad_per_kg"] for h in hs]
total = [p + c for p, c in zip(price, co2_cost)]
#create a bar chart showing the cost of 1 kWh by hour, including electricity price and CO2 cost

cheapest = min(hs, key=lambda h: hours[h][0])
cleanest = min(hs, key=lambda h: hours[h][1])
best = hs[total.index(min(total))]
#cleanest is the hour with the lowest CO2 emissions
#cheapest is the hour with the lowest electricity price
#best is the hour with the lowest total cost (electricity + CO2)

fig, ax = plt.subplots(figsize=(10, 4.5))
BLUE, GREY = "#4C72B0", "#8C8C8C"
blue_bars = ax.bar(hs, price, color=BLUE, label="Electricity price")
grey_bars = ax.bar(hs, co2_cost, bottom=price, color=GREY, label="CO2 cost ($0.11/kg)")
#set the bar colors to be blue for electricity price and gray for CO2 cost

blue_bars[hs.index(cheapest)].set(edgecolor="black", linewidth=1.5)
grey_bars[hs.index(cleanest)].set(edgecolor="black", linewidth=1.5)
#outline the segment that earns each title: the blue part for cheapest, the grey part for cleanest

labels = {}
for h, txt, col in [(best, "best overall", "black"), (cleanest, "cleanest", "#555555"), (cheapest, "cheapest", BLUE)]:
    labels.setdefault(h, []).append((txt, col))
for h, items in labels.items():
    for i, (txt, col) in enumerate(items):
        ax.annotate(txt, (h, total[hs.index(h)]), xytext=(0, 6 + 12 * i), textcoords="offset points",
                    ha="center", fontsize=9, fontweight="bold", color=col)
#labels function is for annotating the bars with the cheapest, cleanest, and best overall hours
#each label gets its own colour: blue = cheapest (price), grey = cleanest (CO2), black = best overall

ax.set_xticks(hs)
ax.set_xlabel("Hour of day")
ax.set_ylabel("$ per kWh")
ax.set_title("Cost of 1 kWh by hour: electricity + CO2")
ax.legend(loc="upper left")
plt.tight_layout()
plt.savefig("chart_cost_co2.png", dpi=150)
print("saved chart_cost_co2.png")
plt.show()
#display the chart and save it as a PNG file