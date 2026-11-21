"""Bring a board in line with its schematic, as KiCad's Update PCB from Schematic
does, from KiCad's own netlist.

    boardwright existing <project dir> update [NETLIST.net] [--body keep|library]

The netlist is KiCad's own (`kicad-cli sch export netlist --format kicadsexpr`),
made here unless one is given. Footprints are matched to symbols by their path, as
KiCad matches them. For each symbol:

- on the board: its reference and value are brought over, and every pad takes
  the net the netlist gives its pin;
- not on the board: its footprint is taken from the library (project
  fp-lib-table, KiCad's global one, then the stock folder) and put beside the
  board outline, unrotated on the top, with its pads on their nets, for you to
  place;
- marked "exclude from board": skipped.

A footprint changed in the schematic is swapped when the new library footprint's
pads are the board footprint's (number, type, shape, position, angle, size,
drill, layers): the link alone (--body keep, the default), or the drawing too
(--body library); the footprint's place, fields, pads and nets stay.

Not done, and listed instead: a footprint changed to one whose pads differ
(swap it in KiCad), a symbol with no footprint or a footprint not found
(nothing is written then), and footprints whose symbol is gone (left on the
board; `existing apply`'s REMOVE takes them off). Tracks and
zones are not touched: DRC shows what a changed net leaves unconnected or
shorted. Each change replaces only its own block, as everywhere in boardwright.

The judge is KiCad: DRC with --schematic-parity reports no parity issue after
an update that did everything. Boards saved by KiCad 10 or later only (pads
carry their net by name).
"""

from __future__ import annotations

import math
import re
import subprocess
import uuid
from pathlib import Path

from . import env, sch
from .copper import blocks
from .copper import num as mm_
from .errors import EnvironmentFault, Usage


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _str(block: str, key: str) -> str | None:
    m = re.search(r'\(%s "((?:[^"\\]|\\.)*)"' % key, block)
    return re.sub(r"\\(.)", r"\1", m.group(1)) if m else None


def read_netlist(path: Path) -> tuple[dict, dict]:
    """KiCad netlist (kicadsexpr) -> ({board path: symbol}, {(ref, pin): net}).
    Net names stay as KiCad writes them on the board, a "/" in a label as
    {slash}; the XML netlist unescapes them and cannot be read back exactly."""
    try:
        text = path.read_text()
    except OSError as e:
        raise Usage(f"cannot read netlist {path}: {e}") from None
    if not text.lstrip().startswith("(export"):
        raise Usage(f"{path} is not a KiCad netlist in its own format (kicad-cli sch export netlist --format kicadsexpr)")
    comps = {}
    for s, e in blocks(text, ("comp",)):
        c = text[s:e]
        sp = re.search(r'\(sheetpath\s*\(names "((?:[^"\\]|\\.)*)"\)\s*\(tstamps "([^"]*)"\)', c)
        ts = re.search(r'\n\s*\(tstamps "([^"]*)"', c[sp.end():] if sp else c)   # one uuid per unit; the board links the first
        if not sp or not ts:
            continue
        props = dict(re.findall(r'\(property\s*\(name "((?:[^"\\]|\\.)*)"\)(?:\s*\(value "((?:[^"\\]|\\.)*)"\))?', c))
        fields = {_unesc(k): _unesc(v) for k, v in _FIELD.findall(c) if k not in ("Reference", "Value", "Footprint")}
        comps[sp.group(2) + ts.group(1)] = {
            "ref": _str(c, "ref"), "value": _str(c, "value") or "", "footprint": _str(c, "footprint") or "",
            "sheetname": re.sub(r"\\(.)", r"\1", sp.group(1)), "sheetfile": props.get("Sheetfile", ""),
            "skip": "exclude_from_board" in props, "fields": fields,
            "dnp": "dnp" in props, "exclude_from_bom": "exclude_from_bom" in props,
        }
    pins = {}
    for s, e in blocks(text, ("net",)):
        n = text[s:e]
        name = _str(n, "name")
        for a, b in blocks(n, ("node",)):
            pins[(_str(n[a:b], "ref"), _str(n[a:b], "pin"))] = name
    return comps, pins


_FIELD = re.compile(r'\(field\s*\(name "((?:[^"\\]|\\.)*)"\)\s*(?:"((?:[^"\\]|\\.)*)")?\s*\)')


def _unesc(v: str) -> str:
    return re.sub(r"\\(.)", r"\1", v)


def _no_datasheet(v: str | None) -> bool:
    return v in (None, "", "~")


def with_fields(fp: str, fields: dict[str, str]) -> tuple[str, list[str]]:
    """The board footprint carrying its symbol's fields (Datasheet, Description,
    user fields), as KiCad's Update PCB from Schematic leaves it, so the
    schematic parity check finds no footprint_symbol_field_mismatch (#95). A
    field the footprint has is set in place; a missing one is added hidden on
    F.Fab at the footprint's origin, the way KiCad writes one. An empty field
    is not added, and "" and "~" are the same empty value. Returns the block
    and the names changed."""
    changed = []
    rot = re.search(r'\n\t\t\(at [-\d.]+ [-\d.]+(?: ([-\d.]+))?\)', fp)
    rot = rot.group(1) if rot and rot.group(1) else "0"
    for name, val in fields.items():
        have = _prop(fp, name)
        have = None if have is None else _unesc(have)
        if have == val or (_no_datasheet(have) and _no_datasheet(val)):
            continue
        if have is not None:
            fp = _set_prop(fp, name, val)
        else:
            props = [(s, e) for s, e in blocks(fp, ("property",)) if fp[s:s + 13] == "\n\t\t(property "]
            k = props[-1][1] if props else fp.index("\n", fp.index("\n\t\t(at "))
            fp = fp[:k] + (f'\n\t\t(property "{_esc(name)}" "{_esc(val)}"\n\t\t\t(at 0 0 {rot})\n\t\t\t(layer "F.Fab")'
                           f'\n\t\t\t(hide yes)\n\t\t\t(uuid "{uuid.uuid4()}")\n\t\t\t(effects\n\t\t\t\t(font\n'
                           '\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t(thickness 0.15)\n\t\t\t\t)\n\t\t\t)\n\t\t)') + fp[k:]
        changed.append(name)
    return fp, changed


# The order KiCad 10 writes a footprint's (attr ...) tokens in.
_ATTR_ORDER = ("smd", "through_hole", "board_only", "exclude_from_pos_files", "exclude_from_bom",
               "allow_missing_courtyard", "dnp", "allow_soldermask_bridges")


def with_flags(fp: str, sym: dict) -> tuple[str, list[str]]:
    """The board footprint with its symbol's "Do not populate" and "Exclude
    from bill of materials" flags in its (attr ...), as KiCad's Update PCB
    sets them; its other attributes are left as they are (#98). Returns the
    block and what changed, e.g. ["dnp set"]."""
    m = re.search(r"\n\t\t\(attr((?: [a-z_]+)*)\)", fp)
    have = m.group(1).split() if m else []
    want = [a for a in have if a not in ("dnp", "exclude_from_bom")] + [a for a in ("dnp", "exclude_from_bom") if sym[a]]
    want.sort(key=lambda a: _ATTR_ORDER.index(a) if a in _ATTR_ORDER else len(_ATTR_ORDER))
    if want == have:
        return fp, []
    changed = [f"{a} {'set' if sym[a] else 'cleared'}" for a in ("dnp", "exclude_from_bom") if (a in have) != sym[a]]
    line = f"\n\t\t(attr {' '.join(want)})" if want else ""
    if m:
        return fp[:m.start()] + line + fp[m.end():], changed
    k = max((e for s, e in blocks(fp, ("property",)) if fp[s:s + 13] == "\n\t\t(property "), default=None)
    for key in ("path", "sheetname", "sheetfile"):
        km = re.search(r'\n\t\t\(%s "[^"]*"\)' % key, fp)
        if km:
            k = km.end()
    if k is None:
        k = fp.index("\n", fp.index("\n\t\t(at "))
    return fp[:k] + line + fp[k:], changed


def _footprints(t: str) -> list[tuple[int, int]]:
    return [(s, e) for s, e in blocks(t, ("footprint",)) if t[s:s + 13] == "\n\t(footprint "]


def _prop(block: str, name: str) -> str | None:
    m = re.search(r'\n\t\t\(property "%s" "((?:[^"\\]|\\.)*)"' % name, block)
    return m.group(1) if m else None


def _set_prop(block: str, name: str, val: str) -> str:
    return re.sub(r'(\n\t\t\(property "%s" )"(?:[^"\\]|\\.)*"' % name, lambda m: f'{m.group(1)}"{_esc(val)}"', block, count=1)


def link(fp: str, path: str, sheetname: str, sheetfile: str) -> str:
    """A board footprint linked to its symbol: path, sheetname and sheetfile after
    its last property, where KiCad writes them."""
    props = [(s, e) for s, e in blocks(fp, ("property",)) if fp[s:s + 13] == "\n\t\t(property "]
    k = props[-1][1] if props else fp.index("\n", fp.index("\n\t\t(at "))
    return fp[:k] + f'\n\t\t(path "{path}")\n\t\t(sheetname "{_esc(sheetname)}")\n\t\t(sheetfile "{_esc(sheetfile)}")' + fp[k:]


def _pads(fp: str) -> list[tuple[int, int, str, str | None]]:
    """(start, end, number, net) of each pad of a footprint block."""
    out = []
    for s, e in blocks(fp, ("pad",)):
        p = fp[s:e]
        num = re.match(r'\s*\(pad "((?:[^"\\]|\\.)*)"', p).group(1)
        net = re.search(r'\n\s*\(net "((?:[^"\\]|\\.)*)"\)', p)
        out.append((s, e, num, net.group(1) if net else None))
    return out


def _set_pad_net(pad: str, net: str, code: int | None = None) -> str:
    """The pad on net `net`; `code` is its number on a board that numbers its nets
    (as KiCad 9 and kicad-tools write them), None on one that names them only."""
    tok = f'(net "{_esc(net)}")' if code is None else f'(net {code} "{_esc(net)}")'
    if re.search(r'\n\s*\(net (?:\d+ )?"', pad):
        return re.sub(r'(\n\s*)\(net (?:\d+ )?"(?:[^"\\]|\\.)*"\)', lambda m: m.group(1) + tok, pad, count=1)
    ind = re.search(r"\n(\s*)\(", pad[1:]).group(1)          # the indent of the pad's own items (the second line)
    m = re.search(r"\n\s*\(uuid ", pad)
    k = m.start() if m else pad.rstrip().rfind("\n")
    return pad[:k] + f'\n{ind}{tok}' + pad[k:]


def _with_pad_nets(fp: str, want: dict, codes: dict | None = None) -> str:
    for s, e, num, _have in reversed(_pads(fp)):
        if num and num in want:
            fp = fp[:s] + _set_pad_net(fp[s:e], want[num], codes[want[num]] if codes else None) + fp[e:]
    return fp


def _flip_layers(s: str) -> str:
    return re.sub(r'"([FB])\.', lambda m: '"' + ("B" if m.group(1) == "F" else "F") + ".", s)


def _num(v: str) -> str:
    return mm_(round(float(v), 4))


def _pad_shapes(fp: str, back: bool, rot: float) -> dict[str, list[tuple]]:
    """Each pad of a footprint as its library defines it: number -> [(type,
    shape, x, y, angle, size, drill, layers, primitives)]. A board footprint
    (rot is its angle) keeps its pads at their library position, in its own
    frame, with the angle absolute; on the back the y axis and the layers are
    mirrored and the angle turns the other way. Measured on KiCad 10.0.8's demo
    boards: 581 of 589 placed footprints match their stock library this way, the
    other 8 differ in size, shape or layers. A library footprint is read with
    back=False, rot=0."""
    out: dict[str, list[tuple]] = {}
    for s, e, num, _net in _pads(fp):
        p = fp[s:e]
        typ, shape = re.match(r'\s*\(pad "(?:[^"\\]|\\.)*" (\S+) (\S+)', p).groups()
        at = re.search(r"\n\s*\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", p)
        x, y, a = float(at.group(1)), float(at.group(2)), float(at.group(3) or 0)
        layers = re.search(r"\(layers ([^)]*)\)", p).group(1)
        prim = blocks(p, ("primitives",))
        prim = re.sub(r"\s+", " ", p[prim[0][0]:prim[0][1]]).strip() if prim else ""
        drill = re.search(r"\(drill ((?:[^()]|\([^()]*\))*)\)", p)
        drill = re.sub(r"\s+", " ", drill.group(1)).strip() if drill else ""
        if back:
            y, layers = -y, _flip_layers(layers)
            prim = re.sub(r"\((start|end|mid|center|xy) ([-\d.]+) ([-\d.]+)\)", lambda m: f"({m.group(1)} {m.group(2)} {mm_(-float(m.group(3)))})", prim)
            drill = re.sub(r"\(offset ([-\d.]+) ([-\d.]+)\)", lambda m: f"(offset {m.group(1)} {mm_(-float(m.group(2)))})", drill)
        a = rot - a if back else a - rot
        prim = re.sub(r"-?\d+(?:\.\d+)?", lambda m: _num(m.group(0)), prim)
        size = " ".join(_num(v) for v in re.search(r"\(size ([^)]*)\)", p).group(1).split())
        out.setdefault(num, []).append((typ, shape, _num(x), _num(y), _num(a % 360 % 360), size, drill, layers, prim))
    return {k: sorted(v) for k, v in out.items()}


_FIELDS = ("type", "shape", "x", "y", "angle", "size", "drill", "layers", "custom shape")


def pad_differences(fp: str, mod: str) -> list[str]:
    """How the pads of board footprint `fp` differ from library footprint `mod`;
    empty when every pad is the same in number, type, shape, position, angle,
    size, drill, layers and custom shape."""
    at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", fp)
    back = re.search(r'\n\t\t\(layer "B\.Cu"\)', fp) is not None
    have, want = _pad_shapes(fp, back, float(at.group(3) or 0)), _pad_shapes(mod, False, 0)
    out = []
    for num in sorted(set(have) | set(want)):
        if num not in want:
            out.append(f"pad {num} is not in the library footprint")
        elif num not in have:
            out.append(f"pad {num} is not on the board")
        elif have[num] != want[num]:
            if len(have[num]) != len(want[num]):
                out.append(f"pad {num}: {len(have[num])} on the board, {len(want[num])} in the library")
                continue
            for h, w in zip(have[num], want[num]):
                for field, hv, wv in zip(_FIELDS, h, w):
                    if hv != wv:
                        out.append(f"pad {num} {field}: {hv or '(none)'} on the board, {wv or '(none)'} in the library")
                        break
                else:
                    continue
                break
    return out


ART = ("fp_line", "fp_arc", "fp_circle", "fp_rect", "fp_poly", "fp_curve", "fp_text", "fp_text_box", "model", "zone")


def _art(fp: str, depth: int) -> list[tuple[int, int]]:
    """The drawings, texts, 3D models and zones of a footprint (not its fields or pads)."""
    head = "\n" + "\t" * depth + "("
    return [(s, e) for s, e in blocks(fp, ART) if fp[s:s + len(head)] == head]


def _upright(a: float) -> float:
    a %= 360
    return a - 180 if 90 < a <= 270 else a


def _placed(item: str, back: bool, x0: float, y0: float, rot: float) -> str:
    """A library footprint's drawing item as KiCad writes it in a footprint placed
    at (x0, y0), turned rot degrees, on the back if `back`. Drawings stay in the
    footprint's own frame (mirrored in y on the back, where an arc's ends swap
    to keep its direction and text is mirrored); a text's angle is absolute and
    kept upright; zones are board-absolute; 3D models are copied as they are.
    Checked against the drawings of the footprints on KiCad's demo boards."""
    kind = re.match(r"\s*\((\S+)", item).group(1)
    if kind == "model":
        return item
    if back:
        item = _flip_layers(item)
        item = re.sub(r"\((start|end|mid|center|xy|at) ([-\d.]+) ([-\d.]+)",
                      lambda m: f"({m.group(1)} {m.group(2)} {mm_(-float(m.group(3)))}", item)
        if kind == "fp_arc":
            st = re.search(r"\(start ([-\d.]+ [-\d.]+)\)", item)
            en = re.search(r"\(end ([-\d.]+ [-\d.]+)\)", item)
            item = (item[:st.start()] + f"(start {en.group(1)})" + item[st.end():en.start()] + f"(end {st.group(1)})" + item[en.end():]
                    if st.start() < en.start() else item)
        if kind in ("fp_text", "fp_text_box"):
            if "(justify" in item:
                item = re.sub(r"\(justify ([^)]*)\)", lambda m: f"(justify {m.group(1)} mirror)", item, count=1)
            else:
                f = blocks(item, ("font",))[0]
                item = item[:f[1]] + " (justify mirror)" + item[f[1]:]
    if kind in ("fp_text", "fp_text_box"):
        def turn(m):
            a = float(m.group(3) or 0)
            return f"(at {m.group(1)} {m.group(2)} {mm_(_upright(rot - a if back else rot + a))})"
        item = re.sub(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", turn, item, count=1)
    if kind == "zone":
        c, s_ = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        item = re.sub(r"\(xy ([-\d.]+) ([-\d.]+)\)",
                      lambda m: (lambda lx, ly: f"(xy {mm_(x0 + lx * c + ly * s_)} {mm_(y0 - lx * s_ + ly * c)})")(
                          float(m.group(1)), float(m.group(2))), item)
    return re.sub(r'\(uuid "[^"]*"\)', lambda m: f'(uuid "{uuid.uuid4()}")', item)


def swap(fp: str, lib_id: str, mod: str, body: str) -> str:
    """Board footprint `fp` linked to library footprint `lib_id` (text `mod`),
    whose pads are the same (see pad_differences). Position, side, fields, pads
    and their nets stay. body="keep" changes the link alone and keeps the drawing;
    body="library" also replaces the drawings, texts, 3D models and zones with
    the library's."""
    fp = re.sub(r'^\n\t\(footprint "(?:[^"\\]|\\.)*"', lambda m: f'\n\t(footprint "{_esc(lib_id)}"', fp, count=1)
    if body == "keep":
        return fp
    at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", fp)
    back = re.search(r'\n\t\t\(layer "B\.Cu"\)', fp) is not None
    x0, y0, rot = float(at.group(1)), float(at.group(2)), float(at.group(3) or 0)
    new = []
    for s, e in _art(mod.strip(), 1):
        item = _placed(mod.strip()[s:e], back, x0, y0, rot)
        new.append("\n" + "\n".join("\t" + ln if ln else ln for ln in item.lstrip("\n").split("\n")))
    old = _art(fp, 2)
    k = old[0][0] if old else _pads(fp)[0][0] if _pads(fp) else fp.rstrip().rfind("\n")
    for s, e in reversed(old):
        fp = fp[:s] + fp[e:]
    return fp[:k] + "".join(new) + fp[k:]


def _extent(mod: str) -> tuple[float, float, float, float]:
    xs, ys = [0.0], [0.0]
    for x, y in re.findall(r"\((?:at|start|end|xy|center|mid) ([-\d.]+) ([-\d.]+)", mod):
        xs.append(float(x))
        ys.append(float(y))
    return min(xs), min(ys), max(xs), max(ys)


def new_footprint(mod: str, lib_id: str, sym: dict, path: str | None, x: float, y: float, nets: dict) -> str:
    """A library footprint (.kicad_mod text) as a board footprint: named LIB:NAME,
    at (x, y) unrotated on the top, linked to its symbol (unless path is None),
    its pads on their nets and its own zones moved with it."""
    t = mod.strip()
    if not t.startswith("(footprint "):
        raise SystemExit(f"{lib_id}: not a footprint file")
    t = re.sub(r'^\(footprint "(?:[^"\\]|\\.)*"', f'(footprint "{_esc(lib_id)}"', t, count=1)
    t = re.sub(r"\n\t\((?:version|generator|generator_version) [^\n]*\)", "", t)
    t = re.sub(r'\(uuid "[^"]*"\)', lambda m: f'(uuid "{uuid.uuid4()}")', t)
    t = re.sub(r'(\n\t\(layer "[^"]*"\))', lambda m: f'{m.group(1)}\n\t(uuid "{uuid.uuid4()}")\n\t(at {mm_(x)} {mm_(y)})', t, count=1)
    if f"(at {mm_(x)} {mm_(y)})" not in t:
        raise SystemExit(f"{lib_id}: no (layer ...) line to place it after")
    for name, val in (("Reference", sym["ref"]), ("Value", sym["value"])):
        t = re.sub(r'(\n\t\(property "%s" )"(?:[^"\\]|\\.)*"' % name, lambda m: f'{m.group(1)}"{_esc(val)}"', t, count=1)
    if path is not None:
        props = [(s, e) for s, e in blocks(t, ("property",)) if t[s:s + 12] == "\n\t(property "]
        k = props[-1][1] if props else t.index("\n", t.index("(at "))
        link = f'\n\t(path "{path}")\n\t(sheetname "{_esc(sym["sheetname"])}")\n\t(sheetfile "{_esc(sym["sheetfile"])}")'
        t = t[:k] + link + t[k:]
    for s, e in reversed(blocks(t, ("zone",))):              # footprint zones are stored board-absolute
        z = re.sub(r"\(xy ([-\d.]+) ([-\d.]+)\)", lambda m: f"(xy {mm_(float(m.group(1)) + x)} {mm_(float(m.group(2)) + y)})", t[s:e])
        t = t[:s] + z + t[e:]
    t = _with_pad_nets(t, nets)
    return "\n\t" + "\n".join(("\t" + ln) if i and ln else ln for i, ln in enumerate(t.split("\n")))


def _outline(t: str) -> tuple[float, float, float, float]:
    """Board-absolute box round the Edge.Cuts drawing (else round every footprint)."""
    pts = []
    for s, e in blocks(t, ("gr_line", "gr_rect", "gr_arc", "gr_poly", "gr_circle", "gr_curve")):
        g = t[s:e]
        if '(layer "Edge.Cuts")' in g:
            pts += [(float(x), float(y)) for x, y in re.findall(r"\((?:start|end|mid|xy|center) ([-\d.]+) ([-\d.]+)\)", g)]
    if not pts:
        pts = [(float(x), float(y)) for x, y in re.findall(r'\n\t\(footprint "[^\n]*\n\t\t\(layer "[^"]*"\)\n\t\t\(uuid "[^"]*"\)\n\t\t\(at ([-\d.]+) ([-\d.]+)', t)]
    if not pts:
        return 0.0, 0.0, 0.0, 0.0
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _netlist(d: Path, pcb: Path, given: str | None) -> Path:
    if given:
        return Path(given)
    sch_file = pcb.with_suffix(".kicad_sch")
    if not sch_file.exists():
        raise EnvironmentFault(f"no schematic {sch_file.name} beside {pcb.name}")
    out = d / "boardwright_out"
    out.mkdir(exist_ok=True)
    nl = out / "netlist.net"
    # update also takes the netlist itself, which needs no kicad-cli here (#144)
    hint = (f"\nOr export the netlist where KiCad works and pass it: `kicad-cli sch export netlist --format kicadsexpr "
            f"-o NETLIST.net {sch_file.name}`, then `boardwright existing {d} update NETLIST.net`.")
    try:
        cli = env.kicad_cli()
    except EnvironmentFault as e:
        raise EnvironmentFault(f"{e}{hint}") from None
    r = subprocess.run([*cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(nl), str(sch_file)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not nl.exists():
        raise EnvironmentFault(f"kicad-cli could not export the netlist:\n{r.stdout[-1500:]}{r.stderr[-1500:]}{hint}")
    return nl


def _library_footprint(d: Path, lib_id: str) -> tuple[Path | None, str]:
    """The .kicad_mod file of footprint LIB:NAME, or None and why it was not found."""
    nick, _, name = lib_id.partition(":")
    lib = sch.fp_dir(d, nick)
    mod = lib / f"{name}.kicad_mod" if lib else None
    if mod is None or not mod.exists():
        return None, (f"library {nick} not in any fp-lib-table or the stock folder" if lib is None else str(mod))
    return mod, ""


def update(d: Path, pcb: Path, netlist: str | None = None, body: str = "keep") -> int:
    env.warn_if_open_in_kicad(pcb)
    t = t0 = pcb.read_text()
    if re.search(r'\n\t\(net 0 ""\)', t):
        raise SystemExit(f"{pcb.name} numbers its nets (saved by KiCad 9 or older); open and save it in KiCad 10 first")
    comps, pins = read_netlist(_netlist(d, pcb, netlist))
    fps = _footprints(t)
    by_path, unlinked = {}, {}                          # footprints by symbol path; those with none, by reference
    for s, e in fps:
        m = re.search(r'\n\t\t\(path "([^"]*)"\)', t[s:e])
        if m:
            by_path[m.group(1)] = (s, e)
        elif not re.search(r"\n\t\t\(attr [^)]*\bboard_only\b", t[s:e]):
            unlinked.setdefault(_prop(t[s:e], "Reference"), (s, e))
    used = set()
    edits, adds, blockers, notes = [], [], [], []           # edits: (start, end, new block)
    for path, c in comps.items():
        if c["skip"]:
            continue
        want = {num: net for (ref, num), net in pins.items() if ref == c["ref"]}
        span = by_path.get(path) or unlinked.get(c["ref"])  # unlinked: matched by reference, as KiCad does
        if span is None:
            if not c["footprint"]:
                blockers.append(f"{c['ref']}: no footprint in the schematic")
                continue
            mod, why = _library_footprint(d, c["footprint"])
            if mod is None:
                blockers.append(f"{c['ref']}: footprint {c['footprint']} not found ({why})")
                continue
            adds.append((path, c, mod, want))
            continue
        s, e = span
        used.add(span)
        fp, lib_id = t[s:e], re.match(r'\n\t\(footprint "((?:[^"\\]|\\.)*)"', t[s:e]).group(1)
        new = fp
        if c["footprint"] and c["footprint"] != lib_id:      # the schematic names another footprint
            mod, why = _library_footprint(d, c["footprint"])
            if mod is None:
                blockers.append(f"{c['ref']}: footprint is {lib_id} on the board, {c['footprint']} in the schematic, "
                                f"which is not found ({why})")
                continue
            text = mod.read_text()
            diff = pad_differences(fp, text)
            if diff:
                blockers.append(f"{c['ref']}: footprint is {lib_id} on the board, {c['footprint']} in the schematic, "
                                f"and their pads differ ({'; '.join(diff[:3])}{'; ...' if len(diff) > 3 else ''}); swap it in KiCad")
                continue
            new = swap(fp, c["footprint"], text, body)
            notes.append(f"{c['ref']}: footprint {lib_id} -> {c['footprint']} (pads match; "
                         f"{'drawing kept' if body == 'keep' else 'drawing from the library'})")
        if span not in by_path.values():                 # matched by reference: link it, as KiCad's re-link does
            new = link(new, path, c["sheetname"], c["sheetfile"])
            notes.append(f"{c['ref']}: linked to its symbol")
        for name in ("Reference", "Value"):
            have, val = _prop(new, name), c["ref" if name == "Reference" else "value"]
            if have is not None and have != val:
                new = _set_prop(new, name, val)
                notes.append(f"{c['ref']}: {name} {have} -> {val}")
        new, fields = with_fields(new, c["fields"])
        if fields:
            notes.append(f"{c['ref']}: {', '.join(fields)} from the symbol")
        new, flags = with_flags(new, c)
        if flags:
            notes.append(f"{c['ref']}: {', '.join(flags)}")
        for _s, _e, num, have in _pads(new):
            if num in want and want[num] != have:
                notes.append(f"{c['ref']}.{num}: net {have or '(none)'} -> {want[num]}")
        new = _with_pad_nets(new, {num: net for _s, _e, num, have in _pads(new) if num in want and want[num] != have
                                   for net in [want[num]]})
        if new != fp:
            edits.append((s, e, new))
    gone = [_prop(t[s:e], "Reference") for span in [*by_path.values(), *unlinked.values()] if span not in used
            for s, e in [span]]
    for b in blockers:
        print("NOT DONE", b)
    if blockers:
        print("nothing written")
        return 1
    if adds:
        x0, y0, x1, _y1 = _outline(t)
        x, y, row = x1 + 10, y0, 0.0
        made = []
        for path, c, mod, want in adds:
            text = mod.read_text()
            ex0, ey0, ex1, ey1 = _extent(text)
            fx, fy = round(x - ex0, 2), round(y - ey0, 2)
            made.append(with_flags(with_fields(new_footprint(text, c["footprint"], c, path, fx, fy, want), c["fields"])[0], c)[0])
            print(f"{c['ref']}: added {c['footprint']} at ({fx:g}, {fy:g}), beside the board: place it")
            y += ey1 - ey0 + 2.54
            row = max(row, ex1 - ex0)
            if y > y0 + 150:
                x, y, row = x + row + 2.54, y0, 0.0
        k = _footprints(t)[-1][1] if fps else t.rstrip().rfind(")")
        edits.append((k, k, "".join(made)))
    for n in notes:
        print(n)
    for r in gone:
        print(f"{r}: not in the schematic; left on the board")
    for s, e, new in sorted(edits, key=lambda x: x[0], reverse=True):
        t = t[:s] + new + t[e:]
    if t.count("(") != t.count(")"):
        raise SystemExit("the update would unbalance the board file; nothing written")
    if pcb.read_text() != t0:
        raise SystemExit(f"{pcb.name} changed on disk since it was read; nothing written")
    if t != t0:
        pcb.write_text(t)
    print(f"{len(adds)} added, {len(edits) - (1 if adds else 0)} footprint(s) changed, {len(gone)} left without a symbol")
    return 0
