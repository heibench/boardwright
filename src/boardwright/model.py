"""One reader for any .kicad_pcb, generated here or drawn by hand.

The file is read as s-expressions, so it does not matter how it is indented,
and only what boardwright uses is taken from it: the copper layers, the
footprints (position, side, pads, texts, graphics), tracks and arcs, vias,
zones and their fill, the board's texts and graphics, the Edge.Cuts outline
and the setup's via tenting.

The board origin. Every board-relative coordinate boardwright prints or
accepts (`pads`, PLACE, TRACKS, VIAS, ZONES, MOVE, selections) is measured
from one point: the top-left corner of the bounding box of the board's
outline, that is of every top-level gr_line, gr_rect, gr_arc, gr_circle,
gr_poly and gr_curve whose own (layer ...) is Edge.Cuts. An arc counts with
the axis extremes of its circle that it reaches, a circle with its whole
bounding square, a curve with its extremes; stroke width does not count,
and neither do Edge.Cuts graphics inside footprints. A board with no
outline, or one whose outline cannot be read (a malformed point, a
collinear arc, any other kind of item on Edge.Cuts), has its origin at the
file's (0, 0). `origin` converts to file coordinates (file = relative +
origin), which is what text appended to the file needs. Footprint positions,
tracks, vias and zones are board-relative; the board's own texts and
graphics (`texts`, `graphics`) stay in file coordinates.

Versions. Files saved by KiCad 6 to 10 are read (versions 20211014 to
20260206; tested on KiCad 8, 9 and 10 files). A newer file is read as if
KiCad 10 had saved it, with a note on stderr, since KiCad's own checks judge
whatever is written from it. A file older than KiCad 6 (KiCad 5's
`(module ...)` syntax) is not read yet (exit 4, #78): open it in a newer KiCad
first.

The reading of each item, the origin rule and the outline chaining are
ported from kicad-tools 0.29.0 (kicad_tools/schema/pcb.py,
core/board_outline.py, core/arcs.py), which boardwright used to read boards
with, under its licence:

MIT License

Copyright (c) 2024 RJ Walters

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from functools import cached_property
from pathlib import Path

from .errors import EnvironmentFault

# The (version N) of the first file KiCad 6 saved, and of KiCad 10's.
KICAD6, NEWEST = 20211014, 20260206


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
    shape: str = "rect"     # KiCad's pad shape: rect, circle, oval, roundrect, ...
    rratio: float = 0.0     # roundrect corner radius as a fraction of the shorter side

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
    tenting: tuple[str | None, str | None] = (None, None)   # the via's own (front, back): yes, no, none or unset


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


# ---- s-expressions ---------------------------------------------------------
# A node is a list, [head, child, ...]; an atom is a str, a _Q when it was quoted.

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+')


class _Q(str):
    """A quoted string: a name, never a number."""


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r"}     # any other escaped character stands for itself


def _tree(text: str) -> list:
    stack: list[list] = [[]]
    for tok in _TOKEN.findall(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            if len(stack) < 2:
                raise ValueError("unbalanced parentheses")
            node = stack.pop()
            stack[-1].append(node)
        elif tok[0] == '"':
            stack[-1].append(_Q(re.sub(r"\\(.)", lambda m: _ESCAPES.get(m[1], m[1]), tok[1:-1], flags=re.S)))
        else:
            stack[-1].append(tok)
    if len(stack) != 1 or not stack[0] or not isinstance(stack[0][0], list):
        raise ValueError("unbalanced parentheses")
    return stack[0][0]


def _kid(node, head: str):
    """The first direct child with this head."""
    return next((c for c in node[1:] if isinstance(c, list) and c and c[0] == head), None)


def _find(node, head: str):
    """The first descendant with this head, depth first in file order (how
    kicad-tools looks up most fields, so a pad's (net) is found where it is)."""
    stack = node[:0:-1]
    while stack:
        c = stack.pop()
        if isinstance(c, list) and c:
            if c[0] == head:
                return c
            stack.extend(c[:0:-1])
    return None


def _find_all(node, head: str) -> list:
    out, stack = [], node[:0:-1]
    while stack:
        c = stack.pop()
        if isinstance(c, list) and c:
            if c[0] == head:
                out.append(c)
            stack.extend(c[:0:-1])
    return out


def _f(node, i: int = 0) -> float | None:
    """The i-th value after the head as a number, None if it is not one."""
    if node is None or len(node) <= i + 1 or isinstance(node[i + 1], list):
        return None
    try:
        return float(node[i + 1])
    except ValueError:
        return None


def _s(node, i: int = 0) -> str | None:
    if node is None or len(node) <= i + 1 or isinstance(node[i + 1], list):
        return None
    return str(node[i + 1])


def _int(v) -> int | None:
    """An unquoted whole number (a net number); a quoted one is a name."""
    return int(v) if isinstance(v, str) and not isinstance(v, _Q) and re.fullmatch(r"-?\d+", v) else None


def _xy(node) -> tuple[float, float]:
    return (_f(node, 0) or 0.0, _f(node, 1) or 0.0)


def _net(node) -> tuple[int, str]:
    """A (net ...) as (number, name): (net N "name"), (net N) or KiCad 10's (net "name")."""
    if node is None or len(node) < 2:
        return 0, ""
    n = _int(node[1])
    return (n, _s(node, 1) or "") if n is not None else (0, _s(node, 0) or "")


# ---- what is read ------------------------------------------------------------

@dataclass
class Text:
    """A footprint's fp_text or Reference/Value property, or a board's gr_text."""
    text_type: str | None       # reference, value, user; None for a board text
    text: str
    position: tuple[float, float]       # footprint-local, or file coordinates for a board text
    rotation: float                     # the board-frame angle, as the file has it
    layer: str
    font_size: tuple[float, float]
    font_thickness: float
    hidden: bool


@dataclass
class Graphic:
    """fp_line/rect/circle/arc/poly in footprint coordinates, or a board's
    gr_line/rect/circle/arc/poly in file coordinates."""
    graphic_type: str
    layer: str
    stroke_width: float
    start: tuple[float, float] = (0.0, 0.0)
    end: tuple[float, float] = (0.0, 0.0)
    mid: tuple[float, float] | None = None
    center: tuple[float, float] | None = None
    radius: float | None = None         # footprint circles only
    points: list[tuple[float, float]] = field(default_factory=list)
    fill: str = ""                      # yes/no (KiCad 7+), solid/none (older)

    @property
    def is_filled(self) -> bool:
        return self.fill.strip().lower() in ("yes", "solid", "true")


@dataclass
class FootprintPad:
    """A pad as its footprint holds it: position footprint-local, angle board-frame."""
    number: str
    type: str
    shape: str
    position: tuple[float, float]
    size: tuple[float, float]
    rotation: float
    layers: list[str]
    net: str
    drill: float
    solder_mask_margin: float | None
    roundrect_rratio: float


@dataclass
class Footprint:
    name: str
    reference: str
    uuid: str
    position: tuple[float, float]       # board-relative
    rotation: float
    layer: str
    pads: list[FootprintPad]
    texts: list[Text]
    graphics: list[Graphic]
    net_tie: bool = False               # KiCad's net_tie_pad_groups: a footprint that joins two nets on purpose


def _arc_of(node):
    """start, mid, end of a graphic arc. KiCad 6 and newer write the three;
    KiCad 5's centre-and-angle arcs are not read, as KiCad 5 files are refused."""
    return tuple(_xy(c) if (c := _find(node, k)) is not None else (0.0, 0.0) for k in ("start", "mid", "end"))


def _text(node, text_type, text: str, prop: bool = False) -> Text:
    t = Text(text_type, text, (0.0, 0.0), 0.0, "", (1.0, 1.0), 0.15, False)
    if (at := _find(node, "at")) is not None:
        t.position, t.rotation = _xy(at), _f(at, 2) or 0.0
    if (layer := _find(node, "layer")) is not None:
        t.layer = _s(layer) or ""
    if prop and (hide := _find(node, "hide")) is not None:
        t.hidden = _s(hide) == "yes"
    if (effects := _find(node, "effects")) is not None:
        if _find(effects, "hide") is not None:
            t.hidden = True
        if (font := _find(effects, "font")) is not None:
            if (size := _find(font, "size")) is not None:
                w = _f(size, 0) or 1.0
                t.font_size = (w, _f(size, 1) or w)
            if (th := _find(font, "thickness")) is not None:
                t.font_thickness = _f(th) or 0.15
    return t


def _graphic(node, kind: str, in_footprint: bool) -> Graphic:
    g = Graphic(kind, "", 0.0)
    if (layer := _find(node, "layer")) is not None:
        g.layer = _s(layer) or ""
    if (stroke := _find(node, "stroke")) is not None and (w := _find(stroke, "width")) is not None:
        g.stroke_width = _f(w) or 0.0
    if (start := _find(node, "start")) is not None:
        g.start = _xy(start)
    end = _find(node, "end")
    if end is not None:
        g.end = _xy(end)
    if kind == "arc":
        g.start, g.mid, g.end = _arc_of(node)
    if (center := _find(node, "center")) is not None:
        g.center = _xy(center)
    if in_footprint and kind == "circle" and g.center is not None and end is not None:
        g.radius = math.hypot(g.end[0] - g.center[0], g.end[1] - g.center[1])
    if kind == "poly" and (pts := _find(node, "pts")) is not None:
        g.points = [_xy(xy) for xy in _find_all(pts, "xy")]
        if not in_footprint and g.points:
            g.start = g.points[0]
    if (fill := _find(node, "fill")) is not None:
        g.fill = _s(fill) or ""
    return g


def _pad(node, names: dict[int, str]) -> FootprintPad:
    at, size = _find(node, "at"), _find(node, "size")
    w = _f(size, 0) or 0.0 if size is not None else 0.0
    rr = _f(_find(node, "roundrect_rratio"))
    layers = _find(node, "layers")
    num, name = _net(_find(node, "net"))
    drill = _find(node, "drill")
    mask = _find(node, "solder_mask_margin")
    return FootprintPad(_s(node, 0) or "", _s(node, 1) or "", _s(node, 2) or "",
                        _xy(at) if at is not None else (0.0, 0.0),
                        (w, _f(size, 1) or w) if size is not None else (0.0, 0.0),
                        _f(at, 2) or 0.0 if at is not None else 0.0,
                        [a for a in layers[1:] if isinstance(a, str)] if layers is not None else [],
                        name or names.get(num, ""),
                        _f(drill) or 0.0 if drill is not None else 0.0,
                        _f(mask) if mask is not None else None,
                        rr if rr is not None else 0.25)


def _footprint(node, names: dict[int, str]) -> Footprint:
    layer, at, uuid = _kid(node, "layer"), _kid(node, "at"), _kid(node, "uuid")
    fp = Footprint(_s(node) or "", "", (_s(uuid) or "") if uuid is not None else "",
                   _xy(at) if at is not None else (0.0, 0.0), (_f(at, 2) or 0.0) if at is not None else 0.0,
                   (_s(layer) or "F.Cu") if layer is not None else "F.Cu", [], [], [])
    for n in _find_all(node, "fp_text"):                 # KiCad 7 and older
        t = _text(n, _s(n, 0) or "", _s(n, 1) or "")
        fp.texts.append(t)
        if t.text_type == "reference":
            fp.reference = t.text
    for n in _find_all(node, "property"):                # KiCad 8 and newer
        if _s(n, 0) == "Reference":
            fp.reference = _s(n, 1) or ""
            fp.texts.append(_text(n, "reference", fp.reference, prop=True))
        elif _s(n, 0) == "Value":
            fp.texts.append(_text(n, "value", _s(n, 1) or "", prop=True))
    fp.pads = [_pad(n, names) for n in _find_all(node, "pad")]
    fp.net_tie = _kid(node, "net_tie_pad_groups") is not None
    fp.graphics = [_graphic(n, kind, True) for kind in ("line", "rect", "circle", "arc", "poly")
                   for n in _find_all(node, f"fp_{kind}")]
    return fp


def _zone(node, names: dict[int, str]):
    """(net, layers, priority, keepout, outline, [(layer, fill polygon), ...]) in file coordinates.

    Most fields are the first of their name anywhere in the zone, as kicad-tools
    reads them: a zone's own (layer) comes before its fills'."""
    first: dict[str, list] = {}
    stack = node[:0:-1]
    while stack:
        c = stack.pop()
        if isinstance(c, list) and c:
            first.setdefault(c[0], c)
            stack.extend(c[:0:-1])
    num, name = _net(first.get("net"))
    if (nn := first.get("net_name")) is not None:
        name = _s(nn) or ""
    name = name or names.get(num, "")
    layer = _s(first.get("layer")) or ""
    layers = [str(a) for a in first["layers"][1:] if isinstance(a, str) and a] if "layers" in first else []
    layer = layer or (layers[0] if layers else "")
    prio = first.get("priority")
    priority = (_int(prio[1]) if len(prio) > 1 else None) or 0 if prio is not None else 0

    def points(poly):
        pts = _find(poly, "pts")
        return [_xy(xy) for xy in _find_all(pts, "xy")] if pts is not None else []
    outline = points(first["polygon"]) if "polygon" in first else []
    fills = []
    for fp in _find_all(node, "filled_polygon"):
        if pts := points(fp):
            fills.append((_s(_find(fp, "layer")) or layer, pts))
    return name, layers or ([layer] if layer else []), priority, "keepout" in first, outline, fills


# ---- the board outline -------------------------------------------------------

def _edge_items(root):
    """The board's own graphics drawn on Edge.Cuts (by their own (layer ...))."""
    for node in root[1:]:
        if isinstance(node, list) and node and str(node[0]).startswith("gr_") and _s(_kid(node, "layer")) == "Edge.Cuts":
            yield node


def _point(node, head: str):
    """A coordinate the outline needs; ValueError when it is missing or not two numbers."""
    c = _kid(node, head)
    if c is None or len(c) != 3 or (x := _f(c, 0)) is None or (y := _f(c, 1)) is None \
            or not math.isfinite(x) or not math.isfinite(y):
        raise ValueError(f"Edge.Cuts {node[0]}: bad or missing {head}")
    return x, y


def _arc_extremes(s, m, e) -> list:
    """s, m, e and the axis extremes of their circle that the arc reaches."""
    bx, by, cx, cy = m[0] - s[0], m[1] - s[1], e[0] - s[0], e[1] - s[1]
    det = 2.0 * (bx * cy - by * cx)
    if math.isnan(det) or abs(det) < 1e-12:
        raise ValueError("Edge.Cuts gr_arc: collinear arc points")
    b2, c2 = bx * bx + by * by, cx * cx + cy * cy
    ux, uy = s[0] + (cy * b2 - by * c2) / det, s[1] + (bx * c2 - cx * b2) / det
    r = math.hypot(s[0] - ux, s[1] - uy)
    if not math.isfinite(r):
        raise ValueError("Edge.Cuts gr_arc: no circle through its points")
    a0, am, ae = (math.atan2(p[1] - uy, p[0] - ux) for p in (s, m, e))
    to_mid, to_end = (am - a0) % math.tau, (ae - a0) % math.tau
    ccw = to_mid <= to_end                  # the way that reaches mid before end
    if to_end == 0.0:
        sweep, ccw = math.tau, True         # start and end meet: the whole circle
    else:
        sweep = to_end if ccw else (a0 - ae) % math.tau
    out = [s, m, e]
    for a in (0.0, math.pi / 2.0, math.pi, 3.0 * math.pi / 2.0):
        if ((a - a0 if ccw else a0 - a) % math.tau) <= sweep + 1e-12:
            out.append((ux + r * math.cos(a), uy + r * math.sin(a)))
    return out


def _flat_closed_curve(pts) -> bool:
    """A cubic that closes along one line and so encloses nothing (exact arithmetic)."""
    if len(pts) != 4 or pts[0] != pts[-1]:
        return False
    if len(set(pts)) <= 2:
        return True
    (ox, oy), (x1, y1), (x2, y2) = [(Fraction(x), Fraction(y)) for x, y in pts[:3]]
    return (x1 - ox) * (y2 - oy) == (y1 - oy) * (x2 - ox)


def _curve_extremes(p) -> list:
    if len(p) != 4:
        raise ValueError("Edge.Cuts gr_curve: expected four control points")
    ts = {0.0, 1.0}
    for k in (0, 1):
        p0, p1, p2, p3 = (q[k] for q in p)
        a, b, c = -p0 + 3 * p1 - 3 * p2 + p3, 2 * (p0 - 2 * p1 + p2), p1 - p0
        if abs(a) < 1e-12:
            roots = [-c / b] if abs(b) >= 1e-12 else []
        else:
            d = b * b - 4 * a * c
            roots = [(-b + sg * math.sqrt(d)) / (2 * a) for sg in (-1, 1)] if d >= 0 else []
        ts.update(t for t in roots if 0 < t < 1)
    ws = lambda t: ((1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3)
    return [(sum(w * q[0] for w, q in zip(ws(t), p)), sum(w * q[1] for w, q in zip(ws(t), p))) for t in ts]


def _outline_bounds(root):
    """(x0, y0, x1, y1) of the Edge.Cuts outline in file coordinates, None if
    there is none; ValueError if it cannot be read. See the module docstring."""
    pts = []
    for node in _edge_items(root):
        kind = node[0]
        if kind in ("gr_rect", "gr_line"):
            pts += [_point(node, "start"), _point(node, "end")]
        elif kind == "gr_arc":
            pts += _arc_extremes(_point(node, "start"), _point(node, "mid"), _point(node, "end"))
        elif kind == "gr_circle":
            (cx, cy), end = _point(node, "center"), _point(node, "end")
            r = math.dist((cx, cy), end)
            pts += [(cx - r, cy - r), (cx + r, cy + r)]
        elif kind in ("gr_poly", "gr_curve"):
            p = _kid(node, "pts")
            chain = []
            for xy in (_kids_xy(p) if p is not None else []):
                if len(xy) != 3 or (x := _f(xy, 0)) is None or (y := _f(xy, 1)) is None \
                        or not math.isfinite(x) or not math.isfinite(y):
                    raise ValueError(f"Edge.Cuts {kind}: bad point")
                chain.append((x, y))
            if len(chain) < 3:
                raise ValueError(f"Edge.Cuts {kind}: missing points")
            if kind == "gr_curve" and _flat_closed_curve(chain):
                continue
            pts += _curve_extremes(chain) if kind == "gr_curve" else chain
        else:
            raise ValueError(f"unsupported Edge.Cuts item {kind}")
    if not pts:
        return None
    xs, ys = zip(*pts)
    return min(xs), min(ys), max(xs), max(ys)


def _kids_xy(node) -> list:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == "xy"]


def _close(a, b, tol: float) -> bool:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 < tol * tol


def contours(segments: list, tol: float = 0.01) -> list[list]:
    """The segments grouped by touching ends (within tol, in any order), each
    group chained into a closed ring, or [] for a group that does not close
    into one simple loop (an open or branched chain, or one with no area).

    The tolerance absorbs the sub-micron gaps exports leave between segments
    that are meant to meet (kicad-tools' 0.01 mm)."""
    n = len(segments)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i in range(n):
        si, ei = segments[i]
        for j in range(i + 1, n):
            sj, ej = segments[j]
            if _close(si, sj, tol) or _close(si, ej, tol) or _close(ei, sj, tol) or _close(ei, ej, tol):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [_ring(segments, idx, tol) for idx in groups.values()]


def _ring(segments, idx: list[int], tol: float) -> list:
    if len(idx) < 3:
        return []
    for i in idx:                       # every end meets exactly one other end
        a, b = segments[i]
        if _close(a, b, tol):
            return []
        for p in (a, b):
            if sum(_close(p, q, tol) for j in idx if j != i for q in segments[j]) != 1:
                return []
    ring = [segments[idx[0]][0], segments[idx[0]][1]]
    rest = set(idx) - {idx[0]}
    while rest:
        cur = ring[-1]
        for i in rest:
            a, b = segments[i]
            if _close(cur, a, tol) or _close(cur, b, tol):
                ring.append(b if _close(cur, a, tol) else a)
                rest.discard(i)
                break
        else:
            break
    if rest or not _close(ring[-1], ring[0], tol):
        return []
    ring[-1] = ring[0]
    ox, oy = ring[0]
    twice_area = sum((a[0] - ox) * (b[1] - oy) - (b[0] - ox) * (a[1] - oy) for a, b in zip(ring, ring[1:]))
    return [] if abs(twice_area) <= tol * tol else ring


def _rect_segments(s, e) -> list:
    (x1, y1), (x2, y2) = s, e
    return [((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))]


_warned: set[str] = set()


class Board:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        try:
            root = _tree(self.path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise EnvironmentFault(f"{self.path}: not a readable KiCad board ({e})") from e
        if root[0] != "kicad_pcb":
            raise EnvironmentFault(f"{self.path}: not a KiCad board (it starts with {str(root[0])!r})")
        v = _kid(root, "version")
        self.version = _int(v[1]) if v is not None and len(v) > 1 else None
        if self.version is not None and self.version < KICAD6:
            raise EnvironmentFault(f"{self.path}: saved by KiCad 5 or older (version {self.version}); "
                                   "boardwright does not read KiCad 5 boards yet (#78). Open it in KiCad 6 or newer and save it first.")
        if self.version is not None and self.version > NEWEST and str(self.path) not in _warned:
            _warned.add(str(self.path))
            print(f"note: {self.path.name} was saved by a KiCad newer than 10 (version {self.version}); "
                  "it is read as KiCad 10 reads it", file=sys.stderr)
        self._root = root
        names = {}
        for n in root[1:]:
            if isinstance(n, list) and n and n[0] == "net" and len(n) > 1:
                names[_int(n[1]) or 0] = _s(n, 1) or ""
        try:
            b = _outline_bounds(root)
        except ValueError:                      # an outline that cannot be read gives no origin
            b = None
        self.origin: tuple[float, float] = (b[0], b[1]) if b else (0.0, 0.0)
        ox, oy = self.origin
        rel = (lambda p: (p[0] - ox, p[1] - oy)) if (ox, oy) != (0.0, 0.0) else (lambda p: p)
        self.footprints: list[Footprint] = []
        self.texts: list[Text] = []            # board texts and graphics, in file coordinates
        self.graphics: list[Graphic] = []
        self._segments, self._arcs, self._vias, self._zones = [], [], [], []
        copper: dict[int, tuple[str, str]] = {}
        self.tenting: tuple[bool | None, bool | None] = (None, None)
        for n in root[1:]:
            if not (isinstance(n, list) and n):
                continue
            head = n[0]
            if head in ("footprint", "module"):
                fp = _footprint(n, names)
                fp.position = rel(fp.position)
                self.footprints.append(fp)
            elif head in ("segment", "arc"):
                width, layer = _find(n, "width"), _find(n, "layer")
                num, name = _net(_find(n, "net"))
                ends = [rel(_xy(c)) if (c := _find(n, k)) is not None else rel((0.0, 0.0))
                        for k in (("start", "mid", "end") if head == "arc" else ("start", "end"))]
                (self._arcs if head == "arc" else self._segments).append(
                    (ends, (_f(width) or 0.0) if width is not None else 0.0, _s(layer) or "", name or names.get(num, "")))
            elif head == "via":
                self._vias.append(self._via(n, names, rel))
            elif head == "zone":
                name, layers, prio, keepout, outline, fills = _zone(n, names)
                self._zones.append((name, layers, prio, keepout, [rel(p) for p in outline],
                                    [(ly, [rel(p) for p in pts]) for ly, pts in fills]))
            elif head in ("gr_line", "gr_arc", "gr_rect", "gr_circle", "gr_poly"):
                self.graphics.append(_graphic(n, head[3:], False))
            elif head == "gr_text":
                self.texts.append(_text(n, None, _s(n, 0) or ""))
            elif head == "layers":
                for c in n[1:]:
                    if isinstance(c, list) and c and _int(c[0]) is not None:
                        copper[_int(c[0])] = (_s(c, 0) or "", _s(c, 1) or "user")
            elif head == "setup" and (t := _find(n, "tenting")) is not None:
                self.tenting = tuple((_s(s) == "yes") if (s := _find(t, side)) is not None and _s(s) in ("yes", "no")
                                     else None for side in ("front", "back"))
        # KiCad's copper layer types; kicad-tools 0.29 left out mixed
        self.layers: list[str] = [name for name, kind in copper.values() if kind in ("signal", "power", "mixed")]

    @staticmethod
    def _via(n, names, rel) -> Via:
        kind = n[1] if len(n) > 1 and isinstance(n[1], str) and n[1] in ("micro", "blind", "buried") else None
        at, size, drill, layers = _find(n, "at"), _find(n, "size"), _find(n, "drill"), _find(n, "layers")
        ls = [a for a in layers[1:] if isinstance(a, str)] if layers is not None else []
        # KiCad drills a via with no blind/buried/micro word through the board,
        # whatever copper pair it names (kicad-tools measured it on kicad-cli 10.0.6)
        cu = re.compile(r"F\.Cu|B\.Cu|In([1-9]|[12]\d|30)\.Cu")
        if kind is None and len(ls) == 2 and all(cu.fullmatch(l) for l in ls) and set(ls) != {"F.Cu", "B.Cu"}:
            ls = ["F.Cu", "B.Cu"]
        tent = _find(n, "tenting")
        num, name = _net(_find(n, "net"))
        x, y = rel(_xy(at) if at is not None else (0.0, 0.0))
        return Via(x, y, (_f(size) or 0.0) if size is not None else 0.0, (_f(drill) or 0.0) if drill is not None else 0.0,
                   ls, name or names.get(num, ""),
                   tuple(_s(_find(tent, side)) if tent is not None and _find(tent, side) is not None else None
                         for side in ("front", "back")))

    @cached_property
    def pads(self) -> list[Pad]:
        out = []
        for fp in self.footprints:
            fx, fy = fp.position
            r = math.radians(fp.rotation or 0)
            for p in fp.pads:
                px, py = p.position
                x = fx + px * math.cos(r) + py * math.sin(r)
                y = fy - px * math.sin(r) + py * math.cos(r)
                out.append(Pad(fp.reference, p.number, p.net, round(x, 4), round(y, 4),
                               fp.layer, p.size[0], p.size[1], (p.rotation or 0),
                               p.type.startswith(("thru", "np_thru")), list(p.layers),
                               p.shape or "rect", p.roundrect_rratio or 0.0))
        return out

    @cached_property
    def tracks(self) -> list[Track]:
        out = [Track(list(ends), width, layer, net) for ends, width, layer, net in self._segments]
        for ends, width, layer, net in self._arcs:
            out.append(Track(_arc_points(*ends), width, layer, net))
        return out

    @cached_property
    def vias(self) -> list[Via]:
        return list(self._vias)

    @cached_property
    def zones(self) -> list[Zone]:
        out = []
        for net, layers, prio, keepout, outline, fills in self._zones:
            zn = Zone(net, layers, prio, keepout, outline)
            for layer, poly in fills:
                zn.fills.setdefault(layer or (layers[0] if layers else ""), []).append(poly)
            out.append(zn)
        return out

    @cached_property
    def outline_segments(self) -> list:
        """Edge.Cuts lines, arcs (as two segments, through their mid) and rects as
        board-relative segments ((x1, y1), (x2, y2))."""
        return [tuple(self._rel(p) for p in s) for s in self._edge_segments(polys=False)]

    @cached_property
    def outline(self) -> list[tuple[float, float]]:
        """The board's outline as a closed ring of board-relative points: of the
        closed contours on Edge.Cuts, the one with the largest bounding box (the
        rest are cutouts or marks). Arcs count as start-mid-end; [] if none closes."""
        best, area = [], -1.0
        for ring in contours(self._edge_segments(polys=True)):
            if ring:
                xs, ys = [p[0] for p in ring], [p[1] for p in ring]
                a = (max(xs) - min(xs)) * (max(ys) - min(ys))
                if a > area:
                    best, area = ring, a
        return [self._rel(p) for p in best]

    def _rel(self, p):
        ox, oy = self.origin
        return (p[0] - ox, p[1] - oy) if (ox, oy) != (0.0, 0.0) else p

    def _edge_segments(self, polys: bool) -> list:
        """Edge.Cuts as segments in file coordinates: lines, arcs, rects and,
        with polys, the top-level gr_poly and gr_curve point chains, closed."""
        edge = [g for g in self.graphics if g.layer == "Edge.Cuts"]
        segs = [(g.start, g.end) for g in edge if g.graphic_type == "line"]
        for g in edge:
            if g.graphic_type == "arc":
                segs += [(g.start, g.mid), (g.mid, g.end)]
        for g in edge:
            if g.graphic_type == "rect":
                segs += _rect_segments(g.start, g.end)
        if polys:
            for n in self._root[1:]:
                if isinstance(n, list) and n and n[0] in ("gr_poly", "gr_curve") and _s(_kid(n, "layer")) == "Edge.Cuts":
                    chain = [(x, y) for pts in _find_all(n, "pts") for xy in _kids_xy(pts)
                             if (x := _f(xy, 0)) is not None and (y := _f(xy, 1)) is not None]
                    if n[0] == "gr_curve" and _flat_closed_curve(chain):
                        continue
                    segs += list(zip(chain, chain[1:]))
                    if len(chain) >= 3:
                        segs.append((chain[-1], chain[0]))
        return segs

    @cached_property
    def bbox(self) -> tuple[float, float, float, float]:
        pts = list(self.outline)
        if not pts:
            pts = [(p.x, p.y) for p in self.pads]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    @cached_property
    def area(self) -> float:
        pts = list(self.outline)
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
    def net_graph(self, net: str, via_len: float = 0.0) -> dict:
        """The net's routed copper as a graph: track ends and via layers as
        (x, y, layer) nodes, each pad of the net as ("pad", ref, num). Edges are
        (node, mm, kind), kind "t" track, "v" via barrel, "p" pad to copper.
        Pours are not followed."""
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
                if node[0] != "pad" and p.on(node[2]) and math.hypot(node[0] - p.x, node[1] - p.y) <= p.reach + 0.05:
                    link(tag, node, math.hypot(node[0] - p.x, node[1] - p.y), "p")
        for p in self.pads:                      # other pads of the net join layers and track ends
            if p.net == net:
                attach(p, ("pad", p.ref, p.num))
        return g

    def route_path(self, a: str, b: str, via_len: float = 0.0):
        """Shortest routed length from pad a to pad b ('U1.3'); None if not joined by tracks.

        Returns (length_mm, vias, layers_used). Pours are not followed: a net that
        relies on a zone for the connection has no track path.
        """
        import heapq
        pa, pb = self.pad(a), self.pad(b)
        g = self.net_graph(pa.net, via_len)
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
