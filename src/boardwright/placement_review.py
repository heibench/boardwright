"""The REVIEW checks that read only pads and courtyards, so `place` runs them
before routing as well as `verify` after (#47):

    near      (A, B, mm)               pad A within mm of pad B
    orient    (CAP, PIN)               CAP's pad on PIN's net is nearer PIN than every ground pad of CAP
    balance   (PART, PIN_A, PIN_B, mm) PART's gaps to the two pins differ by at most mm
    fronts    (IC, mm)                 each signal pin has a clear channel, straight out or at 45 degrees
    via_site  (PAD, mm)                a legal spot for a via of PAD's net within mm of it
    chain     (FROM, [REF ...], TO[, mm])  each shunt's node pad on the series path, or its stub at most mm

fronts and via_site look at pads and courtyards only, never tracks or vias:
they ask whether placement leaves room, so a routed board gets the same
answer `place` gave before routing.

A check that cannot judge (a capacitor with no ground pad, an IC with no
signal pin, a chain with no shunt) fails and says so: passing then would be a
check that ran on nothing. Widths, clearances and via sizes come from the
project's net classes (route.net_classes), the defaults where there is none.
"""

from __future__ import annotations

import math

from .model import Board

KEYS = ("near", "orient", "balance", "fronts", "via_site", "chain", "crossings")
SHUNT_PREFIXES = ("C", "L", "R", "FB")       # reference prefixes a chain's shunts may have


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _pads(b: Board, ref: str) -> list:
    return [p for p in b.pads if p.ref == ref]


def placement_review(b: Board, spec: dict, project=None) -> tuple[list[str], list[str]]:
    """(report lines, failures) for the placement keys in REVIEW."""
    if not any(spec.get(k) for k in KEYS):
        return [], []
    from .placement import Clearance, _pad_shape
    from .route import net_classes
    ground = spec.get("ground", ["GND"])
    cls = net_classes(b, project)
    rule = lambda net: cls(net) or {"width": 0.2, "clearance": 0.2, "via": (0.6, 0.3)}  # noqa: E731
    lines, fails = [], []

    for a, c, lim in spec.get("near", []):
        d = _dist(b.pad(a), b.pad(c))
        lines.append(f"near {a} {c}: {d:.2f} mm (<= {lim})")
        if d > lim:
            fails.append(f"{a} is {d:.2f} mm from {c}, limit {lim}")

    for cap, pin in spec.get("orient", []):
        p = b.pad(pin)
        pads = _pads(b, cap)
        sup = [q for q in pads if q.net == p.net]
        gnd = [q for q in pads if q.net in ground]
        if not sup or not gnd:
            what = f"no pad on {p.net}" if not sup else f"no pad on {'/'.join(ground)}"
            fails.append(f"orient {cap} {pin}: cannot judge, {cap} has {what}")
            continue
        ds, dg = min(_dist(q, p) for q in sup), min(_dist(q, p) for q in gnd)
        lines.append(f"orient {cap} -> {pin}: {p.net} pad {ds:.2f} mm, ground pad {dg:.2f} mm")
        if dg <= ds:
            fails.append(f"{cap} is turned round: its ground pad is {dg:.2f} mm from {pin}, its {p.net} pad {ds:.2f} mm")

    for part, pa_name, pc_name, tol in spec.get("balance", []):
        pa, pc = b.pad(pa_name), b.pad(pc_name)
        qa = [q for q in _pads(b, part) if q.net == pa.net]
        qc = [q for q in _pads(b, part) if q.net == pc.net]
        if not qa or not qc:
            fails.append(f"balance {part}: cannot judge, {part} has no pad on {pa.net if not qa else pc.net}")
            continue
        ga = min(_pad_shape(q).distance(_pad_shape(pa)) for q in qa)
        gc = min(_pad_shape(q).distance(_pad_shape(pc)) for q in qc)
        lines.append(f"balance {part}: {ga:.2f} mm to {pa_name}, {gc:.2f} mm to {pc_name} (differ <= {tol})")
        if abs(ga - gc) > tol:
            fails.append(f"{part}'s gaps to {pa_name} and {pc_name} differ by {abs(ga - gc):.2f} mm, limit {tol}")

    if spec.get("fronts") or spec.get("via_site"):
        cl = Clearance(b, project)

    for ic, length in spec.get("fronts", []):
        fails += _fronts(b, cl, ic, length, ground, rule, lines)

    for name, radius in spec.get("via_site", []):
        fails += _via_site(b, cl, name, radius, rule, lines)

    for entry in spec.get("chain", []):
        fails += _chain(b, entry, ground, rule, lines)

    if spec.get("crossings"):
        fails += _crossings(b, spec["crossings"], ground, lines)
    return lines, fails


def _crossings(b, entries, ground, lines) -> list[str]:
    """REVIEW "crossings": [(NETS, limit)]. Airwire crossings that involve one
    of the named nets, each net's pads joined by a minimum spanning tree with
    copper ignored, poured and ground nets left out (#149). A part turned so its
    nets loop round it, or a group placed out of the order both its ends share,
    shows here before any routing."""
    from .preview import crossings
    from .review import _expand
    skip = {z.net for z in b.zones if not z.keepout} | set(ground)
    found = crossings(b, skip)
    count = {}
    for p in b.pads:
        count[p.net] = count.get(p.net, 0) + 1
    fails = []
    for nets, limit in entries:
        names = _expand(b, [nets] if isinstance(nets, str) else list(nets))
        label = "/".join(names) if len(names) <= 4 else f"{len(names)} nets"
        if not names or not any(count.get(n, 0) >= 2 and n not in skip for n in names):
            fails.append(f"crossings {nets}: cannot judge, no named net with two or more pads outside the pours")
            continue
        mine = [f for f in found if f[0] in names or f[1] in names]
        lines.append(f"crossings {label}: {len(mine)} (<= {limit})")
        if len(mine) > limit:
            shown = ", ".join(f"{x} x {y} at ({px:.1f}, {py:.1f})" for x, y, (px, py) in mine[:5])
            fails.append(f"{label}: {len(mine)} airwire crossings, limit {limit}: {shown}"
                         + (", ..." if len(mine) > 5 else ""))
    return fails


def _fronts(b, cl, ic, length, ground, rule, lines) -> list[str]:
    """Each signal pin of IC has a channel track + 2 x clearance wide (the track
    no wider than the pin), from its
    outer end straight out or at 45 degrees, for `length` mm, clear of other
    nets' pads and of the courtyards of parts that do not connect to it: a
    decoupler or series resistor on the pin's own net belongs in front of it."""
    from shapely import affinity
    from shapely.geometry import LineString

    from .placement import _pad_shape
    fp = next((f for f in b.footprints if f.reference == ic), None)
    pins = [p for p in _pads(b, ic) if p.net and p.net not in ground]
    if fp is None or not pins:
        return [f"fronts {ic}: cannot judge, {ic} has no signal pin" if fp else f"fronts {ic}: no part {ic}"]
    cx, cy = fp.position
    side = cl.fps[ic][0]
    yards = [(r, y) for r, (s, _p, _r, y) in cl.fps.items() if r != ic and s == side and y is not None]
    nets_of = {}
    for q in b.pads:
        nets_of.setdefault(q.ref, set()).add(q.net)
    blocked = []
    for p in pins:
        dx, dy = p.x - cx, p.y - cy
        ux, uy = (math.copysign(1, dx), 0.0) if abs(dx) >= abs(dy) else (0.0, math.copysign(1, dy))
        shape = _pad_shape(p)
        ray = LineString([(p.x, p.y), (p.x + ux * 50, p.y + uy * 50)]).intersection(shape)
        sx, sy = max(ray.coords, key=lambda q: (q[0] - p.x) * ux + (q[1] - p.y) * uy) if not ray.is_empty else (p.x, p.y)
        r = rule(p.net)
        # a track leaves a pin no wider than the pin: a 0.3 mm power class necks down at a 0.3 mm QFP pin
        half = min(r["width"], p.w, p.h) / 2 + r["clearance"]
        free = False
        for turn in (0, 45, -45):
            end = affinity.rotate(LineString([(sx, sy), (sx + ux * length, sy + uy * length)]), turn, origin=(sx, sy))
            lane = end.buffer(half, cap_style=2)
            hit = [i for i in cl.tree.query(lane)
                   if cl.items[i][0] is not None and cl.items[i][1] != p.net and (cl.items[i][2] & set(p.layers))
                   and lane.intersection(cl.items[i][3]).area > 1e-6]
            # a part on the pin's own net belongs in front of it (a decoupler, a series resistor)
            if not hit and not any(p.net not in nets_of.get(r, ()) and lane.intersection(y).area > 1e-6 for r, y in yards):
                free = True
                break
        if not free:
            blocked.append(p)
    lines.append(f"fronts {ic}: {len(pins) - len(blocked)} of {len(pins)} signal pins have a clear {length} mm channel")
    return [f"{ic}.{p.num} ({p.net}) has no clear channel out, straight or at 45 degrees, for {length} mm" for p in blocked]


def _via_site(b, cl, name, radius, rule, lines) -> list[str]:
    """A spot within `radius` of PAD where a via of its net clears every other
    net's pads and the board edge, without sitting on the pad itself."""
    from shapely.geometry import Point

    from .placement import _pad_shape
    p = b.pad(name)
    if not p.net:
        return [f"via_site {name}: cannot judge, {name} has no net"]
    via = rule(p.net)["via"][0]
    own = _pad_shape(p)
    step, best = 0.05, None
    n = int(radius / step)
    spots = sorted(((i * step, j * step) for i in range(-n, n + 1) for j in range(-n, n + 1)
                    if math.hypot(i * step, j * step) <= radius), key=lambda q: math.hypot(*q))
    for dx, dy in spots:
        v = Point(p.x + dx, p.y + dy).buffer(via / 2)
        if v.intersection(own).area > 1e-6:
            continue
        if cl.inside is not None and not cl.inside.contains(v):
            continue
        ok = True
        for i in cl.tree.query(v.buffer(cl.reach)):
            ref, onet, _ly, os = cl.items[i]
            if ref is not None and onet != p.net and v.distance(os) < max(cl.gap(p.net), cl.gap(onet)) - 1e-6:
                ok = False
                break
        if ok:
            best = math.hypot(dx, dy)
            break
    lines.append(f"via_site {name} ({p.net}): " + (f"a {via:g} mm via fits {best:.2f} mm away" if best is not None
                                                     else f"none within {radius} mm"))
    return [] if best is not None else [f"{name} ({p.net}) has no legal spot for a {via:g} mm via within {radius} mm"]


def _chain(b, entry, ground, rule, lines) -> list[str]:
    """The series path FROM -> each REF's two pads -> TO, and every shunt (a part
    off the path with one pad on a node of it and one on ground): its node pad
    sits on the path, or the stub to it is at most `mm` (default 0). A shunt is a
    two-pad passive (SHUNT_PREFIXES): a two-pin header with a supply and a
    ground pin is not one."""
    from shapely.geometry import LineString

    from .placement import _pad_shape
    start, series, stop = entry[0], entry[1], entry[2]
    limit = entry[3] if len(entry) > 3 else 0.0
    head = b.pad(start)
    node, pts, nodes = head.net, [(head.x, head.y)], {head.net}
    for ref in series:
        pads = _pads(b, ref)
        inn = [q for q in pads if q.net == node]
        out = [q for q in pads if q.net != node]
        if not inn or not out:
            return [f"chain {start} -> {stop}: cannot judge, {ref} has no pad on {node}" if not inn
                    else f"chain {start} -> {stop}: cannot judge, {ref} has no second net"]
        pts += [(inn[0].x, inn[0].y), (out[0].x, out[0].y)]
        node = out[0].net
        nodes.add(node)
    tail = b.pad(stop)
    if tail.net != node:
        return [f"chain {start} -> {stop}: cannot judge, {stop} is on {tail.net}, not {node}"]
    pts.append((tail.x, tail.y))
    path = LineString(pts)
    taken = set(series) | {head.ref, tail.ref}
    shunts = []
    for ref in sorted({p.ref for p in b.pads} - taken):
        pads = _pads(b, ref)
        on = [q for q in pads if q.net in nodes]
        if len(pads) == 2 and ref.rstrip("0123456789") in SHUNT_PREFIXES and on and any(q.net in ground for q in pads):
            shunts.append((ref, on[0]))
    if not shunts:
        return [f"chain {start} -> {stop}: cannot judge, no shunt to ground on its nodes ({', '.join(sorted(nodes))})"]
    fails = []
    for ref, pad in shunts:
        stub = _pad_shape(pad).distance(path)
        lines.append(f"chain {start} -> {stop}: shunt {ref} on {pad.net} " +
                     ("inline" if stub <= 1e-6 else f"off the path by a {stub:.2f} mm stub") + f" (<= {limit})")
        if stub > limit + 1e-6:
            fails.append(f"shunt {ref}'s {pad.net} pad is {stub:.2f} mm off the {start} -> {stop} path, limit {limit}")
    return fails
