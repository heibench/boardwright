"""Describe a circuit as parts + pin->net maps, and emit a KiCad schematic.

Crude on purpose: every pin gets a short wire stub and a net label (or a
no-connect flag), so connectivity is exactly what the dict says and never
depends on wire geometry. Readable enough for review, correct by construction,
and KiCad's ERC + netlist export check it anyway.
"""

from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import env
from .copper import blocks
from .sch import _cache_entry, _flatten, _symbol_blocks

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


@dataclass
class Pin:
    name: str
    number: str
    x: float          # library coordinates (y up) of the end a wire meets
    y: float
    angle: float      # the direction the pin points into the body
    pin_type: str
    unit: int         # 0: on every unit


@dataclass
class Symbol:
    """A library symbol, flattened as the schematic's symbol cache holds it,
    and its pins in the order the library lists them."""
    body: str
    pins: list[Pin]

    def get_pin_unit(self, number: str) -> int:
        """The unit of the first pin numbered `number` (1 for a pin on every unit)."""
        return next((p.unit or 1 for p in self.pins if p.number == number), 1)


def _pins(body: str) -> list[Pin]:
    units = [(m.start(), int(m.group(1))) for m in re.finditer(r'\(symbol "[^"]*_(\d+)_\d+"', body)]
    out = []
    for s, e in blocks(body, ("pin",)):
        p = body[s:e]
        typ = re.match(r"\s*\(pin (\w+)", p)
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)", p)
        num = re.search(r'\(number "([^"]*)"', p)
        name = re.search(r'\(name "([^"]*)"', p)
        if typ and at and num and num.group(1):
            unit = next((u for pos, u in reversed(units) if pos < s), 0)
            out.append(Pin(name.group(1) if name else "", num.group(1), float(at.group(1)), float(at.group(2)),
                           float(at.group(3)), typ.group(1), unit))
    return out


def library_symbol(lib_id: str, libs: dict[str, dict[str, str]] | None = None) -> Symbol:
    """LIB:NAME from KiCad's symbol libraries (env.libraries: a board's merged
    view while it is built), `extends` flattened. libs caches each library's
    symbols for the caller."""
    nick, name = lib_id.split(":", 1)
    libs = {} if libs is None else libs
    if nick not in libs:
        libs[nick] = _symbol_blocks((env.libraries()[0] / f"{nick}.kicad_sym").read_text(encoding="utf-8"))
    if name not in libs[nick]:
        raise ValueError(f"{nick}.kicad_sym has no symbol {name!r}")
    body = _flatten(libs[nick], name)
    return Symbol(body, _pins(body))


def _outward(angle_into_body: float) -> tuple[float, float]:
    a = math.radians(angle_into_body + 180)
    return round(math.cos(a)), -round(math.sin(a))  # lib y-up -> sheet y-down


def _label_rot(dx: float, dy: float) -> int:
    return {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(dx, dy)]


PAPERS = [("A4", 297, 210), ("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594), ("A0", 1189, 841)]
MARGIN, TITLE_H, GAP = 15.0, 40.0, 6 * GRID


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


def _rot_of(p: Part, sd: Symbol) -> int:
    """Draw vertical 2-pin parts (R, C) horizontally: labels then sit on one row."""
    pins = [q for q in sd.pins if sd.get_pin_unit(q.number) in (0, p.unit)]
    if len(pins) == 2 and all(q.angle in (90, 270) for q in pins):
        return 90
    return 0


def _rot_pt(x: float, y: float, r: int) -> tuple[float, float]:
    """Rotate a sheet-space (y-down) offset by r degrees CCW as KiCad displays it."""
    a = math.radians(r)
    return round(x * math.cos(a) + y * math.sin(a), 4), round(-x * math.sin(a) + y * math.cos(a), 4)


def _extent(p: Part, sd: Symbol) -> tuple[float, float, float, float]:
    """Sheet-space extent of a part relative to its origin, incl. stubs + labels."""
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


# Deterministic uuids, as kicad-tools 0.29 derives them for a schematic it
# writes (kicad_tools/core/schematic_uuids.py: the namespace and the key
# format), so a regenerated schematic keeps the uuids it had. Ported from
# kicad-tools under its licence:
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
_UUID_NS = uuid.UUID("6f0a7e3c-6076-5d1b-8a2e-4c5d6e076076")


def _key(parts: tuple) -> str:
    def part(v):
        if isinstance(v, int | float) and not isinstance(v, bool):
            s = f"{float(v):.4f}"
            return "0.0000" if s == "-0.0000" else s
        return str(v)
    return "\x1f".join(part(v) for v in parts)


def _stable_uuid(*parts) -> str:
    return str(uuid.uuid5(_UUID_NS, _key(parts)))


class _Uuids:
    """uuid5 of a key and how many times it was asked for before, never one handed out already."""

    def __init__(self) -> None:
        self.taken: set[str] = set()
        self.count: dict[str, int] = {}

    def __call__(self, *key) -> str:
        k = _key(key)
        n = self.count.get(k, 0)
        while True:
            u = str(uuid.uuid5(_UUID_NS, f"{k}\x1f#{n}"))
            n += 1
            if u not in self.taken:
                break
        self.count[k] = n
        self.taken.add(u)
        return u


SHEET_GRID = 1.27     # KiCad's default schematic grid (50 mil): symbols, wires and no-connects sit on it
DATE = "2025-01"      # the title block's date as kicad-tools 0.29 wrote it, kept so regenerated files are unchanged


def _on_grid(v: float) -> float:
    """v on the 1.27 mm grid, to 0.01 mm. A value already stored to 0.01 mm and
    within 0.005 of a grid point stays as it is (kicad-tools 0.29's snap_to_grid)."""
    snapped = round(v / SHEET_GRID) * SHEET_GRID
    stored = round(v, 2)
    if abs(v - stored) < 1e-9 and abs(stored - snapped) <= 0.005 + 1e-9:
        return stored
    return round(snapped, 2)


def _n(v: float) -> str:
    r = round(v, 2)
    return str(int(r)) if r == int(r) else f"{r:.6g}"


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r") + '"'


def _pin_at(sd: Symbol, unit: int, num: str, x: float, y: float, r: int) -> tuple[float, float]:
    """Where a wire meets pin `num` of a symbol placed at (x, y), turned r degrees."""
    pin = next((q for q in sd.pins if q.number == num and q.unit in (0, unit)), None) \
        or next(q for q in sd.pins if q.number == num)
    px, py = pin.x, pin.y
    if r:
        c, s = math.cos(math.radians(r)), math.sin(math.radians(r))
        px, py = px * c - py * s, px * s + py * c
    return round(x + px, 2), round(y - py, 2)


def _prop(name: str, value: str, x: float, y: float, hide: bool) -> str:
    return (f"\n\t\t(property {_q(name)} {_q(value)}\n\t\t\t(at {_n(x)} {_n(y)} 0)\n\t\t\t(effects\n"
            "\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)" + ("\n\t\t\t\t(hide yes)" if hide else "")
            + "\n\t\t\t)\n\t\t)")


def _placed(lib_id: str, x: float, y: float, r: int, unit: int, bom: bool, sid: str, props: str,
            pins: list[tuple[str, str]], sheet: str, ref: str) -> str:
    return (f"\n\t(symbol\n\t\t(lib_id {_q(lib_id)})\n\t\t(at {_n(x)} {_n(y)} {r})\n\t\t(unit {unit})"
            f"\n\t\t(exclude_from_sim no)\n\t\t(in_bom {'yes' if bom else 'no'})\n\t\t(on_board yes)\n\t\t(dnp no)"
            f'\n\t\t(uuid "{sid}")' + props
            + "".join(f'\n\t\t(pin {_q(n)} (uuid "{u}")\n\t\t)' for n, u in pins)
            + f'\n\t\t(instances\n\t\t\t(project "project"\n\t\t\t\t(path "/{sheet}" (reference {_q(ref)}) (unit {unit})'
            "\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)")


def _wire(a: tuple[float, float], b: tuple[float, float], u: str) -> str:
    return (f"\n\t(wire\n\t\t(pts (xy {_n(a[0])} {_n(a[1])}) (xy {_n(b[0])} {_n(b[1])}))"
            f'\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n\t\t(uuid "{u}")\n\t)')


def _label(net: str, x: float, y: float, r: int, u: str) -> str:
    return (f"\n\t(global_label {_q(net)} (shape bidirectional) (at {_n(x)} {_n(y)} {r}) (fields_autoplaced yes)"
            "\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)"
            f"\n\t\t\t(justify {'right' if r == 180 else 'left'})\n\t\t)\n\t\t(uuid \"{u}\")\n\t)")


def write_schematic(c: Circuit, path: Path) -> dict:
    """Write the circuit as a KiCad schematic: each part from its library symbol,
    a wire stub and a global label on every connected pin, a no-connect flag on
    every open one, and PWR_FLAGs. The same circuit and libraries give the same
    file, uuids included."""
    c.nc_nets.clear()
    libs: dict[str, dict[str, str]] = {}
    syms: dict[str, Symbol] = {}
    for p in c.parts:
        if p.lib_id not in syms:
            syms[p.lib_id] = library_symbol(p.lib_id, libs)
    pin_types: dict[str, set[str]] = {}
    for p in c.parts:
        for _num, net in p.pins.items():
            if net:
                pin_types.setdefault(net, set())
    items = [(p.ref, _extent(p, syms[p.lib_id])) for p in c.parts]
    for paper, pw, ph in PAPERS:  # noqa: B007 (used after the loop)
        pos, uw, uh = _pack(c, items, pw - 2 * MARGIN)
        if uh <= ph - 2 * MARGIN - TITLE_H:
            break
    sheet = _stable_uuid("sheet", "", "project", c.title, "1")
    mint = _Uuids()
    placed, wires, ncs, labels = [], [], [], []
    for p in c.parts:
        sd = syms[p.lib_id]
        ox, oy = pos[p.ref]
        r = _rot_of(p, sd)
        x, y = _on_grid(_snap(MARGIN + ox)), _on_grid(_snap(MARGIN + oy))
        sid = mint(sheet, "symbol", p.ref, p.unit)
        seen: dict[str, int] = {}
        pin_ids = []
        for q in sd.pins:
            pin_ids.append((q.number, _stable_uuid("pin", sid, q.number, seen.get(q.number, 0))))
            seen[q.number] = seen.get(q.number, 0) + 1
        props = (_prop("Reference", p.ref, x, y - 5.08, False) + _prop("Value", p.value or p.lib_id.split(":", 1)[1], x, y - 2.54, False)
                 + _prop("Footprint", p.footprint, x, y, True) + _prop("Datasheet", "~", x, y, True))
        placed.append(_placed(p.lib_id, x, y, r, p.unit, p.bom, sid, props, pin_ids, sheet, p.ref))
        defined = {}
        for pin in sd.pins:
            if p.unit and sd.get_pin_unit(pin.number) not in (0, p.unit):
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
            px, py = _pin_at(sd, p.unit, num, x, y, r)
            if net is None:
                ncs.append((_on_grid(px), _on_grid(py)))
                c.nc_nets.append((p.ref, num, f"unconnected-({p.ref}-{pin.name}-Pad{num})"))
                continue
            dx, dy = _outward(pin.angle + r)
            ex, ey = px + dx * STUB, py + dy * STUB
            wires.append(((_on_grid(px), _on_grid(py)), (_on_grid(ex), _on_grid(ey))))
            labels.append((net, round(ex, 2), round(ey, 2), _label_rot(dx, dy)))
            pin_types[net].add(pin.pin_type)

    flags = c.pwr_flags
    if flags is None:
        flags = [n for n, t in pin_types.items() if "power_in" in t and "power_out" not in t]
    fx, fy = _snap(MARGIN + uw + 4 * GRID), _snap(MARGIN + 4 * GRID)
    if fx > pw - MARGIN - 10:
        fx, fy = _snap(MARGIN + 4 * GRID), _snap(MARGIN + uh)
    power = []
    if flags:
        syms["power:PWR_FLAG"] = library_symbol("power:PWR_FLAG", libs)
    for i, net in enumerate(sorted(flags)):
        x = fx + i * 8 * GRID
        ref, px, py = f"#PWR{i + 1:02d}", _on_grid(x), _on_grid(fy)
        sid = mint(sheet, "power", ref)
        props = (_prop("Reference", ref, px, py + 2.54, True) + _prop("Value", "PWR_FLAG", px, py + 5.08, False)
                 + _prop("Footprint", "", px, py, True) + _prop("Datasheet", "", px, py, True))
        power.append(_placed("power:PWR_FLAG", px, py, 0, 1, True, sid, props, [("1", _stable_uuid("pin", sid, "1", 0))], sheet, ref))
        wires.append(((_on_grid(x), _on_grid(fy)), (_on_grid(x), _on_grid(fy + STUB))))
        labels.append((net, round(x, 2), round(fy + STUB, 2), 270))

    out = (f'(kicad_sch\n\t(version 20231120)\n\t(generator "eeschema")\n\t(generator_version "10.0")\n\t(uuid "{sheet}")'
           f"\n\t(paper {_q(paper)})\n\t(title_block\n\t\t(title {_q(c.title)})\n\t\t(date {_q(DATE)})\n\t\t(rev \"A\")"
           '\n\t\t(company "")\n\t\t(comment 1 "")\n\t\t(comment 2 "")\n\t)'
           "\n\t(lib_symbols" + "".join(_cache_entry(sd.body, i) for i, sd in syms.items()) + "\n\t)"
           + "".join(placed) + "".join(power)
           + "".join(_wire(a, b, mint(sheet, "wire", *a, *b)) for a, b in wires)
           + "".join(f'\n\t(no_connect (at {_n(x)} {_n(y)}) (uuid "{mint(sheet, "no_connect", x, y)}")\n\t)' for x, y in ncs)
           + "".join(_label(n, x, y, r, mint(sheet, "global_label", n, x, y)) for n, x, y, r in labels)
           + f'\n\t(sheet_instances\n\t\t(path "/{sheet}" (page "1")\n\t\t)\n\t)\n)')
    Path(path).write_text(out, encoding="utf-8")
    return {"pwr_flags": sorted(flags), "nets": len(c.nets()), "paper": paper}
