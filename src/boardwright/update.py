"""Bring a board in line with its schematic, as KiCad's Update PCB from Schematic
does, from KiCad's own netlist.

    boardwright existing <project dir> update [NETLIST.net]

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

Not done, and listed instead: a footprint changed in the schematic (swap it in
KiCad), a symbol with no footprint or a footprint not found (nothing is written
then), and footprints whose symbol is gone (left on the board). Tracks and
zones are not touched: DRC shows what a changed net leaves unconnected or
shorted. Each change replaces only its own block, as everywhere in boardwright.

The judge is KiCad: DRC with --schematic-parity reports no parity issue after
an update that did everything. Boards saved by KiCad 10 or later only (pads
carry their net by name).
"""

from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

from . import env, sch
from .copper import blocks
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
        comps[sp.group(2) + ts.group(1)] = {
            "ref": _str(c, "ref"), "value": _str(c, "value") or "", "footprint": _str(c, "footprint") or "",
            "sheetname": re.sub(r"\\(.)", r"\1", sp.group(1)), "sheetfile": props.get("Sheetfile", ""),
            "skip": "exclude_from_board" in props,
        }
    pins = {}
    for s, e in blocks(text, ("net",)):
        n = text[s:e]
        name = _str(n, "name")
        for a, b in blocks(n, ("node",)):
            pins[(_str(n[a:b], "ref"), _str(n[a:b], "pin"))] = name
    return comps, pins


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


def _set_pad_net(pad: str, net: str) -> str:
    if re.search(r'\n\s*\(net "', pad):
        return re.sub(r'(\n\s*)\(net "(?:[^"\\]|\\.)*"\)', lambda m: f'{m.group(1)}(net "{_esc(net)}")', pad, count=1)
    ind = re.search(r"\n(\s*)\(", pad[1:]).group(1)          # the indent of the pad's own items (the second line)
    m = re.search(r"\n\s*\(uuid ", pad)
    k = m.start() if m else pad.rstrip().rfind("\n")
    return pad[:k] + f'\n{ind}(net "{_esc(net)}")' + pad[k:]


def _with_pad_nets(fp: str, want: dict) -> str:
    for s, e, num, _have in reversed(_pads(fp)):
        if num and num in want:
            fp = fp[:s] + _set_pad_net(fp[s:e], want[num]) + fp[e:]
    return fp


def _extent(mod: str) -> tuple[float, float, float, float]:
    xs, ys = [0.0], [0.0]
    for x, y in re.findall(r"\((?:at|start|end|xy|center|mid) ([-\d.]+) ([-\d.]+)", mod):
        xs.append(float(x))
        ys.append(float(y))
    return min(xs), min(ys), max(xs), max(ys)


def new_footprint(mod: str, lib_id: str, sym: dict, path: str, x: float, y: float, nets: dict) -> str:
    """A library footprint (.kicad_mod text) as a board footprint: named LIB:NAME,
    at (x, y) unrotated on the top, linked to its symbol, its pads on their nets
    and its own zones moved with it."""
    t = mod.strip()
    if not t.startswith("(footprint "):
        raise SystemExit(f"{lib_id}: not a footprint file")
    t = re.sub(r'^\(footprint "(?:[^"\\]|\\.)*"', f'(footprint "{_esc(lib_id)}"', t, count=1)
    t = re.sub(r"\n\t\((?:version|generator|generator_version) [^\n]*\)", "", t)
    t = re.sub(r'\(uuid "[^"]*"\)', lambda m: f'(uuid "{uuid.uuid4()}")', t)
    t = re.sub(r'(\n\t\(layer "[^"]*"\))', lambda m: f'{m.group(1)}\n\t(uuid "{uuid.uuid4()}")\n\t(at {x:g} {y:g})', t, count=1)
    if f"(at {x:g} {y:g})" not in t:
        raise SystemExit(f"{lib_id}: no (layer ...) line to place it after")
    for name, val in (("Reference", sym["ref"]), ("Value", sym["value"])):
        t = re.sub(r'(\n\t\(property "%s" )"(?:[^"\\]|\\.)*"' % name, lambda m: f'{m.group(1)}"{_esc(val)}"', t, count=1)
    props = [(s, e) for s, e in blocks(t, ("property",)) if t[s:s + 12] == "\n\t(property "]
    k = props[-1][1] if props else t.index("\n", t.index("(at "))
    link = f'\n\t(path "{path}")\n\t(sheetname "{_esc(sym["sheetname"])}")\n\t(sheetfile "{_esc(sym["sheetfile"])}")'
    t = t[:k] + link + t[k:]
    for s, e in reversed(blocks(t, ("zone",))):              # footprint zones are stored board-absolute
        z = re.sub(r"\(xy ([-\d.]+) ([-\d.]+)\)", lambda m: f"(xy {float(m.group(1)) + x:g} {float(m.group(2)) + y:g})", t[s:e])
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
    r = subprocess.run([*env.kicad_cli(), "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(nl), str(sch_file)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not nl.exists():
        raise EnvironmentFault(f"kicad-cli could not export the netlist:\n{r.stdout[-1500:]}{r.stderr[-1500:]}")
    return nl


def update(d: Path, pcb: Path, netlist: str | None = None) -> int:
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
            nick, _, name = c["footprint"].partition(":")
            lib = sch.fp_dir(d, nick)
            mod = lib / f"{name}.kicad_mod" if lib else None
            if mod is None or not mod.exists():
                blockers.append(f"{c['ref']}: footprint {c['footprint']} not found "
                                f"({'library ' + nick + ' not in any fp-lib-table or the stock folder' if lib is None else mod})")
                continue
            adds.append((path, c, mod, want))
            continue
        s, e = span
        used.add(span)
        fp, lib_id = t[s:e], re.match(r'\n\t\(footprint "((?:[^"\\]|\\.)*)"', t[s:e]).group(1)
        if c["footprint"] and c["footprint"] != lib_id:
            blockers.append(f"{c['ref']}: footprint is {lib_id} on the board, {c['footprint']} in the schematic; swap it in KiCad")
            continue
        new = fp
        if span not in by_path.values():                 # matched by reference: link it, as KiCad's re-link does
            new = link(new, path, c["sheetname"], c["sheetfile"])
            notes.append(f"{c['ref']}: linked to its symbol")
        for name in ("Reference", "Value"):
            have, val = _prop(new, name), c["ref" if name == "Reference" else "value"]
            if have is not None and have != val:
                new = _set_prop(new, name, val)
                notes.append(f"{c['ref']}: {name} {have} -> {val}")
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
            made.append(new_footprint(text, c["footprint"], c, path, fx, fy, want))
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
