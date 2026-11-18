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
from boardwright.model import Board


def _l(v):
    """Tuples to lists, recursively, so JSON round-trips compare equal."""
    if isinstance(v, (list, tuple)):
        return [_l(x) for x in v]
    return v


def _graphic(g) -> list:
    return _l([g.graphic_type, g.layer, g.stroke_width, g.start, g.end, g.mid, g.center,
               getattr(g, "radius", None), list(g.points or []), g.is_filled])


def _text(t) -> list:
    return _l([getattr(t, "text_type", None), t.text, t.position, t.rotation, t.layer,
               t.font_size, t.font_thickness, t.hidden])


def _contours(b: Board) -> list:
    from kicad_tools.schema.pcb import PCB

    segs = b.pcb.get_board_outline_segments()
    return _l([PCB._chain_segment_indices(segs, idx, 0.01) for idx in PCB._group_segments_by_connectivity(segs, 0.01)])


def _angle(fp):
    """silk._angle; None where kicad-tools could not link the footprint to its
    node (boards whose footprints share one uuid), "error" where the reference's
    (at ...) has a word for its angle (KiCad 6 and 7 write `unlocked` there)."""
    if fp._sexp_node is None:
        return None
    try:
        return silk._angle(fp)
    except ValueError:
        return "error"


def dump(path: Path) -> dict:
    b = Board(path)
    pcb = b.pcb
    setup = pcb.setup
    return {
        "origin": _l(b.origin),
        "layers": b.layers,
        "bbox": _l(b.bbox),
        "area": b.area,
        "pads": [_l([p.ref, p.num, p.net, p.x, p.y, p.layer, p.w, p.h, p.angle, p.thru, p.layers, p.shape, p.rratio])
                 for p in b.pads],
        "tracks": [_l([t.pts, t.width, t.layer, t.net]) for t in b.tracks],
        "vias": [_l([v.x, v.y, v.size, v.drill, v.layers, v.net, w.tenting_front, w.tenting_back])
                 for v, w in zip(b.vias, pcb.vias)],
        "zones": [_l([z.net, z.layers, z.priority, z.keepout, z.outline, z.fills]) for z in b.zones],
        "tenting": [None if setup is None else setup.tenting_front, None if setup is None else setup.tenting_back],
        "outline": _l(list(pcb.get_board_outline() or [])),
        "outline_segments": _l(pcb.get_board_outline_segments()),
        "contours": _contours(b),
        "footprints": [_l([fp.reference, fp.uuid, fp.position, fp.rotation, fp.layer, _angle(fp),
                           [[q.number, q.type, q.shape, q.position, q.size, q.rotation, q.drill,
                             q.solder_mask_margin, q.layers, q.roundrect_rratio] for q in fp.pads],
                           [_text(t) for t in fp.texts],
                           [_graphic(g) for g in fp.graphics]])
                       for fp in pcb.footprints],
        "texts": [_text(t) for t in pcb.texts],
        "graphics": [_graphic(g) for g in pcb.graphics],
    }


# Kept as they are in the golden; every other field is a list, kept as its
# length and the sha256 of its JSON (the full dumps run to megabytes).
SMALL = ("origin", "layers", "bbox", "area", "tenting")


def summary(d: dict) -> dict:
    return {k: v if k in SMALL else {"n": len(v), "sha256": hashlib.sha256(json.dumps(v).encode()).hexdigest()}
            for k, v in d.items()}
