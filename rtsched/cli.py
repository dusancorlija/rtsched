"""rtsched command line.

    python -m rtsched analyze examples/sensor_node.toml --policy dm
    python -m rtsched simulate examples/sensor_node.toml --policy dm --svg out.svg --window 0:20000
"""

from __future__ import annotations

import argparse
import sys

from . import analysis as an
from .model import load
from .sim import simulate
from .svg import gantt

POLICIES = {
    "rm": an.rate_monotonic,
    "dm": an.deadline_monotonic,
    "audsley": an.audsley,
}


def _prepare(path: str, policy: str):
    tasks = load(path)
    if policy == "edf":
        return tasks
    ranked = POLICIES[policy](tasks)
    if ranked is None:
        sys.exit("audsley: no fixed-priority assignment is schedulable")
    return ranked


def cmd_analyze(args) -> int:
    tasks = _prepare(args.file, args.policy)
    u = an.utilization(tasks)
    n = len(tasks)
    if all(t.d == t.period and not t.critical_sections for t in tasks):
        bounds = (f"Liu & Layland bound {an.liu_layland_bound(n):.3f}, "
                  f"hyperbolic test {'passes' if an.hyperbolic_test(tasks) else 'fails'}")
    else:
        bounds = "utilisation bounds do not apply: constrained deadlines or shared resources"
    print(f"{n} tasks, U = {u:.3f}  ({bounds})\n")

    if args.policy == "edf":
        ok = an.edf_schedulable(tasks)
        test = an.edf_schedulable
        print("EDF processor-demand test:", "schedulable" if ok else "NOT schedulable")
    else:
        results = an.rta(tasks)
        ok = all(r.ok for r in results)
        test = an.fp_schedulable
        w = max(len(t.name) for t in tasks)
        print(f"{'task':<{w}}  prio      C       T       D     U      B       R   slack")
        for r in results:
            t = r.task
            resp = f"{r.response:7d}" if r.ok else "   MISS"
            slack = f"{r.slack:7d}" if r.ok else "      -"
            print(f"{t.name:<{w}}  {t.priority:4d} {t.wcet:6d} {t.period:7d} {t.d:7d} "
                  f"{t.utilization:5.3f} {r.blocking:6d} {resp} {slack}")
        print(f"\n{args.policy.upper()}: {'schedulable' if ok else 'NOT schedulable'}")

    f = an.scale_factor(tasks, test)
    if ok:
        print(f"WCET headroom: x{f:.3f}. Every task may take {100 * (f - 1):.1f} % longer; "
              f"equivalently the CPU clock could drop to {100 / f:.1f} %.")
    else:
        print(f"WCETs must shrink to x{f:.3f} ({100 * (1 - f):.1f} % less work) to become schedulable.")
    return 0 if ok else 1


def cmd_simulate(args) -> int:
    tasks = _prepare(args.file, args.policy)
    trace = simulate(tasks, "edf" if args.policy == "edf" else "fp", args.until)
    bounds = {} if args.policy == "edf" else {r.task.name: r.response for r in an.rta(tasks)}
    print(f"{'task':<14} jobs  max response  analytic bound")
    for t in tasks:
        jobs = sum(1 for j in trace.jobs if j.task.name == t.name)
        b = bounds.get(t.name)
        print(f"{t.name:<14} {jobs:4d}  {trace.max_response(t.name) or 0:12d}  "
              f"{'-' if t.name not in bounds else ('MISS' if b is None else b):>14}")
    misses = trace.misses()
    print(f"\n{len(misses)} deadline misses" + (f", first: {misses[0].task.name} job {misses[0].index} "
                                                  f"(deadline {misses[0].deadline})" if misses else ""))
    if args.svg:
        t0, t1 = (int(x) for x in args.window.split(":")) if args.window else (0, trace.horizon)
        with open(args.svg, "w") as fh:
            fh.write(gantt([(f"{args.policy.upper()} - {args.file}", trace)], t0, t1,
                           unit=args.unit, unit_name=args.unit_name))
        print(f"wrote {args.svg}")
    return 0 if not misses else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rtsched", description="Real-time schedulability analysis and simulation")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("analyze", cmd_analyze), ("simulate", cmd_simulate)):
        s = sub.add_parser(name)
        s.add_argument("file")
        s.add_argument("--policy", choices=[*POLICIES, "edf"], default="rm")
        s.set_defaults(fn=fn)
        if name == "simulate":
            s.add_argument("--until", type=int, help="horizon (default: hyperperiod)")
            s.add_argument("--svg", help="write a Gantt chart")
            s.add_argument("--window", help="time window for the chart, start:end")
            s.add_argument("--unit", type=float, default=1.0, help="axis scale, e.g. 0.001 for us -> ms")
            s.add_argument("--unit-name", default="", help="axis unit label, e.g. ' ms'")
    args = p.parse_args(argv)
    return args.fn(args)
