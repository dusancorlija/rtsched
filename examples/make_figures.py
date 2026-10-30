"""Regenerates the charts in docs/.  python3 examples/make_figures.py"""

from pathlib import Path

import rtsched as rt

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent / "docs"

ts = rt.load(HERE / "rm_vs_edf.toml")
(DOCS / "rm_vs_edf.svg").write_text(rt.gantt(
    [("Rate monotonic", rt.simulate(rt.rate_monotonic(ts), "fp")),
     ("Earliest deadline first", rt.simulate(ts, "edf"))],
    0, 35, title="Same two tasks at U = 0.971: RM misses, EDF does not"))

node = rt.deadline_monotonic(rt.load(HERE / "sensor_node.toml"))
(DOCS / "sensor_node.svg").write_text(rt.gantt(
    [("Deadline monotonic with the priority ceiling protocol", rt.simulate(node, "fp"))],
    0, 20000, unit=1e-3, unit_name=" ms",
    title="Sensor node: first 20 ms of the 100 ms hyperperiod"))
print("ok")
