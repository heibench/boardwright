"""REVIEW "jogs": short sideways steps in a route (#138).

    "jogs": [(NETS, mm)]    NETS a net, a list of nets, or shell patterns;
                            mm the longest step that fails

Two kinds, each named with its place, the step's length and how far it moves
the route sideways:

- jog: a segment shorter than mm between two runs of the net that are
  parallel and head the same way, so the route steps aside and carries on:

      jog on +3V3 B.Cu at (58.85, 18.42): a 0.707 mm step moves the run 0.500 mm sideways

- end jog: a segment shorter than mm from the end of a run to a pad or via
  centre that the run's line misses by under END. The run should have been
  laid on the pad's line instead:

      end jog on +5VD F.Cu at (9.51, 26.80): a 0.240 mm step into a pad or via moves the run 0.170 mm sideways

Both are legal copper that a reviewer marks. Some are forced (a step between
pin rows of different pitch): set mm below them, since every jog under mm
fails.

Square-by-square reviews of five board passes (#138) logged 33 jogs. At 1.0 mm
this names 30 of them in the same or a neighbouring square, on the same net;
the end jogs also name 29 of the 35 micro-segment findings, which were mostly
steps of 0.06 to 0.3 mm into a pad. At 0.5 mm it names 17 of the 33 jogs, and
at 1.5 mm no more than at 1.0. An END of 0.5 mm names one more jog and two
more micro-segment findings, for 377 flags in all against 277.

A step at a pad or via counts as an end jog only; arcs are not checked.
"""

from __future__ import annotations

import math
from collections import defaultdict

SAME = 0.001        # mm: segment ends closer than this meet (as in tidy.py)
END = 0.2           # mm: an end jog is a run that misses its pad's or via's centre by less than this (#138)
PARALLEL = 0.9999   # cosine: runs this close to parallel, or a step this close to along a run (as tidy.py's split)


def _k(p):
    # snapped to the file's nanometres first: float noise must not split one point across a cell edge
    return (round(round(p[0], 6) / SAME), round(round(p[1], 6) / SAME))


def _unit(a, b):
    n = math.dist(a, b)
    return ((b[0] - a[0]) / n, (b[1] - a[1]) / n)


def jogs(b, nets: set[str], mm: float) -> list[tuple]:
    """(kind, net, layer, x, y, step, offset) for every jog shorter than mm on the named nets."""
    segs = [t for t in b.tracks if t.net in nets and len(t.pts) == 2 and t.length >= SAME]
    at = defaultdict(list)
    for t in segs:
        at[(t.net, t.layer, _k(t.a))].append(t)
        at[(t.net, t.layer, _k(t.b))].append(t)
    stops = {(p.net, _k((p.x, p.y))) for p in b.pads} | {(v.net, _k((v.x, v.y))) for v in b.vias}

    def run(s, q):
        """The one other segment meeting s at q, and its far end; None at a junction or an open end."""
        o = [t for t in at[(s.net, s.layer, _k(q))] if t is not s]
        if len(o) != 1:
            return None
        t = o[0]
        return t, (t.b if _k(t.a) == _k(q) else t.a)

    out = []
    for s in segs:
        if s.length >= mm:
            continue
        ra, rb = run(s, s.a), run(s, s.b)
        if ra and rb:
            ua, ub = _unit(ra[1], s.a), _unit(s.b, rb[1])      # into the step, and out of it
            us = _unit(s.a, s.b)
            if ua[0] * ub[0] + ua[1] * ub[1] >= PARALLEL and abs(us[0] * ua[0] + us[1] * ua[1]) < PARALLEL:
                off = abs((s.b[0] - s.a[0]) * ua[1] - (s.b[1] - s.a[1]) * ua[0])
                out.append(("jog", s.net, s.layer, (s.a[0] + s.b[0]) / 2, (s.a[1] + s.b[1]) / 2, s.length, off))
            continue
        for q, other, r in ((s.a, s.b, rb), (s.b, s.a, ra)):
            if r is None or (s.net, _k(q)) not in stops or (s.net, _k(other)) in stops:
                continue
            ut, us = _unit(r[1], other), _unit(other, q)
            if abs(us[0] * ut[0] + us[1] * ut[1]) >= PARALLEL:
                continue                                        # straight on into the pad: no step
            off = abs((q[0] - other[0]) * ut[1] - (q[1] - other[1]) * ut[0])
            if off < END:
                out.append(("end jog", s.net, s.layer, q[0], q[1], s.length, off))
    return sorted(out, key=lambda f: (f[1], f[2], round(f[3], 3), round(f[4], 3)))


def jogs_check(b, spec: dict) -> tuple[list[str], list[str]]:
    """(report lines, failures) for REVIEW "jogs"."""
    from .review import _expand
    lines, fails = [], []
    known = {t.net for t in b.tracks} | {p.net for p in b.pads}
    for nets, mm in spec.get("jogs", []):
        names = []
        for n in _expand(b, [nets] if isinstance(nets, str) else list(nets)):
            if n in known:
                names.append(n)
            else:
                fails.append(f"jogs {n}: no such net")
        found = jogs(b, set(names), mm)
        lines.append(f"jogs {len(names)} net(s), steps under {mm} mm: {len(found)}")
        for kind, net, layer, x, y, step, off in found:
            into = " into a pad or via" if kind == "end jog" else ""
            fails.append(f"{kind} on {net} {layer} at ({x:.2f}, {y:.2f}): a {step:.3f} mm step{into} "
                         f"moves the run {off:.3f} mm sideways")
    return lines, fails
