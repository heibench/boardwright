"""Describe a set of items copied out of a board, in the board's own terms.

    boardwright selection SELECTION_FILE BOARD.kicad_pcb

SELECTION_FILE is KiCad's text for selected or copied board items (what the
API's SaveSelectionToString returns, and what the clipboard holds): a small
kicad_pcb document in absolute file coordinates whose footprints carry no
reference, and a pad selected on its own is wrapped in an anonymous footprint.
Footprints are matched to the board by UUID and loose pads by position;
everything is printed in the board-relative mm the other tools use.
"""

from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path

from .errors import Usage
from .model import Board


def describe(sel_file: Path, board_file: Path) -> list[str]:
    if sel_file.stat().st_size == 0:
        return ["nothing selected"]
    with tempfile.TemporaryDirectory() as td:          # the parser wants a .kicad_pcb name
        f = Path(td) / "selection.kicad_pcb"
        shutil.copy(sel_file, f)
        sel = Board(f)
        _ = sel.pads, sel.tracks, sel.vias, sel.zones   # read while the file exists
    board = Board(board_file)
    ox, oy = board.origin
    R = lambda x, y: f"({x - ox:.3f}, {y - oy:.3f})"
    by_uuid = {fp.uuid: fp for fp in board.pcb.footprints}
    out = []
    for fp in sel.pcb.footprints:
        hit = by_uuid.get(fp.uuid)
        if hit is not None:
            nets = sorted({p.net for p in board.pads if p.ref == hit.reference and p.net})
            out.append(f"footprint {hit.reference} at {R(*fp.position)} rot {fp.rotation:g} {fp.layer}  nets: {', '.join(nets)}")
    # Pads selected on their own arrive wrapped in an anonymous footprint: match each to the board's pad there
    known = {f.uuid for f in sel.pcb.footprints if f.uuid in by_uuid}
    loose = [p for p in sel.pads if not p.ref]
    if not known:
        for p in loose:
            x, y = p.x - ox, p.y - oy
            m = min(board.pads, key=lambda q: math.hypot(q.x - x, q.y - y), default=None)
            if m and math.hypot(m.x - x, m.y - y) < 0.02:
                out.append(f"pad {m.ref}.{m.num} {m.net} at ({m.x:.3f}, {m.y:.3f}) {m.layer}")
            else:
                out.append(f"pad ? {p.net} at {R(p.x, p.y)} (no pad of the board is there)")
    for t in sel.tracks:
        kind = "arc" if len(t.pts) > 2 else "track"
        out.append(f"{kind} {t.net} {t.layer} {R(*t.a)} -> {R(*t.b)} w={t.width:g} len={t.length:.2f}")
    for v in sel.vias:
        out.append(f"via {v.net} at {R(v.x, v.y)} {v.size:g}/{v.drill:g}")
    for z in sel.zones:
        out.append(f"zone {'keep-out' if z.keepout else z.net} {'/'.join(z.layers)}")
    return out or ["selection holds no footprints, tracks, vias or zones"]


def cli(argv: list[str]) -> int:
    argv = ["boardwright", *argv]
    if len(argv) != 3:
        raise Usage(__doc__)
    print(*describe(Path(argv[1]), Path(argv[2])), sep="\n")
    return 0
