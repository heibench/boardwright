"""REVIEW "via_in_pad": vias standing in, or on the edge of, an SMD pad (#177).

    "via_in_pad": ["*"]     nets, or shell patterns, whose vias to judge

An open via in a pad wicks solder down its drill and starves the joint, unless
the board orders the vias filled and capped. DRC passes it, because the via
and the pad share a net. Each via of a named net is named when its centre lies
in an SMD pad of its net on a layer it reaches, or when its copper overlaps
such a pad's edge, with how far:

    via at (75.24, 67.36) on Net-(Rg3-Pad1) stands in Rg3.1 (1.20 x 1.40 mm)
    via at (8.55, 78.83) on GNDD overlaps the edge of C1.1 by 0.07 mm

Not named, since a via there is the design: the only pad of a footprint (a
heatsink tab), an exposed pad (the largest pad of a part with three or more,
at least twice the area of the next), and the pads of a net tie. A
through-hole pad is never named.

On two square-review passes of feastorg/Slice_FPSG, this names every via the
reviews logged: 18 in 0603 and 0805 pads (all eight Rg resistors, both C37
pads) and one on C1.1's edge (0.07 mm measured to the rounded pad; the review
said 0.10). It names none of the 28 vias per pass in the heatsink, exposed and
net-tie pads, which the reviews did not log. On three passes of IOCT and STPC
it also names vias on passive pads the reviews did not log: on C1.1's edge
(both boards), in C7.2 and on R5.2's edge.
"""

from __future__ import annotations

EXPOSED = 2.0       # area ratio: the largest pad of a 3+ pad part this much bigger than the next is an exposed pad


def _by_design(b) -> set[tuple[str, str]]:
    """(ref, pad number) of pads a via in is the design: heatsink tabs, exposed pads, net ties."""
    out = set()
    for fp in b.footprints:
        pads = [p for p in fp.pads if p.type == "smd"]
        if fp.net_tie:
            out |= {(fp.reference, p.number) for p in pads}
        elif len(fp.pads) == 1:
            out |= {(fp.reference, p.number) for p in pads}
        elif len(fp.pads) >= 3:
            area = sorted(((p.size[0] * p.size[1], p.number) for p in fp.pads), reverse=True)
            if area[0][0] >= EXPOSED * area[1][0]:
                out.add((fp.reference, area[0][1]))
    return out


def found(b, nets: set[str]) -> list[tuple[str, str, float, float, str, float]]:
    """(kind, net, x, y, pad, overlap) per via of the named nets in or on an SMD
    pad: kind "in" or "edge"; overlap the depth of an edge overlap in mm."""
    from shapely.geometry import Point

    from .placement import _pad_shape
    skip = _by_design(b)
    out = []
    for v in b.vias:
        if v.net not in nets:
            continue
        c = Point(v.x, v.y)
        for p in b.pads:
            if p.thru or p.net != v.net or (p.ref, p.num) in skip:
                continue
            if not any(p.on(ly) for ly in _span(b, v)):
                continue
            sh = _pad_shape(p)
            if sh.contains(c):
                out.append(("in", v.net, v.x, v.y, f"{p.ref}.{p.num}", 0.0))
            elif (d := sh.distance(c)) < v.size / 2:
                out.append(("edge", v.net, v.x, v.y, f"{p.ref}.{p.num}", v.size / 2 - d))
    return sorted(out, key=lambda f: (f[1], f[4], round(f[2], 3), round(f[3], 3)))


def _span(b, v) -> list[str]:
    cu = b.layers
    if all(ly in cu for ly in v.layers):
        return cu[cu.index(v.layers[0]):cu.index(v.layers[-1]) + 1]
    return cu


def via_in_pad_check(b, spec: dict) -> tuple[list[str], list[str]]:
    """(report lines, failures) for REVIEW "via_in_pad"."""
    if not spec.get("via_in_pad"):
        return [], []
    from .review import _expand
    known = {v.net for v in b.vias} | {t.net for t in b.tracks} | {p.net for p in b.pads}
    names, fails = [], []
    for n in _expand(b, spec["via_in_pad"]):
        if n in known:
            names.append(n)
        else:
            fails.append(f"via_in_pad {n}: no such net")
    pads = {f"{p.ref}.{p.num}": p for p in b.pads}
    hits = found(b, set(names))
    lines = [f"via_in_pad {len(names)} net(s): {len(hits)} via(s) in or on an SMD pad"]
    for kind, net, x, y, pad, over in hits:
        if kind == "in":
            p = pads[pad]
            fails.append(f"via at ({x:.2f}, {y:.2f}) on {net} stands in {pad} ({p.w:.2f} x {p.h:.2f} mm)")
        else:
            fails.append(f"via at ({x:.2f}, {y:.2f}) on {net} overlaps the edge of {pad} by {over:.2f} mm")
    return lines, fails
