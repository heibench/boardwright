"""Board-side helpers: explicit placement, outline, GND pours, routing glue.

Coordinates are board-relative mm (0,0 = top-left of the outline, as
copper.origin defines it).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from . import copper
from .model import balanced

_LAYERS = {
    2: '\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n',
    4: '\t\t(0 "F.Cu" signal)\n\t\t(1 "In1.Cu" signal)\n\t\t(2 "In2.Cu" signal)\n\t\t(31 "B.Cu" signal)\n',
}
_USER_LAYERS = """\t\t(32 "B.Adhes" user "B.Adhesive")
\t\t(33 "F.Adhes" user "F.Adhesive")
\t\t(34 "B.Paste" user)
\t\t(35 "F.Paste" user)
\t\t(36 "B.SilkS" user "B.Silkscreen")
\t\t(37 "F.SilkS" user "F.Silkscreen")
\t\t(38 "B.Mask" user)
\t\t(39 "F.Mask" user)
\t\t(40 "Dwgs.User" user "User.Drawings")
\t\t(44 "Edge.Cuts" user)
\t\t(46 "B.CrtYd" user "B.Courtyard")
\t\t(47 "F.CrtYd" user "F.Courtyard")
\t\t(48 "B.Fab" user)
\t\t(49 "F.Fab" user)
"""


def _stackup_layer(name: str, kind: str, *more: str) -> str:
    return f'\t\t\t(layer "{name}"\n\t\t\t\t(type "{kind}")\n' + "".join(f"\t\t\t\t{m}\n" for m in more) + "\t\t\t)\n"


# The 4-layer stackup, as kicad-tools 0.29's create-pcb wrote it: 35 um copper, prepreg 0.2 / core 1.0 /
# prepreg 0.2 mm, FR4 at er 4.5 and loss tangent 0.02, ENIG. The 2-layer board has no stackup block.
_COPPER = ("(thickness 0.035)",)
_FR4 = ("(material \"FR4\")", "(epsilon_r 4.5)", "(loss_tangent 0.02)")
_STACKUP = "\t\t(stackup\n" + "".join((
    _stackup_layer("F.SilkS", "Top Silk Screen"),
    _stackup_layer("F.Paste", "Top Solder Paste"),
    _stackup_layer("F.Mask", "Top Solder Mask", "(thickness 0.01)"),
    _stackup_layer("F.Cu", "copper", *_COPPER),
    _stackup_layer("dielectric 1", "prepreg", "(thickness 0.2)", *_FR4),
    _stackup_layer("In1.Cu", "copper", *_COPPER),
    _stackup_layer("dielectric 2", "core", "(thickness 1)", *_FR4),
    _stackup_layer("In2.Cu", "copper", *_COPPER),
    _stackup_layer("dielectric 3", "prepreg", "(thickness 0.2)", *_FR4),
    _stackup_layer("B.Cu", "copper", *_COPPER),
    _stackup_layer("B.Mask", "Bottom Solder Mask", "(thickness 0.01)"),
    _stackup_layer("B.Paste", "Bottom Solder Paste"),
    _stackup_layer("B.SilkS", "Bottom Silk Screen"),
)) + '\t\t\t(copper_finish "ENIG")\n\t\t\t(dielectric_constraints no)\n\t\t)\n'
A4 = (297, 210)     # mm, the sheet the board is centred on


def create(sch: Path, pcb: Path, w: float, h: float, layers: int, circuit) -> None:
    """A new board for `circuit`, whose schematic is `sch`: a w x h mm Edge.Cuts
    rectangle centred on an A4 sheet, 2 or 4 copper layers, and every part's
    footprint from the project's libraries, its pads on the circuit's nets.

    Each footprint is at (0, 0) on the sheet, where its library coordinates are
    its board coordinates, for `place` to move. No-connect pads are left off any
    net (set_pad_nets gives them KiCad's name), and footprints are linked to
    their symbols by `place` (link_symbols)."""
    from datetime import date

    from .update import _esc, _library_footprint, _with_pad_nets, new_footprint

    if layers not in _LAYERS:
        raise ValueError(f"LAYERS must be 2 or 4, not {layers}")
    d = sch.parent
    nets = list(dict.fromkeys(n for p in circuit.parts for n in p.pins.values() if n))
    codes = {n: i for i, n in enumerate(nets, 1)}
    fps = []
    for p in circuit.parts:
        if not p.footprint:
            raise ValueError(f"{p.ref} has no footprint")
        mod, why = _library_footprint(d, p.footprint)
        if mod is None:
            raise ValueError(f"{p.ref}: footprint {p.footprint} not found ({why})")
        fp = new_footprint(mod.read_text(), p.footprint, {"ref": p.ref, "value": p.value}, None, 0, 0, {})
        fps.append(_with_pad_nets(fp, {num: net for num, net in p.pins.items() if net}, codes))
    ox, oy = (A4[0] - w) / 2, (A4[1] - h) / 2
    corners = [(ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h)]
    edge = "".join(
        f"\t(gr_line\n\t\t(start {copper.num(x0)} {copper.num(y0)})\n\t\t(end {copper.num(x1)} {copper.num(y1)})\n"
        f"\t\t(stroke\n\t\t\t(width 0.1)\n\t\t\t(type default)\n\t\t)\n\t\t(layer \"Edge.Cuts\")\n\t\t(uuid \"{uuid.uuid4()}\")\n\t)\n"
        for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]))
    pcb.write_text(
        "(kicad_pcb\n\t(version 20241229)\n\t(generator \"boardwright\")\n"
        "\t(general\n\t\t(thickness 1.6)\n\t\t(legacy_teardrops no)\n\t)\n\t(paper \"A4\")\n"
        f"\t(title_block\n\t\t(title \"{_esc(sch.stem)}\")\n\t\t(date \"{date.today().isoformat()}\")\n"
        "\t\t(rev 1.0)\n\t\t(company \"\")\n\t)\n"
        f"\t(layers\n{_LAYERS[layers]}{_USER_LAYERS}\t)\n"
        f"\t(setup\n{_STACKUP if layers == 4 else ''}\t\t(pad_to_mask_clearance 0)\n\t)\n"
        "\t(net 0 \"\")\n" + "".join(f"\t(net {codes[n]} \"{_esc(n)}\")\n" for n in nets)
        + edge.rstrip("\n") + "".join(fps) + "\n)")


def _write(pcb_path: Path, t0: str, t: str) -> None:
    if not balanced(t):
        raise SystemExit(f"the edit would unbalance {pcb_path.name}; nothing written")
    if pcb_path.read_text() != t0:
        raise SystemExit(f"{pcb_path.name} changed on disk since it was read; nothing written")
    if t != t0:
        pcb_path.write_text(t)


def place(pcb_path: Path, placements: dict[str, tuple]) -> None:
    """Place every footprint of a board fresh from `create`: placements maps
    ref -> (x, y, rot) or (x, y, rot, 'B') for the back. Each footprint's own
    block is edited (turned over, moved); the rest of the file stays as it was."""
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
        fp = move_footprint(fp, ref, x, y, rot, origin)
        t = t[:s] + fp + t[e:]
    _write(pcb_path, t0, t)
    link_symbols(pcb_path, pcb_path.with_suffix(".kicad_sch"))


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
    the footprint-local geometry mirrored in y, including its zones, which KiCad
    keeps board-absolute: `create` puts the footprint at (0, 0), where the two
    frames are the same; a pad's absolute angle a becomes 2r - a and a text's
    180 + 2r - a (r the footprint's angle), and texts are mirrored."""
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
    schematic, by reference, as KiCad links them: `create` writes no link."""
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
