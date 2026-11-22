"""REVIEW "islands": pour pieces cut off from the rest of their net (#150).

    "islands": ["GND"]      nets, or shell patterns, whose pours to judge

A net poured on two or more layers is meant to be one piece of copper across
them. A fill piece is an island when no stitching via and no track joins it
to the net's copper on another layer, and it reaches the net through one pad
at most: a single point, the thermal spokes of that pad. KiCad reports such a
pad as `starved_thermal` when its spokes fall short; it does not say which
piece of pour is at fault or where a via would join it. A piece with no pad at
all is dead copper. A piece joined only through two or more pads (a two-layer
board's pours tied by connector pins, say) is not judged here.

For each island this names the layer, its bounds and area, the pad it holds,
and a spot inside it where a via of the net fits (the via's radius plus the
clearance from the piece's edge), nearest that pad, and whether the net has
fill under that spot on another layer for the via to reach. An island a via
fits in fails, and so does dead copper; a sliver too small for a via is only
reported. KiCad's DRC can pass a board with islands: it flags a pad once its
spokes fall short, and this names the piece behind it.

The case behind it: Slice_TEMP_PICO_L4L-r1, pin 28 (GND). A first via went in
the obvious gap on the other side of the pad and changed nothing; the fill
pieces showed the island to the west, and a via there cleared the error
(f4e1a07; heibench/research topics/eda-agents/field-report.md, T5).

A net poured on one layer only (a switch node, a local supply) is not judged:
it has no other layer to join. A pad within GAP of a piece is one it holds:
its thermal relief leaves that gap between pad and fill.
"""

from __future__ import annotations

GAP = 0.6           # mm: wider than KiCad's default thermal-relief gap (0.5 mm)


def islands(b, net: str, via: tuple[float, float] = (0.6, 0.3), clearance: float = 0.2) -> list[dict]:
    """The islands of net's pours, as dicts: layer, bounds, area, pads, spot,
    plane (the layer under the spot that has fill of the net, or None)."""
    from shapely import STRtree
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import nearest_points

    from .route import pad_shape
    cu = b.layers
    pieces = []
    for z in b.zones:
        if z.net != net or z.keepout:
            continue
        for ly, polys in z.fills.items():
            for poly in polys:
                if len(poly) >= 3:
                    g = Polygon(poly)
                    pieces.append((ly, g if g.is_valid else g.buffer(0)))
    # (layers, shape, kind): pieces first, by index. What anchors a piece to the
    # rest of its net is copper touching it: a stitching via (KiCad connects
    # same-net vias to a zone solid, without a relief), a track running into
    # it, or another zone's fill overlapping it, and through them other copper;
    # never a pad, since a pad's spokes are what an island feeds, not what
    # joins it.
    items = [({ly}, g, "fill") for ly, g in pieces]
    for t in b.tracks:
        if t.net == net:
            items.append(({t.layer}, LineString(t.pts).buffer(t.width / 2), "track"))
    for v in b.vias:
        if v.net == net:
            span = cu[cu.index(v.layers[0]):cu.index(v.layers[-1]) + 1] if all(ly in cu for ly in v.layers) else cu
            items.append((set(span), Point(v.x, v.y).buffer(v.size / 2), "via"))
    up = list(range(len(items)))

    def root(i):
        while up[i] != i:
            up[i] = up[up[i]]
            i = up[i]
        return i
    tree = STRtree([g for _l, g, _k in items])
    for i, (ls, g, _kind) in enumerate(items):
        for j in tree.query(g):
            j = int(j)
            jl, jg, jk = items[j]
            if j <= i or not ls & jl:
                continue
            if g.distance(jg) <= 1e-6:
                up[root(i)] = root(j)
    reach: dict[int, set] = {}
    for i, (ls, _g, kind) in enumerate(items):
        # a via joins layers, but reaches only the copper it touches: a stitch
        # via over no fill on the far side joins nothing there (#170)
        reach.setdefault(root(i), set()).update(ls if kind != "via" else ())
    pads = [p for p in b.pads if p.net == net]
    out = []
    for i, (ly, g) in enumerate(pieces):
        if len(reach[root(i)]) > 1:
            continue
        held = [p for p in pads if p.on(ly) and g.distance(pad_shape(p)) <= GAP]
        if len(held) > 1:                       # joined at two or more points: not an island
            continue
        inner = g.buffer(-(via[0] / 2 + clearance))
        spot = plane = None
        if not inner.is_empty:
            target = Point(held[0].x, held[0].y) if held else g.representative_point()
            s = nearest_points(inner, target)[0]
            spot = (round(s.x, 2), round(s.y, 2))
            plane = next((oly for oly, og in pieces if oly != ly and og.contains(s)), None)
        x0, y0, x1, y1 = g.bounds
        out.append({"layer": ly, "bounds": (round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)),
                    "area": round(g.area, 2), "pads": [f"{p.ref}.{p.num}" for p in held],
                    "spot": spot, "plane": plane})
    return out


def islands_check(b, spec: dict) -> tuple[list[str], list[str]]:
    """(report lines, failures) for REVIEW "islands"."""
    if not spec.get("islands"):
        return [], []
    from .review import _expand
    from .route import net_classes
    cls = net_classes(b)
    lines, fails = [], []
    names = spec["islands"]
    for net in _expand(b, [names] if isinstance(names, str) else list(names)):
        poured = {ly for z in b.zones if z.net == net and not z.keepout for ly, ps in z.fills.items() if ps}
        if len(poured) < 2:
            fails.append(f"islands {net}: cannot judge, {net} is not poured on two or more layers")
            continue
        rule = cls(net) or {}
        found = islands(b, net, rule.get("via", (0.6, 0.3)), rule.get("clearance", 0.2))
        lines.append(f"islands {net}: {len(found)}")
        for f in found:
            where = f"{f['layer']} {f['bounds']}, {f['area']} mm2"
            if not f["pads"]:
                if f["spot"] is None:
                    via = "no room for a via: remove it"
                else:
                    via = f"a via at {f['spot']} joins it" + (f" to {f['plane']}" if f["plane"] else ", but no other layer has its fill there")
                fails.append(f"{net} island on {where} connects to nothing: dead copper; {via}")
                continue
            if f["spot"] is None:                  # a sliver: no via fits, and too small to matter
                lines.append(f"  {net} sliver on {where} through {', '.join(f['pads'])}: no room for a via")
                continue
            via = f"a via at {f['spot']} joins it" + (f" to {f['plane']}" if f["plane"] else ", but no other layer has its fill there")
            fails.append(f"{net} island on {where} reaches the net only through {', '.join(f['pads'])}: {via}")
    return lines, fails
