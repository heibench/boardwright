"""REVIEW "bends": the angle at each bend of a route (#138).

    "bends": [(NETS, FAIL)]     NETS a net, a list of nets, or shell patterns;
                                FAIL the kinds that fail, from "acute", "square", "off-45"

A bend is a point where exactly two straight segments of one net meet on one
layer, outside any pad or via of that net (there the copper covers the inside
corner). Its angle is the angle between the two segments, 180 degrees for a
straight run. Kinds:

- acute: a bend under 90 degrees. The inside corner can trap etchant during
  fabrication (an acid trap); usually worth failing.
- square: a bend of 90 degrees. Harmless electrically below the GHz range
  (#128), but a reviewer's convention marks it: report it, and fail it when
  the board asks.
- off-45: a segment that runs off the octilinear (0, 45, 90 degree) grid,
  wherever it is, at a pad or via too: the direction shows however the corner
  is covered. Every bend that is neither acute, square nor 135 degrees has one.
  Segments shorter than tidy.MICRO are left to "tidy", since their direction
  is noise. On a board routed at any angle every segment is off-45, so fail it
  only on an octilinear one.

Every place found is reported; only the kinds in FAIL fail.
Square-by-square reviews of three routed boards (#138) logged 8 square
corners, and this check names 7 of them in the same or a neighbouring square,
on the same net. It names both 45 degree acute corners on those boards, which
the reviews logged under other names (a hook that overshoots a pad and turns
back, an acute join in a stair-step). The reviews' "acute" findings were mostly
turns off the 45 degree grid, which is off-45 here: it names 3 of those 4.
Arcs are not bends and are not checked.

On two passes of a fourth board, not used to set any of this, it named all 10
square corners logged; none of the 5 off-grid findings, which were segments
at a via, a pad or a T-junction. off-45 was then made a property of the
segment, which names 4 of those 5.
"""

from __future__ import annotations

import math
from collections import defaultdict

SAME = 0.001        # mm: segment ends closer than this meet (as in tidy.py)
TOL = 0.5           # degrees: how far from 90 or 135 a bend may be and still count as one (as segments.py)
KINDS = ("acute", "square", "off-45")


def kind(angle: float) -> str | None:
    """The kind of a bend of this angle in degrees: "acute", "square", or None."""
    if angle < 90 - TOL:
        return "acute"
    if abs(angle - 90) <= TOL:
        return "square"
    return None


def off_grid(t) -> float | None:
    """A straight segment's direction in degrees (0 to 180) when it runs off the 45 degree grid, else None."""
    d = math.degrees(math.atan2(t.b[1] - t.a[1], t.b[0] - t.a[0])) % 180
    return d if min(d % 45, 45 - d % 45) > TOL else None


def bends(b, nets: set[str]) -> list[tuple[str, float, str, str, float, float]]:
    """(kind, angle, net, layer, x, y) for every reported bend on the named nets, and
    every off-45 segment with its direction and start."""
    from shapely.geometry import Point

    from .route import pad_shape
    from .tidy import MICRO, _Points

    key = _Points(q for t in b.tracks if t.net in nets for q in (t.a, t.b))   # one point for ends within SAME
    at = defaultdict(list)
    arcs = set()
    for t in b.tracks:
        if t.net not in nets:
            continue
        if len(t.pts) > 2:
            arcs |= {(t.net, t.layer, key(q)) for q in (t.a, t.b)}
        elif t.length >= SAME:
            at[(t.net, t.layer, key(t.a))].append((t.a, t.b))
            at[(t.net, t.layer, key(t.b))].append((t.b, t.a))
    out = []
    for t in b.tracks:
        if t.net in nets and len(t.pts) == 2 and t.length >= MICRO and (d := off_grid(t)) is not None:
            out.append(("off-45", d, t.net, t.layer, *t.a))
    for (net, layer, k), ends in at.items():
        if len(ends) != 2 or (net, layer, k) in arcs:
            continue
        (q, o1), (_q, o2) = ends
        if any(v.net == net and math.dist(q, (v.x, v.y)) < v.size / 2 for v in b.vias):
            continue
        if any(p.net == net and p.on(layer) and pad_shape(p).contains(Point(q)) for p in b.pads):
            continue
        a = abs(math.degrees(math.atan2(o1[1] - q[1], o1[0] - q[0]) - math.atan2(o2[1] - q[1], o2[0] - q[0]))) % 360
        a = min(a, 360 - a)
        if (kd := kind(a)) is not None:
            out.append((kd, a, net, layer, *q))
    return sorted(out, key=lambda f: (f[2], f[3], round(f[4], 3), round(f[5], 3)))


def bends_check(b, spec: dict) -> tuple[list[str], list[str]]:
    """(report lines, failures) for REVIEW "bends"."""
    from .review import _expand
    lines, fails = [], []
    known = {t.net for t in b.tracks} | {p.net for p in b.pads}
    for nets, fail in spec.get("bends", []):
        bad = [k for k in fail if k not in KINDS]
        if bad:
            fails.append(f"bends: unknown kind {', '.join(bad)}; the kinds are {', '.join(KINDS)}")
            continue
        names = []
        for n in _expand(b, [nets] if isinstance(nets, str) else list(nets)):
            if n in known:
                names.append(n)
            else:
                fails.append(f"bends {n}: no such net")
        found = bends(b, set(names))
        counts = {k: sum(f[0] == k for f in found) for k in KINDS}
        lines.append(f"bends {len(names)} net(s): " + ", ".join(f"{k} {n}" for k, n in counts.items())
                     + f" (failing: {', '.join(fail) or 'none'})")
        for kd, a, net, layer, x, y in found:
            where = (f"off-45 segment on {net} {layer} from ({x:.2f}, {y:.2f}), running at {a:.1f} degrees" if kd == "off-45"
                     else f"{kd} bend on {net} {layer} at ({x:.2f}, {y:.2f}), {a:.1f} degrees")
            (fails if kd in fail else lines).append(where)
    return lines, fails
