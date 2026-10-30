"""Task model. All times are integers (e.g. microseconds) so that analysis and
simulation are exact: no floating-point rounding in response times."""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field, replace
from functools import reduce
from pathlib import Path


@dataclass(frozen=True)
class CriticalSection:
    resource: str
    length: int


@dataclass(frozen=True)
class Task:
    name: str
    wcet: int
    period: int
    deadline: int | None = None          # relative; defaults to the period
    priority: int | None = None          # 0 = highest; assigned by a policy
    critical_sections: tuple[CriticalSection, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.wcet <= 0 or self.period <= 0:
            raise ValueError(f"{self.name}: wcet and period must be positive")
        if self.d <= 0:
            raise ValueError(f"{self.name}: deadline must be positive")
        if sum(cs.length for cs in self.critical_sections) > self.wcet:
            raise ValueError(f"{self.name}: critical sections exceed the WCET")

    @property
    def d(self) -> int:
        return self.period if self.deadline is None else self.deadline

    @property
    def utilization(self) -> float:
        return self.wcet / self.period

    def scaled(self, factor: float) -> Task:
        """WCET (and critical sections) multiplied by factor, rounded up."""
        css = tuple(CriticalSection(cs.resource, max(1, math.ceil(cs.length * factor)))
                    for cs in self.critical_sections)
        return replace(self, wcet=max(1, math.ceil(self.wcet * factor)), critical_sections=css)


TaskSet = list[Task]


def hyperperiod(tasks: TaskSet) -> int:
    return reduce(math.lcm, (t.period for t in tasks), 1)


def by_priority(tasks: TaskSet) -> TaskSet:
    if any(t.priority is None for t in tasks):
        raise ValueError("assign priorities first (rm, dm or audsley)")
    return sorted(tasks, key=lambda t: t.priority)


def load(path: str | Path) -> TaskSet:
    """Reads a task set from TOML:

        [[task]]
        name = "control"
        wcet = 900
        period = 5000
        deadline = 4000                      # optional
        critical_sections = [{ resource = "spi", length = 200 }]
    """
    data = tomllib.loads(Path(path).read_text())
    tasks = []
    for t in data["task"]:
        css = tuple(CriticalSection(c["resource"], int(c["length"])) for c in t.get("critical_sections", []))
        tasks.append(Task(t["name"], int(t["wcet"]), int(t["period"]), t.get("deadline"),
                          t.get("priority"), css))
    return tasks
