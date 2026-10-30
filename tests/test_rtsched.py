import math
import random
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import rtsched as rt
from rtsched.cli import main as cli_main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
PERIODS = [10, 20, 25, 40, 50, 100, 200]  # keeps hyperperiods small


def random_taskset(rng, n, u_total, constrained=False, resources=False):
    """UUniFast utilisations (Bini & Buttazzo) on a harmonic-ish period grid."""
    us, remaining = [], u_total
    for i in range(1, n):
        nxt = remaining * rng.random() ** (1 / (n - i))
        us.append(remaining - nxt)
        remaining = nxt
    us.append(remaining)
    tasks = []
    for i, u in enumerate(us):
        period = rng.choice(PERIODS) * 10
        wcet = max(1, round(u * period))
        deadline = rng.randint(max(wcet, period // 2), period) if constrained else None
        css = ()
        if resources and wcet >= 4 and rng.random() < 0.6:
            css = (rt.CriticalSection(rng.choice("AB"), rng.randint(1, wcet // 2)),)
        tasks.append(rt.Task(f"t{i}", wcet, period, deadline, critical_sections=css))
    return tasks


class Bounds(unittest.TestCase):
    def test_liu_layland(self):
        self.assertAlmostEqual(rt.liu_layland_bound(1), 1.0)
        self.assertAlmostEqual(rt.liu_layland_bound(2), 2 * (math.sqrt(2) - 1))
        self.assertAlmostEqual(rt.liu_layland_bound(10_000), math.log(2), places=4)

    def test_model_validation(self):
        with self.assertRaises(ValueError):
            rt.Task("x", 0, 10)
        with self.assertRaises(ValueError):
            rt.Task("x", 3, 10, critical_sections=(rt.CriticalSection("r", 4),))


class ResponseTimeAnalysis(unittest.TestCase):
    def test_textbook_example(self):
        ts = rt.rate_monotonic([rt.Task("a", 1, 4), rt.Task("b", 2, 6), rt.Task("c", 3, 12)])
        self.assertEqual([r.response for r in rt.rta(ts)], [1, 3, 10])

    def test_rm_fails_where_edf_succeeds(self):
        ts = rt.load(EXAMPLES / "rm_vs_edf.toml")
        self.assertFalse(rt.fp_schedulable(rt.rate_monotonic(ts)))
        self.assertTrue(rt.edf_schedulable(ts))

    def test_blocking_under_priority_ceiling(self):
        ts = rt.deadline_monotonic(rt.load(EXAMPLES / "sensor_node.toml"))
        b = {t.name: rt.blocking(ts, t.name) for t in ts}
        self.assertEqual(b, {"adc_dma": 0, "can_tx": 1500, "control": 1500, "telemetry": 0, "logger": 0})

    def test_sensor_node_needs_deadline_monotonic(self):
        ts = rt.load(EXAMPLES / "sensor_node.toml")
        self.assertFalse(rt.fp_schedulable(rt.rate_monotonic(ts)))
        self.assertTrue(rt.fp_schedulable(rt.deadline_monotonic(ts)))


class SimulationAgreesWithAnalysis(unittest.TestCase):
    def test_critical_instant_is_exact(self):
        """Synchronous release is the worst case for fixed priority: without
        blocking, the simulated worst response equals RTA exactly."""
        rng = random.Random(1)
        checked = 0
        for _ in range(300):
            ts = rt.rate_monotonic(random_taskset(rng, rng.randint(2, 6), rng.uniform(0.4, 0.95)))
            results = rt.rta(ts)
            if not all(r.ok for r in results):
                continue
            trace = rt.simulate(ts, "fp")
            for r in results:
                self.assertEqual(trace.max_response(r.task.name), r.response, r.task)
            self.assertEqual(trace.misses(), [])
            checked += 1
        self.assertGreater(checked, 100)

    def test_blocking_bound_is_safe(self):
        rng = random.Random(2)
        checked = 0
        for _ in range(200):
            ts = rt.deadline_monotonic(random_taskset(rng, rng.randint(2, 6), rng.uniform(0.3, 0.8),
                                                      constrained=True, resources=True))
            results = rt.rta(ts)
            if not all(r.ok for r in results):
                continue
            trace = rt.simulate(ts, "fp")
            for r in results:
                self.assertLessEqual(trace.max_response(r.task.name), r.response)
            self.assertEqual(trace.misses(), [])
            checked += any(r.blocking for r in results)
        self.assertGreater(checked, 50)

    def test_edf_demand_test_is_exact(self):
        rng = random.Random(3)
        verdicts = set()
        for _ in range(300):
            ts = random_taskset(rng, rng.randint(2, 5), rng.uniform(0.6, 1.05), constrained=True)
            ok = rt.edf_schedulable(ts)
            missed = bool(rt.simulate(ts, "edf").misses())
            self.assertEqual(ok, not missed, ts)
            verdicts.add(ok)
        self.assertEqual(verdicts, {True, False})  # both outcomes exercised

    def test_rm_miss_is_visible_in_simulation(self):
        ts = rt.rate_monotonic(rt.load(EXAMPLES / "rm_vs_edf.toml"))
        misses = rt.simulate(ts, "fp").misses()
        self.assertTrue(misses)
        self.assertEqual(misses[0].task.name, "slow")
        self.assertEqual(rt.simulate(rt.load(EXAMPLES / "rm_vs_edf.toml"), "edf").misses(), [])


class PriorityAssignment(unittest.TestCase):
    def test_audsley_matches_dm_without_blocking(self):
        """DM is optimal for constrained deadlines without blocking, so
        Audsley's algorithm must succeed exactly when DM does."""
        rng = random.Random(4)
        for _ in range(300):
            ts = random_taskset(rng, rng.randint(2, 6), rng.uniform(0.5, 1.0), constrained=True)
            dm_ok = rt.fp_schedulable(rt.deadline_monotonic(ts))
            opa = rt.audsley(ts)
            self.assertEqual(dm_ok, opa is not None)
            if opa is not None:
                self.assertTrue(rt.fp_schedulable(opa))


class Sizing(unittest.TestCase):
    def test_edf_scale_factor_is_inverse_utilisation(self):
        ts = [rt.Task("a", 1000, 4000), rt.Task("b", 1000, 8000), rt.Task("c", 1250, 10000)]
        u = rt.utilization(ts)
        self.assertAlmostEqual(rt.scale_factor(ts, rt.edf_schedulable), 1 / u, delta=0.005)

    def test_fp_scale_factor_is_tight(self):
        ts = rt.deadline_monotonic(rt.load(EXAMPLES / "sensor_node.toml"))
        f = rt.scale_factor(ts, rt.fp_schedulable)
        self.assertTrue(rt.fp_schedulable([t.scaled(f) for t in ts]))
        self.assertFalse(rt.fp_schedulable([t.scaled(f * 1.01) for t in ts]))


class Outputs(unittest.TestCase):
    def test_gantt_is_valid_svg(self):
        ts = rt.load(EXAMPLES / "rm_vs_edf.toml")
        svg = rt.gantt([("RM", rt.simulate(rt.rate_monotonic(ts), "fp")),
                        ("EDF", rt.simulate(ts, "edf"))], title="t")
        root = ET.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))

    def test_cli(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli_main(["analyze", str(EXAMPLES / "sensor_node.toml"), "--policy", "dm"]), 0)
            self.assertEqual(cli_main(["analyze", str(EXAMPLES / "sensor_node.toml"), "--policy", "rm"]), 1)
            self.assertEqual(cli_main(["simulate", str(EXAMPLES / "rm_vs_edf.toml"), "--policy", "edf"]), 0)
        self.assertIn("schedulable", out.getvalue())


if __name__ == "__main__":
    unittest.main()
