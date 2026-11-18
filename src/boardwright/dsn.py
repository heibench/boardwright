"""The board as Freerouting reads it: a Specctra DSN.

What is written, in kicad-tools 0.29's layout (`kct pcb export-dsn`, which this
replaces), all in um at a resolution of 0.1 um:

- structure: the copper layers front to back; the board outline from Edge.Cuts,
  inset by the project's min_copper_edge_clearance, its cutouts as keepouts;
  the Default class's width and clearance; each copper zone as a plane of its
  net; each rule area that bars tracks or vias as a keepout
- placement and library: one image per footprint (per library footprint, side
  and pad geometry), its pins on padstacks named by shape and size, NPTH holes
  as image keepouts, and a via padstack per via size in use
- network: every net with its pins, and the net classes of the .kicad_pro
  (width, clearance, via), each raised to the board minima of the .kicad_pro
  and the unconditional clearance, track_width and via_diameter rules of the
  .kicad_dru
- wiring: the board's arcs (as 12-segment polylines), tracks and vias, all
  protected, so Freerouting routes around them and treats their nets as joined

Not written, because Specctra has no form for it (kicad-tools listed these as
omissions and wrote the DSN anyway): conditional or layer-specific .kicad_dru
rules, hole and annular-ring minima, the pads, pour and footprint restrictions
of a rule area, zone outlines with arcs and zone holes, zones and Edge.Cuts
inside footprints. A net in several classes is given the one KiCad gives
priority to.
"""

# Ported from kicad-tools 0.29.0 (kicad_tools/export/dsn.py, the net-class part
# of kicad_tools/router/board_clearance_rules.py, and the custom-pad copper of
# kicad_tools/router/fixed_copper.py) under its licence:
#
# MIT License
#
# Copyright (c) 2024 RJ Walters
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from .copper import blocks
from .model import _arc_points

# KiCad's Default net class as kicad-tools 0.29 named and sized it when a board
# has no .kicad_pro (KiCadToDSNExporter's defaults), and KiCad's own Default
# clearance (board_clearance_rules.KICAD_DEFAULT_CLEARANCE_MM)
DEFAULT_CLASS = "kicad_default"
_NO_PROJECT = (0.25, 0.2, 0.8, 0.4)          # width, clearance, via diameter, via drill
_KICAD_CLEARANCE = 0.2
# The .kicad_dru constraint keywords and severities kicad-cli 10.0.1 accepts
# (kicad-tools board_clearance_rules, each probed against kicad-cli); any other
# makes KiCad ignore every rule in the file, so the export ignores them too.
_DRU_KEYWORDS = frozenset({
    "annular_width", "assertion", "bridged_mask", "clearance", "connection_width", "courtyard_clearance",
    "creepage", "diff_pair_gap", "diff_pair_uncoupled", "disallow", "edge_clearance", "hole_clearance",
    "hole_size", "hole_to_hole", "length", "mechanical_clearance", "mechanical_hole_clearance",
    "min_resolved_spokes", "physical_clearance", "physical_hole_clearance", "silk_clearance", "skew",
    "solder_mask_expansion", "solder_mask_sliver", "solder_paste_abs_margin", "solder_paste_rel_margin",
    "text_height", "text_thickness", "thermal_relief_gap", "thermal_spoke_width", "track_angle",
    "track_segment_length", "track_width", "via_count", "via_dangling", "via_diameter", "zone_connection",
})
_DRU_SEVERITIES = frozenset({"error", "warning", "ignore", "exclusion"})
_DRU_FLOORS = ("clearance", "track_width", "via_diameter")
# conditions true of every item a floor applies to (a DSN has no microvias)
_TRIVIAL = {
    "track_width": {"a.type=='track'"},
    "via_diameter": {"a.type=='via'", "a.type=='via'&&a.via_type!='micro'", "a.via_type!='micro'"},
}
# Edge.Cuts arcs and circles become chords within this distance of the curve,
# the tolerance kicad-tools 0.29 certified its outline tessellation to
_OUTLINE_ERROR = 1e-4
# a custom pad's circle anchor is a 256-gon scaled out to contain the circle
_ROUND_OUT = 1.0 / math.cos(math.pi / 256)


# -- reading the board --------------------------------------------------------

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+')


class _Q(str):
    """A quoted string: a name, never a number."""


def _tree(text: str) -> list:
    """The s-expression as nested lists: [head, child, ...], strings unquoted."""
    stack: list[list] = [[]]
    for tok in _TOKEN.findall(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            node = stack.pop()
            stack[-1].append(node)
        elif tok[0] == '"':
            stack[-1].append(_Q(re.sub(r"\\(.)", r"\1", tok[1:-1])))
        else:
            stack[-1].append(tok)
    return stack[0][0]


def _kid(node: list, head: str) -> list | None:
    return next((c for c in node[1:] if isinstance(c, list) and c and c[0] == head), None)


def _kids(node: list, head: str) -> list[list]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == head]


def _all(node: list, head: str) -> list[list]:
    """Every descendant with this head, in document order."""
    out = []
    for c in node[1:]:
        if isinstance(c, list) and c:
            if c[0] == head:
                out.append(c)
            out += _all(c, head)
    return out


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _xy(node: list | None) -> tuple[float, float]:
    return (_f(node[1]), _f(node[2])) if node and len(node) > 2 else (0.0, 0.0)


@dataclass
class Pad:
    number: str
    kind: str                   # smd, thru_hole, np_thru_hole, connect
    shape: str                  # rect, roundrect, oval, circle, trapezoid, custom
    x: float                    # in the footprint, mm
    y: float
    width: float
    height: float
    drill: float
    layers: list[str]
    net: str
    rratio: float = 0.0
    slot: tuple[float, float] | None = None
    rotation: float = 0.0       # degrees within the footprint
    node: list | None = None    # a custom pad's own block, for its primitives


@dataclass
class Footprint:
    ref: str
    lib: str
    layer: str
    x: float
    y: float
    rotation: float
    pads: list[Pad] = field(default_factory=list)


@dataclass
class NetClass:
    name: str
    width: float
    clearance: float
    via: float
    drill: float
    nets: list[str] = field(default_factory=list)


def _layers(text: str) -> list[str]:
    """The board's routable copper layers (signal, power, mixed), front to back."""
    s0, e0 = blocks(text, ("layers",))[0]
    found = re.findall(r'\(\d+ "([^"]*\.Cu)" (?:signal|power|mixed)\b', text[s0:e0])
    return sorted(found, key=lambda l: (0, 0) if l == "F.Cu" else (2, 0) if l == "B.Cu" else (1, int(l[2:-3])))


def _net_names(text: str) -> dict[str, str]:
    """Net number -> name, from every `(net N "name")` in the file."""
    return {n: name for n, name in re.findall(r'\(net (\d+) "((?:[^"\\]|\\.)*)"\)', text)}


def _net(node: list | None, names: dict[str, str]) -> str:
    """The net name of a `(net ...)`: (net "name"), (net N "name") or (net N)."""
    if not node or len(node) < 2:
        return ""
    if len(node) > 2:
        return node[2]
    return node[1] if isinstance(node[1], _Q) else names.get(node[1], "")


def _reference(fp: list) -> str:
    legacy = ""
    for c in fp[1:]:
        if not isinstance(c, list) or len(c) < 3:
            continue
        if c[0] == "property" and c[1] == "Reference":
            return c[2] or "?"
        if c[0] == "fp_text" and c[1] == "reference" and not legacy:
            legacy = c[2]
    return legacy or "?"


def _pad(node: list, fp_rotation: float, names: dict[str, str]) -> Pad | None:
    if len(node) < 4:
        return None
    at = _kid(node, "at")
    px, py = _xy(at)
    angle = _f(at[3]) if at and len(at) > 3 else 0.0
    size = _kid(node, "size")
    w, h = (_f(size[1]) or 1.0, _f(size[2]) or 1.0) if size and len(size) > 2 else (1.0, 1.0)
    drill, slot = 0.0, None
    d = _kid(node, "drill")
    if d and len(d) > 1:
        if d[1] == "oval":
            dims = [_f(v) for v in d[2:4] if not isinstance(v, list)]
            if len(dims) == 2 and all(dims):
                slot = (dims[0], dims[1])
                drill = min(slot)
        else:
            drill = _f(d[1])
    layers = _kid(node, "layers")
    rr = _kid(node, "roundrect_rratio")
    return Pad(node[1], node[2] or "smd", node[3] or "rect", px, py, w, h, drill,
               [l for l in (layers or [])[1:] if isinstance(l, str)], _net(_kid(node, "net"), names),
               _f(rr[1]) if rr and len(rr) > 1 else 0.0, slot, (angle - fp_rotation) % 360.0,
               node if node[3] == "custom" else None)


def _points(poly: list | None) -> list[tuple[float, float]] | None:
    """The (xy ...) of a `(polygon (pts ...))`; None if it has arcs."""
    pts = _kid(poly, "pts") if poly else None
    if pts is None:
        return []
    if _kid(pts, "arc"):
        return None
    return [_xy(p) for p in _kids(pts, "xy")]


# -- the board outline ----------------------------------------------------------

def _arc_chain(s, m, e) -> list[tuple[float, float]]:
    """A start-mid-end arc as chords within _OUTLINE_ERROR of it."""
    (x1, y1), (x2, y2), (x3, y3) = s, m, e
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        return [s, e]
    ux = ((x1 ** 2 + y1 ** 2) * (y2 - y3) + (x2 ** 2 + y2 ** 2) * (y3 - y1) + (x3 ** 2 + y3 ** 2) * (y1 - y2)) / d
    uy = ((x1 ** 2 + y1 ** 2) * (x3 - x2) + (x2 ** 2 + y2 ** 2) * (x1 - x3) + (x3 ** 2 + y3 ** 2) * (x2 - x1)) / d
    r = math.hypot(x1 - ux, y1 - uy)
    a1, a2, a3 = (math.atan2(y - uy, x - ux) for x, y in (s, m, e))
    ccw = (a2 - a1) % (2 * math.pi) < (a3 - a1) % (2 * math.pi)
    sweep = (a3 - a1) % (2 * math.pi) if ccw else -((a1 - a3) % (2 * math.pi))
    step = 2 * math.acos(max(-1.0, 1 - _OUTLINE_ERROR / r)) if r > _OUTLINE_ERROR else math.pi
    n = max(2, math.ceil(abs(sweep) / step))
    return [s] + [(ux + r * math.cos(a1 + sweep * i / n), uy + r * math.sin(a1 + sweep * i / n))
                  for i in range(1, n)] + [e]


def _cubic_chain(p: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """A Bezier as chords: halved until its control points are within _OUTLINE_ERROR of the chord."""
    def flat(q):
        (ax, ay), (bx, by) = q[0], q[3]
        L = math.hypot(bx - ax, by - ay)
        if L == 0:
            return all(math.hypot(x - ax, y - ay) <= _OUTLINE_ERROR for x, y in q)
        return all(abs((bx - ax) * (ay - y) - (ax - x) * (by - ay)) / L <= _OUTLINE_ERROR for x, y in q[1:3])

    def split(q, depth):
        if depth > 20 or flat(q):
            return [q[3]]
        mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        ab, bc, cd = mid(q[0], q[1]), mid(q[1], q[2]), mid(q[2], q[3])
        abc, bcd = mid(ab, bc), mid(bc, cd)
        m = mid(abc, bcd)
        return split([q[0], ab, abc, m], depth + 1) + split([m, bcd, cd, q[3]], depth + 1)
    return [p[0]] + split(p, 0)


def _outline_segments(root: list) -> list[tuple]:
    segs: list[tuple] = []
    for g in root[1:]:
        if not (isinstance(g, list) and g and g[0].startswith("gr_")):
            continue
        layer = _kid(g, "layer")
        if not layer or len(layer) < 2 or layer[1] != "Edge.Cuts":
            continue
        kind = g[0]
        if kind == "gr_line":
            segs.append((_xy(_kid(g, "start")), _xy(_kid(g, "end"))))
        elif kind == "gr_rect":
            a, b = _xy(_kid(g, "start")), _xy(_kid(g, "end"))
            c = [a, (b[0], a[1]), b, (a[0], b[1])]
            segs += list(zip(c, c[1:] + c[:1]))
        elif kind == "gr_poly":
            c = [_xy(p) for p in _kids(_kid(g, "pts") or ["pts"], "xy")]
            if len(c) < 3:
                raise ValueError("an Edge.Cuts polygon has fewer than 3 points")
            segs += list(zip(c, c[1:] + c[:1]))
        elif kind == "gr_arc" and _kid(g, "mid"):
            c = _arc_chain(_xy(_kid(g, "start")), _xy(_kid(g, "mid")), _xy(_kid(g, "end")))
            segs += list(zip(c, c[1:]))
        elif kind == "gr_curve":
            c = [_xy(p) for p in _kids(_kid(g, "pts") or ["pts"], "xy")]
            if len(c) != 4:
                raise ValueError("an Edge.Cuts curve does not have four points")
            c = _cubic_chain(c)
            segs += list(zip(c, c[1:]))
        elif kind == "gr_circle":
            (cx, cy), (ex, ey) = _xy(_kid(g, "center")), _xy(_kid(g, "end"))
            r = math.hypot(ex - cx, ey - cy)
            if r <= 0:
                raise ValueError("an Edge.Cuts circle has no radius")
            n = max(8, math.ceil(math.pi / math.acos(max(-1.0, 1 - _OUTLINE_ERROR / r))))
            c = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
            segs += list(zip(c, c[1:] + c[:1]))
        else:
            raise ValueError(f"Edge.Cuts {kind} is not a shape the outline is read from")
    return segs


def _outline(root: list) -> tuple[list, list]:
    """The board's outer ring and its cutouts, from the top-level Edge.Cuts graphics.

    The board is the face whose exterior encloses the most area; its holes,
    and closed loops inside it, are cutouts. An outline that does not close
    or cannot be read gives no boundary."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize_full, unary_union

    try:
        segs = _outline_segments(root)
    except ValueError:
        return [], []

    def snap(pt):
        return (round(pt[0], 3), round(pt[1], 3))      # 1 um: close endpoint micro-gaps

    lines = [LineString([snap(a), snap(b)]) for a, b in segs if snap(a) != snap(b)]
    if not lines:
        return [], []
    faces = polygonize_full(unary_union(lines))[0]
    faces = list(faces.geoms) if hasattr(faces, "geoms") else list(faces)
    if not faces:
        return [], []
    board = max(faces, key=lambda f: Polygon(f.exterior).area)
    shell = Polygon(board.exterior)
    cutouts = [Polygon(ring) for ring in board.interiors]
    for face in faces:
        if face is board:
            continue
        inside = face.representative_point()
        if shell.contains(inside) and not any(c.contains(inside) for c in cutouts):
            cutouts.append(Polygon(face.exterior))
    return list(board.exterior.coords)[:-1], [list(c.exterior.coords)[:-1] for c in cutouts if c.area > 0]


def _inset(outline: list, cutouts: list, edge: float) -> tuple[list, list]:
    """Move the boundary in, and the cutouts out, by the copper-to-edge clearance:
    Specctra has no edge rule, but a router keeps copper inside the boundary and
    out of keepouts."""
    if not outline or edge <= 0:
        return outline, cutouts
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    poly = Polygon(outline)
    if cutouts:
        poly = poly.difference(unary_union([Polygon(c) for c in cutouts]))
    inset = poly.buffer(-edge, join_style=2) if poly.is_valid else None
    if inset is None or inset.is_empty or inset.geom_type != "Polygon":
        return outline, cutouts
    return list(inset.exterior.coords)[:-1], [list(r.coords)[:-1] for r in inset.interiors]


# -- net classes ----------------------------------------------------------------

def _mm(raw, fallback: float) -> float:
    """A .kicad_pro / .kicad_dru length (a number or "0.2mm", "8mil", "0.01in") in mm."""
    if raw is None or isinstance(raw, bool):
        return fallback
    if isinstance(raw, int | float):
        v = float(raw)
    else:
        t, scale = str(raw).strip().lower(), 1.0
        if t.endswith("mm"):
            t = t[:-2]
        elif t.endswith("mil"):
            t, scale = t[:-3], 0.0254
        elif t.endswith("in"):
            t, scale = t[:-2], 25.4
        try:
            v = float(t) * scale
        except ValueError:
            return fallback
    return v if v >= 0 else fallback


def _dru_floors(path: Path) -> list[tuple[str, float]]:
    """(constraint, min) of every unconditional clearance, track_width and
    via_diameter rule in the .kicad_dru, or none if KiCad would ignore the file."""
    try:
        rules = _all(_tree("(rules " + path.read_text(errors="replace") + ")"), "rule")
    except (OSError, IndexError):
        return []
    out = []
    for rule in rules:
        sev = _kid(rule, "severity")
        severity = (str(sev[1]).casefold() if len(sev) > 1 else "") if sev else None
        if severity is not None and severity not in _DRU_SEVERITIES:
            return []
        cond, layer = _kid(rule, "condition"), _kid(rule, "layer")
        condition = cond[1] if cond and len(cond) > 1 else None
        for c in _all(rule, "constraint"):
            if len(c) < 2 or c[1] not in _DRU_KEYWORDS:
                return []
            low = _kid(c, "min")
            value = _mm(low[1], -1.0) if low and len(low) > 1 else -1.0
            if severity == "ignore" or c[1] not in _DRU_FLOORS or value < 0 or layer is not None:
                continue
            if condition is None or re.sub(r"\s+", "", condition).casefold() in _TRIVIAL.get(c[1], ()):
                out.append((c[1], value))
    return out


def _matches(pattern: str, net: str) -> bool:
    if fnmatch.fnmatchcase(net, pattern):
        return True
    try:
        return re.fullmatch(pattern, net) is not None
    except re.error:
        return False


def _project(pcb: Path) -> dict | None:
    try:
        project = json.loads(pcb.with_suffix(".kicad_pro").read_text())
    except (OSError, ValueError):
        return None
    return project if isinstance(project, dict) else None


def _rules(project: dict | None) -> dict:
    """The .kicad_pro's board rules (min_clearance, min_track_width, ...)."""
    board = (project or {}).get("board")
    ds = board.get("design_settings") if isinstance(board, dict) else None
    rules = ds.get("rules") if isinstance(ds, dict) else None
    return rules if isinstance(rules, dict) else {}


def net_classes(pcb: Path, nets: list[str]) -> dict[str, NetClass]:
    """The board's net classes as the DSN carries them, keyed by KiCad class
    name, Default first, each with its nets (from `nets`, in that order)."""
    project = _project(pcb)
    d = NetClass(DEFAULT_CLASS, *_NO_PROJECT)
    classes = {"Default": d}
    rules, settings, by_name = _rules(project), {}, {}
    if project is not None:
        settings = project.get("net_settings") if isinstance(project.get("net_settings"), dict) else {}
        # a project without classes: kicad-tools 0.29's Default (project_file.DEFAULT_NETCLASS_DEFINITION)
        defs = settings["classes"] if "classes" in settings else \
            [{"name": "Default", "track_width": 0.25, "via_diameter": 0.6, "via_drill": 0.3}]
        by_name = {e["name"]: e for e in defs or [] if isinstance(e, dict) and isinstance(e.get("name"), str) and e["name"]}
        clearance = {n: _mm(e.get("clearance"), -1.0) for n, e in by_name.items()}
        clearance = {n: v for n, v in clearance.items() if v >= 0}
        de = by_name.get("Default", {})
        d.width, d.via, d.drill = _mm(de.get("track_width"), d.width), _mm(de.get("via_diameter"), d.via), \
            _mm(de.get("via_drill"), d.drill)
        d.clearance = clearance.get("Default", _KICAD_CLEARANCE)
        for n, e in by_name.items():
            if n != "Default":
                classes[n] = NetClass(n, _mm(e.get("track_width"), d.width), clearance.get(n, d.clearance),
                                      _mm(e.get("via_diameter"), d.via), _mm(e.get("via_drill"), d.drill))
    assigned = settings.get("netclass_assignments") if isinstance(settings.get("netclass_assignments"), dict) else {}
    patterns = [(e.get("netclass"), e.get("pattern")) for e in settings.get("netclass_patterns") or []
                if isinstance(e, dict) and isinstance(e.get("netclass"), str) and isinstance(e.get("pattern"), str)
                and e.get("pattern")]
    # KiCad's precedence between classes: the smaller priority wins, then the name
    order = {n: (e.get("priority", i) if isinstance(e.get("priority", i), int) else i, n)
             for i, (n, e) in enumerate((n, e) for n, e in by_name.items() if n != "Default")}

    def class_of(net: str) -> str:
        a = assigned.get(net)
        if isinstance(a, list):         # KiCad 9 may list several
            a = a[0] if len(a) == 1 else None
        found = [a] if isinstance(a, str) else list(dict.fromkeys(c for c, p in patterns if _matches(p, net)))
        found = [c for c in found if c in classes]
        return min(found, key=lambda c: order.get(c, (2 ** 31 - 1, c))) if found else "Default"

    of = {n: class_of(n) for n in nets}
    floors = [("clearance", _mm(rules.get("min_clearance"), 0.0)), ("width", _mm(rules.get("min_track_width"), 0.0)),
              ("via", _mm(rules.get("min_via_diameter"), 0.0)), ("drill", _mm(rules.get("min_via_hole"), 0.0))]
    attr = {"clearance": "clearance", "track_width": "width", "via_diameter": "via"}
    floors += [(attr[k], v) for k, v in _dru_floors(pcb.with_suffix(".kicad_dru"))]
    for a, v in floors:
        if v > 0:
            for c in classes.values():
                setattr(c, a, max(getattr(c, a), v))
    for n in nets:
        classes[of[n]].nets.append(n)
    return classes


# -- writing the DSN ------------------------------------------------------------

def _um(mm: float) -> float:
    return round(mm * 1000.0, 3)


def _q(s: str) -> str:
    return f'"{s}"' if not s or re.search(r"[\s()\"']", s) else s


def _polygon(layer: str, pts: list) -> str:
    coords = " ".join(f"{_um(x):.1f} {_um(y):.1f}" for x, y in pts)
    if pts[-1] != pts[0]:
        coords += f" {_um(pts[0][0]):.1f} {_um(pts[0][1]):.1f}"
    return f"      (polygon {_q(layer)} 0 {coords})"


class _Dsn:
    def __init__(self, pcb: Path):
        text = pcb.read_text()
        self.pcb = pcb
        self.root = root = _tree(text)
        self.layers = _layers(text)
        names = _net_names(text)
        self.fps: list[Footprint] = []
        self.arcs, self.segments, self.vias = [], [], []
        self.zones = []
        for node in root[1:]:
            if not (isinstance(node, list) and node):
                continue
            head = node[0]
            if head in ("footprint", "module"):
                at = _kid(node, "at")
                rot = _f(at[3]) if at and len(at) > 3 else 0.0
                layer = _kid(node, "layer")
                fp = Footprint(_reference(node), (node[1] if len(node) > 1 and isinstance(node[1], str) else "")
                               or "unknown", (layer[1] if layer and len(layer) > 1 else "") or "F.Cu", *_xy(at), rot)
                fp.pads = [p for p in (_pad(c, rot, names) for c in _kids(node, "pad")) if p]
                self.fps.append(fp)
            elif head in ("segment", "arc"):
                ends = [_kid(node, k) for k in (("start", "mid", "end") if head == "arc" else ("start", "end"))]
                width, layer, net = _kid(node, "width"), _kid(node, "layer"), _kid(node, "net")
                if not (all(ends) and width and layer and net):
                    continue
                net, layer = _net(net, names), (layer[1] if len(layer) > 1 else "") or "F.Cu"
                if not net or layer not in self.layers:
                    continue
                pts = [_xy(e) for e in ends]
                (self.arcs if head == "arc" else self.segments).append(
                    (_arc_points(*pts) if head == "arc" else pts, layer, _f(width[1]) or 0.25, net))
            elif head == "via":
                at, size, net = _kid(node, "at"), _kid(node, "size"), _kid(node, "net")
                if at and size and net:     # a via of no net still has its padstack
                    self.vias.append((*_xy(at), _f(size[1]) or 0.8, _net(net, names)))
            elif head == "zone":
                self.zones.append(node)
        self.names = names
        self.classes = net_classes(pcb, sorted({p.net for fp in self.fps for p in fp.pads if p.net}))
        self.edge = _mm(_rules(_project(pcb)).get("min_copper_edge_clearance"), 0.0)
        self.images = self._image_names()

    # copper layers named by a layer list (wildcards expanded)
    def _copper(self, specs: list[str]) -> list[str]:
        out: list[str] = []
        for s in specs:
            got = list(self.layers) if s == "*.Cu" else \
                [l for l in ("F.Cu", "B.Cu") if l in self.layers] if s == "F&B.Cu" else \
                [s] if s in self.layers else []
            out += [l for l in got if l not in out]
        return out

    def _image_layers(self, pad: Pad, back: bool) -> list[str]:
        """The layers a pad's padstack names in its image. A Specctra reader swaps
        a back-placed image's padstack layers (seen with Freerouting 2.5.0,
        kicad-tools #7518), so a back image names each pad on the mirror layer."""
        copper = self._copper(pad.layers) or ["F.Cu"]
        if not back or any(c not in self.layers for c in copper):
            return copper
        last = len(self.layers) - 1
        return sorted((self.layers[last - self.layers.index(c)] for c in copper), key=self.layers.index)

    def _is_pin(self, pad: Pad) -> bool:
        """An NPTH hole is an obstacle, not a pin; a pad with no copper here is nothing."""
        return pad.kind != "np_thru_hole" and (bool(self._copper(pad.layers)) or pad.kind == "thru_hole")

    # -- structure

    def _zone_lines(self) -> tuple[list[str], list[tuple]]:
        planes, keepouts = [], []
        for z in self.zones:
            layer = _kid(z, "layer")
            ls = _kid(z, "layers")
            specs = [l for l in ls[1:] if isinstance(l, str)] if ls else ([layer[1]] if layer and len(layer) > 1 else [])
            layers = self._copper(specs)
            polys = _kids(z, "polygon")
            if not layers or not polys:
                continue
            pts = _points(polys[0])
            if pts is None or len(pts) < 3:
                continue
            ko = _kid(z, "keepout")
            if ko is None:
                n = _kid(z, "net")
                nn = _kid(z, "net_name")
                net = (nn[1] if nn and len(nn) > 1 else "") or _net(n, self.names)
                if net:
                    planes += [(net, l, pts) for l in layers]
                continue

            def barred(k):
                c = _kid(ko, k)
                return bool(c and len(c) > 1 and c[1] == "not_allowed")
            tag = {(True, True): "keepout", (True, False): "wire_keepout", (False, True): "via_keepout"}.get(
                (barred("tracks"), barred("vias")))
            if tag:
                keepouts += [(tag, l, pts) for l in layers]
        return planes, keepouts

    def structure(self) -> str:
        out = ["  (structure"]
        for i, layer in enumerate(self.layers):
            out += [f"    (layer {_q(layer)}", "      (type signal)", "      (property", f"        (index {i})",
                    "      )", "    )"]
        boundary, cutouts = _inset(*_outline(self.root), self.edge)
        if boundary:
            out += ["    (boundary", "      (path pcb 0"]
            out += [f"        {_um(x):.1f} {_um(y):.1f}" for x, y in boundary + boundary[:1]]
            out += ["      )", "    )"]
        d = self.classes["Default"]
        c = _um(d.clearance)
        out += ["    (rule", f"      (width {_um(d.width):.1f})", f"      (clearance {c:.1f})",
                f"      (clearance {c:.1f} (type default_smd))", f"      (clearance {c:.1f} (type smd_smd))", "    )"]
        planes, keepouts = self._zone_lines()
        for net, layer, pts in planes:
            out += [f"    (plane {_q(net)}", _polygon(layer, pts), "    )"]
        for tag, layer, pts in keepouts + [("keepout", l, c) for c in cutouts for l in self.layers]:
            out += [f'    ({tag} ""', _polygon(layer, pts), "    )"]
        out.append("  )")
        return "\n".join(out)

    # -- placement and library

    def _image_names(self) -> list[str]:
        """One image per library footprint, side and pad geometry. A Specctra
        reader mirrors a back image in x while KiCad stores back pads already
        flipped, so back images are their own; and pad shapes depend on each
        pad's angle within its footprint, so a later variant of a footprint
        gets a hash suffix (kicad-tools #7481, #7484)."""
        names, variants = [], {}
        for fp in self.fps:
            base = fp.lib if fp.layer == "F.Cu" else f"{fp.lib}__back"
            sig = tuple((p.number, p.kind, p.shape, p.x, p.y, p.width, p.height, p.drill, p.slot, tuple(p.layers),
                         p.rratio, p.rotation, repr(p.node) if p.node else "") for p in fp.pads)
            known = variants.setdefault(base, {})
            if sig not in known:
                known[sig] = base if not known else f"{base}__{hashlib.sha1(repr(sig).encode()).hexdigest()[:6]}"
            names.append(known[sig])
        return names

    def placement(self) -> str:
        out = ["  (placement"]
        for fp, image in zip(self.fps, self.images):
            # KiCad's angle is counter-clockwise on a y-down board; a Specctra
            # reader turns by +angle in the numeric frame (kicad-tools #7481)
            rot = round((-fp.rotation) % 360.0, 4)
            out += [f"    (component {_q(image)}",
                    f"      (place {_q(fp.ref)} {_um(fp.x):.1f} {_um(fp.y):.1f} "
                    f"{'front' if fp.layer == 'F.Cu' else 'back'} {rot:g})", "    )"]
        out.append("  )")
        return "\n".join(out)

    def _npth(self, pad: Pad, px: float, py: float) -> list[str]:
        out = []
        for layer in self.layers:
            if pad.slot and abs(pad.slot[0] - pad.slot[1]) > 1e-6:
                w, h = _um(pad.slot[0]), _um(pad.slot[1])
                half = abs(w - h) / 2
                dx, dy = (half, 0.0) if w > h else (0.0, half)
                out.append(f'      (keepout "" (path {_q(layer)} {min(w, h):.1f} '
                           f"{px - dx:.1f} {py - dy:.1f} {px + dx:.1f} {py + dy:.1f}))")
            else:
                out.append(f'      (keepout "" (circle {_q(layer)} {_um(pad.drill or min(pad.width, pad.height)):.1f} '
                           f"{px:.1f} {py:.1f}))")
        return out

    def _custom_hull(self, pad: Pad) -> list[tuple[float, float]] | None:
        """Convex hull (mm, in the image) of a custom pad's anchor and primitives:
        exact for filled zero-width gr_poly primitives, else a box round each."""
        from shapely.affinity import rotate
        from shapely.geometry import Point, Polygon, box
        from shapely.ops import unary_union

        node = pad.node
        opts = _kid(node, "options")
        anchor = _kid(opts, "anchor") if opts else None
        anchor = str(anchor[1]).lower() if anchor and len(anchor) > 1 else "circle"
        w, h = pad.width, pad.height
        prims = [c for c in (_kid(node, "primitives") or ["primitives"])[1:] if isinstance(c, list)]

        def width_of(c):
            s = _kid(c, "stroke")
            wn = _kid(s, "width") if s else _kid(c, "width")
            return _f(wn[1]) if wn and len(wn) > 1 else 0.0

        def exact(c):
            fill = _kid(c, "fill")
            tok = (_kid(fill, "type") or fill)[1] if fill and len(fill) > 1 else ""
            pts = [_xy(p) for p in _kids(_kid(c, "pts") or ["pts"], "xy")]
            if c[0] != "gr_poly" or width_of(c) != 0 or str(tok).lower() not in ("yes", "true", "solid") or len(pts) < 3:
                return None
            poly = Polygon(pts)
            return poly if poly.is_valid and not poly.is_empty else None

        shapes = [box(-w / 2, -h / 2, w / 2, h / 2) if anchor == "rect"
                  else Point(0, 0).buffer(w / 2 * _ROUND_OUT, quad_segs=64)]
        polys = [exact(c) for c in prims]
        if anchor in ("rect", "circle") and (anchor == "rect" or abs(w - h) <= 1e-9) and all(polys):
            copper = unary_union(shapes + polys)
        else:
            half = (w / 2, h / 2) if anchor == "rect" else (max(w, h) / 2,) * 2
            shapes = [box(-half[0], -half[1], half[0], half[1])]
            for c in prims:
                pts = [_xy(p) for p in _all(c, "xy") + [k for k in c[1:] if isinstance(k, list) and
                                                        k[0] in ("start", "mid", "end", "center")]]
                if not pts:
                    return None
                if c[0] == "gr_circle" and len(pts) >= 2:
                    (cx, cy), (ex, ey) = pts[0], pts[1]
                    r = math.hypot(ex - cx, ey - cy)
                    pts = [(cx - r, cy - r), (cx + r, cy + r)]
                elif c[0] == "gr_arc" and len(pts) == 3:
                    pts = _arc_chain(*pts)
                g = width_of(c) / 2
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                shapes.append(box(min(xs) - g, min(ys) - g, max(xs) + g, max(ys) + g))
            copper = unary_union(shapes)
        if copper.is_empty:
            return None
        hull = rotate(copper, -pad.rotation, origin=(0, 0)).convex_hull
        if hull.geom_type != "Polygon":
            return None
        return list(hull.exterior.coords)[:-1]

    def _outline(self, pad: Pad, mirror: bool) -> tuple[str, tuple[float, ...]]:
        """A pad's copper in image coordinates (um): rect (x1 y1 x2 y2), circle
        (d), path (width x1 y1 x2 y2) or polygon (x y ...); never smaller than
        the pad. `mirror` negates x, as for the pins of a back image."""
        sign = -1.0 if mirror else 1.0
        rot = round(pad.rotation % 360.0, 6)
        w, h = _um(pad.width), _um(pad.height)

        def rect(rw, rh):
            return "rect", (-rw / 2, -rh / 2, rw / 2, rh / 2)

        if pad.shape == "circle":
            return "circle", (max(w, h),)
        if pad.shape == "custom":
            hull = self._custom_hull(pad)
            if hull is not None:
                return "polygon", tuple(v for x, y in hull for v in (sign * _um(x), _um(y)))
            return rect(w, h)
        a = math.radians(-rot)          # KiCad angles are counter-clockwise on a y-down board
        ca, sa = math.cos(a), math.sin(a)

        def place(px, py):
            return sign * (px * ca - py * sa), px * sa + py * ca

        if pad.shape == "oval" and abs(w - h) > 1e-6:
            half = abs(w - h) / 2
            (x1, y1), (x2, y2) = (place(-half, 0.0), place(half, 0.0)) if w > h else (place(0.0, -half), place(0.0, half))
            return "path", (min(w, h), x1, y1, x2, y2)
        if pad.shape == "oval":
            return "circle", (w,)
        quarter = rot % 90.0
        if quarter < 1e-6 or quarter > 90.0 - 1e-6:
            if round(rot / 90.0) % 2 == 1:
                w, h = h, w
            return rect(w, h)
        pts: list[float] = []
        for cx, cy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
            pts += list(place(cx, cy))
        return "polygon", tuple(pts)

    def _padstack(self, pad: Pad, back: bool) -> tuple[str, str]:
        kind, n = self._outline(pad, back)
        n = tuple(round(v, 1) + 0.0 for v in n)       # the 0.1 um the DSN is written in
        if kind == "rect":
            w, h, suffix = round(n[2] - n[0], 1), round(n[3] - n[1], 1), ""
        else:
            w, h = _um(pad.width), _um(pad.height)
            suffix = f"_{kind}{hashlib.sha1(f'{kind}{n}'.encode()).hexdigest()[:8]}"
        if pad.kind == "thru_hole":
            name, layers = f"Round[A]Pad_{w}x{h}_Drill{_um(pad.drill)}{suffix}_um", list(self.layers)
        else:
            layers = self._image_layers(pad, back)
            side = "T" if layers == ["F.Cu"] else "B" if layers == ["B.Cu"] else \
                "M" + "".join(str(self.layers.index(c)) for c in layers)
            name = f"Rect[{side}]Pad_{w}x{h}{suffix}_um"
        out = [f"    (padstack {_q(name)}"]
        for layer in layers:
            body = {"circle": lambda: f"circle {_q(layer)} {n[0]:.1f} 0.0 0.0",
                    "path": lambda: f"path {_q(layer)} " + " ".join(f"{v:.1f}" for v in n),
                    "polygon": lambda: f"polygon {_q(layer)} 0 " + " ".join(f"{v:.1f}" for v in n),
                    "rect": lambda: f"rect {_q(layer)} " + " ".join(f"{v:.1f}" for v in n)}[kind]()
            out.append(f"      (shape ({body}))")
        out += ["      (attach off)", "    )"]
        return name, "\n".join(out)

    def via_name(self, diameter: float) -> str:
        return f"Via[0-{len(self.layers) - 1}]_Pad{_um(diameter):.0f}_um"

    def library(self) -> str:
        out = ["  (library"]
        seen, stacks = set(), {}
        for fp, image in zip(self.fps, self.images):
            if image in seen:
                continue
            seen.add(image)
            out.append(f"    (image {_q(image)}")
            back = fp.layer != "F.Cu"
            for pad in fp.pads:
                # back offsets are already flipped in the file: negate x so the
                # reader's mirror puts them back
                px, py = _um(-pad.x if back else pad.x), _um(pad.y)
                if pad.kind == "np_thru_hole":
                    out += self._npth(pad, px, py)
                    continue
                if not self._is_pin(pad):
                    continue
                name, text = self._padstack(pad, back)
                stacks.setdefault(name, text)
                out.append(f"      (pin {_q(name)} {_q(pad.number)} {px:.1f} {py:.1f})")
            out.append("    )")
        for d in [self.classes["Default"].via] + [c.via for c in self.classes.values()] + [v[2] for v in self.vias]:
            name = self.via_name(d)
            if name not in stacks:
                stacks[name] = "\n".join([f"    (padstack {_q(name)}"]
                                         + [f"      (shape (circle {_q(l)} {_um(d):.1f}))" for l in self.layers]
                                         + ["      (attach off)", "    )"])
        out += list(stacks.values())
        out.append("  )")
        return "\n".join(out)

    # -- network and wiring

    def network(self) -> str:
        out = ["  (network"]
        pins: dict[str, list[str]] = {}
        for fp in self.fps:
            for pad in fp.pads:
                if pad.net and self._is_pin(pad):
                    pins.setdefault(pad.net, []).append(f"{fp.ref}-{pad.number}")
        for net, ps in sorted(pins.items()):
            out += [f"    (net {_q(net)}", "      (pins"] + [f"        {_q(p)}" for p in sorted(ps)] + ["      )", "    )"]
        for name, c in self.classes.items():
            members = sorted(n for n in c.nets if n in pins)
            if name != "Default" and not members:
                continue
            out.append(f"    (class {_q(c.name)}")
            out += [f"      {_q(n)}" for n in members]
            out += ["      (circuit", f"        (use_via {_q(self.via_name(c.via))})", "      )",
                    "      (rule", f"        (width {_um(c.width):.1f})", f"        (clearance {_um(c.clearance):.1f})",
                    "      )", "    )"]
        out.append("  )")
        return "\n".join(out)

    def wiring(self) -> str | None:
        if not (self.arcs or self.segments or any(v[3] for v in self.vias)):
            return None
        out = ["  (wiring"]
        for pts, layer, width, net in self.arcs + self.segments:
            coords = " ".join(f"{_um(x):.1f} {_um(y):.1f}" for x, y in pts)
            out += ["    (wire", f"      (path {_q(layer)} {_um(width):.1f} {coords})", f"      (net {_q(net)})",
                    "      (type protect)", "    )"]
        for x, y, size, net in (v for v in self.vias if v[3]):
            out += ["    (via", f"      {_q(self.via_name(size))} {_um(x):.1f} {_um(y):.1f}", f"      (net {_q(net)})",
                    "      (type protect)", "    )"]
        out.append("  )")
        return "\n".join(out)

    def text(self) -> str:
        head = [f"(pcb {_q(self.pcb.stem)}", "  (parser", '    (string_quote ")', "    (space_in_quoted_tokens on)",
                '    (host_cad "KiCad\'s Pcbnew")', '    (host_version "boardwright")', "  )", "  (resolution um 10)",
                "  (unit um)"]
        parts = head + [self.structure(), self.placement(), self.library(), self.network()]
        wiring = self.wiring()
        if wiring:
            parts.append(wiring)
        return "\n".join(parts + [")"])


def export(pcb: Path, dsn: Path) -> int:
    """Write the DSN Freerouting routes `pcb` from; return how many curved
    tracks went in as fixed polylines."""
    d = _Dsn(pcb)
    dsn.parent.mkdir(parents=True, exist_ok=True)
    dsn.write_text(d.text())
    return len(d.arcs)
