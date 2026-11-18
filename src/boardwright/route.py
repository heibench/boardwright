"""Route one connection, pad to pad, round the copper that is already there.

    from boardwright.route import route
    r = route(board, "U1.22", "Y1.1", width=0.15, clearance=0.15, layers=["B.Cu"])
    r.tracks   # [(net, [(x, y), ...], width, layer), ...]   board-relative, as TRACKS
    r.vias     # [(net, x, y, size, drill), ...]              as VIAS

A grid search (A*, 45-degree moves) over the free space of each allowed layer.
Free space is what is left after every other net's pads, tracks, vias,
keep-outs and local polygons are grown by the clearance plus half the track
width, and the board edge is pulled in likewise. Pours (priority-0 zones) are
not obstacles: KiCad refills them round a new track. A via may be placed where
a through via clears every layer.

It finds *a* legal path for a short connection; it does not push other tracks
aside, tune length or route pairs. KiCad's DRC stays the judge of the result.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from .model import Board, Pad


@dataclass
class Routed:
    net: str
    tracks: list = field(default_factory=list)
    vias: list = field(default_factory=list)
    length: float = 0.0

    def __bool__(self) -> bool:
        return bool(self.tracks)


def pad_shape(p: Pad):
    """The pad's copper as a polygon. Width runs along (cos a, -sin a): y is down."""
    return affinity.translate(affinity.rotate(box(-p.w / 2, -p.h / 2, p.w / 2, p.h / 2), -p.angle, origin=(0, 0)), p.x, p.y)


def _copper(board: Board, net: str, layer: str, window, extra, ignore=frozenset()) -> list:
    """Shapes of every other net's copper on `layer` that touches the window.

    Tracks and vias of nets in `ignore` are left out (they are about to be removed);
    their pads still count."""
    wx0, wy0, wx1, wy1 = window
    hit = lambda x0, y0, x1, y1: x1 >= wx0 and x0 <= wx1 and y1 >= wy0 and y0 <= wy1
    out = []
    for p in board.pads:
        if p.net != net and p.on(layer) and hit(p.x - p.reach, p.y - p.reach, p.x + p.reach, p.y + p.reach):
            out.append(pad_shape(p))
    for t in list(board.tracks) + [e for e in extra if e[0] == "t"]:
        if isinstance(t, tuple):
            _k, tnet, pts, w, tl = t
        else:
            tnet, pts, w, tl = t.net, t.pts, t.width, t.layer
        if tnet == net or tl != layer or (tnet in ignore and not isinstance(t, tuple)):
            continue
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        if hit(min(xs) - w, min(ys) - w, max(xs) + w, max(ys) + w):
            out.append(LineString(pts).buffer(w / 2, cap_style="round"))
    for v in list(board.vias) + [e for e in extra if e[0] == "v"]:
        if isinstance(v, tuple):
            _k, vnet, x, y, size = v
        else:
            vnet, x, y, size = v.net, v.x, v.y, v.size
        if vnet != net and not (vnet in ignore and not isinstance(v, tuple)) and hit(x - size, y - size, x + size, y + size):
            out.append(Point(x, y).buffer(size / 2))
    for z in board.zones:
        if layer not in z.layers or len(z.outline) < 3:
            continue
        if z.keepout or (z.net != net and z.priority > 0):
            out.append(Polygon(z.outline))
    return out


def _outline(board: Board):
    pts = board.outline
    if len(pts) >= 3:
        poly = Polygon(pts)
        if poly.is_valid and poly.area > 0:
            return poly
    return box(*board.bbox)


def _simplify(pts):
    out = [pts[0]]
    for a, b in zip(pts[1:], pts[2:] + [None]):
        if b is None:
            out.append(a)
            break
        (x0, y0), (x1, y1), (x2, y2) = out[-1], a, b
        if abs((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)) > 1e-9:
            out.append(a)
    return out


def route(board: Board, a: str, b: str, width: float = 0.2, clearance: float = 0.2,
          layers: list[str] | None = None, via: tuple[float, float] = (0.6, 0.3), via_cost: float = 4.0,
          edge: float = 0.3, step: float = 0.05, margin: float = 4.0, extra: list | None = None,
          max_nodes: int = 300_000, ignore=frozenset(), grow: int = 2) -> Routed:
    """Route pad a to pad b ("REF.PAD"). `extra` holds copper added since the board was read:
    ("t", net, pts, width, layer) and ("v", net, x, y, size).

    The route changes layer without a new via where it is already on its own
    net's through copper (a via, or a through-hole pad), so routes sharing a pad
    share its via instead of stacking one each."""
    pa, pb = board.pad(a), board.pad(b)
    net = pa.net
    if pb.net != net:
        raise ValueError(f"{a} is on {pa.net!r} and {b} on {pb.net!r}")
    extra = extra or []
    layers = layers or [l for l in board.layers if l in ("F.Cu", "B.Cu")]
    if not any(pa.on(l) for l in layers) or not any(pb.on(l) for l in layers):
        raise ValueError(f"{a} or {b} has no copper on {layers}")
    outline = _outline(board)
    while True:
        x0 = min(pa.x, pb.x) - margin
        y0 = min(pa.y, pb.y) - margin
        x1 = max(pa.x, pb.x) + margin
        y1 = max(pa.y, pb.y) + margin
        window = (x0, y0, x1, y1)
        nx, ny = int((x1 - x0) / step) + 1, int((y1 - y0) / step) + 1
        gx = pa.x + (np.arange(nx) - round((pa.x - x0) / step)) * step      # grid passes through pad a
        gy = pa.y + (np.arange(ny) - round((pa.y - y0) / step)) * step
        X, Y = np.meshgrid(gx, gy, indexing="ij")
        inside = shapely.contains_xy(outline.buffer(-(edge + width / 2)), X, Y)
        free = {}
        for l in layers:
            shapes = _copper(board, net, l, window, extra, ignore)
            blocked = unary_union(shapes).buffer(clearance + width / 2) if shapes else None
            f = inside.copy()
            if blocked is not None and not blocked.is_empty:
                f &= ~shapely.contains_xy(blocked, X, Y)
            free[l] = f
        via_ok, reuse = None, None
        if len(layers) > 1:
            via_ok = shapely.contains_xy(outline.buffer(-(edge + via[0] / 2)), X, Y)
            for l in board.layers:                      # a through via has to clear every layer
                shapes = _copper(board, net, l, window, extra, ignore)
                if shapes:
                    via_ok &= ~shapely.contains_xy(unary_union(shapes).buffer(clearance + via[0] / 2), X, Y)
            own = []                                    # this net's through copper: its vias and through-hole pads
            for v in board.vias:
                if v.net == net:
                    own.append(Point(v.x, v.y).buffer(max(v.size / 2 - width / 2, step)))
            for e in extra:
                if e[0] == "v" and e[1] == net:
                    own.append(Point(e[2], e[3]).buffer(max(e[4] / 2 - width / 2, step)))
            for p in board.pads:
                if p.thru and p.net == net:
                    inner = pad_shape(p).buffer(-width / 2)
                    own.append(inner if not inner.is_empty else Point(p.x, p.y).buffer(step))
            reuse = shapely.contains_xy(unary_union(own), X, Y) if own else np.zeros_like(via_ok)
            for l in layers:
                via_ok &= free[l]
                reuse &= free[l]
        ia = (int(round((pa.x - gx[0]) / step)), int(round((pa.y - gy[0]) / step)))
        ib = (int(round((pb.x - gx[0]) / step)), int(round((pb.y - gy[0]) / step)))
        # the two pads themselves are always reachable on the layers they have copper on
        sa, sb = pad_shape(pa), pad_shape(pb)
        own_a, own_b = shapely.contains_xy(sa, X, Y), shapely.contains_xy(sb, X, Y)
        for l in layers:
            if pa.on(l):
                free[l] |= own_a & inside
            if pb.on(l):
                free[l] |= own_b & inside
        goal = {(ib[0], ib[1], li) for li, l in enumerate(layers) if pb.on(l)}
        start = [(ia[0], ia[1], li) for li, l in enumerate(layers) if pa.on(l)]
        path = _astar(start, goal, [free[l] for l in layers], via_ok, ib, step, via_cost, max_nodes, reuse)
        if path is not None or grow <= 0 or margin > max(outline.bounds[2] - outline.bounds[0], outline.bounds[3] - outline.bounds[1]):
            break
        margin *= 2                                   # widen the search window and try again
        grow -= 1
    out = Routed(net)
    if path is None:
        return out
    run, cur = [], None
    def flush():
        if len(run) > 1:
            pts = _simplify(run)
            out.tracks.append((net, [(round(x, 4), round(y, 4)) for x, y in pts], width, layers[cur]))
            out.length += sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
    for ix, iy, li in path:
        pt = (float(gx[ix]), float(gy[iy]))
        if cur is None:
            cur, run = li, [(pa.x, pa.y)] if (ix, iy) == ia else [pt]
            if run[-1] != pt:
                run.append(pt)
            continue
        if li != cur:
            flush()
            if reuse is None or not reuse[ix, iy]:      # on its own via or through-hole pad: no new via
                out.vias.append((net, round(pt[0], 4), round(pt[1], 4), via[0], via[1]))
            cur, run = li, [pt]
        else:
            run.append(pt)
    # the last grid point is the cell nearest pad b's centre, inside the pad: no stub to the exact centre
    flush()
    return out


_MOVES = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
          (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2))]


def _astar(start, goal, free, via_ok, ib, step, via_cost, max_nodes, reuse=None):
    nx, ny = free[0].shape
    def h(ix, iy):
        dx, dy = abs(ix - ib[0]), abs(iy - ib[1])
        return (max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)) * step
    best, came, heap, n = {}, {}, [], 0
    for s in start:
        best[s] = 0.0
        heapq.heappush(heap, (h(s[0], s[1]), 0, s, None))
    turn = 0.15 * step * 4                       # a small price per bend keeps paths straight
    while heap:
        _f, _n, node, d_in = heapq.heappop(heap)
        if node in goal:
            path = [node]
            while path[-1] in came:
                path.append(came[path[-1]])
            return path[::-1]
        g = best[node]
        ix, iy, li = node
        if len(best) > max_nodes:
            return None
        for di, (dx, dy, c) in enumerate(_MOVES):
            jx, jy = ix + dx, iy + dy
            if not (0 <= jx < nx and 0 <= jy < ny) or not free[li][jx, jy]:
                continue
            if dx and dy and not (free[li][ix + dx, iy] and free[li][ix, iy + dy]):
                continue                           # no squeezing diagonally between two blocked cells
            ng = g + c * step + (turn if d_in is not None and d_in != di else 0.0)
            nb = (jx, jy, li)
            if ng < best.get(nb, 1e18):
                best[nb], came[nb] = ng, node
                n += 1
                heapq.heappush(heap, (ng + h(jx, jy), n, nb, di))
        here = reuse is not None and reuse[ix, iy]
        if via_ok is not None and (via_ok[ix, iy] or here):
            for lj in range(len(free)):
                if lj != li and free[lj][ix, iy]:
                    nb = (ix, iy, lj)
                    ng = g + (step if here else via_cost)
                    if ng < best.get(nb, 1e18):
                        best[nb], came[nb] = ng, node
                        n += 1
                        heapq.heappush(heap, (ng + h(ix, iy), n, nb, None))
    return None


def net_classes(board: Board, project=None):
    """net name -> {"class", "width", "clearance", "via", "pair_width", "pair_gap"} from a project file:
    `project` if given, else the .kicad_pro beside the board.

    A net takes the class the project assigns it, by explicit assignment or by
    the first matching pattern; anything a class leaves unset falls back to
    the Default class. With no project file every net gets None and route()'s
    own conservative defaults apply."""
    import fnmatch
    import json
    from pathlib import Path
    pro = Path(project) if project else board.path.with_suffix(".kicad_pro")
    if not pro.exists():
        return lambda net: None
    j = json.loads(pro.read_text())
    ns = j.get("net_settings", {})
    classes = {c.get("name"): c for c in ns.get("classes", [])}
    default = classes.get("Default", {})
    assign = ns.get("netclass_assignments") or {}
    patterns = ns.get("netclass_patterns") or []
    edge = j.get("board", {}).get("design_settings", {}).get("rules", {}).get("min_copper_edge_clearance")
    def pick(c, key, fallback):
        v = c.get(key)
        return v if v is not None else default.get(key, fallback)
    def lookup(net: str):
        name = None
        a = assign.get(net)
        if a:
            name = a[0] if isinstance(a, list) else a
        else:
            for p in patterns:
                if fnmatch.fnmatchcase(net, p.get("pattern", "")):
                    name = p.get("netclass")
                    break
        c = classes.get(name) or default
        out = {"class": name or "Default", "width": pick(c, "track_width", 0.2), "clearance": pick(c, "clearance", 0.2),
               "via": (pick(c, "via_diameter", 0.6), pick(c, "via_drill", 0.3)),
               "pair_width": pick(c, "diff_pair_width", None), "pair_gap": pick(c, "diff_pair_gap", None)}
        if edge is not None:
            out["edge"] = max(edge, 0.2)
        return out
    return lookup


def defaults_for(board: Board, project=None, net: str | None = None) -> dict:
    """route() keywords for a net from the project's net classes; {} without a project."""
    c = net_classes(board, project)(net or "")
    if c is None:
        return {}
    return {k: c[k] for k in ("width", "clearance", "via", "edge") if k in c}


def expand(m, board: Board, ignore=frozenset(), project=None) -> tuple[list, list]:
    """A spec's ROUTES as extra TRACKS and VIAS. Raises if any connection cannot be routed.

    ROUTES = [("U1.22", "Y1.1"), ("U1.5", "R9.2", {"layers": ["B.Cu"], "width": 0.15})]
    Each route takes width, clearance and via size from the net class the project
    assigns to its net. ROUTE_DEFAULTS = {...} overrides that for every route, and
    a route's own options override both.
    Hand TRACKS and VIAS in the same spec are obstacles for the routes.
    """
    routes = getattr(m, "ROUTES", [])
    if not routes:
        return [], []
    spec_defaults = getattr(m, "ROUTE_DEFAULTS", {})
    per_net = []
    for r in routes:                                  # each route takes its own net's class from the project
        o = defaults_for(board, project, board.pad(r[0]).net)
        o.update(spec_defaults)
        o.update(r[2] if len(r) > 2 else {})
        per_net.append((r[0], r[1], o))
    routes = per_net
    opt = {"ignore": frozenset(ignore)}
    extra = [("t", t[0], t[1], t[2] if len(t) > 2 else 0.25, t[3] if len(t) > 3 else "F.Cu") for t in getattr(m, "TRACKS", [])]
    extra += [("v", v[0], v[1], v[2], v[3] if len(v) > 4 else 0.6) for v in getattr(m, "VIAS", [])]
    tracks, vias, failed = route_all(board, routes, opt, extra)
    if failed:
        raise SystemExit("could not route: " + "; ".join(failed) + "  (try other layers, a smaller width, or hand TRACKS)")
    return tracks, vias


def route_all(board: Board, routes: list, defaults: dict | None = None, extra: list | None = None) -> tuple[list, list, list[str]]:
    """Route a list in order; each result is an obstacle for the next.

    routes: (a, b) or (a, b, {options}) with options as route()'s keywords.
    Returns (TRACKS, VIAS, failures).
    """
    tracks, vias, failed, extra = [], [], [], list(extra or [])
    for r in routes:
        a, b = r[0], r[1]
        opt = dict(defaults or {})
        if len(r) > 2:
            opt.update(r[2])
        res = route(board, a, b, extra=extra, **opt)
        if not res:
            failed.append(f"{a} -> {b}")
            continue
        tracks += res.tracks
        vias += res.vias
        extra += [("t", t[0], t[1], t[2], t[3]) for t in res.tracks] + [("v", v[0], v[1], v[2], v[3]) for v in res.vias]
    return tracks, vias, failed
