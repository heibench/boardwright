"""Every field boardwright reads from a board, as plain JSON, for
test_board_reader.py's parity goldens.

What is dumped is what the callers of model.Board read: the Board's own
properties (origin, copper layers, pads, tracks, vias, zones, bbox, area),
the footprints edits.py, existing.py, placement.py, preview.py, selection.py
and silk.py walk (their pads, texts and graphics), the board's texts and
graphics, its outline and outline segments, the via tenting silk.py reads,
and the closed Edge.Cuts contours silk._material builds from the segments.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from boardwright import silk
from boardwright.model import Board, contours


def _l(v):
    """Tuples to lists, recursively, so JSON round-trips compare equal."""
    if isinstance(v, (list, tuple)):
        return [_l(x) for x in v]
    return v


def _graphic(g) -> list:
    return _l([g.graphic_type, g.layer, g.stroke_width, g.start, g.end, g.mid, g.center,
               g.radius, list(g.points), g.is_filled])


def _text(t) -> list:
    return _l([t.text_type, t.text, t.position, t.rotation, t.layer,
               t.font_size, t.font_thickness, t.hidden])


def dump(path: Path) -> dict:
    b = Board(path)
    return {
        "origin": _l(b.origin),
        "layers": b.layers,
        "bbox": _l(b.bbox),
        "area": b.area,
        "pads": [_l([p.ref, p.num, p.net, p.x, p.y, p.layer, p.w, p.h, p.angle, p.thru, p.layers, p.shape, p.rratio])
                 for p in b.pads],
        "tracks": [_l([t.pts, t.width, t.layer, t.net]) for t in b.tracks],
        "vias": [_l([v.x, v.y, v.size, v.drill, v.layers, v.net, *v.tenting]) for v in b.vias],
        "zones": [_l([z.net, z.layers, z.priority, z.keepout, z.outline, z.fills]) for z in b.zones],
        "tenting": _l(b.tenting),
        "outline": _l(b.outline),
        "outline_segments": _l(b.outline_segments),
        "contours": _l(contours(b.outline_segments)),
        "footprints": [_l([fp.reference, fp.uuid, fp.position, fp.rotation, fp.layer, silk._angle(fp),
                           [[q.number, q.type, q.shape, q.position, q.size, q.rotation, q.drill,
                             q.solder_mask_margin, q.layers, q.roundrect_rratio] for q in fp.pads],
                           [_text(t) for t in fp.texts],
                           [_graphic(g) for g in fp.graphics]])
                       for fp in b.footprints],
        "texts": [_text(t) for t in b.texts],
        "graphics": [_graphic(g) for g in b.graphics],
    }


# Kept as they are in the golden; every other field is a list, kept as its
# length and the sha256 of its JSON (the full dumps run to megabytes).
SMALL = ("origin", "layers", "bbox", "area", "tenting")


def summary(d: dict) -> dict:
    return {k: v if k in SMALL else {"n": len(v), "sha256": hashlib.sha256(json.dumps(v).encode()).hexdigest()}
            for k, v in d.items()}
