"""Schedulability analysis for preemptive uniprocessor scheduling.

Fixed priority:  exact response-time analysis (Joseph & Pandya / Audsley et
                 al.) with blocking under the immediate priority ceiling
                 protocol; rate- and deadline-monotonic and Audsley's optimal
                 priority assignment.
EDF:             processor-demand test (Baruah, Rosier & Howell).
Sizing:          the largest WCET scale factor that stays schedulable, i.e.
                 how much slower the CPU could run.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .model import Task, TaskSet, by_priority, hyperperiod


# ── utilisation bounds (sufficient tests) ─────────────────────────────────────

def utilization(tasks: TaskSet) -> float:
    return sum(t.utilization for t in tasks)


def liu_layland_bound(n: int) -> float:
    return n * (2 ** (1 / n) - 1)


def hyperbolic_test(tasks: TaskSet) -> bool:
    """Bini & Buttazzo: RM-schedulable if prod(U_i + 1) <= 2 (implicit deadlines)."""
    return math.prod(t.utilization + 1 for t in tasks) <= 2.0


# ── priority assignment ───────────────────────────────────────────────────────

def _with_order(tasks: TaskSet, order: list[Task]) -> TaskSet:
    rank = {t.name: i for i, t in enumerate(order)}
    return [replace(t, priority=rank[t.name]) for t in tasks]


def rate_monotonic(tasks: TaskSet) -> TaskSet:
    return _with_order(tasks, sorted(tasks, key=lambda t: (t.period, t.name)))


def deadline_monotonic(tasks: TaskSet) -> TaskSet:
    return _with_order(tasks, sorted(tasks, key=lambda t: (t.d, t.name)))


def audsley(tasks: TaskSet) -> TaskSet | None:
    """Optimal priority assignment: fill priority levels from the lowest up,
    each time picking any task that is schedulable there with all remaining
    tasks above it. Returns None if no fixed-priority order works."""
    remaining = list(tasks)
    lowest_first: list[Task] = []
    while remaining:
        for cand in remaining:
            others = [t for t in remaining if t is not cand]
            trial = others + [cand] + list(reversed(lowest_first))
            ranked = _with_order(trial, trial)
            # blocking depends on the tasks below, which are already fixed
            r = response_time(ranked, cand.name)
            if r is not None:
                lowest_first.append(cand)
                remaining = others
                break
        else:
            return None
    return _with_order(tasks, list(reversed(lowest_first)))


# ── fixed-priority response-time analysis ─────────────────────────────────────

def ceilings(tasks: TaskSet) -> dict[str, int]:
    """Priority ceiling of each resource: the highest priority of any user."""
    ceil: dict[str, int] = {}
    for t in by_priority(tasks):
        for cs in t.critical_sections:
            ceil.setdefault(cs.resource, t.priority)
    return ceil


def blocking(tasks: TaskSet, name: str) -> int:
    """Worst-case blocking under the (immediate) priority ceiling protocol: the
    longest single critical section of a lower-priority task on a resource
    whose ceiling is at or above this task's priority."""
    ceil = ceilings(tasks)
    me = next(t for t in tasks if t.name == name)
    return max((cs.length for t in tasks if t.priority > me.priority
                for cs in t.critical_sections if ceil[cs.resource] <= me.priority), default=0)


def response_time(tasks: TaskSet, name: str) -> int | None:
    """Exact worst-case response time with constrained deadlines (D <= T).
    Returns None if it exceeds the deadline."""
    me = next(t for t in tasks if t.name == name)
    hp = [t for t in tasks if t.priority < me.priority]
    b = blocking(tasks, name)
    r = me.wcet + b + sum(t.wcet for t in hp)
    while True:
        nxt = me.wcet + b + sum(math.ceil(r / t.period) * t.wcet for t in hp)
        if nxt > me.d:
            return None
        if nxt == r:
            return r
        r = nxt


@dataclass(frozen=True)
class TaskResult:
    task: Task
    blocking: int
    response: int | None

    @property
    def ok(self) -> bool:
        return self.response is not None

    @property
    def slack(self) -> int | None:
        return None if self.response is None else self.task.d - self.response


def rta(tasks: TaskSet) -> list[TaskResult]:
    return [TaskResult(t, blocking(tasks, t.name), response_time(tasks, t.name)) for t in by_priority(tasks)]


def fp_schedulable(tasks: TaskSet) -> bool:
    return all(r.ok for r in rta(tasks))


# ── EDF processor-demand test ─────────────────────────────────────────────────

def demand(tasks: TaskSet, t: int) -> int:
    """Processor demand bound: work with release and deadline inside [0, t]."""
    return sum(max(0, (t - x.d) // x.period + 1) * x.wcet for x in tasks)


def edf_schedulable(tasks: TaskSet) -> bool:
    u = utilization(tasks)
    if u > 1.0 + 1e-12:
        return False
    if all(t.d >= t.period for t in tasks):
        return True  # implicit deadlines: U <= 1 is exact
    # Only absolute deadlines up to L need checking (La bound or hyperperiod).
    h = hyperperiod(tasks)
    limit = h
    if u < 1.0:
        la = sum((t.period - t.d) * t.utilization for t in tasks) / (1 - u)
        limit = min(h, max(max(t.d for t in tasks), math.ceil(la)))
    points = sorted({k * t.period + t.d for t in tasks for k in range((limit - t.d) // t.period + 1)})
    return all(demand(tasks, p) <= p for p in points)


# ── sizing ────────────────────────────────────────────────────────────────────

def scale_factor(tasks: TaskSet, schedulable, lo: float = 0.01, hi: float = 100.0, iters: int = 40) -> float:
    """Largest WCET multiplier for which schedulable(scaled tasks) holds.
    > 1 means headroom (the CPU could be that much slower), < 1 means the
    WCETs must shrink by that factor."""
    if not schedulable([t.scaled(lo) for t in tasks]):
        return 0.0
    for _ in range(iters):
        mid = math.sqrt(lo * hi)
        if schedulable([t.scaled(mid) for t in tasks]):
            lo = mid
        else:
            hi = mid
    return lo
