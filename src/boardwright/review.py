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
