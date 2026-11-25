"""REVIEW "margin": copper that clears another net by little more than the rule (#176).

    "margin": [(NETS, mm)]      NETS a net, a list of nets, or shell patterns

KiCad's DRC fails a gap under the clearance rule and passes everything else, so
a track 0.141 mm from another net under a 0.14 mm rule passes it. For each
named net, this measures the edge-to-edge gap from its tracks and vias to every
other net's pads, tracks and vias on a shared copper layer, along the whole
route, and fails each pair of nets that comes within the rule plus mm:

    /OUT4 within 0.141 mm of /OUT5 (rule 0.14) on F.Cu near (65.13, 26.84), 12.46 mm of track that close

The rule for a pair is the larger of the two nets' net-class clearances, as
KiCad takes it. Each pair is reported once, at its smallest gap, with the
length of track that runs within the rule plus mm of the other net (the
longer of the two nets' lengths, so two parallel tracks count once). When the
other copper is a pad and the track crosses the line between that pad and a
neighbouring pad of the same part, the place is named as a squeeze between
them.

Pads are measured with their real shape (rounded corners included), as KiCad's
DRC measures them; a gap measured by hand to a square corner can read low.
Not measured: pad to pad (the footprints fix those gaps), pour fills (a fill
keeps its zone's clearance by construction), the board edge, and custom
.kicad_dru rules.

Square-by-square reviews of five board passes (#138, #176) logged 16 places
where copper was legal but tight, and 19 tracks squeezed between pads. At
0.05 mm this names 12 of the 16 and 14 of the 19 in the same or a neighbouring
square, on the same net. At 0.1 mm it names all 16, but on the cleanest pass
it names 64 pairs where 0.05 mm names 7. Of the 4 clearance findings it misses
at 0.05 mm:
- two sit 0.05 and 0.06 mm over the rule;
- one is a track between two vias at 0.575 and 0.765 mm;
- one was measured by hand to a square pad corner: the real gap to the
  rounded pad is 0.246 mm, not 0.143.
"""

from __future__ import annotations

import math

NEIGHBOUR = 2.6     # mm: pads of one part this close, centre to centre, are neighbours (a 2.54 mm header pitch)


def _between(track, net, pad, pads) -> object | None:
    """The neighbouring pad of pad's part, on neither net nor the track's, whose
    centre line the track crosses, if any. A track leaving its own pad is not squeezed."""
    from shapely.geometry import LineString, Point
    for o in pads:
        if o is pad or o.ref != pad.ref or o.net == net or math.dist((o.x, o.y), (pad.x, pad.y)) > NEIGHBOUR:
            continue
        line = LineString([(pad.x, pad.y), (o.x, o.y)])
        if any(q is not pad and q is not o and q.ref == pad.ref and line.distance(Point(q.x, q.y)) < min(q.w, q.h) / 2
               for q in pads):
            continue                                    # another pad of the part sits between them
        if track.intersects(line):
            return o
    return None


def tight(b, nets: set[str], margin: float) -> list[tuple]:
    """(gap, rule, net, other, layer, x, y, run, squeeze) per pair of nets, one
    of them named, whose copper comes within rule + margin; squeeze is
    "REF.a/REF.b" or "". Sorted by gap."""
    from shapely import STRtree
    from shapely.geometry import LineString, Point

    from .placement import _copper_layers, _pad_shape
    from .route import net_classes

    cls = net_classes(b)
    gap = lambda n: (cls(n) or {}).get("clearance", 0.2)  # noqa: E731
    cu = b.layers
    items = []                                          # (pad or None, net, layers, shape, centreline, width)
    for p in b.pads:
        if p.net:
            items.append((p, p.net, _copper_layers(p.layers, cu), _pad_shape(p), None, 0.0))
    for t in b.tracks:
        items.append((None, t.net, {t.layer}, LineString(t.pts).buffer(t.width / 2), LineString(t.pts), t.width))
    for v in b.vias:
        items.append((None, v.net, set(cu), Point(v.x, v.y).buffer(v.size / 2), None, 0.0))
    tree = STRtree([it[3] for it in items])
    reach = max([gap(it[1]) for it in items] + [0.2]) + margin
    best = {}
    for pad, net, ly, sh, line, w in items:
        if pad is not None or not net:
            continue
        for j in tree.query(sh.buffer(reach)):
            pad2, net2, ly2, sh2, _l, _w = items[j]
            shared = ly & ly2
            if not net2 or net2 == net or not shared or (net not in nets and net2 not in nets):
                continue
            rule = max(gap(net), gap(net2))
            d = sh.distance(sh2)
            if d >= rule + margin:
                continue
            run = line.intersection(sh2.buffer(rule + margin + w / 2)).length if line is not None else 0.0
            key = tuple(sorted((net, net2)))
            cur = best.get(key)
            if cur is None or d < cur[0]:
                near = sh2.boundary.interpolate(sh2.boundary.project(sh.centroid))
                sq = ""
                if pad2 is not None and line is not None and (o := _between(line, net, pad2, b.pads)) is not None:
                    sq = f"{pad2.ref}.{pad2.num}/{o.num}"
                best[key] = [d, rule, net, net2, sorted(shared)[0], near.x, near.y, cur[7] if cur else {}, sq]
            best[key][7][net] = best[key][7].get(net, 0.0) + run
    out = [(*v[:7], max(v[7].values()), v[8]) for v in best.values()]
    return sorted(out, key=lambda v: (v[0], v[2], v[3]))


def margin_check(b, spec: dict) -> tuple[list[str], list[str]]:
    """(report lines, failures) for REVIEW "margin"."""
    from .review import _expand
    lines, fails = [], []
    known = {t.net for t in b.tracks} | {p.net for p in b.pads}
    for nets, mm in spec.get("margin", []):
        names = []
        for n in _expand(b, [nets] if isinstance(nets, str) else list(nets)):
            if n in known:
                names.append(n)
            else:
                fails.append(f"margin {n}: no such net")
        found = tight(b, set(names), mm)
        lines.append(f"margin {len(names)} net(s), rule + {mm} mm: {len(found)} pair(s) closer")
        for d, rule, net, other, layer, x, y, run, sq in found:
            x, y = (0.0 if abs(v) < 0.005 else v for v in (x, y))      # no "-0.00"
            fails.append(f"{net} within {d:.3f} mm of {other} (rule {rule}) on {layer} near ({x:.2f}, {y:.2f}), "
                         f"{run:.2f} mm of track that close" + (f", squeezed between {sq}" if sq else ""))
    return lines, fails
