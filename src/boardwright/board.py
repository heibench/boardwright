"""Board-side helpers: explicit placement, outline, GND pours, routing glue.

Coordinates are board-relative mm (0,0 = top-left of the outline), as
kicad-tools' update_footprint_position takes them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from kicad_tools.schema.pcb import PCB

from . import env


def kct(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run([*env.kct(), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"kct {' '.join(args)} -> {r.returncode}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    return r


def create(sch: Path, pcb: Path, w: float, h: float, layers: int = 2) -> None:
    kct("create-pcb", str(sch), "-o", str(pcb), "--width", str(w), "--height", str(h), "--layers", str(layers))


def place(pcb_path: Path, placements: dict[str, tuple], circuit=None, board_dir: Path | None = None) -> None:
    """placements: ref -> (x, y, rot) or (x, y, rot, 'B') for bottom side."""
    pcb = PCB.load(pcb_path)
    refs = {fp.reference for fp in pcb.footprints}
    missing = refs - set(placements)
    if missing:
        raise ValueError(f"unplaced: {sorted(missing)}")
    parts = {p.ref: p for p in circuit.parts} if circuit else {}
    for ref, spec in placements.items():
        x, y, rot = spec[:3]
        if len(spec) > 3 and spec[3] == "B":
            fp = pcb.get_footprint(ref)
            nets = {pad.number: pad.net_name for pad in fp.pads if pad.net_name}
            p = parts[ref]
            nick, name = p.footprint.split(":")
            pcb.remove_footprint(ref)
            pcb.add_footprint_from_file(board_dir / "libs" / f"{nick}.pretty" / f"{name}.kicad_mod",
                                        ref, x, y, rot, layer="B.Cu", value=p.value,
                                        library_id=p.footprint)
            for num, net in nets.items():
                pcb.assign_net_to_footprint_pad(ref, num, net)
        elif not pcb.update_footprint_position(ref, x, y, rot):
            raise ValueError(f"no footprint {ref}")
    pcb.save(pcb_path)


def gnd_pour(pcb_path: Path, net: str = "GND", layers=("F.Cu", "B.Cu"), clearance=0.3, solid=False) -> None:
    """Whole-board pour. solid=True connects pads without thermal reliefs (power boards)."""
    from . import copper
    from .model import Board
    t = pcb_path.read_text()
    bd = Board(pcb_path)
    ox, oy = bd.origin
    x0, y0, x1, y1 = bd.bbox
    rect = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    copper.append(pcb_path, [copper.zone(copper._net(t, net, True), layer, rect, ox, oy, 0, clearance, solid, 0.25)
                             for layer in layers])
