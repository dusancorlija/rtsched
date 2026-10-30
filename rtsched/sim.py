"""Event-driven simulation of a preemptive uniprocessor scheduler.

Policies:
  fp   fixed priority, with the immediate priority ceiling protocol: a job
       inside a critical section runs at the resource's ceiling, so it cannot
       be preempted by any other user of that resource (no deadlock, at most
       one blocking critical section per job).
  edf  earliest deadline first. Critical sections are executed but not
       arbitrated (no SRP); use fp to study blocking.

Each job runs half of its non-critical work, then its critical sections in
order, then the rest. Releases are synchronous at t = 0 (the critical instant
for fixed priority), so the observed worst case over a hyperperiod equals
the analytic worst case when there is no blocking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .analysis import ceilings
from .model import Task, TaskSet, hyperperiod


@dataclass(frozen=True)
class Slice:
    task: str
    job: int
    start: int
    end: int
    resource: str | None


@dataclass
class Job:
    task: Task
    index: int
    release: int
    deadline: int
    segments: list[list]               # [remaining, resource | None]
    start: int | None = None
    finish: int | None = None

    @property
    def resource(self) -> str | None:
        return self.segments[0][1] if self.segments else None

    @property
    def response(self) -> int | None:
        return None if self.finish is None else self.finish - self.release

    @property
    def missed(self) -> bool:
        return self.finish is None or self.finish > self.deadline


@dataclass
class Trace:
    policy: str
    horizon: int
    tasks: TaskSet
    slices: list[Slice] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)

    def misses(self) -> list[Job]:
        return [j for j in self.jobs if j.deadline <= self.horizon and j.missed]

    def max_response(self, name: str) -> int | None:
        rs = [j.response for j in self.jobs if j.task.name == name and j.response is not None]
        return max(rs) if rs else None


def _segments(task: Task, actual: int) -> list[list]:
    cs_total = sum(cs.length for cs in task.critical_sections)
    normal = max(0, actual - cs_total)
    first = normal // 2
    segs = [[first, None]] + [[cs.length, cs.resource] for cs in task.critical_sections] + [[normal - first, None]]
    return [s for s in segs if s[0] > 0]


def simulate(tasks: TaskSet, policy: str = "fp", horizon: int | None = None,
             exec_time: Callable[[Task, int], int] | None = None) -> Trace:
    if policy not in ("fp", "edf"):
        raise ValueError("policy must be 'fp' or 'edf'")
    if policy == "fp" and any(t.priority is None for t in tasks):
        raise ValueError("fp needs priorities: use rate_monotonic(), deadline_monotonic() or audsley()")
    horizon = horizon or hyperperiod(tasks)
    ceil = ceilings(tasks) if policy == "fp" else {}
    trace = Trace(policy, horizon, tasks)
    next_release = {t.name: 0 for t in tasks}
    count = {t.name: 0 for t in tasks}
    ready: list[Job] = []

    def key(j: Job):
        if policy == "edf":
            return (j.deadline, j.release, j.task.name)
        eff = min(j.task.priority, ceil[j.resource]) if j.resource else j.task.priority
        # On a tie, the job that holds a resource keeps the CPU (ceiling rule).
        return (eff, 0 if j.resource else 1, j.release)

    t = 0
    while t < horizon:
        for task in tasks:
            while next_release[task.name] <= t:
                k = count[task.name]
                r = next_release[task.name]
                actual = task.wcet if exec_time is None else max(1, min(task.wcet, exec_time(task, k)))
                job = Job(task, k, r, r + task.d, _segments(task, actual))
                ready.append(job)
                trace.jobs.append(job)
                count[task.name] += 1
                next_release[task.name] += task.period

        upcoming = min(next_release.values())
        if not ready:
            t = min(upcoming, horizon)
            continue

        job = min(ready, key=key)
        if job.start is None:
            job.start = t
        seg = job.segments[0]
        run = min(seg[0], upcoming - t, horizon - t)

        last = trace.slices[-1] if trace.slices else None
        if last and last.end == t and last.task == job.task.name and last.job == job.index and last.resource == seg[1]:
            trace.slices[-1] = Slice(last.task, last.job, last.start, t + run, seg[1])
        else:
            trace.slices.append(Slice(job.task.name, job.index, t, t + run, seg[1]))

        t += run
        seg[0] -= run
        if seg[0] == 0:
            job.segments.pop(0)
            if not job.segments:
                job.finish = t
                ready.remove(job)
    return trace
