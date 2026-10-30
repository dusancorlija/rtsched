"""Gantt charts of simulation traces as standalone SVG (no dependencies)."""

from __future__ import annotations

from html import escape

from .sim import Trace

INK, MUTED, GRID, MISS = "#15171a", "#7a7e85", "#eceae6", "#d93025"
PALETTE = ["#3d6fd8", "#e2531a", "#2f9e6e", "#8e5bd8", "#c99a06", "#d2477a", "#4a9bb5", "#6b7280"]
RESOURCE = ["#15171a", "#7a4a12", "#0b5d3b"]


def gantt(panels: list[tuple[str, Trace]], t0: int = 0, t1: int | None = None,
          unit: float = 1.0, unit_name: str = "", title: str = "") -> str:
    """panels: (subtitle, trace) pairs stacked vertically, sharing the time axis.
    unit converts trace ticks to axis units (e.g. 1e-3 for µs -> ms)."""
    t1 = t1 if t1 is not None else max(tr.horizon for _, tr in panels)
    W, L, R = 1000, 110, 20
    row, gap_top = 30, 46
    sx = lambda t: L + (t - t0) / (t1 - t0) * (W - L - R)

    heights = [gap_top + row * len(tr.tasks) + 26 for _, tr in panels]
    H = (40 if title else 10) + sum(heights) + 36
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
           'font-family="Inter, -apple-system, Segoe UI, sans-serif" font-size="11">',
           f'<rect width="{W}" height="{H}" fill="#fff"/>']
    y = 10
    if title:
        out.append(f'<text x="{L}" y="26" font-size="15" font-weight="600" fill="{INK}">{escape(title)}</text>')
        y = 40

    resources = sorted({cs.resource for _, tr in panels for t in tr.tasks for cs in t.critical_sections})
    rcolor = {r: RESOURCE[i % len(RESOURCE)] for i, r in enumerate(resources)}

    for (sub, tr), h in zip(panels, heights):
        order = sorted(tr.tasks, key=lambda t: (t.priority if t.priority is not None else t.d, t.name))
        color = {t.name: PALETTE[i % len(PALETTE)] for i, t in enumerate(order)}
        rowy = {t.name: y + gap_top + i * row for i, t in enumerate(order)}
        misses = tr.misses()
        verdict = (f'<tspan fill="{MISS}" font-weight="600">{len(misses)} deadline miss'
                   f'{"es" if len(misses) != 1 else ""}</tspan>' if misses else
                   f'<tspan fill="#2f9e6e" font-weight="600">all deadlines met</tspan>')
        out.append(f'<text x="{L}" y="{y + 18}" font-size="13" font-weight="600" fill="{INK}">{escape(sub)}</text>')
        out.append(f'<text x="{W - R}" y="{y + 18}" text-anchor="end" fill="{MUTED}">{verdict}</text>')

        # time grid
        span = (t1 - t0) * unit
        step = next(s for s in (1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000) if span / s <= 12)
        k = int(t0 * unit // step)
        while k * step <= t1 * unit:
            tt = k * step / unit
            if tt >= t0:
                out.append(f'<line x1="{sx(tt):.1f}" x2="{sx(tt):.1f}" y1="{y + gap_top - 8}" '
                           f'y2="{y + gap_top + row * len(order)}" stroke="{GRID}"/>')
                out.append(f'<text x="{sx(tt):.1f}" y="{y + gap_top + row * len(order) + 14}" '
                           f'text-anchor="middle" fill="{MUTED}">{k * step:g}{unit_name}</text>')
            k += 1

        for t in order:
            ry = rowy[t.name]
            out.append(f'<text x="{L - 10}" y="{ry + 15}" text-anchor="end" fill="{INK}">{escape(t.name)}</text>')
            out.append(f'<line x1="{L}" x2="{W - R}" y1="{ry + 22}" y2="{ry + 22}" stroke="{GRID}"/>')

        for s in tr.slices:
            if s.end <= t0 or s.start >= t1:
                continue
            a, b = sx(max(s.start, t0)), sx(min(s.end, t1))
            fill = rcolor[s.resource] if s.resource else color[s.task]
            out.append(f'<rect x="{a:.2f}" y="{rowy[s.task] + 6}" width="{max(b - a, 0.6):.2f}" height="16" fill="{fill}"/>')

        for j in tr.jobs:
            ry = rowy[j.task.name]
            if t0 <= j.release <= t1:
                x = sx(j.release)
                out.append(f'<path d="M{x:.1f},{ry + 22} v-20 m-3,4 l3,-4 l3,4" stroke="{MUTED}" fill="none" stroke-width="1"/>')
            if j.missed and j.deadline <= tr.horizon and t0 <= j.deadline <= t1:
                x = sx(j.deadline)
                out.append(f'<path d="M{x - 4:.1f},{ry + 2} l8,8 m0,-8 l-8,8" stroke="{MISS}" stroke-width="2"/>')

        if resources:
            lx = L
            for r in resources:
                out.append(f'<rect x="{lx}" y="{y + 26}" width="10" height="10" fill="{rcolor[r]}"/>')
                out.append(f'<text x="{lx + 14}" y="{y + 35}" fill="{MUTED}">critical section on {escape(r)}</text>')
                lx += 150
        y += h

    out.append(f'<text x="{L}" y="{H - 10}" fill="{MUTED}">↑ release   '
               f'<tspan fill="{MISS}">✕ deadline miss</tspan></text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"
