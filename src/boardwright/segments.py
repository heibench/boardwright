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
  by distance), where connections that continue each other in a straight line
  through a pad share one segment, plus one per via.

A net or chain whose own tracks include one off the octilinear grid (more than
0.5 degrees from a multiple of 45) is routed at any angle, and needs only one
segment per connection.

Segments are counted after joining straight neighbours: two segments that meet
end to end in the same direction, with nothing else there, are one run. A bend
the route has to make round an obstacle counts as excess too, so the number
compares two layouts of the same nets; it is not a verdict on its own.

The minimum is a reference, not a lower bound: a route can share one segment
between two connections where the tree through the pads does not (a
T-junction, a via partway along a run, or a run that passes over a pad on the
way), so excess can go below zero on such a net. The reference only ever
errs high, so it hides excess rather than inventing it (#167). A poured net cannot be judged, since its pour joins
pads that tracks otherwise would: named, it fails; matched by a pattern, it is
left out. A net with no track cannot be judged either, and fails, except that a
pattern leaves out one with nothing to join: a single pad, or copper with no net.
"""

from __future__ import annotations

import math
from collections import defaultdict

TOL = 0.05          # mm: how far off an octilinear line a pair of pads may sit


def _octilinear(a, b) -> int:
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return 1 if dx < TOL or dy < TOL or abs(dx - dy) < TOL else 2


def _any_angle(b, group) -> bool:
    """Whether any of the group's tracks runs off the octilinear grid."""
    for t in b.tracks:
        if t.net in group and t.a != t.b:
            ang = math.degrees(math.atan2(t.b[1] - t.a[1], t.b[0] - t.a[0])) % 45
            if min(ang, 45 - ang) > 0.5:
                return True
    return False


def runs(b, net: str) -> int:
    """The net's track segments, counting straight neighbours that meet end to
    end with nothing else there as one."""
    from .tidy import _at, _centres, _Points  # one point for ends within SAME; pad or via centres by distance

    ts = [t for t in b.tracks if t.net == net and t.a != t.b]
    _k = _Points(q for t in ts for q in (t.a, t.b))
    segs = [(*_k(t.a), *_k(t.b), t.layer) for t in ts]
    stops = _centres(b, {net})
    at, ends = defaultdict(list), defaultdict(list)
    for t, s in zip(ts, segs):
        at[(s[0], s[1], s[4])].append(s)
        at[(s[2], s[3], s[4])].append(s)
        ends[(s[0], s[1], s[4])].append(t.a)
        ends[(s[2], s[3], s[4])].append(t.b)

    def direction(s):
        dx, dy = s[2] - s[0], s[3] - s[1]
        n = math.hypot(dx, dy)
        return (dx / n, dy / n) if n else None              # both ends one point: no direction
    joins = 0
    for key, ss in at.items():
        if len(ss) == 2 and not any(_at(stops, net, q) for q in ends[key]):
            u, v = direction(ss[0]), direction(ss[1])
            if u and v and abs(abs(u[0] * v[0] + u[1] * v[1]) - 1) < 1e-3:
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


def _tree_minimum(pts, any_angle: bool = False) -> int:
    """Segments over a minimum spanning tree of the points: one per straight
    connection (on the octilinear grid, or at any angle when any_angle), two
    per other, where connections that continue each other in a straight line
    through a point share one segment."""
    pts = sorted(set(pts))
    if len(pts) < 2:
        return 0
    inside, edges = {0}, []
    while len(inside) < len(pts):
        i, j = min(((i, j) for i in inside for j in range(len(pts)) if j not in inside),
                   key=lambda ij: math.dist(pts[ij[0]], pts[ij[1]]))
        inside.add(j)
        edges.append((i, j))
    straight = [any_angle or _octilinear(pts[i], pts[j]) == 1 for i, j in edges]
    up = list(range(len(edges)))

    def root(k):
        while up[k] != k:
            up[k] = up[up[k]]
            k = up[k]
        return k

    def away(e, k):                                 # unit direction of edge e leaving point k
        i, j = edges[e]
        o = j if i == k else i
        dx, dy = pts[o][0] - pts[k][0], pts[o][1] - pts[k][1]
        n = math.hypot(dx, dy)
        return dx / n, dy / n
    for k in range(len(pts)):
        at = [e for e, (i, j) in enumerate(edges) if k in (i, j) and straight[e]]
        for x in range(len(at)):
            for y in range(x + 1, len(at)):
                (ux, uy), (vx, vy) = away(at[x], k), away(at[y], k)
                if ux * vx + uy * vy < -0.9999:     # opposite ways out of k: one straight run through it
                    up[root(at[x])] = root(at[y])
    return len({root(e) for e, s in enumerate(straight) if s}) + 2 * straight.count(False)


def segments_check(b, spec: dict) -> tuple[list[str], list[str]]:
    """(report lines, failures) for REVIEW "segments"."""
    from .review import _expand
    lines, fails = [], []
    chains = _chains(b)
    known = {t.net for t in b.tracks} | {p.net for p in b.pads}
    poured = {z.net for z in b.zones if not z.keepout and any(z.fills.values())}
    for nets, limit in spec.get("segments", []):
        given = [nets] if isinstance(nets, str) else list(nets)
        named = {n for n in given if not any(c in n for c in "*?[")}
        names = []
        for n in given:
            if n not in named:                      # a pattern leaves poured nets out
                names += [x for x in _expand(b, [n]) if x not in poured]
            else:
                names.append(n)
        done = set()
        for net in names:
            if net in done:
                continue
            if net not in known:
                fails.append(f"segments {net}: no such net")
                continue
            if net in poured:
                fails.append(f"segments {net}: cannot judge, it is poured")
                continue
            chain = next((c for c in chains if net in c[2]), None)
            group = chain[2] if chain else [net]
            done.update(group)
            if not any(t.net in group for t in b.tracks):
                # a pattern also leaves out what has nothing to join: one pad, or copper with no net
                lone = sum(1 for p in b.pads if p.net and p.net in group) < 2
                if named & set(group) or not lone:
                    fails.append(f"segments {net}: cannot judge, it has no track")
                continue
            vias = sum(1 for v in b.vias if v.net in group)
            actual = sum(runs(b, n) for n in group)
            free = _any_angle(b, group)
            if chain:
                (a, z), parts = chain[0], chain[1]
                least = (1 if free else _octilinear((a.x, a.y), (z.x, z.y))) + len(parts) + vias
                what = f"{a.ref}.{a.num} -> {z.ref}.{z.num} through {', '.join(parts)} ({', '.join(group)})"
            else:
                least = _tree_minimum([(p.x, p.y) for p in b.pads if p.net == net], free) + vias
                what = net
            lines.append(f"segments {what}: {actual}, minimum {least} (excess <= {limit})")
            if actual - least > limit:
                fails.append(f"{what} takes {actual} segments where {least} would do, excess "
                             f"{actual - least}, limit {limit}")
    return lines, fails
