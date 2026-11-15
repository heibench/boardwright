"""Board-side helpers: explicit placement, outline, GND pours, routing glue.

Coordinates are board-relative mm (0,0 = top-left of the outline), as
kicad-tools' update_footprint_position takes them.
"""

from __future__ import annotations

import re
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
    if board_dir is not None:
        place_footprint_zones(pcb_path, board_dir)


def place_footprint_zones(pcb_path: Path, board_dir: Path) -> int:
    """Put each footprint's own zones (an RF module's antenna keep-out, say) where
    KiCad would: the library outline turned and moved with the footprint, in board
    coordinates. kicad-tools 0.29 leaves them in the library's coordinates when it
    creates the board and only shifts them on later moves, so they end up beside
    the part and KiCad reports the footprint as differing from its library copy.
    Returns the number of zones placed."""
    import math

    from .copper import blocks

    t = pcb_path.read_text()
    out, pos, n = [], 0, 0
    for s, e in blocks(t, ("footprint",)):
        fp = t[s:e]
        zones = blocks(fp, ("zone",))
        if not zones:
            continue
        lib_id = re.search(r'\(footprint "([^"]+)"', fp).group(1)
        nick, name = lib_id.split(":", 1)
        mod = (board_dir / "libs" / f"{nick}.pretty" / f"{name}.kicad_mod").read_text()
        lib_zones = blocks(mod, ("zone",))
        if len(lib_zones) != len(zones):
            raise ValueError(f"{lib_id}: {len(zones)} zone(s) on the board, {len(lib_zones)} in the library")
        at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", fp)
        fx, fy, rot = float(at.group(1)), float(at.group(2)), float(at.group(3) or 0)
        back = re.search(r'\n\t\t\(layer "B\.Cu"\)', fp) is not None
        c, sn = math.cos(math.radians(rot)), math.sin(math.radians(rot))

        def place(x: float, y: float) -> tuple[float, float]:
            if back:                    # a back-side footprint's outline is mirrored top to bottom
                y = -y
            return fx + x * c + y * sn, fy - x * sn + y * c

        new_fp, last = [], 0
        for (zs, ze), (ls, le) in zip(zones, lib_zones):
            lib_pts = [place(float(x), float(y)) for x, y in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", mod[ls:le])]
            z = fp[zs:ze]
            if len(re.findall(r"\(xy [-\d.]+ [-\d.]+\)", z)) != len(lib_pts):
                raise ValueError(f"{lib_id}: zone outline differs from the library's")
            it = iter(lib_pts)
            new_fp.append(fp[last:zs] + re.sub(r"\(xy [-\d.]+ [-\d.]+\)",
                                               lambda m: "(xy %s %s)" % tuple(f"{v:.6f}".rstrip("0").rstrip(".") for v in next(it)), z))
            last = ze
            n += 1
        new_fp.append(fp[last:])
        out.append(t[pos:s] + "".join(new_fp))
        pos = e
    if n:
        pcb_path.write_text("".join(out) + t[pos:])
    return n


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
