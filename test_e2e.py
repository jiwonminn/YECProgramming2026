"""End-to-end tests for the YEC 2026 EV charging pipeline (standard library only).

Runs the real commands, exactly as the case packet describes:
    main.py <input> <schedule.csv>  ->  tools/validate.py  ->  tools/score.py  ->  dashboard.py

    python tests/test_e2e.py -v          (works from any folder)
    python -m unittest discover -s tests -v
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next((p for p in (HERE, *HERE.parents)
            if (p / "main.py").exists() and (p / "tools").is_dir()), None)
if ROOT is None:
    raise SystemExit(
        "Put this file inside the repo (next to main.py, or in a tests/ folder).")
sys.path.insert(0, str(ROOT))
from tools.io_util import load_dir, load_schedule  # noqa: E402
from tools.score import score  # noqa: E402

SAMPLES = ["s1_basic", "s2_tight_cap", "s3_evening_rush"]
HEADER = "car_id,charger_id,hour,kW"
DATA_RE = re.compile(
    r'<script id="data" type="application/json">(.*?)</script>', re.S)


def run(script, *args):
    return subprocess.run([sys.executable, str(ROOT / script), *map(str, args)],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)


def folder(sample):
    return ROOT / "samples" / sample


def reference(sample):
    lines = (folder(sample) /
             "reference.csv").read_text(encoding="utf-8-sig").splitlines()
    return float(lines[1].split(",")[0])


def scored(sample, schedule):
    return score(load_dir(folder(sample)), load_schedule(Path(schedule)))


class PipelineTests(unittest.TestCase):
    """main.py -> validate.py -> score.py -> dashboard.py on every sample."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = {}
        for s in SAMPLES:
            path = Path(cls.tmp.name) / f"{s}.csv"
            r = run("main.py", folder(s), path)
            assert r.returncode == 0, f"main.py failed on {s}:\n{r.stderr}"
            cls.out[s] = dict(path=path, stdout=r.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # ---------------------------------------------------------- main.py output
    def test_schedule_header_and_rows(self):
        for s, o in self.out.items():
            with self.subTest(s):
                lines = o["path"].read_text(encoding="utf-8").splitlines()
                self.assertEqual(lines[0], HEADER)
                self.assertGreater(len(lines), 1)

    def test_schedule_is_plain_utf8(self):
        for s, o in self.out.items():
            with self.subTest(s):
                raw = o["path"].read_bytes()
                self.assertFalse(raw.startswith(
                    (b"\xff\xfe", b"\xef\xbb\xbf")))
                raw.decode("utf-8")

    def test_stdout_has_rule_and_summary(self):
        for s, o in self.out.items():
            with self.subTest(s):
                for label in ("Selected rule:", "Electricity cost", "CO2",
                              "Unmet energy", "Combined score"):
                    self.assertIn(label, o["stdout"])

    def test_deterministic(self):
        for s, o in self.out.items():
            with self.subTest(s):
                again = Path(self.tmp.name) / f"{s}_again.csv"
                self.assertEqual(
                    run("main.py", folder(s), again).returncode, 0)
                self.assertEqual(again.read_bytes(), o["path"].read_bytes())

    # ---------------------------------------------------------- validity
    def test_passes_official_validator(self):
        for s, o in self.out.items():
            with self.subTest(s):
                r = run("tools/validate.py", folder(s), o["path"])
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("VALID: 0 errors", r.stdout)

    def test_every_row_counts(self):
        for s, o in self.out.items():
            with self.subTest(s):
                r = scored(s, o["path"])
                self.assertEqual(r["validate_errors"], 0)
                self.assertEqual(r["legal_rows"], r["raw_rows"])

    def test_no_car_overcharged(self):
        for s, o in self.out.items():
            with self.subTest(s):
                need = {c.car_id: c.kwh_needed for c in load_dir(
                    folder(s)).cars}
                got = {}
                for row in load_schedule(o["path"]).rows:
                    got[row["car_id"]] = got.get(
                        row["car_id"], 0.0) + row["kW"]
                for cid, kwh in got.items():
                    self.assertLessEqual(
                        kwh, need[cid] + 1e-6, f"{cid} overcharged")

    # ---------------------------------------------------------- quality
    def test_beats_or_ties_greedy_baseline(self):
        for s, o in self.out.items():
            with self.subTest(s):
                base = scored(
                    s, folder(s) / "schedule_baseline.csv")["combined_score"]
                self.assertLessEqual(scored(s, o["path"])[
                                     "combined_score"], base + 0.01)

    def test_close_to_best_possible(self):
        for s, o in self.out.items():
            with self.subTest(s):
                mine, ref = scored(s, o["path"])[
                    "combined_score"], reference(s)
                self.assertGreaterEqual(
                    mine, ref - 0.01, "below proven optimum?")
                self.assertLessEqual(
                    mine, ref + 0.60, f"{mine:.4f} vs best {ref:.4f}")

    def test_tight_cap_hits_best_possible_and_has_unmet(self):
        r = scored("s2_tight_cap", self.out["s2_tight_cap"]["path"])
        self.assertAlmostEqual(r["combined_score"],
                               reference("s2_tight_cap"), delta=0.01)
        self.assertGreater(r["unmet_kwh"], 0)

    def test_input_csv_and_folder_agree(self):
        b = Path(self.tmp.name) / "from_input_csv.csv"
        self.assertEqual(run("main.py", folder("s1_basic") /
                         "input.csv", b).returncode, 0)
        self.assertAlmostEqual(scored("s1_basic", b)["combined_score"],
                               scored("s1_basic", self.out["s1_basic"]["path"])[
            "combined_score"],
            places=6)

    # ---------------------------------------------------------- dashboard
    def _dashboard(self, s):
        html_path = Path(self.tmp.name) / f"{s}.html"
        r = run("dashboard.py", folder(s),
                self.out[s]["path"], "-o", html_path)
        self.assertEqual(r.returncode, 0, r.stderr)
        html = html_path.read_text(encoding="utf-8")
        self.assertNotIn("__DATA__", html)
        return json.loads(DATA_RE.search(html).group(1))

    def test_dashboard_numbers_match_scorer(self):
        for s, o in self.out.items():
            with self.subTest(s):
                d, r = self._dashboard(s), scored(s, o["path"])
                kpi = {k["label"]: k["value"] for k in d["kpis"]}
                self.assertEqual(kpi["Combined score"],
                                 f"${r['combined_score']:,.2f}")
                self.assertAlmostEqual(
                    float(kpi["CO2"].split()[0]), r["co2_kg"], delta=0.01)
                self.assertAlmostEqual(
                    float(kpi["Unmet"].split()[0]), r["unmet_kwh"], delta=0.05)
                self.assertAlmostEqual(
                    sum(sum(v) for v in d["co2"].values()), r["co2_kg"], delta=0.01)
                self.assertNotIn("report.py error", [
                                 m["metric"] for m in d["report"]])

    def test_dashboard_heatmap_detail_consistent(self):
        for s in SAMPLES:
            with self.subTest(s):
                d = self._dashboard(s)
                idx = {h["h"]: i for i, h in enumerate(d["hours"])}
                for c in d["chargers"]:
                    active = {d["hours"][i]["h"]
                              for i, v in enumerate(d["co2"][c]) if v > 0}
                    self.assertEqual(active, {int(h) for h in d["detail"][c]})
                    for h, info in d["detail"][c].items():
                        i = idx[int(h)]
                        self.assertTrue(info["car"])
                        self.assertAlmostEqual(
                            info["kw"] * d["hours"][i]["co2"], d["co2"][c][i], delta=1e-3)

    def test_dashboard_will_not_overwrite_template(self):
        r = run("dashboard.py", folder("s1_basic"), self.out["s1_basic"]["path"],
                "-o", ROOT / "dashboard.html")
        self.assertNotEqual(r.returncode, 0)


class CliTests(unittest.TestCase):
    def test_main_without_arguments_prints_usage(self):
        r = run("main.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Usage", r.stderr)


if __name__ == "__main__":
    unittest.main()
