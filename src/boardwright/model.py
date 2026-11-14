"""One reader for any .kicad_pcb, generated here or drawn by hand.

Built on kicad-tools' parser so it does not depend on how the file is
indented or which KiCad version saved it. All coordinates are board-relative
mm as kicad-tools reports them; `origin` converts to file coordinates
(file = relative + origin), which is what text appended to the file needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from kicad_tools.schema.pcb import PCB


@dataclass
class Pad:
    ref: str
    num: str
    net: str
    x: float
    y: float
    layer: str          # the footprint's side
    w: float
    h: float
    angle: float
    thru: bool
    layers: list[str]

    @property
    def reach(self) -> float:
        return max(self.w, self.h) / 2

    def on(self, layer: str) -> bool:
        """Has copper on this layer. A paste-only or mask-only pad has none anywhere."""
        if self.layers:
            return layer in self.layers or "*.Cu" in self.layers or (self.thru and any(l.endswith(".Cu") for l in self.layers))
        return self.thru or layer == self.layer


@dataclass
class Track:
    pts: list[tuple[float, float]]      # 2 points for a segment, more for an arc
    width: float
    layer: str
    net: str

    @property
    def length(self) -> float:
        return sum(math.dist(a, b) for a, b in zip(self.pts, self.pts[1:]))

    @property
    def a(self):
        return self.pts[0]

    @property
    def b(self):
        return self.pts[-1]


@dataclass
class Via:
    x: float
    y: float
    size: float
    drill: float
    layers: list[str]
    net: str


@dataclass
class Zone:
    net: str
    layers: list[str]
    priority: int
    keepout: bool
    outline: list[tuple[float, float]]
    fills: dict[str, list[list[tuple[float, float]]]] = field(default_factory=dict)

    def area(self, layer: str) -> float:
        return sum(_area(p) for p in self.fills.get(layer, []))

    def covers(self, layer: str, x: float, y: float) -> bool:
        return any(inside(x, y, p) for p in self.fills.get(layer, []))


def _area(pts) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2


def inside(x: float, y: float, poly) -> bool:
    c = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _arc_points(s, m, e, n=12):
    """Polyline through a 3-point arc."""
    (x1, y1), (x2, y2), (x3, y3) = s, m, e
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-9:
        return [s, e]
    ux = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / d
    uy = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / d
    r = math.hypot(x1 - ux, y1 - uy)
    a1, a2, a3 = (math.atan2(y - uy, x - ux) for x, y in (s, m, e))
    def unwrap(a, ref, ccw):
        while ccw and a < ref:
            a += 2 * math.pi
        while not ccw and a > ref:
            a -= 2 * math.pi
        return a
    ccw = (unwrap(a2, a1, True) - a1) < (unwrap(a3, a1, True) - a1)
    a3 = unwrap(a3, a1, ccw)
    return [(ux + r * math.cos(a1 + (a3 - a1) * i / n), uy + r * math.sin(a1 + (a3 - a1) * i / n)) for i in range(n + 1)]


class Board:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.pcb = PCB.load(str(path))

    @cached_property
    def origin(self) -> tuple[float, float]:
        o = self.pcb.board_origin
        return (o[0], o[1]) if o else (0.0, 0.0)

    @cached_property
    def layers(self) -> list[str]:
        return [l.name for l in self.pcb.copper_layers]

    @cached_property
    def pads(self) -> list[Pad]:
        out = []
        for fp in self.pcb.footprints:
            fx, fy = fp.position
            r = math.radians(fp.rotation or 0)
            for p in fp.pads:
                px, py = p.position
                x = fx + px * math.cos(r) + py * math.sin(r)
                y = fy - px * math.sin(r) + py * math.cos(r)
                out.append(Pad(fp.reference, str(p.number), p.net_name or "", round(x, 4), round(y, 4),
                               fp.layer, p.size[0], p.size[1], (p.rotation or 0),
                               (p.type or "").startswith(("thru", "np_thru")), list(p.layers or [])))
        return out

    @cached_property
    def tracks(self) -> list[Track]:
        out = [Track([s.start, s.end], s.width, s.layer, s.net_name or "") for s in self.pcb.segments]
        for a in getattr(self.pcb, "arcs", []) or []:
            out.append(Track(_arc_points(a.start, a.mid, a.end), a.width, a.layer, a.net_name or ""))
        return out

    @cached_property
    def vias(self) -> list[Via]:
        return [Via(v.position[0], v.position[1], v.size, v.drill, list(v.layers), v.net_name or "") for v in self.pcb.vias]

    @cached_property
    def zones(self) -> list[Zone]:
        out = []
        for z in self.pcb.zones:
            layers = list(z.layers) if z.layers else ([z.layer] if z.layer else [])
            zn = Zone(z.net_name or "", layers, z.priority or 0, bool(z.keepout), [tuple(p) for p in (z.polygon or [])])
            fl = list(getattr(z, "filled_polygon_layers", None) or [])
            for i, poly in enumerate(z.filled_polygons or []):
                layer = fl[i] if i < len(fl) and fl[i] else (z.filled_polygon_layer or (layers[0] if layers else ""))
                zn.fills.setdefault(layer, []).append([tuple(p) for p in poly])
            out.append(zn)
        return out

    @cached_property
    def bbox(self) -> tuple[float, float, float, float]:
        pts = list(self.pcb.get_board_outline() or [])
        if not pts:
            pts = [(p.x, p.y) for p in self.pads]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    @cached_property
    def area(self) -> float:
        pts = list(self.pcb.get_board_outline() or [])
        if len(pts) >= 3:
            return _area([tuple(p) for p in pts])
        x1, y1, x2, y2 = self.bbox
        return (x2 - x1) * (y2 - y1)

    def pad(self, name: str) -> Pad:
        """'U1.24' -> the pad (first match for multi-pad numbers)."""
        ref, num = name.split(".", 1)
        for p in self.pads:
            if p.ref == ref and p.num == num:
                return p
        raise KeyError(name)

    def net_lengths(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for t in self.tracks:
            out[t.net] = out.get(t.net, 0) + t.length
        return out

    # ---- connectivity along copper, for path lengths -------------------
    def route_path(self, a: str, b: str, via_len: float = 0.0):
        """Shortest routed length from pad a to pad b ('U1.3'); None if not joined by tracks.

        Returns (length_mm, vias, layers_used). Pours are not followed: a net that
        relies on a zone for the connection has no track path.
        """
        import heapq
        pa, pb = self.pad(a), self.pad(b)
        net = pa.net
        tr = [t for t in self.tracks if t.net == net]
        vias = [v for v in self.vias if v.net == net]
        key = lambda x, y, l: (round(x, 2), round(y, 2), l)
        g: dict = {}
        def link(u, v, w, kind):
            g.setdefault(u, []).append((v, w, kind))
            g.setdefault(v, []).append((u, w, kind))
        for t in tr:
            link(key(*t.a, t.layer), key(*t.b, t.layer), t.length, "t")
        for v in vias:
            ls = self.layers[self.layers.index(v.layers[0]):self.layers.index(v.layers[-1]) + 1] \
                if all(l in self.layers for l in v.layers) else v.layers
            for l1 in ls:
                for l2 in ls:
                    if l1 < l2:
                        link(key(v.x, v.y, l1), key(v.x, v.y, l2), via_len, "v")
        def attach(p, tag):
            for node in list(g):
                if p.on(node[2]) and math.hypot(node[0] - p.x, node[1] - p.y) <= p.reach + 0.05:
                    link(tag, node, math.hypot(node[0] - p.x, node[1] - p.y), "p")
        for p in self.pads:                      # other pads of the net join layers and track ends
            if p.net == net:
                attach(p, ("pad", p.ref, p.num))
        src, dst = ("pad", pa.ref, pa.num), ("pad", pb.ref, pb.num)
        if src not in g or dst not in g:
            return None
        best = {src: (0.0, 0, frozenset())}
        n = 0
        heap = [(0.0, 0, 0, src, frozenset())]
        while heap:
            dist, _n, nv, u, ls = heapq.heappop(heap)
            if u == dst:
                return round(dist, 3), nv, sorted(ls)
            if dist > best.get(u, (1e18,))[0]:
                continue
            for v, w, kind in g.get(u, []):
                nd = dist + w
                if nd < best.get(v, (1e18,))[0]:
                    nls = ls | ({v[2]} if kind == "t" else frozenset())
                    best[v] = (nd, nv + (kind == "v"), nls)
                    n += 1
                    heapq.heappush(heap, (nd, n, nv + (kind == "v"), v, nls))
        return None
