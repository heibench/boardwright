"""A board edit as a plain list of operations.

    boardwright edits SPEC.py BOARD.kicad_pcb OUT.json [PROJECT.kicad_pro]

PROJECT gives ROUTES their default width and clearance when the board file
is a copy that does not sit beside its project.

Turns a spec's MOVE, RIPUP, VIAS, TRACKS and ROUTES (board-relative mm, as
everywhere else in this tool; ROUTES are pad-to-pad connections worked out by
boardwright/route.py) into an edit list in the board file's own absolute
coordinates, checked against the board first: every reference and net must
exist, and hand tracks must not cross. The list is what `boardwright.live apply`
executes, and it is simple enough for anything else to execute too.

    {"ops": [
      {"op": "move_footprint", "ref": "U1", "x": 120.5, "y": 80.0, "rotation": 90},
      {"op": "remove_routing", "nets": ["/SDA", "GND"]},
      {"op": "add_via", "net": "GND", "x": 110.0, "y": 85.0, "diameter": 0.6, "drill": 0.3},
      {"op": "add_track", "net": "GND", "x1": 110.0, "y1": 85.0, "x2": 115.0, "y2": 85.0,
       "width": 0.25, "layer": "F.Cu"}
    ]}

mm, absolute, y down; rotation in degrees and optional; vias are through
vias; remove_routing deletes every track, arc and via on those nets. Ops are
meant to run in order as one undoable change.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import copper, env
from .errors import Usage
from .model import Board


def from_spec(m, board: Board, project=None) -> dict:
    copper.check_tracks(m)
    ox, oy = board.origin
    refs = {fp.reference for fp in board.footprints}
    nets = {p.net for p in board.pads} | {t.net for t in board.tracks} | {z.net for z in board.zones}
    r = lambda v: round(v, 4)
    def need_net(n):
        if n not in nets:
            raise Usage(f"no net {n!r} on {board.path.name}")
        return n
    ops = []
    if getattr(m, "ROUTES", None) and getattr(m, "MOVE", None):
        raise Usage("ROUTES are worked out on the board as it is; apply the MOVE first, then route in a second edit")
    from .route import expand
    rtracks, rvias = expand(m, board, ignore=set(getattr(m, "RIPUP", [])), project=project)
    for ref, pos in getattr(m, "MOVE", {}).items():
        if ref not in refs:
            raise Usage(f"no footprint {ref!r} on {board.path.name}")
        op = {"op": "move_footprint", "ref": ref, "x": r(pos[0] + ox), "y": r(pos[1] + oy)}
        if len(pos) > 2 and pos[2] is not None:
            op["rotation"] = pos[2]
        ops.append(op)
    rip = [need_net(n) for n in getattr(m, "RIPUP", [])]
    if rip:
        ops.append({"op": "remove_routing", "nets": rip})
    for v in list(getattr(m, "VIAS", [])) + rvias:
        size, drill = (v[3], v[4]) if len(v) > 4 else (0.6, 0.3)
        ops.append({"op": "add_via", "net": need_net(v[0]), "x": r(v[1] + ox), "y": r(v[2] + oy),
                    "diameter": size, "drill": drill})
    for t in list(getattr(m, "TRACKS", [])) + rtracks:
        width = t[2] if len(t) > 2 else 0.25
        layer = t[3] if len(t) > 3 else "F.Cu"
        if layer not in board.layers:
            raise Usage(f"{board.path.name} has no layer {layer}")
        for (x1, y1), (x2, y2) in zip(t[1], t[1][1:]):
            ops.append({"op": "add_track", "net": need_net(t[0]), "x1": r(x1 + ox), "y1": r(y1 + oy),
                        "x2": r(x2 + ox), "y2": r(y2 + oy), "width": width, "layer": layer})
    return {"ops": ops}


def describe(doc: dict) -> list[str]:
    out = []
    for o in doc["ops"]:
        k = o["op"]
        if k == "move_footprint":
            out.append(f"move {o['ref']} to ({o['x']}, {o['y']})" + (f" rot {o['rotation']}" if "rotation" in o else ""))
        elif k == "remove_routing":
            out.append(f"remove all routing on {', '.join(o['nets'])}")
        elif k == "add_via":
            out.append(f"via {o['net']} at ({o['x']}, {o['y']}) {o['diameter']}/{o['drill']}")
        elif k == "add_track":
            out.append(f"track {o['net']} {o['layer']} w={o['width']}: ({o['x1']}, {o['y1']}) -> ({o['x2']}, {o['y2']})")
        else:
            raise Usage(f"unknown op {k!r}")
    return out


def load_spec(path: str):
    m = env.load_source(path, "edit_spec")
    return m


def cli(argv: list[str]) -> int:
    argv = ["boardwright", *argv]
    if len(argv) not in (4, 5):
        raise Usage(__doc__)
    doc = from_spec(load_spec(argv[1]), Board(argv[2]), argv[4] if len(argv) == 5 else None)
    Path(argv[3]).write_text(json.dumps(doc, indent=1) + "\n")
    print(f"{len(doc['ops'])} op(s) -> {argv[3]}  (absolute mm)")
    print(*("  " + l for l in describe(doc)), sep="\n")
    return 0
