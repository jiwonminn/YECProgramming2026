"""Load EV-charging challenge inputs from a data directory or input.csv, and read schedules."""
from __future__ import annotations
import csv
import io
import math
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class Meta:
    building_cap_kw: float
    carbon_price_cad_per_kg: float
    unmet_penalty_cad_per_kwh: float

@dataclass
class Charger:
    charger_id: str
    max_kw: float

@dataclass
class Car:
    car_id: str
    arrival_hour: int
    departure_hour: int
    kwh_needed: float
    flag: str

@dataclass
class Hour:
    hour: int
    price_cad_per_kwh: float
    co2_kg_per_kwh: float

@dataclass
class Instance:
    meta: Meta
    chargers: list[Charger]
    cars: list[Car]
    hours: list[Hour]

FLAGS = {"none", "accessible", "on_call", "visitor"}
SCHEDULE_COLUMNS = ["car_id", "charger_id", "hour", "kW"]

# utf-8-sig strips the byte-order mark Excel adds when saving "CSV UTF-8".
ENCODING = "utf-8-sig"

def _open(path: Path, mode: str = "r"):
    if "w" in mode:
        return Path(path).open(mode, newline="", encoding="utf-8")
    return Path(path).open(mode, newline="", encoding=ENCODING)

def _meta_from_map(meta_map: dict) -> Meta:
    return Meta(
        building_cap_kw=meta_map["building_cap_kw"],
        carbon_price_cad_per_kg=meta_map["carbon_price_cad_per_kg"],
        unmet_penalty_cad_per_kwh=meta_map["unmet_penalty_cad_per_kwh"],
    )

def load_dir(path: Path) -> Instance:
    path = Path(path)
    if path.is_dir() and (path / "meta.csv").exists():
        meta_map = {}
        with _open(path / "meta.csv") as f:
            for row in csv.DictReader(f):
                meta_map[row["key"]] = float(row["value"])
        with _open(path / "chargers.csv") as f:
            chargers = [Charger(r["charger_id"], float(r["max_kw"])) for r in csv.DictReader(f)]
        with _open(path / "cars.csv") as f:
            cars = [
                Car(r["car_id"], int(r["arrival_hour"]), int(r["departure_hour"]), float(r["kwh_needed"]), r["flag"])
                for r in csv.DictReader(f)
            ]
        return Instance(_meta_from_map(meta_map), chargers, cars, load_hours(path / "hours.csv"))
    return load_input_csv(path if path.is_file() else path / "input.csv")

def load_hours(path: Path) -> list[Hour]:
    with _open(path) as f:
        return [
            Hour(int(r["hour"]), float(r["price_cad_per_kwh"]), float(r["co2_kg_per_kwh"]))
            for r in csv.DictReader(f)
        ]

def load_input_csv(path: Path) -> Instance:
    meta_map = {}
    chargers, cars, hours = [], [], []
    with _open(path) as f:
        for row in csv.DictReader(f):
            t = row["record_type"]
            if t == "META":
                meta_map[row["meta_key"]] = float(row["meta_value"])
            elif t == "CHARGER":
                chargers.append(Charger(row["charger_id"], float(row["max_kw"])))
            elif t == "CAR":
                cars.append(
                    Car(
                        row["car_id"],
                        int(row["arrival_hour"]),
                        int(row["departure_hour"]),
                        float(row["kwh_needed"]),
                        row["flag"],
                    )
                )
            elif t == "HOUR":
                hours.append(
                    Hour(int(row["hour"]), float(row["price_cad_per_kwh"]), float(row["co2_kg_per_kwh"]))
                )
            else:
                raise ValueError(f"unknown record_type {t!r}")
    return Instance(_meta_from_map(meta_map), chargers, cars, hours)

def write_instance(inst: Instance, path: Path) -> None:
    """Write an instance in both formats: meta/chargers/cars/hours.csv and the single input.csv."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    m = inst.meta
    meta_rows = [
        ("building_cap_kw", m.building_cap_kw),
        ("carbon_price_cad_per_kg", m.carbon_price_cad_per_kg),
        ("unmet_penalty_cad_per_kwh", m.unmet_penalty_cad_per_kwh),
    ]
    with _open(path / "meta.csv", "w") as f:
        w = csv.writer(f)
        w.writerow(["key", "value"])
        w.writerows([(k, _fmt(v)) for k, v in meta_rows])
    with _open(path / "chargers.csv", "w") as f:
        w = csv.writer(f)
        w.writerow(["charger_id", "max_kw"])
        w.writerows([(c.charger_id, _fmt(c.max_kw)) for c in inst.chargers])
    with _open(path / "cars.csv", "w") as f:
        w = csv.writer(f)
        w.writerow(["car_id", "arrival_hour", "departure_hour", "kwh_needed", "flag"])
        w.writerows([(c.car_id, c.arrival_hour, c.departure_hour, _fmt(c.kwh_needed), c.flag) for c in inst.cars])
    with _open(path / "hours.csv", "w") as f:
        w = csv.writer(f)
        w.writerow(["hour", "price_cad_per_kwh", "co2_kg_per_kwh"])
        w.writerows([(h.hour, f"{h.price_cad_per_kwh:.4f}", f"{h.co2_kg_per_kwh:.3f}") for h in inst.hours])
    cols = ["record_type", "charger_id", "max_kw", "car_id", "arrival_hour", "departure_hour", "kwh_needed",
            "flag", "hour", "price_cad_per_kwh", "co2_kg_per_kwh", "meta_key", "meta_value"]
    with _open(path / "input.csv", "w") as f:
        w = csv.DictWriter(f, fieldnames=cols, restval="")
        w.writeheader()
        for k, v in meta_rows:
            w.writerow({"record_type": "META", "meta_key": k, "meta_value": _fmt(v)})
        for c in inst.chargers:
            w.writerow({"record_type": "CHARGER", "charger_id": c.charger_id, "max_kw": _fmt(c.max_kw)})
        for c in inst.cars:
            w.writerow({"record_type": "CAR", "car_id": c.car_id, "arrival_hour": c.arrival_hour,
                        "departure_hour": c.departure_hour, "kwh_needed": _fmt(c.kwh_needed), "flag": c.flag})
        for h in inst.hours:
            w.writerow({"record_type": "HOUR", "hour": h.hour, "price_cad_per_kwh": f"{h.price_cad_per_kwh:.4f}",
                        "co2_kg_per_kwh": f"{h.co2_kg_per_kwh:.3f}"})

def _fmt(v: float) -> str:
    return f"{v:g}" if float(v) != int(v) else str(int(v))

@dataclass
class ScheduleFile:
    rows: list[dict] = field(default_factory=list)      # readable rows; "line" is the CSV line number
    problems: list[str] = field(default_factory=list)   # rows that could not be read at all

def load_schedule(path: Path) -> ScheduleFile:
    """Read schedule.csv. Unreadable rows are reported in `problems` and skipped, never fatal.

    A missing required column makes every row unreadable, so the schedule scores as empty.
    """
    out = ScheduleFile()
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        out.problems.append(f"cannot read {path}: {e.strerror or e}")
        return out
    # Windows PowerShell's `>` writes UTF-16; Excel may write a BOM or a legacy code page. Never crash on encoding.
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data.decode("utf-16", errors="replace")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
    with io.StringIO(text, newline="") as f:
        reader = csv.DictReader(f)
        header = {(h or "").strip().lower(): h for h in (reader.fieldnames or [])}
        missing = [c for c in SCHEDULE_COLUMNS if c.lower() not in header]
        if missing:
            out.problems.append(
                f"missing column(s) {missing}; header must be exactly {','.join(SCHEDULE_COLUMNS)}"
            )
            return out
        for line, r in enumerate(reader, start=2):
            raw = {c: (r.get(header[c.lower()]) or "").strip() for c in SCHEDULE_COLUMNS}
            if not any(raw.values()):
                continue  # blank line
            if r.get(None):  # more fields than the header, e.g. a decimal comma: A7,C1,8,2,8
                out.problems.append(
                    f"schedule.csv line {line}: more fields than the header (decimal comma? use 2.8, not 2,8)"
                )
                continue
            try:
                if "_" in raw["hour"] or "_" in raw["kW"]:
                    raise ValueError("underscore")
                hour_f = float(raw["hour"])
                if not math.isfinite(hour_f) or hour_f != int(hour_f):
                    raise ValueError(f"hour {raw['hour']!r} is not a whole number")
                kw = float(raw["kW"])
                if not math.isfinite(kw):
                    raise ValueError(f"kW {raw['kW']!r} is not a finite number")
            except ValueError as e:
                msg = str(e) if "whole number" in str(e) or "finite" in str(e) else f"unreadable number in {raw}"
                out.problems.append(f"schedule.csv line {line}: {msg}")
                continue
            out.rows.append(
                {"line": line, "car_id": raw["car_id"], "charger_id": raw["charger_id"], "hour": int(hour_f), "kW": kw}
            )
    return out
