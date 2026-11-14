# YEC 2026 Programming: Case packet

Prepared by GDG on Campus York University for the 2026 York Engineering Competition.

Event: Sat Nov 14 (10:00-20:00) and Sun Nov 15 (10:00-19:00), WSC 104. Teams of 3-4 York undergrads.

## The problem
York is adding EV chargers to a campus parkade. Drivers arrive, say when they're leaving and how much
energy they need, and your software decides who charges where and when. Make it cheap, low-carbon and
fair, without ever drawing more power than the building can supply.

## Input files
Each input folder (`samples/s1_basic/`, and on Sunday `hidden_tests/h1_.../`) holds the same data in two
forms. Use whichever is easier.

Separate files:
- `meta.csv`: a `key,value` table with three rows: `building_cap_kw`, `carbon_price_cad_per_kg` (0.11),
  `unmet_penalty_cad_per_kwh` (1.00)
- `chargers.csv`: `charger_id, max_kw`
- `cars.csv`: `car_id, arrival_hour, departure_hour, kwh_needed, flag` where flag is `none`, `accessible`, `on_call` or `visitor`
- `hours.csv`: `hour` (0-23), `price_cad_per_kwh`, `co2_kg_per_kwh`

Or one file:
- `input.csv`: everything above in one table, with a `record_type` column (`META`, `CHARGER`, `CAR`, `HOUR`).
  Each row fills only the columns for its type and leaves the rest blank. META rows use `meta_key,meta_value`.

The first lines of `samples/s1_basic/`:

```
# meta.csv
key,value
building_cap_kw,18
carbon_price_cad_per_kg,0.11
unmet_penalty_cad_per_kwh,1

# chargers.csv
charger_id,max_kw
C1,7.2

# cars.csv
car_id,arrival_hour,departure_hour,kwh_needed,flag
A1,8,17,24,accessible

# hours.csv
hour,price_cad_per_kwh,co2_kg_per_kwh
0,0.0366,0.155
```

Hours are whole numbers. A car can charge in hour `h` when `arrival_hour <= h < departure_hour`.
Charging at `kW` for one hour delivers `kW` kWh.

## What your program must produce
A file called `schedule.csv` with exactly this header:

```
car_id,charger_id,hour,kW
```

One row per car, charger and hour it charges. It must be produced from the input by one command, in any
language. Everything else (UI, charts, reports, extra outputs) is up to you. For example:

```
car_id,charger_id,hour,kW
A1,C1,8,7.2
A1,C2,9,3.6
A2,C1,9,7.2
```

Write the file from your program as plain UTF-8 text, with a dot as the decimal point (`3.6`, not `3,6`).
Don't make it with PowerShell `>` (that saves UTF-16), and don't re-save it from Excel. Open it in a text
editor before you upload it.

## Rules every row must follow
1. The car and charger exist, and the hour is in `hours.csv` and inside the car's window.
2. `kW` is a number from 0 up to that charger's `max_kw`.
3. **One car per charger per hour**, and one charger per car per hour.
4. In each hour, total kW across all chargers stays within `building_cap_kw`.

Cars may use a different charger in different hours (the parkade has valet staff who move cars).

Rows that break a rule, or can't be read, are dropped and count as if they weren't there. The rest of your
schedule still scores. Where a per-hour limit is crossed, the row that crosses it is dropped, reading the
file top to bottom.

### Good to know
- `kW` can be any decimal, like `3.6` or `5.25`. A car doesn't have to charge at the charger's maximum.
- Chargers differ only in `max_kw`. Moving a car between chargers is free.
- Don't charge a car past its `kwh_needed`. Extra energy costs money and CO2 but helps nobody.
- Unmet energy costs $1.00/kWh, far more than any hour's price. Delivering every kWh you can matters most;
  choosing cheap and clean hours comes second.
- Totals are checked with a tiny tolerance (0.000001 kW). If you round kW, round down, or an hour can end up
  just over a limit and that row is dropped.
- Hidden tests are the same kind of input as the samples, with different days, cars, chargers and caps. Don't
  hard-code the number of cars, chargers, hours or charger sizes.

## Tiers
- **CORE** (aim to finish Saturday evening; loops and sorting are enough): read the input, write a valid
  `schedule.csv`, show the schedule simply (a timeline, table, plot or formatted spreadsheet all count) and
  summarize total cost, CO2 and unmet charging.
- **OPTIMIZE**: get closer to the best possible score; weigh cost against CO2; handle changes during the day
  (a car arrives early, the power cap drops at 3 PM). Changes during the day are shown in your demo with a
  scenario you choose. They aren't part of the hidden tests.
- **BONUS**: a polished dashboard, what-if scenarios, forecasting.

## Fairness
Flags are information only. The packet doesn't say who should go first. Some inputs ask for more energy
than the parkade can deliver, so not every car can be fully charged. Decide on a priority policy and defend
it in your presentation. The scorer reports unmet kWh by flag but doesn't reward any particular policy.

## How the hidden tests are scored (lower combined score is better)

```
combined = electricity cost ($) + CO2 cost ($) + unmet penalty ($)
CO2 cost      = kg CO2 x $0.11/kg   ($110/tonne, Canada's 2026 federal carbon price benchmark)
unmet penalty = $1.00 per kWh not delivered
```

The hidden tests decide **Hidden-Test Performance (20 marks)**, part of Strategy / Algorithm (40) in the
rulebook's rubric. Judges score everything else, including your fairness policy and how you handle changes
during the day.

Points for each hidden test:
- An empty schedule (nothing charged) earns 0.
- Matching GDG's greedy baseline (`tools/greedy_baseline.py`) earns half.
- Matching the best possible schedule earns full points.
- In between, points scale on a straight line. Worse than an empty schedule earns 0, and matching or beating
  the best possible earns full points. Your result is the average over the hidden tests.

Each sample folder includes `schedule_baseline.csv` and `reference.csv` (the best possible score) so you can
see where you stand. Sample scores (lower is better):

| Sample | Real Ontario day | Greedy baseline | Best possible |
|---|---|---|---|
| s1_basic | Tue Oct 6, 2026 | 18.87 | 7.58 |
| s2_tight_cap (not every car can be charged) | Mon Oct 5, 2026 | 62.53 | 56.46 |
| s3_evening_rush | Fri Oct 2, 2026 | 16.64 | 16.56 |

Greedy is close to the best on some inputs and far from it on others. The hidden tests use different days.

## Tools in this pack (need Python 3, no extra packages)
On Windows use `python` (or `py`); on macOS use `python3`.

```bash
python tools/greedy_baseline.py samples/s1_basic -o schedule.csv
python tools/validate.py samples/s1_basic schedule.csv
python tools/score.py samples/s1_basic schedule.csv --baseline-schedule samples/s1_basic/schedule_baseline.csv
```

`validate.py` uses exactly the scorer's rules: VALID means every row counts. Run it often.

## Sunday hidden-test flow
- **1:30 PM:** code freeze. Submit your code through the submission form. The password for
  `hidden_tests.enc` (in your starter pack since Saturday) goes up in the room. The rulebook calls this
  file `hidden_tests.zip`; it's the same file. Don't try to open it as a zip, use `unlock.py`.
- **Unlock:** `python tools/unlock.py hidden_tests.enc PASSWORD`. This creates `hidden_tests/` with one
  input folder per test. Spaces, dashes and capital letters in the password don't matter. Try the command
  with any password on Saturday so you know it runs on your laptop (it will say "wrong password").
- **By 1:45 PM:** run your submitted code on each hidden input and upload one `schedule.csv` per test,
  named after the test folder (for example `h1_mixed.csv`), through the second upload field of the
  submission form.
- **Integrity:** run exactly the code you submitted. The top 3 and any team with an unusual result re-run
  their submitted code live on a hidden input during their demo. We compare the score (within $0.01), not the
  exact file. A mismatch is treated as plagiarism. If your code uses randomness, fix the seed so the same input
  always gives the same schedule.

## Where the hourly data comes from
Every `hours.csv` is a real Ontario day from the IESO (Independent Electricity System Operator) public reports:
- **Price:** the Day-Ahead Hourly Ontario Zonal Price, converted from $/MWh to $/kWh. It's the wholesale
  energy price only, without delivery charges.
- **CO2:** GDG multiplied IESO's hourly Generator Output by Fuel Type by lifecycle emission factors
  (IPCC AR5 medians, kg CO2e/kWh): gas 0.490, biofuel 0.230, solar 0.048, hydro 0.024, nuclear 0.012,
  wind 0.011. Storage output ("other") is counted at the average mix of the other fuels.
- IESO reports in "hour ending" 1-24 (Eastern Standard Time). Hour 0 here is IESO hour ending 1.

At $110/tonne, CO2 adds roughly 1-2 cents per kWh, which is 12-37% of the hourly cost on these days, so
cheapest and cleanest hours are not always the same.
