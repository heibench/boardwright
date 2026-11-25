"""REVIEW "tidy": track debris that DRC passes and a reviewer marks (#138).

    "tidy": ["/ESTOP", "+5V", "*"]      nets, or shell patterns

Each finding names its place. On each named net and copper layer:

- micro: a segment shorter than MICRO, or of zero length.
- split: two collinear segments of one width meeting end to end with nothing
  else there, where one segment would do.
- overlap: two collinear segments lying over each other.
- near-miss: two track ends that should be one point but are NEAR apart.
- dangling: a track end touching no other track, pad or via. A track end in
  its own net's pour is still reported, with the pour named: the pour joins it,
  but nothing needed the track to go there.
- off-centre: a track end on a pad of its net, more than OFF from the pad's
  centre (a stub left inside the pad, or a track stopping short of the centre).
- short-of-pad: a track end outside the pad it serves, joined to it only by
  the track's own width overlapping the pad.
- on-track: a track end on the body of another track of its net, not at an end.
- crosses: a segment that runs over a pad of its net, starting and ending
  outside it, with its line more than OFF from the pad's centre. The copper
  joins them, so DRC passes it, but the route was meant to stop at the pad. A
  straight run through the centre is not named: one segment serving pads on
  its line is a fair route. A merge of collinear segments that dropped a
  pad-centre vertex leaves this (feastorg/Slice_FPSG dd208b7, a GNDD bar
  0.513 mm from C1.1's centre, gone in 802a2d8).

These are what DRC cannot see because the copper is legal. The thresholds come
from square-by-square reviews of three routed boards (#138): every 10 mm square
checked against the board file, each finding logged. The reviews logged
pieces from 0.002 to 0.071 mm and ends 0.007 mm apart. At the values below the
check flags, in the same or a neighbouring square and on the same net, 9 of
the 9 micro-segment findings (as micro or split), 6 of 6 short-of-pad, 5 of 8
duplicate-segment on copper and 5 of 11 stub. The stubs it misses are mostly
a short straight run out of a pad before the first bend, which is sometimes
forced by the pin pitch and is left to the reviewer. The flags it raised in
squares the review passed, inspected, were the same kinds of defect, missed.
The findings are kept out of this repository so that they can go on scoring
these checks.

The example boards here, routed by Freerouting, carry micro, split and
near-miss findings too.

Arcs count as track ends but are not checked as segments.
"""

from __future__ import annotations

import math
from collections import defaultdict

SAME = 0.001        # mm: ends closer than this are one point (boardwright rounds to 3 places)
MICRO = 0.05        # mm: a shorter segment is debris (#138)
NEAR = 0.05         # mm: ends closer than this but not SAME should have been one point (#138)
OFF = 0.05          # mm: a track end farther than this from its pad's centre is off it
LINE = 0.02         # mm: how far off a segment's line another may sit and still lie over it


def _k(p):
    # snapped to the file's nanometres first: float noise must not split one point across a cell edge
    return (round(round(p[0], 6) / SAME), round(round(p[1], 6) / SAME))


def _unit(a, b):
    n = math.dist(a, b)
    return ((b[0] - a[0]) / n, (b[1] - a[1]) / n)


def findings(b, nets: set[str]) -> list[tuple[str, str, str, float, float, str]]:
    """(kind, net, layer, x, y, detail) for every finding on the named nets."""
    from shapely.geometry import LineString, Point

    from .route import pad_shape

    out = []
    tracks = [t for t in b.tracks if t.net in nets]
    segs = [t for t in tracks if len(t.pts) == 2]
    pads, vias = defaultdict(list), defaultdict(list)
    for p in b.pads:
        if p.net in nets:
            pads[p.net].append(p)
    for v in b.vias:
        if v.net in nets:
            vias[v.net].append(v)
    stops = {(n, _k((p.x, p.y))) for n, ps in pads.items() for p in ps}
    stops |= {(n, _k((v.x, v.y))) for n, vs in vias.items() for v in vs}

    for t in segs:
        if t.length < MICRO:
            out.append(("micro", t.net, t.layer, *t.a, f"a {t.length:.3f} mm segment"))

    by, joint = defaultdict(list), defaultdict(list)
    for t in segs:
        if t.length >= SAME:
            by[(t.net, t.layer)].append(t)
            for q in (t.a, t.b):
                joint[(t.net, t.layer, _k(q))].append((t, q))
    for (net, layer, k), tq in joint.items():
        if len(tq) == 2 and (net, k) not in stops:
            (t1, q), (t2, _q) = tq
            u, v = _unit(t1.a, t1.b), _unit(t2.a, t2.b)
            if abs(abs(u[0] * v[0] + u[1] * v[1]) - 1) < 1e-4 and t1.width == t2.width:
                out.append(("split", net, layer, *q, "two collinear segments where one would do"))

    for (net, layer), ts in by.items():
        for i, a in enumerate(ts):
            ux, uy = _unit(a.a, a.b)
            for c in ts[i + 1:]:
                if max(abs((q[0] - a.a[0]) * uy - (q[1] - a.a[1]) * ux) for q in (c.a, c.b)) > LINE:
                    continue
                s0, s1 = sorted((q[0] - a.a[0]) * ux + (q[1] - a.a[1]) * uy for q in (c.a, c.b))
                over = min(a.length, s1) - max(0.0, s0)
                if over > 0.01:
                    x, y = a.a[0] + ux * max(0.0, s0), a.a[1] + uy * max(0.0, s0)
                    out.append(("overlap", net, layer, x, y, f"two segments lie over each other for {over:.3f} mm"))

    ends = defaultdict(dict)                        # (net, layer) -> point key -> (point, the tracks ending there)
    for t in tracks:
        for q in (t.a, t.b):
            ends[(t.net, t.layer)].setdefault(_k(q), (q, set()))[1].add(id(t))
    for (net, layer), pts in ends.items():
        items = list(pts.values())
        for i, (p, ti) in enumerate(items):
            for q, tj in items[i + 1:]:
                d = math.dist(p, q)
                own = any(id(t) in ti and id(t) in tj and len(t.pts) == 2 for t in tracks)
                if SAME <= d < NEAR and not own:
                    out.append(("near-miss", net, layer, *p, f"two track ends {d:.3f} mm apart"))

    for t in segs:
        line = LineString(t.pts)
        for p in pads[t.net]:
            if not p.on(t.layer):
                continue
            sh = pad_shape(p).buffer(1e-4)
            if not line.intersects(sh) or sh.contains(Point(t.a)) or sh.contains(Point(t.b)):
                continue
            c = Point(p.x, p.y)
            if (d := line.distance(c)) > OFF:
                q = line.interpolate(line.project(c))
                out.append(("crosses", t.net, t.layer, q.x, q.y,
                            f"runs over {p.ref}.{p.num} {d:.3f} mm from its centre, with no vertex there"))

    degree = defaultdict(int)
    for t in tracks:
        for q in (t.a, t.b):
            degree[(t.net, t.layer, _k(q))] += 1
    for t in tracks:
        for q in (t.a, t.b):
            if degree[(t.net, t.layer, _k(q))] > 1:
                continue
            if any(math.dist(q, (v.x, v.y)) < v.size / 2 for v in vias[t.net]):
                continue
            pt = Point(q)
            on = [p for p in pads[t.net] if p.on(t.layer) and pad_shape(p).buffer(1e-4).contains(pt)]
            if on:
                p, d = on[0], math.dist(q, (on[0].x, on[0].y))
                if d > OFF:
                    out.append(("off-centre", t.net, t.layer, *q, f"ends {d:.3f} mm from the centre of {p.ref}.{p.num}"))
                continue
            near = [p for p in pads[t.net] if p.on(t.layer) and pad_shape(p).distance(pt) < t.width / 2]
            if near:
                p = near[0]
                out.append(("short-of-pad", t.net, t.layer, *q,
                            f"ends outside {p.ref}.{p.num}, joined to it only by the track's width"))
            elif any(o is not t and o.layer == t.layer and o.net == t.net
                     and LineString(o.pts).distance(pt) < o.width / 2 for o in tracks):
                out.append(("on-track", t.net, t.layer, *q, "ends on the body of another track, not at its end"))
            else:
                pour = any(z.net == t.net and not z.keepout and z.covers(t.layer, *q) for z in b.zones)
                out.append(("dangling", t.net, t.layer, *q, "ends on nothing" + (f" (inside the {t.net} pour)" if pour else "")))
    return out


def tidy_check(b, spec: dict) -> tuple[list[str], list[str]]:
    """(report lines, failures) for REVIEW "tidy"."""
    if not spec.get("tidy"):
        return [], []
    from .review import _expand
    known = {t.net for t in b.tracks} | {p.net for p in b.pads}
    names, fails = [], []
    for n in _expand(b, spec["tidy"]):
        if n in known:
            names.append(n)
        else:
            fails.append(f"tidy {n}: no such net")
    found = sorted(findings(b, set(names)), key=lambda f: (f[1], f[2], f[0], round(f[3], 3), round(f[4], 3)))
    counts = defaultdict(int)
    for kind, *_ in found:
        counts[kind] += 1
    lines = [f"tidy {len(names)} net(s): " + (", ".join(f"{k} {n}" for k, n in sorted(counts.items())) or "clean")]
    fails += [f"{kind} on {net} {layer} at ({x:.2f}, {y:.2f}): {what}" for kind, net, layer, x, y, what in found]
    return lines, fails
