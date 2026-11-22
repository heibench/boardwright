"""REVIEW "segments": track segments against the fewest the route needs (#148).

    "segments": [(NETS, excess)]    a net, a list of nets, or a shell pattern

A net that runs through a series part (a two-pad part whose two nets each join
exactly two pads: an inline resistor, a solder jumper, a 0 ohm link) is judged
with the whole chain it belongs to, from the pad before the first part to the
pad after the last. That is the case it was built for: a column of series
parts placed before routing gives each signal a dog-leg out to the column and
back, which DRC cannot see (heibench/research topics/eda-agents/field-report.md,
technique T1).

The minimum is what an octilinear (0, 45, 90 degree) route needs:

- a chain: one segment between its outer pads if they lie on a common
  octilinear line, two otherwise, plus one per part on it (the part splits
  the run), plus one per via (a layer change starts a new run);
- any other net: the same per connection of its pads (a minimum spanning tree
  by distance), plus one per via.

Segments are counted after joining straight neighbours: two segments that meet
end to end in the same direction, with nothing else there, are one run. A bend
the route has to make round an obstacle counts as excess too, so the number
compares two layouts of the same nets; it is not a verdict on its own. A named
net with no track cannot be judged, and fails.
"""

from __future__ import annotations

import math
from collections import defaultdict

TOL = 0.05          # mm: how far off an octilinear line a pair of pads may sit


def _octilinear(a, b) -> int:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return 1 if dx < TOL or dy < TOL or abs(dx - dy) < TOL else 2


def runs(b, net: str) -> int:
    """The net's track segments, counting straight neighbours that meet end to
    end with nothing else there as one."""
    segs = [(round(t.a[0], 3), round(t.a[1], 3), round(t.b[0], 3), round(t.b[1], 3), t.layer)
            for t in b.tracks if t.net == net and t.a != t.b]
    stops = {(round(v.x, 3), round(v.y, 3)) for v in b.vias if v.net == net}
    stops |= {(round(p.x, 3), round(p.y, 3)) for p in b.pads if p.net == net}
    at = defaultdict(list)
    for s in segs:
        at[(s[0], s[1], s[4])].append(s)
        at[(s[2], s[3], s[4])].append(s)

    def direction(s):
        dx, dy = s[2] - s[0], s[3] - s[1]
        n = math.hypot(dx, dy)
        return dx / n, dy / n
    joins = 0
    for (x, y, _layer), ss in at.items():
        if len(ss) == 2 and (x, y) not in stops:
            (ux, uy), (vx, vy) = direction(ss[0]), direction(ss[1])
            if abs(abs(ux * vx + uy * vy) - 1) < 1e-3:
                joins += 1
    return len(segs) - joins


def _chains(b) -> list[tuple[list, list[str], list[str]]]:
    """Every chain of series parts: (outer pads, parts, nets)."""
    pads = defaultdict(list)
    for p in b.pads:
        if p.net:
            pads[p.net].append(p)
    links = {}
    for ref in sorted({p.ref for p in b.pads}):
        pp = [p for p in b.pads if p.ref == ref]
        if len(pp) == 2 and pp[0].net != pp[1].net and all(p.net and len(pads[p.net]) == 2 for p in pp):
            links[ref] = pp
    out, seen = [], set()
    for ref, pp in links.items():
        if ref in seen:
            continue
        seen.add(ref)
        parts, nets, ends = [ref], [pp[0].net, pp[1].net], []
        for side in (0, 1):
            net, came = pp[side].net, ref
            while True:
                other = next(q for q in pads[net] if q.ref != came)
                if other.ref in links and other.ref not in seen:
                    seen.add(other.ref)
                    parts.append(other.ref)
                    net, came = next(q for q in links[other.ref] if q.num != other.num).net, other.ref
                    nets.append(net)
                    continue
                if other.ref in links:          # a ring of series parts: no outer pad
                    break
                ends.append(other)
                break
        if len(ends) == 2:
            out.append((ends, parts, nets))
    return out


def _tree_minimum(pts) -> int:
    """Octilinear segments over a minimum spanning tree of the points."""
    if len(pts) < 2:
        return 0
    inside, total = {0}, 0
    while len(inside) < len(pts):
        i, j = min(((i, j) for i in inside for j in range(len(pts)) if j not in inside),
                   key=lambda ij: math.dist(pts[ij[0]], pts[ij[1]]))
        inside.add(j)
        total += _octilinear(pts[i], pts[j])
    return total


def segments_check(b, spec: dict) -> tuple[list[str], list[str]]:
    """(report lines, failures) for REVIEW "segments"."""
    from .review import _expand
    lines, fails = [], []
    chains = _chains(b)
    known = {t.net for t in b.tracks} | {p.net for p in b.pads}
    for nets, limit in spec.get("segments", []):
        names = _expand(b, [nets] if isinstance(nets, str) else list(nets))
        done = set()
        for net in names:
            if net in done:
                continue
            if net not in known:
                fails.append(f"segments {net}: no such net")
                continue
            chain = next((c for c in chains if net in c[2]), None)
            group = chain[2] if chain else [net]
            done.update(group)
            if not any(t.net in group for t in b.tracks):
                fails.append(f"segments {net}: cannot judge, it has no track")
                continue
            vias = sum(1 for v in b.vias if v.net in group)
            actual = sum(runs(b, n) for n in group)
            if chain:
                (a, z), parts = chain[0], chain[1]
                least = _octilinear((a.x, a.y), (z.x, z.y)) + len(parts) + vias
                what = f"{a.ref}.{a.num} -> {z.ref}.{z.num} through {', '.join(parts)} ({', '.join(group)})"
            else:
                least = _tree_minimum([(p.x, p.y) for p in b.pads if p.net == net]) + vias
                what = net
            lines.append(f"segments {what}: {actual}, minimum {least} (excess <= {limit})")
            if actual - least > limit:
                fails.append(f"{what} takes {actual} segments where {least} would do, excess "
                             f"{actual - least}, limit {limit}")
    return lines, fails
