"""Board-side helpers: explicit placement, outline, GND pours, routing glue.

Coordinates are board-relative mm (0,0 = top-left of the outline, as
copper.origin defines it).
"""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

from . import copper, env


def kct(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run([*env.kct(), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"kct {' '.join(args)} -> {r.returncode}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    return r


def create(sch: Path, pcb: Path, w: float, h: float, layers: int = 2) -> None:
    kct("create-pcb", str(sch), "-o", str(pcb), "--width", str(w), "--height", str(h), "--layers", str(layers))


def _write(pcb_path: Path, t0: str, t: str) -> None:
    if t.count("(") != t.count(")"):
        raise SystemExit(f"the edit would unbalance {pcb_path.name}; nothing written")
    if pcb_path.read_text() != t0:
        raise SystemExit(f"{pcb_path.name} changed on disk since it was read; nothing written")
    if t != t0:
        pcb_path.write_text(t)


def place(pcb_path: Path, placements: dict[str, tuple]) -> None:
    """Place every footprint of a board fresh from `create`: placements maps
    ref -> (x, y, rot) or (x, y, rot, 'B') for the back. Each footprint's own
    block is edited (turned over, its zones put on the board, moved); the rest of
    the file stays as it was."""
    from .existing import move_footprint
    from .update import _footprints, _prop

    t = t0 = pcb_path.read_text()
    spans = {_prop(t[s:e], "Reference"): (s, e) for s, e in _footprints(t)}
    missing = set(spans) - set(placements)
    if missing:
        raise ValueError(f"unplaced: {sorted(missing)}")
    unknown = set(placements) - set(spans)
    if unknown:
        raise ValueError(f"no footprint {', '.join(sorted(unknown))}")
    origin = copper.origin(pcb_path)
    for ref, (s, e) in sorted(spans.items(), key=lambda kv: kv[1], reverse=True):
        x, y, rot = placements[ref][:3]
        fp = t[s:e]
        if len(placements[ref]) > 3 and placements[ref][3] == "B":
            fp = flip(fp)
        fp = move_footprint(_zones_on_board(fp), ref, x, y, rot, origin)
        t = t[:s] + fp + t[e:]
    _write(pcb_path, t0, t)
    link_symbols(pcb_path, pcb_path.with_suffix(".kicad_sch"))


def _zones_on_board(fp: str) -> str:
    """A footprint block with its own zones (an RF module's antenna keep-out, say)
    turned and moved with the footprint into board coordinates, where KiCad keeps
    them. kicad-tools' create-pcb (0.29) writes them in the library's coordinates,
    the footprint's own frame."""
    at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", fp)
    fx, fy, rot = float(at.group(1)), float(at.group(2)), float(at.group(3) or 0)
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))

    def board(m):
        lx, ly = float(m.group(1)), float(m.group(2))
        return f"(xy {copper.num(fx + lx * c + ly * s)} {copper.num(fy - lx * s + ly * c)})"
    for zs, ze in reversed(copper.blocks(fp, ("zone",))):
        fp = fp[:zs] + re.sub(r"\(xy ([-\d.]+) ([-\d.]+)\)", board, fp[zs:ze]) + fp[ze:]
    return fp


_ITEMS = ("property", "fp_text", "fp_text_box", "fp_line", "fp_arc", "fp_circle", "fp_rect", "fp_poly", "fp_curve",
          "pad", "zone")
_CHAMFER = {"top_left": "bottom_left", "bottom_left": "top_left", "top_right": "bottom_right", "bottom_right": "top_right"}


def _mirror_text(item: str) -> str:
    """A text item with `mirror` added to its justification, as on the back."""
    es, ee = copper.blocks(item, ("effects",))[0]
    eff = item[es:ee]
    j = re.search(r"\(justify([^()]*)\)", eff)
    if j:
        if "mirror" not in j.group(1).split():
            eff = eff[:j.end() - 1] + " mirror" + eff[j.end() - 1:]
    elif "\n" in eff.strip("\n\t"):
        k = eff.rfind("\n")
        eff = eff[:k] + eff[:eff.index("(")].replace("\n", "\n\t", 1) + "(justify mirror)" + eff[k:]
    else:
        eff = eff[:-1] + " (justify mirror))"
    return item[:es] + eff + item[ee:]


def flip(fp: str) -> str:
    """A front footprint block of a board fresh from `create` turned over onto
    the back, in place, as KiCad's Flip stores it (kicad-tools 0.29 checked its
    own version of these rules against pcbnew 10.0.6): F.*/B.* layers swapped;
    the footprint-local geometry mirrored in y, including its zones, which are
    still in the footprint's own frame then (see _zones_on_board); a pad's
    absolute angle a becomes 2r - a and a text's 180 + 2r - a (r the footprint's
    angle), and texts are mirrored."""
    from .update import _flip_layers

    at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", fp)
    r = float(at.group(3) or 0)

    def neg(m):
        return f"({m.group(1)} {m.group(2)} {copper.num(-float(m.group(3)))}"
    out, last = [], 0
    for s, e in copper.blocks(fp, _ITEMS):
        if fp[s:s + 4] != "\n\t\t(":
            continue
        item = fp[s:e]
        kind = re.match(r"\s*\((\S+)", item).group(1)
        item = re.sub(r"\((layers?) ([^()]*)\)", lambda m: f"({m.group(1)} {_flip_layers(m.group(2))})", item)
        if kind in ("pad", "property", "fp_text"):
            a = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", item)
            ang = float(a.group(3) or 0)
            new = 2 * r - ang if kind == "pad" else round((180 + 2 * r - ang) % 360, 6) % 360
            tail = f" {copper.num(new)}" if a.group(3) or new else ""
            head, rest = item[:a.start()] + f"(at {a.group(1)} {copper.num(-float(a.group(2)))}{tail})", item[a.end():]
            if kind == "pad":                    # its drill offset and custom-shape primitives
                rest = re.sub(r"\((start|end|mid|center|xy|offset) ([-\d.]+) ([-\d.]+)", neg, rest)
                rest = re.sub(r"\(chamfer ([^()]*)\)",
                              lambda m: "(chamfer " + " ".join(_CHAMFER.get(w, w) for w in m.group(1).split()) + ")", rest)
                item = head + rest
            else:
                item = _mirror_text(head + rest)
        else:
            item = re.sub(r"\((start|end|mid|center|xy) ([-\d.]+) ([-\d.]+)", neg, item)
            if kind == "fp_text_box":
                item = _mirror_text(item)
        out.append(fp[last:s] + item)
        last = e
    fp = "".join(out) + fp[last:]
    return re.sub(r'(\n\t\t\(layer )"F\.Cu"\)', r'\1"B.Cu")', fp, count=1)


def set_pad_nets(pcb_path: Path, nets) -> None:
    """Put pads on nets: nets is (ref, pad number, net name), every pad of that
    number taking it. A net the board does not list yet is added to its net list;
    otherwise only the footprints' own blocks change."""
    from .update import _esc, _footprints, _prop, _with_pad_nets

    t = t0 = pcb_path.read_text()
    table = {re.sub(r"\\(.)", r"\1", name): int(n) for n, name in re.findall(r'\n\t\(net (\d+) "((?:[^"\\]|\\.)*)"\)', t)}
    new = [name for _r, _n, name in nets if name not in table]
    for name in dict.fromkeys(new):
        table[name] = max(table.values(), default=0) + 1
    want: dict[str, dict] = {}
    for ref, num, name in nets:
        want.setdefault(ref, {})[num] = name
    for s, e in reversed(_footprints(t)):
        ref = _prop(t[s:e], "Reference")
        if ref in want:
            t = t[:s] + _with_pad_nets(t[s:e], want.pop(ref), table) + t[e:]
    if want:
        raise ValueError(f"no footprint {', '.join(sorted(want))}")
    if new:
        k = list(re.finditer(r'\n\t\(net \d+ "(?:[^"\\]|\\.)*"\)', t))[-1].end()
        t = t[:k] + "".join(f'\n\t(net {table[n]} "{_esc(n)}")' for n in dict.fromkeys(new)) + t[k:]
    _write(pcb_path, t0, t)


def link_symbols(pcb_path: Path, sch_path: Path) -> int:
    """Link each footprint of a generated board to its symbol on the (flat, root)
    schematic, by reference, as KiCad links them: kicad-tools writes no link."""
    from . import sch, update
    if not sch_path.exists():
        return 0
    s = sch.Sheet(sch_path)
    uuids = {}
    for a, b in s.instances():
        blk = s.text[a:b]
        m = re.search(r'\n\t\t\(uuid "([^"]*)"\)', blk)
        if m:
            uuids[sch.prop(blk, "Reference")] = m.group(1)
    t = pcb_path.read_text()
    n = 0
    for a, b in reversed(update._footprints(t)):
        fp = t[a:b]
        ref = update._prop(fp, "Reference")
        if "\n\t\t(path " not in fp and ref in uuids:
            t = t[:a] + update.link(fp, "/" + uuids[ref], "/", sch_path.name) + t[b:]
            n += 1
    pcb_path.write_text(t)
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
