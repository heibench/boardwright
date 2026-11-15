"""Placement by intent: say where a pad goes, not where the part origin is.

    PLACE = {
        "U1": (14.5, 34, 0),                                        # fixed, as before
        "C3": pad_at(1, ("U1", 24), dy=-1.7, toward=("U1", 23), side="B"),
        "R3": pad_at(2, (20.5, 32.3), rot=180),
    }

pad_at(pad, target, dx, dy, toward | rot, side): put `pad` of this part at
target (+dx, +dy). target is a pad of a fixed part or a point. The rotation
is the one of 0/90/180/270 that brings the part's far pad closest to `toward`
(a pad or a point), or `rot` if given. Solved against the real footprints by
trial placement, so no rotation or mirror convention has to be remembered.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import board as B
from .model import Board


@dataclass
class At:
    pad: str
    target: tuple
    dx: float = 0.0
    dy: float = 0.0
    toward: tuple | None = None
    rot: int | None = None
    side: str = "F"


def pad_at(pad, target, dx=0.0, dy=0.0, toward=None, rot=None, side="F") -> At:
    return At(str(pad), target, dx, dy, toward, rot, side)


def _point(t, pos) -> tuple[float, float]:
    if isinstance(t[0], str):
        return pos[(t[0], str(t[1]))]
    return float(t[0]), float(t[1])


def resolve(pristine: Path, place: dict, circuit, board_dir: Path) -> dict:
    """Returns PLACE with every At replaced by (x, y, rot[, 'B'])."""
    cons = {r: s for r, s in place.items() if isinstance(s, At)}
    if not cons:
        return place
    fixed = {r: s for r, s in place.items() if not isinstance(s, At)}
    for r, c in cons.items():
        for t in (c.target, c.toward):
            if t and isinstance(t[0], str) and t[0] in cons:
                raise ValueError(f"{r}: target {t[0]} is itself placed with pad_at; anchor on a fixed part")
    tmp = pristine.with_suffix(".solve.kicad_pcb")
    seen: dict[int, dict] = {}
    for k in (0, 90, 180, 270):
        shutil.copy(pristine, tmp)
        trial = dict(fixed)
        for r, c in cons.items():
            trial[r] = (10.0, 10.0, k) + (("B",) if c.side == "B" else ())
        B.place(tmp, trial, circuit, board_dir)
        pos = {}
        for p in Board(tmp).pads:
            pos.setdefault((p.ref, p.num), (p.x, p.y))
        seen[k] = pos
    tmp.unlink()
    out = dict(fixed)
    for r, c in cons.items():
        best = None
        for k, pos in seen.items():
            if (r, c.pad) not in pos:
                raise ValueError(f"{r} has no pad {c.pad}")
            tx, ty = _point(c.target, pos)
            px, py = pos[(r, c.pad)]
            sx, sy = tx + c.dx - px, ty + c.dy - py              # shift that lands the pad
            if c.toward is not None:
                others = [(q, v) for (rr, q), v in pos.items() if rr == r and q != c.pad]
                far = max(others, key=lambda qv: math.dist(qv[1], (px, py)))[1] if others else (px, py)
                wx, wy = _point(c.toward, pos)
                cost = math.hypot(far[0] + sx - wx, far[1] + sy - wy)
            else:
                cost = 0.0 if k == (c.rot or 0) % 360 else 1e9
            if best is None or cost < best[0]:
                best = (cost, round(10.0 + sx, 3), round(10.0 + sy, 3), k)
        out[r] = (best[1], best[2], best[3]) + (("B",) if c.side == "B" else ())
        print(f"placed {r}: {out[r]}")
    return out


# ---- clear placement: what a moved part would touch, and where it would not ----

def _copper_layers(layers, all_cu: list[str]) -> set[str]:
    out = set()
    for ly in layers:
        out |= set(all_cu) if ly == "*.Cu" else ({ly} if ly.endswith(".Cu") else set())
    return out


def _courtyard(fp):
    """A footprint's courtyard as a shapely polygon in its own frame (None if it
    has none): the outline its CrtYd lines, rects, circles and polygons close."""
    from shapely.geometry import LineString, Point, Polygon, box
    from shapely.ops import polygonize, unary_union
    lines, areas = [], []
    for g in fp.graphics:
        if not str(g.layer or "").endswith("CrtYd"):
            continue
        k = g.graphic_type
        if k == "rect" and g.start and g.end:
            areas.append(box(*map(min, zip(g.start, g.end)), *map(max, zip(g.start, g.end))))
        elif k == "circle" and g.center:
            r = g.radius or (math.dist(g.center, g.end) if g.end else 0)
            areas.append(Point(g.center).buffer(r))
        elif k in ("poly", "polygon") and len(g.points or []) >= 3:
            areas.append(Polygon(g.points))
        elif k == "arc" and g.start and g.mid and g.end:
            lines.append(LineString([g.start, g.mid, g.end]))
        elif g.start and g.end:
            lines.append(LineString([g.start, g.end]))
    areas += list(polygonize(lines))
    return unary_union(areas) if areas else None


def _pad_shape(p):
    """A pad's copper outline (shapely), from its shape, size and angle."""
    from shapely import affinity
    from shapely.geometry import LineString, Point, box
    w, h = p.w, p.h
    if p.shape == "circle":
        s = Point(p.x, p.y).buffer(w / 2)
    elif p.shape == "oval":
        r, d = min(w, h) / 2, abs(w - h) / 2
        s = LineString([(p.x - d, p.y), (p.x + d, p.y)] if w >= h else [(p.x, p.y - d), (p.x, p.y + d)]).buffer(r)
    elif p.shape == "roundrect" and p.rratio > 0:
        r = p.rratio * min(w, h)
        s = box(p.x - w / 2 + r, p.y - h / 2 + r, p.x + w / 2 - r, p.y + h / 2 - r).buffer(r)
    else:                                                    # rect, and the box round anything else
        s = box(p.x - w / 2, p.y - h / 2, p.x + w / 2, p.y + h / 2)
    return affinity.rotate(s, -p.angle, origin=(p.x, p.y)) if p.angle else s


class Clearance:
    """The board's copper and courtyards as shapely shapes, to test a part's
    pads and courtyard against everything except the part itself. Shapes are in
    the model's board-relative millimetres; clearances come from the project's
    net classes (route.net_classes), 0.2 mm where there is no project."""

    def __init__(self, b: Board, project=None):
        from shapely import STRtree, affinity
        from shapely.geometry import LineString, Point, Polygon

        from .route import net_classes
        self.b, self.affinity = b, affinity
        cls = net_classes(b, project)
        self.gap = lambda net: (cls(net) or {}).get("clearance", 0.2) if net else 0.2
        self.edge = (cls("") or {}).get("edge", 0.3)
        cu = b.layers
        self.items = []                                      # (ref or None, net, copper layers, shape)
        for p in b.pads:
            self.items.append((p.ref, p.net, _copper_layers(p.layers, cu), _pad_shape(p)))
        for t in b.tracks:
            self.items.append((None, t.net, {t.layer}, LineString(t.pts).buffer(t.width / 2)))
        for v in b.vias:
            self.items.append((None, v.net, set(cu), Point(v.x, v.y).buffer(v.size / 2)))
        self.tree = STRtree([s for *_, s in self.items])
        self.reach = max([self.gap(net) for _r, net, _l, _s in self.items] + [0.2])
        self.fps = {}                                        # ref -> (side, position, rotation, courtyard)
        for fp in b.pcb.footprints:
            fx, fy = fp.position
            yard = _courtyard(fp)
            if yard is not None:
                yard = affinity.translate(affinity.rotate(yard, -(fp.rotation or 0), origin=(0, 0)), fx, fy)
            self.fps[fp.reference] = ("B" if (fp.layer or "").startswith("B") else "F", (fx, fy), fp.rotation or 0, yard)
        outline = list(b.pcb.get_board_outline() or [])
        self.inside = Polygon(outline).buffer(-self.edge) if len(outline) >= 3 else None

    def _moved(self, ref: str, at: tuple | None):
        """ref's pads and courtyard, where it is or at (x, y, rot)."""
        side, (fx, fy), r0, yard = self.fps[ref]
        pads = [(net, ly, s) for rr, net, ly, s in self.items if rr == ref]
        if at is None:
            return pads, yard
        x, y, r = at
        def move(s):
            return self.affinity.translate(self.affinity.rotate(self.affinity.translate(s, -fx, -fy), r0 - r, origin=(0, 0)), x, y)
        return [(net, ly, move(s)) for net, ly, s in pads], (move(yard) if yard is not None else None)

    def clashes(self, ref: str, at: tuple | None = None, first: bool = False) -> list[str]:
        """What ref's pads and courtyard touch, where it is or at (x, y, rot)."""
        pads, yard = self._moved(ref, at)
        out = []
        for net, ly, s in pads:
            for i in self.tree.query(s.buffer(self.reach)):
                other, onet, oly, os = self.items[i]
                if other == ref or not (ly & oly) or (net and onet == net):
                    continue
                gap = max(self.gap(net), self.gap(onet))
                if s.distance(os) < gap - 1e-6:
                    what = f"{other}'s pad on {onet or 'no net'}" if other else f"{onet or 'unnamed'} copper"
                    out.append(f"{ref}'s pad on {net or 'no net'} is {s.distance(os):.2f} mm from {what} (needs {gap:g})")
                    if first:
                        return out
        side = self.fps[ref][0]
        if yard is not None:
            for other, (oside, _p, _r, oyard) in self.fps.items():
                if other != ref and oside == side and oyard is not None and yard.intersection(oyard).area > 1e-6:
                    out.append(f"{ref} courtyard overlaps {other}'s")
                    if first:
                        return out
        if self.inside is not None:                           # copper to board edge, as KiCad checks it
            for _net, _ly, s in pads:
                if not self.inside.contains(s):
                    out.append(f"{ref} has a pad within {self.edge:g} mm of the board edge or outside it")
                    if first:
                        return out
                    break
        return out

    def free(self, ref: str, near: tuple[float, float] | None = None, step: float = 0.25, n: int = 8) -> list[tuple]:
        """Up to n spots (x, y, rot), nearest `near` first, where ref clears everything."""
        x0, y0, x1, y1 = self.b.bbox
        cx, cy = near if near else ((x0 + x1) / 2, (y0 + y1) / 2)
        cands = [(x0 + i * step, y0 + j * step) for i in range(int((x1 - x0) / step) + 1) for j in range(int((y1 - y0) / step) + 1)]
        cands.sort(key=lambda p: math.hypot(p[0] - cx, p[1] - cy))
        out = []
        for x, y in cands:
            for r in (0, 90, 180, 270):
                if not self.clashes(ref, (round(x, 3), round(y, 3), r), first=True):
                    out.append((round(x, 3), round(y, 3), r))
                    break
            if len(out) >= n:
                break
        return out
