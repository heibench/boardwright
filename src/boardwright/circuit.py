"""Describe a circuit as parts + pin->net maps, and emit a KiCad schematic.

Crude on purpose: every pin gets a short wire stub and a net label (or a
no-connect flag), so connectivity is exactly what the dict says and never
depends on wire geometry. Readable enough for review, correct by construction,
and KiCad's ERC + netlist export check it anyway.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from kicad_tools.schematic.models.schematic import Schematic
from kicad_tools.schematic.models.symbol import SymbolDef

GRID = 2.54
STUB = 2 * GRID


@dataclass
class Part:
    ref: str
    lib_id: str
    value: str
    footprint: str
    pins: dict[str, str | None]  # pin number -> net name, None = no-connect
    unit: int = 1
    bom: bool = True   # False for mounting holes etc. (footprint is exclude_from_bom)


@dataclass
class Circuit:
    title: str
    parts: list[Part] = field(default_factory=list)
    # nets that need a PWR_FLAG because no power_out pin drives them
    # (e.g. a rail entering from a connector). Auto-detected if left empty.
    pwr_flags: list[str] | None = None
    # filled by write_schematic: (ref, pad, KiCad's "unconnected-(...)" net name)
    nc_nets: list[tuple[str, str, str]] = field(default_factory=list)
    # schematic grouping: lists of refs drawn together (functional blocks)
    groups: list[list[str]] | None = None

    def add(self, ref, lib_id, value, footprint, pins, unit=1, bom=True) -> Part:
        p = Part(ref, lib_id, value, footprint, {str(k): v for k, v in pins.items()}, unit, bom)
        self.parts.append(p)
        return p

    def nets(self) -> dict[str, list[tuple[str, str]]]:
        out: dict[str, list[tuple[str, str]]] = {}
        for p in self.parts:
            for pin, net in p.pins.items():
                if net:
                    out.setdefault(net, []).append((p.ref, pin))
        return out


def _outward(angle_into_body: float) -> tuple[float, float]:
    a = math.radians(angle_into_body + 180)
    return round(math.cos(a)), -round(math.sin(a))  # lib y-up -> sheet y-down


def _label_rot(dx: float, dy: float) -> int:
    return {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(dx, dy)]


PAPERS = [("A4", 297, 210), ("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594), ("A0", 1189, 841)]
MARGIN, TITLE_H, GAP = 15.0, 40.0, 6 * GRID


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


def _rot_of(p: Part, sd) -> int:
    """Draw vertical 2-pin parts (R, C) horizontally: labels then sit on one row."""
    pins = [q for q in sd.pins if sd.get_pin_unit(q.number) in (0, p.unit)]
    if len(pins) == 2 and all(q.angle in (90, 270) for q in pins):
        return 90
    return 0


def _rot_pt(x: float, y: float, r: int) -> tuple[float, float]:
    """Rotate a sheet-space (y-down) offset by r degrees CCW as KiCad displays it."""
    a = math.radians(r)
    return round(x * math.cos(a) + y * math.sin(a), 4), round(-x * math.sin(a) + y * math.cos(a), 4)


def _extent(p: Part) -> tuple[float, float, float, float]:
    """Sheet-space extent of a part relative to its origin, incl. stubs + labels."""
    sd = SymbolDef.from_library(p.lib_id)
    r = _rot_of(p, sd)
    xs, ys = [-5.0, 5.0], [-5.0, 5.0]
    for pin in sd.pins:
        if sd.get_pin_unit(pin.number) not in (0, p.unit) or pin.number not in p.pins:
            continue
        px, py = _rot_pt(pin.x, -pin.y, r)
        net = p.pins[pin.number]
        dx, dy = _outward(pin.angle + r)
        L = 0 if net is None else STUB + 0.85 * len(net) + 3
        xs += [px, px + dx * L]
        ys += [py, py + dy * L]
    pad = 4.0
    return min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad


def _pack(c: Circuit, items: list[tuple[str, tuple]], width: float) -> tuple[dict, float, float]:
    """Shelf-pack each group; inside a shelf, short parts stack in columns.

    Returns key -> origin offset, used width, used height.
    """
    groups = [list(g) for g in (c.groups or [])]
    grouped = {r for g in groups for r in g}
    rest = [k for k, _ in items if k not in grouped]
    if rest:
        groups.append(rest)
    ext = dict(items)
    size = {k: (e[2] - e[0], e[3] - e[1]) for k, e in ext.items()}
    pos, y, used_w = {}, 0.0, 0.0
    g2 = GAP / 2
    for g in groups:
        keys = sorted(g, key=lambda k: -size[k][1])
        x, row_h, col_x, col_y, col_w = 0.0, None, 0.0, 0.0, 0.0
        for key in keys:
            w, h = size[key]
            if row_h is None:
                row_h = h
            if col_y > 0 and col_y + h <= row_h:      # stack in current column
                px, py = col_x, col_y
                col_w = max(col_w, w)
            else:                                     # new column
                col_x = x if col_y == 0 else col_x + col_w + g2
                if col_x > 0 and col_x + w > width:   # new shelf
                    y += row_h + g2
                    row_h, col_x = h, 0.0
                px, py, col_w = col_x, 0.0, w
            x0, y0 = ext[key][0], ext[key][1]
            pos[key] = (px - x0, y + py - y0)
            col_y = py + h + g2
            x = col_x + col_w + g2
            used_w = max(used_w, col_x + col_w)
        y += (row_h or 0) + GAP
    return pos, used_w, y


def write_schematic(c: Circuit, path: Path) -> dict:
    c.nc_nets.clear()
    pin_types: dict[str, set[str]] = {}
    for p in c.parts:
        for _num, net in p.pins.items():
            if net:
                pin_types.setdefault(net, set())
    items = [(p.ref, _extent(p)) for p in c.parts]
    for paper, pw, ph in PAPERS:  # noqa: B007 (used after the loop)
        pos, uw, uh = _pack(c, items, pw - 2 * MARGIN)
        if uh <= ph - 2 * MARGIN - TITLE_H:
            break
    sch = Schematic(title=c.title, paper=paper)
    for p in c.parts:
        ox, oy = pos[p.ref]
        r = _rot_of(p, SymbolDef.from_library(p.lib_id))
        s = sch.add_symbol(p.lib_id, x=_snap(MARGIN + ox), y=_snap(MARGIN + oy), ref=p.ref,
                           value=p.value, footprint=p.footprint, unit=p.unit, rotation=r)
        defined = {}
        for pin in s.symbol_def.pins:
            if p.unit and s.symbol_def.get_pin_unit(pin.number) not in (0, p.unit):
                continue
            defined[pin.number] = pin
        missing = set(p.pins) - set(defined)
        if missing:
            raise ValueError(f"{p.ref} ({p.lib_id}) has no pins {sorted(missing)}")
        unassigned = set(defined) - set(p.pins)
        if unassigned:
            raise ValueError(f"{p.ref}: pins {sorted(unassigned)} not assigned (use None for NC)")
        for num, net in p.pins.items():
            pin = defined[num]
            px, py = s.pin_position(num)
            if net is None:
                sch.add_no_connect(px, py)
                c.nc_nets.append((p.ref, num, f"unconnected-({p.ref}-{pin.name}-Pad{num})"))
                continue
            dx, dy = _outward(pin.angle + r)
            ex, ey = px + dx * STUB, py + dy * STUB
            sch.add_wire((px, py), (ex, ey))
            sch.add_global_label(net, ex, ey, rotation=_label_rot(dx, dy), snap=False)
            pin_types[net].add(pin.pin_type)

    flags = c.pwr_flags
    if flags is None:
        flags = [n for n, t in pin_types.items() if "power_in" in t and "power_out" not in t]
    fx, fy = _snap(MARGIN + uw + 4 * GRID), _snap(MARGIN + 4 * GRID)
    if fx > pw - MARGIN - 10:
        fx, fy = _snap(MARGIN + 4 * GRID), _snap(MARGIN + uh)
    for i, net in enumerate(sorted(flags)):
        x = fx + i * 8 * GRID
        sch.add_pwr_flag(x, fy)
        sch.add_wire((x, fy), (x, fy + STUB))
        sch.add_global_label(net, x, fy + STUB, rotation=270, snap=False)
    sch.write(str(path), auto_size_paper=False)
    nobom = {p.ref for p in c.parts if not p.bom}
    if nobom:
        blocks = Path(path).read_text().split("\n\t(symbol\n")
        for i, b in enumerate(blocks):
            if any(f'(property "Reference" "{r}"' in b for r in nobom):
                blocks[i] = b.replace("(in_bom yes)", "(in_bom no)", 1)
        Path(path).write_text("\n\t(symbol\n".join(blocks))
    return {"pwr_flags": sorted(flags), "nets": len(c.nets()), "paper": paper}
