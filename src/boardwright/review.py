"""Engineering review beyond DRC: things KiCad calls legal but an engineer would not.

Works on any board file, generated here or drawn by hand, after KiCad has
filled the zones (the DRC step with --refill-zones --save-board does that).
A board's board.py may declare

    REVIEW = {
        "near":     [("C1.1", "U1.3", 4.0)],            # pad-to-pad centre distance <= mm
        "maxlen":   {"FB": 10},                          # all copper on a net <= mm
        "maxpath":  [("U1.5", "Y1.1", 8.0)],             # routed pad-to-pad length <= mm
        "match":    [([("J1.A6", "U1.33"), ("J1.A7", "U1.32")], 2.0)],   # paths equal within mm
        "skew":     [("USB_DP", "USB_DM", 2.0)],         # crude: total copper of two nets
        "coverage": {"B.Cu": 0.7},                       # whole-board pour fills >= this share
        "ref":      [(["USB_DP", "USB_DM"], 1.0)],       # mm of these nets allowed off a ground reference
        "ground":   ["GND"],                             # nets that count as reference (default GND)
        "via_gnd":  2.0,                                 # a "ref" net's via needs a ground via within mm
        "current":  [("L1.2", "J2.1", 2.0)],             # this path carries amps: one pour piece, or tracks wide enough
        "temp_rise": 10,                                 # deg C allowed for "current" (default 10)
        "via_near": [("C3.2", 1.5)],                     # this pad needs a via of its own net within mm
        "loop":     [("C3", "U1.24", 1.5)],              # decoupler C3 for U1.24: see loop_check
        "apart":    [("FB", ["SW"], 1.2)],               # quiet net(s) this far from noisy net(s): see apart_check
        "clear_under": [("Y1", 0.5)],                    # no other net's track or via under a part: see apart_check
        "segments": [(["/ESTOP", "/INT"], 0)],           # segments beyond the fewest the route needs: see segments.py
        "islands":  ["GND"],                             # pour pieces cut off from the net: see islands.py
        "tidy":     ["*"],                               # track debris: micro segments, splits, stray ends: see tidy.py
        "bends":    [("*", ["acute"])],                  # bends under 90 (or at 90, or off 45) fail: see bends.py
    }

Always checked for polygons declared in ZONES: each fills as ONE piece and no
foreign net is routed through it.
"""

from __future__ import annotations

import math
from pathlib import Path

from .model import Board, inside


def crossings(b: Board, m) -> list[str]:
    """Foreign-net tracks that run inside a declared ZONES polygon on its layer."""
    out = []
    for z in getattr(m, "ZONES", []):
        net, layer, poly = z[0], z[1], z[2]
        hits: dict[str, tuple[float, float]] = {}
        for t in b.tracks:
            if t.layer != layer or t.net == net:
                continue
            for (x1, y1), (x2, y2) in zip(t.pts, t.pts[1:]):
                for i in range(11):
                    x, y = x1 + (x2 - x1) * i / 10, y1 + (y2 - y1) * i / 10
                    if inside(x, y, poly):
                        hits.setdefault(t.net, (round(x, 1), round(y, 1)))
                        break
        for other, at in hits.items():
            out.append(f"net {other} is routed through the {net} polygon on {layer} near {at}")
    return out


def reference_layer(b: Board, layer: str) -> str | None:
    """The copper layer a trace on `layer` refers to: its neighbour toward the middle."""
    ls = b.layers
    if layer not in ls or len(ls) < 2:
        return None
    i = ls.index(layer)
    return ls[i + 1] if i < len(ls) / 2 else ls[i - 1]


def off_reference(b: Board, nets, ground, step=0.25) -> dict[str, tuple[float, tuple[float, float] | None]]:
    """Per net: mm of track with no ground copper on the reference layer, and where it starts."""
    gz = [z for z in b.zones if z.net in ground and not z.keepout]
    out = {}
    for net in nets:
        bad, first = 0.0, None
        # a plane is always cleared round the net's own vias and through-hole pads:
        # that gap is unavoidable, so samples within 1 mm of one are not counted
        own = [(v.x, v.y) for v in b.vias if v.net == net] + [(p.x, p.y) for p in b.pads if p.net == net and p.thru]
        for t in b.tracks:
            if t.net != net:
                continue
            rl = reference_layer(b, t.layer)
            for (x1, y1), (x2, y2) in zip(t.pts, t.pts[1:]):
                L = math.hypot(x2 - x1, y2 - y1)
                n = max(1, int(L / step))
                for i in range(n):
                    x, y = x1 + (x2 - x1) * (i + .5) / n, y1 + (y2 - y1) * (i + .5) / n
                    if any(math.hypot(x - ax, y - ay) < 1.0 for ax, ay in own):
                        continue
                    if not any(z.covers(rl, x, y) for z in gz):
                        bad += L / n
                        first = first or (round(x, 1), round(y, 1))
        out[net] = (bad, first)
    return out


def width_for_current(amps: float, rise: float = 10.0, oz: float = 1.0, inner: bool = False) -> float:
    """IPC-2221 trace width in mm for a current, temperature rise and copper weight.

    I = k * dT^0.44 * A^0.725 with A in square mils, k = 0.048 outer, 0.024 inner.
    Conservative by design, and a chart fit, not physics: it ignores planes
    and neighbouring copper, which carry heat away."""
    k = 0.024 if inner else 0.048
    area = (amps / (k * rise ** 0.44)) ** (1 / 0.725)
    return area / (1.378 * oz) * 0.0254


def via_current(drill: float, rise: float = 10.0, plating: float = 0.025) -> float:
    """Amps one plated via carries by the same formula, its barrel taken as a
    trace as wide as the hole's circumference and as thick as the plating (mm)."""
    area = (math.pi * drill / 0.0254) * (plating / 0.0254)
    return 0.048 * rise ** 0.44 * area ** 0.725


def neck(poly, pa, pc, cap: float = 10.0) -> float:
    """Narrowest channel (mm) current must pass through to get from pad pa to pad
    pc inside one filled piece of copper: the widest w for which the piece, shrunk
    by w/2 on every edge, still joins the two pads. Parallel channels are not added
    together, so a pour fed through two thin spokes measures as one spoke: this
    errs on the safe side. The pads' own size is not counted."""
    from shapely.geometry import Polygon

    from .route import pad_shape

    piece = Polygon(poly).buffer(0)
    sa, sc = pad_shape(pa), pad_shape(pc)

    def joined(w: float) -> bool:
        shrunk = piece.buffer(-w / 2)
        if shrunk.is_empty:
            return False
        for part in getattr(shrunk, "geoms", [shrunk]):
            if part.distance(sa) <= w / 2 + 1e-6 and part.distance(sc) <= w / 2 + 1e-6:
                return True
        return False

    if joined(cap):
        return cap
    lo, hi = 0.0, cap
    for _ in range(24):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if joined(mid) else (lo, mid)
    return lo


def current_check(b: Board, spec: dict) -> tuple[list[str], list[str]]:
    """(report lines, failures) for REVIEW["current"]: a list of (pad a, pad b, amps).

    A path carries its current if both pads sit in one filled piece of a pour of
    their net that nowhere narrows below the IPC-2221 width (see `neck`), or if
    tracks at least as wide join them (vias counted against their own capacity). Current is a property of a path, not
    of a net: a sense line on a power net carries none of it."""
    rise = spec.get("temp_rise", 10)
    lines, fails = [], []
    for a, c, amps in spec.get("current", []):
        pa, pc = b.pad(a), b.pad(c)
        net = pa.net
        need = {l: width_for_current(amps, rise, inner=l not in ("F.Cu", "B.Cu")) for l in b.layers}
        how, necked = None, []
        for z in b.zones:
            if z.net != net or z.keepout:
                continue
            for layer, polys in z.fills.items():
                if how or not (pa.on(layer) and pc.on(layer)):
                    continue
                for poly in polys:
                    if inside(pa.x, pa.y, poly) and inside(pc.x, pc.y, poly):
                        cap = max(2 * need[layer], 1.0)
                        w = neck(poly, pa, pc, cap=cap)
                        if w + 1e-3 >= need[layer]:
                            at = "at least " if w >= cap else ""
                            how = f"one piece of the {net} pour on {layer}, narrowest {at}{w:.2f} mm"
                        else:
                            necked.append(f"{layer} pour narrows to {w:.2f} mm")
        if how is None:
            wide = Board.__new__(Board)                 # the same board, keeping only tracks wide enough
            wide.__dict__.update(b.__dict__)
            wide.__dict__["tracks"] = [t for t in b.tracks if t.net != net or t.width >= need[t.layer] - 1e-6]
            r = wide.route_path(a, c)
            if r:
                per_via = min((via_current(v.drill, rise) for v in b.vias if v.net == net), default=0.0)
                if r[1] and per_via < amps:
                    fails.append(f"{a} -> {c} carries {amps} A through {r[1]} via(s) in series, each good for about {per_via:.1f} A")
                how = f"tracks >= {need['F.Cu']:.2f} mm, {r[0]:.1f} mm long, {r[1]} via(s)"
        lines.append(f"current {a} -> {c}: {amps} A at {rise} C rise needs {need['F.Cu']:.2f} mm outer: " + (how or "NOT carried"))
        if how is None:
            thin = b.route_path(a, c)
            fails.append(f"{a} -> {c} must carry {amps} A: no shared {net} pour and no track path at least {need['F.Cu']:.2f} mm wide"
                         + (f" ({'; '.join(necked)})" if necked else "")
                         + (f" (a {thin[0]:.1f} mm path exists but is narrower)" if thin else " (no track path at all)"))
    return lines, fails


def _paths(g: dict, src) -> tuple[dict, dict]:
    """Shortest copper distance from src to every node, vias crossed, and each node's predecessor."""
    import heapq
    best, prev, heap, n = {src: 0.0}, {}, [(0.0, 0, src)], 0
    while heap:
        d, _n, u = heapq.heappop(heap)
        if d > best[u]:
            continue
        for v, w, _kind in g.get(u, []):
            if d + w < best.get(v, 1e18):
                best[v], prev[v] = d + w, u
                n += 1
                heapq.heappush(heap, (d + w, n, v))
    return best, prev


def _on_plane(b: Board, net: str, u) -> bool:
    """Whether graph node u is a via of net standing in a fill of the net's pour."""
    vias = [v for v in b.vias if v.net == net and (round(v.x, 2), round(v.y, 2)) == u[:2]]
    return any(z.net == net and not z.keepout and z.covers(ly, v.x, v.y) for v in vias for z in b.zones for ly in z.fills)


def _to_via(b: Board, p, lim: float) -> tuple[float, int]:
    """(copper distance from pad p to its nearest own-net via, vias within lim):
    along its tracks, or across the pour fill the pad sits in."""
    g = b.net_graph(p.net)
    node = ("pad", p.ref, p.num)
    at = {(round(v.x, 2), round(v.y, 2)) for v in b.vias if v.net == p.net}
    dist = {}
    for u, d in (_paths(g, node)[0] if node in g else {}).items():
        if u[0] != "pad" and u[:2] in at:
            dist[u[:2]] = min(d, dist.get(u[:2], 1e18))
    layer = next((ly for ly in b.layers if p.on(ly)), None)
    for z in b.zones:
        if z.net != p.net or z.keepout:
            continue
        for poly in z.fills.get(layer, []):
            if inside(p.x, p.y, poly):
                for v in b.vias:
                    if v.net == p.net and inside(v.x, v.y, poly):
                        key = (round(v.x, 2), round(v.y, 2))
                        dist[key] = min(math.hypot(v.x - p.x, v.y - p.y), dist.get(key, 1e18))
    return min(dist.values(), default=1e18), sum(d <= lim for d in dist.values())


def loop_check(b: Board, spec: dict) -> tuple[list[str], list[str]]:
    """REVIEW "loop": [(CAP, PIN, mm)], a decoupler and the IC pin it serves (#122).

    TI SPRABV2 ranks the capacitor's trace length above its distance from the
    pin, and says not to feed the pin through the plane before the capacitor:
    - each of CAP's ground pads, and its pad on PIN's net when that net has a
      pour, reaches a via of its own net within mm of copper: its tracks, or
      the pour fill it sits in
    - when PIN's net has a pour, PIN reaches CAP by tracks and vias, and no
      via standing in that pour, other than those on the way to CAP, is
      nearer PIN along copper than CAP is. A via the pin shares with a cap on
      the back is on the way, and allowed.
    A cap with no pad on PIN's net or no ground pad cannot be judged, and fails."""
    lines, fails = [], []
    ground = spec.get("ground", ["GND"])
    planes = {z.net for z in b.zones if not z.keepout}
    for cap, pin, lim in spec.get("loop", []):
        pp = b.pad(pin)
        pads = [p for p in b.pads if p.ref == cap]
        feed = [p for p in pads if p.net == pp.net]
        gnd = [p for p in pads if p.net in ground]
        if not feed or not gnd:
            fails.append(f"loop {cap} -> {pin}: cannot judge, {cap} has no "
                         + ("pad on " + pp.net if not feed else "/".join(ground) + " pad"))
            continue
        for p in gnd + [f for f in feed if f.net in planes]:
            d, n = _to_via(b, p, lim)
            lines.append(f"loop {cap}.{p.num} ({p.net}): " + ("no via" if d > 1e17 else f"{d:.2f} mm to a via, {n} within")
                         + f" (<= {lim})")
            if d > lim:
                fails.append(f"{cap}.{p.num} ({p.net}) " + (f"has no {p.net} via on its copper" if d > 1e17 else
                             f"is {d:.2f} mm of copper from its nearest {p.net} via") + f", limit {lim}")
        if pp.net not in planes:
            lines.append(f"loop {pin} -> {cap}: {pp.net} has no pour, no plane to feed through")
            continue
        g = b.net_graph(pp.net)
        src = ("pad", pp.ref, pp.num)
        dist, prev = _paths(g, src) if src in g else ({}, {})
        caps = [("pad", cap, f.num) for f in feed if ("pad", cap, f.num) in dist]
        if not caps:
            fails.append(f"{pin} reaches {cap} only through the {pp.net} pour: the pin is fed through the plane, "
                         "not the capacitor")
            continue
        end = min(caps, key=dist.get)
        on_path, u = set(), end
        while u in prev:
            on_path.add(u[:2])
            u = prev[u]
        fed = [(dist[u], u) for u in dist if u[0] != "pad" and u[:2] not in on_path and _on_plane(b, pp.net, u)]
        if fed and min(fed)[0] < dist[end]:
            d, u = min(fed)
            fails.append(f"{pin} reaches a {pp.net} plane via at ({u[0]:.2f}, {u[1]:.2f}) {d:.2f} mm out, before "
                         f"{cap} at {dist[end]:.2f} mm: the pin is fed through the plane, not the capacitor")
        else:
            lines.append(f"loop {pin} -> {cap}: {dist[end]:.2f} mm, no plane via off that path nearer")
    return lines, fails


def apart_check(b: Board, spec: dict) -> tuple[list[str], list[str]]:
    """REVIEW "apart" and "clear_under" (#125): keeping quiet copper from noise.

    "apart": [(QUIET, NOISY, mm)], QUIET a net or a list of nets, NOISY likewise.
    The copper of the quiet nets (pads, tracks, vias) keeps mm from the copper
    of the noisy nets (pads, tracks, vias and pour fills), edge to edge, on the
    same layer and on each adjacent one (TI SNVA021: feedback away from the
    inductor and the switch node). Two pads of one part are left out: the
    pinout fixes that gap, not the layout.

    "clear_under": [(REF, mm)]. No track or via of a net other than REF's own
    and the ground nets crosses REF's courtyard grown by mm, on any layer
    (Microchip, TI SZZA009, Espressif: no traces under the crystal). Pours
    are not counted: a ground pour under a crystal is the usual advice.

    A quiet or noisy side with no copper, and a part with no courtyard, cannot
    be judged, and fail."""
    if not (spec.get("apart") or spec.get("clear_under")):
        return [], []
    from shapely.geometry import Polygon

    from .placement import Clearance
    cl = Clearance(b)
    lines, fails = [], []
    names = lambda v: [v] if isinstance(v, str) else list(v)  # noqa: E731
    for quiet, noisy, lim in spec.get("apart", []):
        q, n = set(names(quiet)), set(names(noisy))
        qs = [it for it in cl.items if it[1] in q]
        ns = [it for it in cl.items if it[1] in n]
        ns += [(None, z.net, {ly}, Polygon(poly)) for z in b.zones if z.net in n and not z.keepout
               for ly, polys in z.fills.items() for poly in polys if len(poly) >= 3]
        label = f"apart {'/'.join(sorted(q))} | {'/'.join(sorted(n))}"
        if not qs or not ns:
            fails.append(f"{label}: cannot judge, no copper on " + ("/".join(sorted(q)) if not qs else "/".join(sorted(n))))
            continue
        best = None
        for qr, qn, ql, qsh in qs:
            for nr, nn, nl, nsh in ns:
                if qr is not None and qr == nr:
                    continue
                pairs = [(a, c) for a in ql for c in nl if a in b.layers and c in b.layers
                         and abs(b.layers.index(a) - b.layers.index(c)) <= 1]
                if not pairs:
                    continue
                d = qsh.distance(nsh)
                if best is None or d < best[0]:
                    best = (d, qn, nn, pairs[0], qsh.representative_point())
        if best is None:
            lines.append(f"{label}: no copper on the same or an adjacent layer")
            continue
        d, qn, nn, (la, lc), at = best
        where = la if la == lc else f"{la}/{lc}"
        lines.append(f"{label}: {d:.2f} mm ({qn} to {nn}, {where}) (>= {lim})")
        if d < lim:
            fails.append(f"{qn} comes within {d:.2f} mm of {nn} on {where}, near ({at.x:.1f}, {at.y:.1f}), limit {lim}")
    ground = set(spec.get("ground", ["GND"]))
    for ref, margin in spec.get("clear_under", []):
        yard = cl.fps.get(ref, (None, None, None, None))[3]
        if yard is None:
            fails.append(f"clear_under {ref}: cannot judge, " + ("no courtyard" if ref in cl.fps else f"no part {ref}"))
            continue
        area = yard.buffer(margin)
        own = {p.net for p in b.pads if p.ref == ref} | ground
        hits = sorted({net for r, net, _l, sh in cl.items if r is None and net not in own and sh.intersects(area)})
        lines.append(f"clear_under {ref} (+{margin} mm): " + (", ".join(hits) if hits else "clear"))
        if hits:
            fails.append(f"{', '.join(hits)} {'runs' if len(hits) == 1 else 'run'} under {ref} (courtyard + {margin} mm)")
    return lines, fails


def _expand(b: Board, names) -> list[str]:
    """Net names; shell-style wildcards match the board's nets (hierarchical names on existing boards)."""
    import fnmatch
    allnets = {t.net for t in b.tracks} | {p.net for p in b.pads}
    out = []
    for n in names:
        out += sorted(x for x in allnets if fnmatch.fnmatchcase(x, n)) if any(c in n for c in "*?[") else [n]
    return out


def review(pcb: Path, m) -> list[str]:
    """Returns failures; prints a short report."""
    b = Board(pcb)
    spec = getattr(m, "REVIEW", {})
    fails = []
    declared = {(z[0], z[1]) for z in getattr(m, "ZONES", [])}
    for z in b.zones:
        if z.keepout:
            continue
        for layer in z.layers:
            n = len(z.fills.get(layer, []))
            tag = f"zone {z.net} {layer}: {n} piece(s)"
            if (z.net, layer) in declared and n != 1:
                fails.append(tag + " -- a declared power polygon must fill as one piece")
            cov = z.area(layer) / b.area if b.area else 0
            if cov > 0.2 or layer in spec.get("coverage", {}):
                tag += f", covers {cov:.0%} of the board"
            lim = spec.get("coverage", {}).get(layer)
            if lim is not None and z.priority == 0 and z.net in spec.get("ground", ["GND"]) and cov < lim:
                fails.append(f"{z.net} pour on {layer} covers {cov:.0%} of the board, limit {lim:.0%}")
            print("   ", tag)
    fails += crossings(b, m)
    from .placement_review import placement_review
    lines, pf = placement_review(b, spec)
    for ln in lines:
        print("   ", ln)
    fails += pf
    if spec.get("fab"):
        from .fab import fab_review
        lines, ff = fab_review(b, Path(pcb), spec["fab"], spec.get("fab_copper_oz", 1))
        for ln in lines:
            print("   ", ln)
        fails += ff
    L = b.net_lengths()
    for net, lim in spec.get("maxlen", {}).items():
        print(f"    len {net}: {L.get(net, 0):.2f} mm (<= {lim})")
        if L.get(net, 0) > lim:
            fails.append(f"net {net} is {L.get(net, 0):.2f} mm long, limit {lim}")
    for a, c, lim in spec.get("maxpath", []):
        r = b.route_path(a, c)
        print(f"    path {a} -> {c}: {('%.2f mm, %d via(s), %s' % (r[0], r[1], '/'.join(r[2]))) if r else 'no track path'} (<= {lim})")
        if not r or r[0] > lim:
            fails.append(f"path {a} -> {c} is {r[0] if r else 'missing'}, limit {lim}")
    for paths, tol in spec.get("match", []):
        rs = [(a, c, b.route_path(a, c)) for a, c in paths]
        for a, c, r in rs:
            print(f"    match {a} -> {c}: {('%.2f mm, %d via(s)' % (r[0], r[1])) if r else 'no track path'}")
        if any(r is None for _a, _c, r in rs):
            fails.append("match group has a path with no track connection: " + ", ".join(f"{a}->{c}" for a, c, r in rs if r is None))
            continue
        spread = max(r[0] for *_x, r in rs) - min(r[0] for *_x, r in rs)
        print(f"      spread {spread:.2f} mm (<= {tol})")
        if spread > tol:
            fails.append(f"matched paths differ by {spread:.2f} mm, limit {tol}: " + ", ".join(f"{a}->{c}" for a, c, _r in rs))
    for a, c, lim in spec.get("skew", []):
        d = abs(L.get(a, 0) - L.get(c, 0))
        print(f"    skew {a}/{c}: {L.get(a, 0):.2f} vs {L.get(c, 0):.2f} = {d:.2f} mm (<= {lim})")
        if d > lim:
            fails.append(f"{a}/{c} length mismatch {d:.2f} mm, limit {lim}")
    ground = spec.get("ground", ["GND"])
    for nets, lim in spec.get("ref", []):
        nets = _expand(b, nets)
        for net, (bad, at) in off_reference(b, nets, ground).items():
            print(f"    ref {net}: {bad:.2f} mm with no {'/'.join(ground)} reference (<= {lim})" + (f", first near {at}" if at else ""))
            if bad > lim:
                fails.append(f"net {net} runs {bad:.2f} mm with no ground under it, limit {lim}, first near {at}")
        vg = spec.get("via_gnd")
        if vg:
            gv = [v for v in b.vias if v.net in ground]
            gp = [p for p in b.pads if p.net in ground and p.thru]
            for v in b.vias:
                if v.net in nets:
                    d = min([math.hypot(v.x - g.x, v.y - g.y) for g in gv + gp] or [1e9])
                    if d > vg:
                        fails.append(f"{v.net} via at ({v.x:.1f}, {v.y:.1f}) has no ground via within {vg} mm (nearest {d:.1f})")
    lines, cf = current_check(b, spec)
    for ln in lines:
        print("   ", ln)
    fails += cf
    lines, lf = loop_check(b, spec)
    for ln in lines:
        print("   ", ln)
    fails += lf
    lines, af = apart_check(b, spec)
    for ln in lines:
        print("   ", ln)
    fails += af
    from .segments import segments_check
    lines, sf = segments_check(b, spec)
    for ln in lines:
        print("   ", ln)
    fails += sf
    from .islands import islands_check
    lines, isf = islands_check(b, spec)
    for ln in lines:
        print("   ", ln)
    fails += isf
    from .tidy import tidy_check
    lines, tf = tidy_check(b, spec)
    for ln in lines:
        print("   ", ln)
    fails += tf
    from .bends import bends_check
    lines, bf = bends_check(b, spec)
    for ln in lines:
        print("   ", ln)
    fails += bf
    for name, lim in spec.get("via_near", []):
        p = b.pad(name)
        d = min([math.hypot(v.x - p.x, v.y - p.y) for v in b.vias if v.net == p.net] or [1e9])
        print(f"    via_near {name} ({p.net}): {'no via' if d > 1e8 else '%.2f mm' % d} (<= {lim})")
        if d > lim:
            fails.append(f"{name} has no {p.net} via within {lim} mm" + ("" if d > 1e8 else f" (nearest {d:.2f})"))
    return fails


def cli(argv: list[str]) -> int:
    argv = ["boardwright", *argv]
    # boardwright review BOARD.kicad_pcb [SPEC.py]   -- review any board file
    import importlib.util
    import types
    spec = types.SimpleNamespace()
    if len(argv) > 2:
        sp = importlib.util.spec_from_file_location("review_spec", argv[2])
        spec = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(spec)
    print("review:")
    fails = review(Path(argv[1]), spec)
    print(f"{'OK  ' if not fails else 'FAIL'} review", *fails, sep="\n    ")
    return (1 if fails else 0)
