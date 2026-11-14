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
