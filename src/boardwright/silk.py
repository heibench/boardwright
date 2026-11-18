"""Reference text placement for a generated board.

Each footprint's visible reference is moved, and turned 90 degrees where that
fits better, just far enough to clear pad and via mask openings, other
silkscreen, every courtyard and the board edge. Only the (at ...) of each
moved reference changes; the rest of the file stays as it was. A reference
with no clear spot within the search radius stays where it is.

Ported from kicad-tools 0.29's `place-silk-refs --allow-rotate`
(kicad_tools/silkscreen/place_refs.py and the helpers it takes from
validate/rules/silkscreen.py and geometry/courtyard.py), which `gen` used to
run; tests/test_silk_refs.py holds it to that command's output on every
example. The board is read through model.py. Ported from kicad-tools under its
licence:

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
from pathlib import Path

from shapely.affinity import rotate
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box

from . import copper
from .model import contours

# kicad-tools 0.29's defaults (kicad_tools/silkscreen/_silk_defaults.py), as
# `gen` ran the command: silk-to-pad and silk-to-silk clearance, silk to board
# edge (kicad-cli's default silk_edge_clearance), how far from the part to
# search and the spacing of the search rings, all mm. MASK is the command's
# solder-mask margin with no --mfr.
CLEARANCE, EDGE, MAX_OFFSET, STEP, MASK = 0.15, 0.2, 8.0, 0.25, 0.05
# Added to CLEARANCE because the text box under-sizes KiCad's stroke font:
# measured by kicad-tools against kicad-cli 10.0 DRC, 1 mm / 0.15 mm text
# beside a 1 mm pad ("C22" and "LED4" both needed 0.225 mm more).
SLACK = 0.225
# A reference sits at least this much nearer its own courtyard than any
# other part's where it can, so it reads as that part's (kicad-tools' value).
ASSOCIATION = 0.4
# Text box width per character, as a fraction of the font width (kicad-tools'
# approximation of the stroke font).
CHAR_W = 0.7
EPS = 1e-4
SILK = {"F.SilkS": "F", "F.Silkscreen": "F", "B.SilkS": "B", "B.Silkscreen": "B"}
CRTYD = {"F": "F.CrtYd", "B": "B.CrtYd"}


def _transform(fp):
    """Footprint-local -> board-relative. KiCad's angle turns toward -y."""
    x0, y0 = fp.position
    t = math.radians(-fp.rotation)
    c, s = math.cos(t), math.sin(t)
    return lambda p: (x0 + p[0] * c - p[1] * s, y0 + p[0] * s + p[1] * c)


def _inverse(fp):
    x0, y0 = fp.position
    t = math.radians(-fp.rotation)
    c, s = math.cos(t), math.sin(t)

    def inv(p):
        dx, dy = p[0] - x0, p[1] - y0
        return dx * c + dy * s, -dx * s + dy * c
    return inv


def _text_box(text: str, size, thickness: float, center, angle: float):
    """A centred box over the text; angle is the board-frame angle."""
    if not text:
        return None
    w = size[0] * len(text) * CHAR_W + thickness
    h = size[1] + thickness
    cx, cy = center
    g = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return rotate(g, -angle, origin=center) if angle else g


def _ink(g, xf):
    """The printed ink of a silk line, rect or poly; None for what prints nothing
    and for circles and arcs, which are not modelled."""
    if g.graphic_type not in ("line", "rect", "poly"):
        return None
    w = g.stroke_width
    xf = xf or (lambda p: p)
    if g.graphic_type == "poly":
        pts = [xf(p) for p in (getattr(g, "points", ()) or ())]
        if len(pts) < 3:
            return None
        if getattr(g, "is_filled", False):
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            if w > 0:
                poly = poly.buffer(w / 2)
            return None if poly.is_empty else poly
        return LineString([*pts, pts[0]]).buffer(w / 2) if w > 0 else None
    if w <= 0:
        return None
    if g.graphic_type == "line":
        a, b = xf(g.start), xf(g.end)
        return None if a == b else LineString([a, b]).buffer(w / 2)
    (sx, sy), (ex, ey) = g.start, g.end
    return LineString([xf(p) for p in ((sx, sy), (ex, sy), (ex, ey), (sx, ey), (sx, sy))]).buffer(w / 2)


def _openings(pcb) -> dict[str, list]:
    """Exposed copper per silk side: pad mask openings (SMD on its side, through
    pads on both), untented vias, and non-plated holes on both sides."""
    out: dict[str, list] = {"F": [], "B": []}
    for fp in pcb.footprints:
        xf = _transform(fp)
        for pad in fp.pads:
            cx, cy = xf(pad.position)
            rot = getattr(pad, "rotation", 0.0) or 0.0
            if pad.type == "np_thru_hole":
                w, h = (max(pad.size[i], pad.drill) + 2 * MASK for i in (0, 1))
                sides = ("F", "B")
            else:
                if pad.type == "smd":
                    sides = ("F",) if fp.layer == "F.Cu" else ("B",)
                elif pad.type == "thru_hole":
                    sides = ("F", "B")
                else:
                    continue
                m = pad.solder_mask_margin if pad.solder_mask_margin is not None else MASK
                w, h = pad.size[0] + 2 * m, pad.size[1] + 2 * m
            g = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            if rot % 360.0:
                g = rotate(g, -rot, origin=(cx, cy))
            for side in sides:
                out[side].append(g)
    for via in pcb.vias:
        if via.size <= 0:
            continue
        for side in ("F", "B"):
            if _tented(via, pcb.tenting, side):
                continue
            d = via.size + 2 * MASK
            cx, cy = via.x, via.y
            out[side].append(box(cx - d / 2, cy - d / 2, cx + d / 2, cy + d / 2))
    return out


def _tented(via, tenting, side: str) -> bool:
    """The via's own setting, else the board's, else tented (KiCad 10's default
    when neither says, as kicad-tools measured it against kicad-cli 10.0.5)."""
    own = via.tenting[0 if side == "F" else 1]
    if own in ("yes", "no"):
        return own == "yes"
    board = tenting[0 if side == "F" else 1]
    return True if board is None else board


def _static_silk(pcb) -> dict[str, list]:
    """Silkscreen that does not move: footprint texts other than the reference,
    footprint and board graphics, board texts."""
    out: dict[str, list] = {"F": [], "B": []}
    for fp in pcb.footprints:
        xf = _transform(fp)
        for t in fp.texts:
            side = SILK.get(t.layer)
            if t.text_type == "reference" or side is None or t.hidden:
                continue
            g = _text_box(t.text, t.font_size, t.font_thickness, xf(t.position), t.rotation)
            if g is not None:
                out[side].append(g)
        for gr in fp.graphics:
            side = SILK.get(gr.layer)
            g = _ink(gr, xf) if side else None
            if g is not None:
                out[side].append(g)
    ox, oy = pcb.origin                         # board items are still in file coordinates
    to_board = lambda p: (p[0] - ox, p[1] - oy)
    for t in pcb.texts:
        side = SILK.get(t.layer)
        if side is None or t.hidden:
            continue
        g = _text_box(t.text, t.font_size, t.font_thickness, to_board(t.position), t.rotation)
        if g is not None:
            out[side].append(g)
    for gr in pcb.graphics:
        side = SILK.get(gr.layer)
        g = _ink(gr, to_board if (ox or oy) else None) if side else None
        if g is not None:
            out[side].append(g)
    return out


def _chain(segments):
    """Line segments joined end to end into one closed ring, else None."""
    close = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1]) <= 1e-3
    rest = list(segments)
    start, cur = rest.pop(0)
    ring = [start, cur]
    while rest:
        for i, (a, b) in enumerate(rest):
            if close(a, cur) or close(b, cur):
                cur = b if close(a, cur) else a
                ring.append(cur)
                rest.pop(i)
                break
        else:
            return None
    return ring if close(ring[0], ring[-1]) else None


def _courtyard(fp, side: str):
    """The footprint's courtyard on a side as a polygon: its first rect, else its
    first poly, else its lines chained into a ring, else its first circle."""
    layer = CRTYD[side]
    gs = [g for g in fp.graphics if g.layer == layer]
    if not gs:
        return None
    xf = _transform(fp)
    rects = [g for g in gs if g.graphic_type == "rect"]
    polys = [g for g in gs if g.graphic_type == "poly"]
    lines = [(g.start, g.end) for g in gs if g.graphic_type == "line"]
    circles = [g for g in gs if g.graphic_type == "circle"]
    ring = None
    if rects:
        (sx, sy), (ex, ey) = rects[0].start, rects[0].end
        ring = [(sx, sy), (ex, sy), (ex, ey), (sx, ey), (sx, sy)]
    elif polys and len(polys[0].points) >= 3:
        ring = list(polys[0].points)
    elif lines:
        ring = _chain(lines)
    elif circles:
        c = circles[0]
        if c.center is not None and c.radius and c.radius > 0:
            g = Point(*xf(c.center)).buffer(c.radius)
            return g if not g.is_empty and g.area > 0 else None
        return None
    if ring is None or len(ring) < 3:
        return None
    poly = Polygon([xf(p) for p in ring])
    if not poly.is_valid:
        poly = poly.buffer(0)
    return None if poly.is_empty or poly.area <= 0 else poly


def _material(pcb):
    """(the board's material as a polygon, its outline), or (None, None) when the
    Edge.Cuts lines do not close into separate contours."""
    segs = pcb.outline_segments
    if not segs:
        return None, None
    polys = []
    for ring in contours(segs, 0.01):
        if not ring:
            return None, None
        poly = Polygon(ring)
        if not poly.is_valid or poly.is_empty or poly.area <= 0:
            return None, None
        if any(poly.boundary.intersects(o.boundary) for o in polys):
            return None, None
        polys.append(poly)
    material = Polygon()
    for poly in polys:             # nested contours alternate material and cutout
        material = material.symmetric_difference(poly)
    return material, MultiLineString([[a, b] for a, b in segs])


def _candidates(bbox, tw: float, th: float) -> list[tuple[float, float]]:
    """Centres on rings around the part, STEP apart out to MAX_OFFSET: each ring's
    edge midpoints, then its corners."""
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    out = []
    for ring in range(math.floor(MAX_OFFSET / STEP) + 1):
        d = ring * STEP
        top, bottom, left, right = y0 - d - th / 2, y1 + d + th / 2, x0 - d - tw / 2, x1 + d + tw / 2
        out += [(cx, top), (cx, bottom), (left, cy), (right, cy), (left, top), (right, top), (left, bottom), (right, bottom)]
    return out


def _part_box(fp, side: str):
    """The part's extent: its courtyard, else its pads, else 1 mm round its anchor."""
    c = _courtyard(fp, side)
    if c is not None:
        return c.bounds
    xf = _transform(fp)
    xs, ys = [], []
    for pad in fp.pads:
        cx, cy = xf(pad.position)
        xs += [cx - pad.size[0] / 2, cx + pad.size[0] / 2]
        ys += [cy - pad.size[1] / 2, cy + pad.size[1] / 2]
    if xs:
        return min(xs), min(ys), max(xs), max(ys)
    x, y = fp.position
    return x - 1.0, y - 1.0, x + 1.0, y + 1.0


def _ref_block(fp_text: str) -> tuple[int, int] | None:
    for s, e in copper.blocks(fp_text, ("property", "fp_text")):
        if re.match(r'\s*\((?:property "Reference"|fp_text reference) ', fp_text[s:e]):
            return s, e
    return None


def _at(block: str):
    return re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", block)


def plan(pcb) -> dict[str, tuple[float, float, float]]:
    """ref -> new footprint-local (x, y, angle) of each reference that moves.
    `pcb` is a model.Board."""
    refs = [fp.reference for fp in pcb.footprints]
    if len(refs) != len(set(refs)):
        raise ValueError("duplicate footprint references; give each part its own before placing its text")
    openings, silk = _openings(pcb), _static_silk(pcb)
    courtyards: dict[str, list] = {"F": [], "B": []}
    own: dict[tuple[str, str], object] = {}
    for fp in pcb.footprints:
        for side in ("F", "B"):
            c = _courtyard(fp, side)
            if c is not None:
                courtyards[side].append((c, fp.reference))
                own[(fp.reference, side)] = c
    material, outline = _material(pcb)
    if material is None:
        return {}

    entries, texts = [], {"F": {}, "B": {}}       # texts: the references as they stand, as obstacles
    for fp in pcb.footprints:
        t = next((t for t in fp.texts if t.text_type == "reference"), None)
        if t is None or t.hidden or SILK.get(t.layer) is None:
            continue
        angle = _angle(fp)
        center = _transform(fp)(t.position)
        g = _text_box(t.text, t.font_size, t.font_thickness, center, angle)
        if g is None:
            continue
        side = SILK[t.layer]
        entries.append((fp, t, side, center, angle))
        texts[side][fp.reference] = g

    moves = {}
    for fp, t, side, center, angle in sorted(entries, key=lambda e: e[0].reference):
        ref = fp.reference
        del texts[side][ref]
        obstacles = silk[side] + list(texts[side].values())
        others = [g for g, owner in courtyards[side] if owner != ref]
        mine = own.get((ref, side))

        def clear(g):
            if not material.covers(g):
                return False
            grown = g.buffer(CLEARANCE + SLACK)
            if any(grown.intersects(o) for o in openings[side]) or any(grown.intersects(o) for o in obstacles):
                return False
            if any(g.intersects(c) for c, _ in courtyards[side]):
                return False
            return g.distance(outline) >= EDGE - EPS

        def margin(g):
            if mine is None or not others:
                return None
            return min(o.distance(g) for o in others) - mine.distance(g)

        points = _candidates(_part_box(fp, side), t.font_size[0], t.font_size[1])
        points.sort(key=lambda p: math.hypot(p[0] - center[0], p[1] - center[1]))
        best = None              # (point, angle, geometry, margin)
        for point in [center, *points]:
            done = False
            for rot in (angle, angle + 90.0):
                g = _text_box(t.text, t.font_size, t.font_thickness, point, rot)
                if not clear(g):
                    continue
                m = margin(g)
                if best is None or (m is not None and (best[3] is None or m > best[3] + EPS)):
                    best = (point, rot, g, m)
                if m is None or m >= ASSOCIATION:
                    done = True
                    break
            if done:
                break
        if best is None:
            texts[side][ref] = _text_box(t.text, t.font_size, t.font_thickness, center, angle)
            continue
        texts[side][ref] = best[2]
        (x, y), rot = best[0], best[1]
        if abs(x - center[0]) > EPS or abs(y - center[1]) > EPS or rot != angle:
            moves[ref] = (*_inverse(fp)((x, y)), rot)
    return moves


def _angle(fp) -> float:
    """The reference's own (at x y angle) as the file has it: the board-frame angle."""
    return next((t.rotation for t in fp.texts if t.text_type == "reference"), 0.0)


def place_refs(pcb_path: Path) -> list[str]:
    """Move the references `plan` moves, editing only their (at ...) in the file.
    Returns the references moved."""
    from .board import _write
    from .model import Board
    from .update import _footprints, _prop

    t = t0 = pcb_path.read_text()
    moves = plan(Board(pcb_path))
    for s, e in reversed(_footprints(t)):
        fp = t[s:e]
        ref = _prop(fp, "Reference")
        if ref not in moves:
            continue
        rs, re_ = _ref_block(fp)
        blk = fp[rs:re_]
        a = _at(blk)
        x, y, rot = moves[ref]
        ang = f" {copper.num(rot)}" if a.group(3) or rot != 0.0 else ""
        blk = blk[:a.start()] + f"(at {copper.num(x)} {copper.num(y)}{ang})" + blk[a.end():]
        t = t[:s] + fp[:rs] + blk + fp[re_:] + t[e:]
    _write(pcb_path, t0, t)
    return sorted(moves)
