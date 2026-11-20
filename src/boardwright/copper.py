"""Hand-placed copper and silk, appended to the .kicad_pcb as text.

Everything takes board-relative mm (0,0 = top-left of the outline), like PLACE.
Used for what an autorouter does badly: power polygons, stitching and thermal
vias, keepouts, hand-routed traces, silkscreen labels.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from .errors import Usage


def num(v: float) -> str:
    """A length or angle as KiCad writes it: at most 6 decimals (1 nm), no
    trailing zeros. Python's :g keeps 6 significant digits instead, which
    rounds 149.119895 to 149.12 and 157.1375 to 157.138 (#41)."""
    s = f"{round(float(v), 6):.6f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def origin(pcb) -> tuple[float, float]:
    """File coordinates of the board-relative (0, 0), as model.py defines it.

    Takes a path. One definition for generated and hand-drawn boards alike, so
    what `pads` prints is what TRACKS, VIAS and ZONES are written in.
    """
    from .model import Board
    return Board(pcb).origin


def blocks(text: str, heads: tuple[str, ...]) -> list[tuple[int, int]]:
    """(start, end) of every top-level-ish s-expression whose head is in `heads`,
    found by matching parentheses (any nesting, any indentation, strings respected)."""
    out = []
    pat = re.compile(r"\n[ \t]*\((" + "|".join(map(re.escape, heads)) + r")\b")
    pos = 0
    while True:
        m = pat.search(text, pos)
        if not m:
            return out
        i = m.end(0) - len(m.group(1)) - 1
        depth, j, instr = 0, i, False
        while j < len(text):
            ch = text[j]
            if instr:
                if ch == "\\":
                    j += 1
                elif ch == '"':
                    instr = False
            elif ch == '"':
                instr = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append((m.start(0), j + 1))
        pos = j + 1


def ripup(text: str, nets: set[str]) -> tuple[str, int]:
    """Remove every track, arc and via of the given nets."""
    names = dict(re.findall(r'\n\s*\(net (\d+) "([^"]*)"\)', text))
    drop = []
    for s0, e0 in blocks(text, ("segment", "arc", "via")):
        n = re.search(r'\(net (?:(\d+)(?: "([^"]*)")?|"([^"]*)")', text[s0:e0])
        if not n:
            continue
        net = n.group(3) if n.group(3) is not None else (n.group(2) or names.get(n.group(1), ""))
        if net in nets:
            drop.append((s0, e0))
    for s0, e0 in reversed(drop):
        text = text[:s0] + text[e0:]
    return text, len(drop)


def _net(text: str, name: str, zone: bool = False) -> str:
    """Net reference in the file's own style: numbered (pre-KiCad-10 save) or by name."""
    m = re.search(r'\n\t\(net (\d+) "%s"\)' % re.escape(name), text)
    if not m:
        return f'(net "{name}")'
    return f'(net {m.group(1)}) (net_name "{name}")' if zone else f'(net {m.group(1)})'


def _u() -> str:
    return str(uuid.uuid4())


def _pts(pts, ox, oy) -> str:
    return " ".join(f"(xy {round(x + ox, 4)} {round(y + oy, 4)})" for x, y in pts)


def zone(netref, layer, pts, ox, oy, priority=1, clearance=0.25, solid=True, min_thickness=0.2) -> str:
    connect = "(connect_pads yes (clearance %s))" % clearance if solid else "(connect_pads (clearance %s))" % clearance
    return (f'\t(zone {netref} (layer "{layer}") (uuid "{_u()}") (hatch edge 0.5) (priority {priority})\n'
            f'\t\t{connect} (min_thickness {min_thickness})\n'
            f'\t\t(fill yes (thermal_gap 0.3) (thermal_bridge_width 0.4) (island_removal_mode 0))\n'
            f'\t\t(polygon (pts {_pts(pts, ox, oy)}))\n\t)\n')


def keepout(layers, pts, ox, oy, tracks=True, vias=True, pour=True) -> str:
    ls = " ".join(f'"{l}"' for l in layers)
    na = lambda b: "not_allowed" if b else "allowed"
    return (f'\t(zone (net 0) (net_name "") (layers {ls}) (uuid "{_u()}") (hatch edge 0.5)\n'
            f'\t\t(connect_pads (clearance 0)) (min_thickness 0.25)\n'
            f'\t\t(keepout (tracks {na(tracks)}) (vias {na(vias)}) (pads allowed) '
            f'(copperpour {na(pour)}) (footprints allowed))\n'
            f'\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))\n'
            f'\t\t(polygon (pts {_pts(pts, ox, oy)}))\n\t)\n')


def via(netref, x, y, ox, oy, size=0.6, drill=0.3) -> str:
    return (f'\t(via (at {round(x + ox, 4)} {round(y + oy, 4)}) (size {size}) (drill {drill}) '
            f'(layers "F.Cu" "B.Cu") {netref} (uuid "{_u()}"))\n')


def track(netref, pts, ox, oy, width=0.25, layer="F.Cu") -> str:
    out = ""
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        out += (f'\t(segment (start {round(x1 + ox, 4)} {round(y1 + oy, 4)}) (end {round(x2 + ox, 4)} {round(y2 + oy, 4)}) '
                f'(width {width}) (layer "{layer}") {netref} (uuid "{_u()}"))\n')
    return out


def text(s, x, y, ox, oy, size=1.0, layer="F.SilkS", rot=0) -> str:
    mirror = " (justify mirror)" if layer.startswith("B.") else ""
    return (f'\t(gr_text "{s}" (at {round(x + ox, 4)} {round(y + oy, 4)} {rot}) (layer "{layer}") (uuid "{_u()}")\n'
            f'\t\t(effects (font (size {size} {size}) (thickness {round(size * 0.15, 3)})){mirror})\n\t)\n')


def append(pcb: Path, chunks: list[str]) -> None:
    if not chunks:
        return
    t = pcb.read_text().rstrip()
    assert t.endswith(")")
    pcb.write_text(t[:-1].rstrip() + "\n" + "".join(chunks) + ")\n")


def _cross(p1, p2, p3, p4) -> bool:
    def o(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return o(p1, p2, p3) * o(p1, p2, p4) < 0 and o(p3, p4, p1) * o(p3, p4, p2) < 0


def check_vias(m) -> None:
    """Each VIAS entry is (net, x, y[, size, drill]); anything else is a usage
    error naming the entry, before anything is written (#107)."""
    for v in getattr(m, "VIAS", []):
        ok = (isinstance(v, (tuple, list)) and len(v) in (3, 5) and isinstance(v[0], str)
              and all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in v[1:]))
        if not ok:
            raise Usage(f"VIAS entry {v!r} is not (net, x, y[, size, drill])")


def check_tracks(m) -> None:
    """Hand routes of different nets must not cross on a layer, or pass over a foreign hand via."""
    import math
    check_vias(m)
    segs = [(t[0], a, b, t[3] if len(t) > 3 else "F.Cu", t[2] if len(t) > 2 else 0.25)
            for t in getattr(m, "TRACKS", []) for a, b in zip(t[1], t[1][1:])]
    for i, (n1, a, b, l1, _w) in enumerate(segs):
        for n2, c, d, l2, _w2 in segs[i + 1:]:
            if n1 != n2 and l1 == l2 and _cross(a, b, c, d):
                raise ValueError(f"TRACKS: {n1} {a}->{b} crosses {n2} {c}->{d} on {l1}")
    for v in getattr(m, "VIAS", []):
        r = (v[3] if len(v) > 3 else 0.6) / 2
        for n, a, b, _l, w in segs:
            if n == v[0]:
                continue
            (x1, y1), (x2, y2), (px, py) = a, b, (v[1], v[2])
            L2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
            t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / L2)) if L2 else 0
            dist = math.hypot(px - (x1 + t * (x2 - x1)), py - (y1 + t * (y2 - y1)))
            if dist < r + w / 2 + 0.15:
                raise ValueError(f"TRACKS: {n} {a}->{b} passes {dist:.2f} mm from the {v[0]} via at {(px, py)}")


def apply(pcb: Path, m, stage: str) -> None:
    """stage 'pre' (before routing): VIAS, TRACKS, KEEPOUTS.  'post': ZONES, TEXT.

    ZONES go in after routing: exported as DSN planes, Freerouting stops routing
    those nets and still runs other nets through them (tried on tps54202_buck).
    boardwright.review names any net that crosses a polygon; hand-route that one.
    """
    t = pcb.read_text()
    ox, oy = origin(pcb)
    ch = []
    if stage == "pre":
        check_tracks(m)
        for v in getattr(m, "VIAS", []):
            ch.append(via(_net(t, v[0]), v[1], v[2], ox, oy, *v[3:]))
        for tr in getattr(m, "TRACKS", []):          # (net, [(x,y)...], width, layer)
            ch.append(track(_net(t, tr[0]), tr[1], ox, oy, *tr[2:]))
        for k in getattr(m, "KEEPOUTS", []):        # (layers, pts)
            ch.append(keepout(k[0], k[1], ox, oy))
    else:
        for z in getattr(m, "ZONES", []):           # (net, layer, pts[, priority])
            ch.append(zone(_net(t, z[0], True), z[1], z[2], ox, oy, *z[3:]))
        for tx in getattr(m, "TEXT", []):           # (string, x, y[, size, layer, rot])
            ch.append(text(tx[0], tx[1], tx[2], ox, oy, *tx[3:]))
    append(pcb, ch)


class Pad(tuple):
    """(ref, pad, net, x, y, layer) plus .reach, half the pad's longer side."""
    def __new__(cls, t, reach):
        o = super().__new__(cls, t)
        o.reach = reach
        return o


def pads(pcb: Path) -> list:
    """(ref, pad, net, x, y, layer) board-relative, each with .reach; any KiCad file."""
    from .model import Board
    return [Pad((p.ref, p.num, p.net, round(p.x, 3), round(p.y, 3), p.layer), p.reach) for p in Board(pcb).pads]


def segments(text: str) -> list[tuple[float, float, float, float, float, str, str]]:
    """(x1, y1, x2, y2, width, layer, net name) in file coordinates; either net style."""
    names = dict(re.findall(r'\n\s*\(net (\d+) "([^"]*)"\)', text))
    out = []
    for m in re.finditer(r'\(segment\s+\(start ([-\d.]+) ([-\d.]+)\)\s+\(end ([-\d.]+) ([-\d.]+)\)'
                         r'\s+\(width ([\d.]+)\)\s+\(layer "([^"]+)"\)\s+\(net (?:(\d+)|"([^"]*)")', text):
        net = m.group(8) if m.group(8) is not None else names.get(m.group(7), m.group(7))
        out.append((*map(float, m.groups()[:5]), m.group(6), net))
    return out
