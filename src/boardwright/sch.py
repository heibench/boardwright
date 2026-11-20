"""Edit an existing KiCad schematic in place, a block at a time.

    boardwright sch <project dir> parts [PATTERN]
    boardwright sch <project dir> set REF Field=Value [Field=Value ...]
    boardwright sch <project dir> add SPEC.py
    boardwright sch <project dir> remove REF [REF ...]
    boardwright sch <project dir> repoint OLD_LIB:OLD_NAME NEW_LIB:NEW_NAME [--body keep|library]
    boardwright sch ercdiff OLD.json NEW.json

Nothing is parsed and rewritten: the file is searched for the exact block to
change, only that span is replaced, and the result is written only if the
file on disk is still what was read. Everything else stays byte-identical, so
a diff shows exactly the edit.

`set` changes properties (Value, Footprint, any other the part already has)
and the flags dnp, in_bom, on_board (yes/no).

`add` takes ADD = [(ref, like, value, footprint, {pin: net}), ...] and an
optional SHEET = "file.kicad_sch" (default: the root sheet). `like` is
either the reference of a part already in the project, which is copied (symbol,
fields and the file's own format come along), or a library symbol LIB:NAME,
looked up as for `repoint` and added to the sheet's symbol cache, with its
fields from the library and the file's format from a part already placed.
The new part goes in free space with a short wire from each pin to a label of
the kind its net already uses (a sheet pin's hierarchical label, a local or a
global label) or, for a power net, to a copy of that net's power symbol, from
any sheet. A net that is local to another sheet is refused: it can only be
reached through a sheet pin. Pins not listed are left open. Library symbols
must be single-unit and not power symbols.

The judge is KiCad: record the connectivity before (`netspec snap`) and
compare after (`netspec diff`), and compare ERC reports with `ercdiff`. An edit
is right when the difference is the change you meant and nothing else.

`repoint` points every part that uses one library symbol at another, on every
sheet: the symbol cache entry, its units and each part's lib_id are renamed
(`--body keep`, the default, keeps the drawing), or the cache entry is replaced
from the new library (`--body library`). The new symbol is found through the
project's sym-lib-table, then KiCad's global one, then KiCad's stock libraries.
Its pin numbers must be the same set as the cached symbol's, or nothing is
written.

Hierarchy: parts on sub-sheets are listed and can be `set`. On a sheet that is
used more than once, one symbol stands for a part in each use: `parts` says
so, `set` changes all of them (and says so), and `remove` and `add` refuse.
A part added to a sub-sheet takes that sheet's hierarchy path from a part
already on it.

Limits: nothing is moved or re-drawn. A schematic open in
KiCad will not notice the change: close and reopen it.
"""

from __future__ import annotations

import fnmatch
import hashlib
import importlib.util
import math
import re
import uuid
from pathlib import Path

from . import env
from .copper import blocks
from .copper import num as mm_
from .errors import EnvironmentFault, Usage

GRID = 1.27


class Sheet:
    def __init__(self, path: Path):
        self.path = path
        self.text = path.read_text()
        self.digest = hashlib.sha256(self.text.encode()).hexdigest()

    def instances(self) -> list[tuple[int, int]]:
        """Spans of placed symbols (not the cached library symbols)."""
        return [(s, e) for s, e in blocks(self.text, ("symbol",)) if re.match(r"\n\t\(symbol\b", self.text[s:s + 12])]

    def write(self, new: str) -> None:
        env.warn_if_open_in_kicad(self.path)
        if hashlib.sha256(self.path.read_text().encode()).hexdigest() != self.digest:
            raise SystemExit(f"{self.path.name} changed on disk since it was read; nothing written")
        if new.count("(") != new.count(")"):
            raise SystemExit("edit would unbalance the file; nothing written")
        self.path.write_text(new)
        self.text, self.digest = new, hashlib.sha256(new.encode()).hexdigest()


def prop(block: str, name: str) -> str | None:
    m = re.search(r'\(property "%s" "((?:[^"\\]|\\.)*)"' % re.escape(name), block)
    return m.group(1) if m else None


def refs(block: str) -> list[str]:
    """Every reference a placed symbol goes by. A sheet used more than once in a
    hierarchy gives each of its symbols one reference per use, listed under
    (instances ...); the "Reference" property holds only one of them."""
    i = block.find("(instances")
    out = re.findall(r'\(reference "((?:[^"\\]|\\.)*)"\)', block[i:]) if i >= 0 else []
    return out or [prop(block, "Reference") or ""]


def sheets(d: Path) -> list[Sheet]:
    files = sorted(p for p in d.glob("*.kicad_sch") if not p.name.startswith(("~", "_")))
    if not files:
        raise EnvironmentFault(f"no .kicad_sch in {d}")
    return [Sheet(p) for p in files]


def root(d: Path) -> Sheet:
    pros = list(d.glob("*.kicad_pro"))
    if len(pros) == 1 and pros[0].with_suffix(".kicad_sch").exists():
        return Sheet(pros[0].with_suffix(".kicad_sch"))
    ss = sheets(d)
    if len(ss) != 1:
        raise EnvironmentFault("cannot tell which sheet is the root: expected <project>.kicad_sch beside one .kicad_pro")
    return ss[0]


def find(d: Path, ref: str) -> tuple[Sheet, int, int]:
    hits = [(sh, s, e) for sh in sheets(d) for s, e in sh.instances() if ref in refs(sh.text[s:e])]
    if len(hits) != 1:
        raise SystemExit(f"{len(hits)} symbols have the reference {ref!r} (need exactly one; multi-unit parts are not handled)")
    return hits[0]


def shared_with(block: str, ref: str) -> list[str]:
    return [r for r in refs(block) if r != ref]


def locked(sh: Sheet) -> bool:
    return (sh.path.parent / f"~{sh.path.name}.lck").exists()


def parts(d: Path, pattern: str) -> int:
    for sh in sheets(d):
        for s, e in sh.instances():
            b = sh.text[s:e]
            lib = re.search(r'\(lib_id "([^"]*)"', b).group(1)
            flags = "".join(f" {k}" for k in ("dnp",) if re.search(r"\(%s yes\)" % k, b))
            all_refs = refs(b)
            for ref in all_refs:
                if ref.startswith("#") or not fnmatch.fnmatch(ref, pattern):
                    continue
                also = f"  same symbol as {', '.join(r for r in all_refs if r != ref)}" if len(all_refs) > 1 else ""
                print(f"{ref:<8}{(prop(b, 'Value') or ''):<26}{(prop(b, 'Footprint') or ''):<44} {lib}  [{sh.path.name}]{flags}{also}")
    return 0


def set_fields(d: Path, ref: str, pairs: list[str]) -> int:
    sh, s, e = find(d, ref)
    b = sh.text[s:e]
    others = shared_with(b, ref)
    if others:
        print(f"note: {ref} is one use of a symbol on a sheet that is used more than once; this also changes {', '.join(others)}")
    for pair in pairs:
        name, _, val = pair.partition("=")
        if name in ("dnp", "in_bom", "on_board"):
            if val not in ("yes", "no"):
                raise Usage(f"{name} takes yes or no")
            nb, n = re.subn(r"\(%s (?:yes|no)\)" % name, f"({name} {val})", b, count=1)
        else:
            old = prop(b, name)
            if old is None:
                have = ", ".join(re.findall(r'\(property "([^"]*)"', b))
                raise Usage(f"{ref} has no property {name!r} (it has: {have})")
            esc = val.replace("\\", "\\\\").replace('"', '\\"')
            nb, n = re.subn(r'(\(property "%s" )"(?:[^"\\]|\\.)*"' % re.escape(name), lambda m: f'{m.group(1)}"{esc}"', b, count=1)
            if name == "Reference":
                if others:                       # rename this use only; the property belongs to all of them
                    nb, n = re.subn(r'\(reference "%s"\)' % re.escape(ref), f'(reference "{esc}")', b, count=1)
                else:
                    nb = re.sub(r'\(reference "(?:[^"\\]|\\.)*"\)', f'(reference "{esc}")', nb)
        if n != 1:
            raise SystemExit(f"could not set {name} on {ref}")
        print(f"{ref}: {name} -> {val}")
        b = nb
    sh.write(sh.text[:s] + b + sh.text[e:])
    if locked(sh):
        print(f"note: {sh.path.name} is open in KiCad; close and reopen it to see the change")
    return 0


def remove(d: Path, refs: list[str]) -> int:
    for ref in refs:
        sh, s, e = find(d, ref)
        others = shared_with(sh.text[s:e], ref)
        if others:
            raise SystemExit(f"{ref} shares its symbol with {', '.join(others)} (a sheet used more than once): "
                             "removing it would remove them too; do this one in KiCad")
        sh.write(sh.text[:s] + sh.text[e:])
        print(f"removed {ref} from {sh.path.name} (its wires and labels are left; ERC will show what now dangles)")
    return 0


# ---- add ---------------------------------------------------------------

def _lib_pins(text: str, lib_id: str) -> dict[str, tuple[float, float, float]]:
    """pin number -> (x, y, angle) in library coordinates, from the sheet's symbol cache."""
    cache = blocks(text, ("lib_symbols",))
    body = _symbol_blocks(text[cache[0][0]:cache[0][1]]).get(lib_id) if cache else None
    if body is None:
        raise SystemExit(f"{lib_id} is not in the sheet's symbol cache")
    out = {}
    for s, e in blocks(body, ("pin",)):
        p = body[s:e]
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", p)
        num = re.search(r'\(number "([^"]*)"', p)
        if at and num:
            out[num.group(1)] = (float(at.group(1)), float(at.group(2)), float(at.group(3) or 0))
    return out


def _fresh(block: str) -> str:
    return re.sub(r'\(uuid "[^"]*"\)', lambda m: f'(uuid "{uuid.uuid4()}")', block)


def _retarget(block: str, x: float, y: float, tidy: bool = True) -> str:
    """Move a cloned symbol to (x, y), unrotated and unmirrored, fields carried along."""
    m = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: [-\d.]+)?\)", block)
    ox, oy = float(m.group(1)), float(m.group(2))
    block = block[:m.start()] + f"\n\t\t(at {mm_(x)} {mm_(y)} 0)" + block[m.end():]
    block = re.sub(r"\n\t\t\(mirror [xy]\)", "", block, count=1)
    def shift(mm):
        name = re.match(r'\(property "([^"]*)"', mm.group(1)).group(1)
        if not tidy:                                # a power symbol keeps its own field layout
            return f"{mm.group(1)}(at {mm_(float(mm.group(2)) - ox + x)} {mm_(float(mm.group(3)) - oy + y)} {mm.group(4) or '0'})"
        if name == "Reference":                     # the copy is unrotated: put its two visible fields beside it
            return f"{mm.group(1)}(at {mm_(x + 2.54)} {mm_(y - 1.27)} 0)"
        if name == "Value":
            return f"{mm.group(1)}(at {mm_(x + 2.54)} {mm_(y + 1.27)} 0)"
        return f"{mm.group(1)}(at {mm_(float(mm.group(2)) - ox + x)} {mm_(float(mm.group(3)) - oy + y)} {mm.group(4) or '0'})"
    if tidy:
        block = re.sub(r'(\(property "(?:Reference|Value)" "(?:[^"\\]|\\.)*"[\s\S]*?)\(justify [^)]*\)', r"\1(justify left)", block, count=2)
    return re.sub(r'(\(property "[^"]*" "(?:[^"\\]|\\.)*"\s+)\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', shift, block)


def _rot(dx: float, dy: float, deg: float) -> tuple[float, float]:
    """A sheet-axis offset (y down) turned counter-clockwise on screen by deg."""
    c, s = round(math.cos(math.radians(deg)), 9), round(math.sin(math.radians(deg)), 9)
    return dx * c + dy * s, -dx * s + dy * c


def _place_power(src: str, ex: float, ey: float, away: float, pin: tuple[float, float, float]) -> str:
    """A copy of power symbol `src` whose pin sits on (ex, ey) and whose body
    points `away` (0 right, 90 up, 180 left, 270 down), so it never lies over the
    part it connects. Its fields turn with it; their text stays upright."""
    qx, qy, qa = pin                                 # a symbol's body lies in its pin's direction
    m = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", src)
    ox, oy, r0 = float(m.group(1)), float(m.group(2)), float(m.group(3) or 0)
    r = (away - qa) % 360
    px, py = _rot(qx, -qy, r)
    x, y = round(ex - px, 4), round(ey - py, 4)
    b = src[:m.start()] + f"\n\t\t(at {mm_(x)} {mm_(y)} {mm_(r)})" + src[m.end():]
    b = re.sub(r"\n\t\t\(mirror [xy]\)", "", b, count=1)

    def move(mm):
        dx, dy = _rot(float(mm.group(2)) - ox, float(mm.group(3)) - oy, -r0)
        dx, dy = _rot(dx, dy, r)
        return f"{mm.group(1)}(at {mm_(x + dx)} {mm_(y + dy)} {mm.group(4) or '0'})"
    return re.sub(r'(\(property "[^"]*" "(?:[^"\\]|\\.)*"\s+)\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', move, b)


PAPER = {"A5": (210, 148), "A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A1": (841, 594), "A0": (1189, 841),
         "A": (279.4, 215.9), "B": (431.8, 279.4), "C": (558.8, 431.8), "D": (863.6, 558.8), "USLetter": (279.4, 215.9)}


def snap(v: float) -> float:
    return round(round(v / GRID) * GRID, 4)


def _free_spot(t: str, w_mm: float, h_mm: float) -> tuple[float, float]:
    """Top-left of an empty w_mm x h_mm strip on the sheet for the new parts.

    Looks right of everything drawn, then below it, inside the frame; a full
    sheet is an error rather than a part dropped on top of the drawing."""
    m = re.search(r'\(paper "([^"]+)"(?: ([\d.]+) ([\d.]+))?', t)
    pw, ph = (float(m.group(2)), float(m.group(3))) if m and m.group(2) else PAPER.get(m.group(1) if m else "A4", (297, 210))
    cache = blocks(t, ("lib_symbols",))
    body = t[cache[0][1]:] if cache else t              # what is drawn, not the cached library symbols
    cell = 2.54
    nx, ny = int(pw / cell) + 1, int(ph / cell) + 1
    used = [[False] * ny for _ in range(nx)]
    def mark(x, y, r=0.0):
        k = int(r / cell) + 1
        ix, iy = int(x / cell), int(y / cell)
        for i in range(max(0, ix - k), min(nx, ix + k + 1)):
            for j in range(max(0, iy - k), min(ny, iy + k + 1)):
                used[i][j] = True
    for x, y in re.findall(r"\(at ([-\d.]+) ([-\d.]+)", body):            # symbols, labels, text: keep clear round each
        mark(float(x), float(y), 7.62)
    for x1, y1, x2, y2 in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)\s*\(xy ([-\d.]+) ([-\d.]+)\)", body):   # wires, lines
        x1, y1, x2, y2 = map(float, (x1, y1, x2, y2))
        steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / cell))
        for i in range(steps + 1):
            mark(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps, 2.54)
    margin = 20.0                                        # clear of the frame, its ruler and a part's own fields
    w, h = int((w_mm + 5.08) / cell) + 1, int((h_mm + 5.08) / cell) + 1
    for j in range(int(margin / cell), ny - h - int(margin / cell)):
        for i in range(int(margin / cell), nx - w - int(margin / cell)):
            if i * cell > pw - 125 and j * cell > ph - 60:              # the title block corner
                continue
            if not any(used[a][b] for a in range(i, i + w) for b in range(j, j + h)):
                return snap(i * cell + 2.54), snap(j * cell + 2.54)
    raise SystemExit("no free area on the sheet for the new parts; make room in KiCad or use a larger sheet")


def _pin_end(ang: float) -> tuple[int, int]:
    """Unit step away from the body for a pin at library angle ang, in sheet axes."""
    a = math.radians(ang + 180)
    return round(math.cos(a)), -round(math.sin(a))


def _extent(lp: dict, pins: dict) -> tuple[float, float, float, float]:
    """Sheet-axis box (relative to the part's origin) round its pins, the stub
    wires and the labels drawn on them: min x, min y, max x, max y."""
    xs, ys = [-2 * GRID, 2 * GRID], [-2 * GRID, 2 * GRID]
    for num, (px, py, ang) in lp.items():
        dx, dy = _pin_end(ang)
        reach = 2 * GRID + (len(pins.get(num, "")) * 1.0 + 2.54 if num in pins else 0)
        sx, sy = px, -py
        xs += [sx, sx + dx * reach]
        ys += [sy, sy + dy * reach]
    return min(xs) - GRID, min(ys) - GRID, max(xs) + GRID, max(ys) + GRID


# ---- symbols taken straight from a library -----------------------------

def _library_symbol(d: Path, lib_id: str) -> str:
    """LIB:NAME from its library, flattened as KiCad caches it."""
    nick, name = lib_id.split(":", 1)
    lib = _lib_file(d, nick)
    if lib is None or not lib.exists():
        raise Usage(f"no library {nick!r} in {d / 'sym-lib-table'}, KiCad's global table or its stock libraries")
    try:
        syms = _symbol_blocks(lib.read_text())
    except OSError as e:
        raise EnvironmentFault(f"cannot read {lib}: {e}") from None
    if name not in syms:
        raise Usage(f"{lib.name} has no symbol {name!r}")
    return _flatten(syms, name)


def _cache_entry(body: str, lib_id: str) -> str:
    """A library symbol as the schematic's lib_symbols cache holds it: one tab
    deeper, named LIB:NAME (its units keep the bare name)."""
    name = lib_id.split(":", 1)[1]
    lines = body.split("\n")
    fresh = "\n".join([lines[0]] + ["\t" + ln if ln else ln for ln in lines[1:]])
    return re.sub(r'\(symbol "%s"' % re.escape(name), f'(symbol "{lib_id}"', fresh, count=1)


def _check_placeable(body: str, lib_id: str) -> None:
    name = lib_id.split(":", 1)[1]
    if re.search(r"\n\t\t\(power\b", body):
        raise Usage(f"{lib_id} is a power symbol: name its net in a pin map instead, and add one in KiCad if the sheet has none")
    units = {int(u) for u in re.findall(r'\(symbol "%s_(\d+)_\d+"' % re.escape(name), body)} - {0}
    if len(units) > 1:
        raise SystemExit(f"{lib_id} has {len(units)} units; multi-unit parts are not handled, add this one in KiCad")


def _from_library(template: str, body: str, lib_id: str, x: float, y: float) -> str:
    """A placed symbol for library symbol `body` at (x, y), in the file's own
    format: the head, pin lines and instance path come from `template` (another
    placed symbol on the same sheet); the fields come from the library."""
    t = _fresh(template)
    p0 = re.search(r"\n\t\t\(property ", t)
    i0 = re.search(r"\n\t\t\(instances\b", t)
    pins_ = blocks(t, ("pin",))
    if not pins_:
        raise SystemExit(f"no placed part on the sheet has a pin to take the file's format from; "
                         f"add {lib_id} in KiCad, or name an existing part to copy (#99)")
    pin_tpl = t[pins_[0][0]:pins_[0][1]]
    head, tail = t[:p0.start()], t[i0.start():]
    head = re.sub(r'\(lib_id "[^"]*"\)', f'(lib_id "{lib_id}")', head, count=1)
    head = re.sub(r"\n\t\t\(lib_name \"[^\"]*\"\)", "", head)
    head = re.sub(r"\n\t\t\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)", f"\n\t\t(at {mm_(x)} {mm_(y)} 0)", head, count=1)
    head = re.sub(r"\(unit \d+\)", "(unit 1)", head, count=1)
    for flag in ("exclude_from_sim", "in_bom", "on_board"):
        m = re.search(r"\n\t\t\(%s (yes|no)\)" % flag, body)
        if m:
            head = re.sub(r"\(%s (?:yes|no)\)" % flag, f"({flag} {m.group(1)})", head, count=1)
    head = re.sub(r"\(dnp (?:yes|no)\)", "(dnp no)", head, count=1)
    tail = re.sub(r"\(unit \d+\)", "(unit 1)", tail)
    fields = []
    for s, e in blocks(body, ("property",)):
        p = body[s:e]
        if re.match(r'\s*\(property "ki_', p):
            continue
        fields.append(re.sub(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)",
                             lambda m: f"(at {mm_(x + float(m.group(1)))} {mm_(y - float(m.group(2)))} {m.group(3) or '0'})",
                             p, count=1))
    pins = [_fresh(re.sub(r'\(pin "[^"]*"', f'(pin "{n}"', pin_tpl, count=1)) for n in _pin_numbers(body)]
    return _retarget(head + "".join(fields) + "".join(pins) + tail, x, y, tidy=False)   # the library placed the fields


def _cached_entry(text: str, lib_id: str) -> str | None:
    cache = blocks(text, ("lib_symbols",))
    return _symbol_blocks(text[cache[0][0]:cache[0][1]]).get(lib_id) if cache else None


def _with_cached(t: str, lib_id: str, entry: str) -> str:
    """t with `entry` (a symbol already in cache form) in its symbol cache, unless there."""
    if _cached_entry(t, lib_id) is not None:
        return t
    cache = blocks(t, ("lib_symbols",))
    if not cache:
        raise SystemExit("the sheet has no symbol cache (lib_symbols) to add to")
    k = t.rfind("\n", cache[0][0], cache[0][1])
    return t[:k] + entry + t[k:]


def _instance_path(block: str) -> str | None:
    m = re.search(r'\(path "([^"]*)"', block[block.find("(instances"):]) if "(instances" in block else None
    return m.group(1) if m else None


def _set_path(block: str, path: str) -> str:
    i = block.find("(instances")
    return block if i < 0 else block[:i] + re.sub(r'\(path "[^"]*"', f'(path "{path}"', block[i:])


def _target(d: Path, name: str | None, all_sheets: list[Sheet]) -> Sheet:
    """The sheet to add to: the root, or a sub-sheet used exactly once."""
    if not name:
        return root(d)
    hits = [s for s in all_sheets if s.path.name == name]
    if not hits:
        raise Usage(f"no sheet {name!r} in {d} (there are {', '.join(s.path.name for s in all_sheets)})")
    uses = sum(len(re.findall(r'\(property "Sheetfile" "%s"' % re.escape(name), s.text)) for s in all_sheets)
    if uses > 1:
        raise SystemExit(f"{name} is used {uses} times in the hierarchy; a part added to it would be added to each use. "
                         "Not handled: add it in KiCad")
    return hits[0]


def add(d: Path, spec_path: str) -> int:
    sp = importlib.util.spec_from_file_location("sch_spec", spec_path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    all_sheets = sheets(d)
    sh = _target(d, getattr(m, "SHEET", None), all_sheets)
    sh = next(s for s in all_sheets if s.path == sh.path)
    t = sh.text
    others = [s for s in all_sheets if s.path != sh.path]
    here = [t[s:e] for s, e in sh.instances()]
    everywhere = [(s, s.text[a:b]) for s in [sh, *others] for a, b in s.instances()]
    taken = {r for _, b in everywhere for r in refs(b)}
    by_ref = {}                                          # reference -> (sheet text, placed symbol) to copy
    power = {}                                           # net name -> (sheet text, a power symbol to copy), this sheet first
    for s, b in everywhere:
        r = prop(b, "Reference") or ""
        by_ref.setdefault(r, (s.text, b))
        if r.startswith("#PWR"):
            power.setdefault(prop(b, "Value"), (s.text, b))
    def names(kind, texts):
        return {n for x in texts for n in re.findall(r'\n\t\(%s "([^"]*)"' % kind, x)}
    labels, hier = names("label", [t]), names("hierarchical_label", [t])
    globals_ = names("global_label", [s.text for s in all_sheets])
    elsewhere = names("label", [s.text for s in others]) | names("hierarchical_label", [s.text for s in others])
    def first(kind, texts):
        return next((x[a:b] for x in texts for a, b in blocks(x, (kind,))), None)
    rest = [s.text for s in others]
    wire_t = first("wire", [t, *rest])
    label_here = first("label", [t])
    label_t = label_here or first("label", rest)
    glabel_t, hlabel_t = first("global_label", [t, *rest]), first("hierarchical_label", [t])
    if wire_t is None or (label_t is None and glabel_t is None):
        raise SystemExit("the project has no wire or no label to take the file's format from")
    parts = [b for b in here if not (prop(b, "Reference") or "#").startswith("#")]
    # a part with a pin, which a symbol added from the library copies its pin lines from (#99);
    # any part carries the sheet's instance path
    template = next((b for b in parts if blocks(b, ("pin",))), parts[0] if parts else None)
    if template is None:
        raise SystemExit(f"{sh.path.name} has no placed part to take its format and hierarchy path from; add one in KiCad first")
    path = _instance_path(template)
    plan = []                                            # (ref, like, value, footprint, pins, lib_id, source, from library, extent)
    for ref, like, value, footprint, pins in m.ADD:
        if ref in taken or any(ref == p[0] for p in plan):
            raise Usage(f"{ref} already exists")
        pins = {str(k): v for k, v in pins.items()}
        if like in by_ref and not like.startswith("#"):
            src_text, src = by_ref[like]
            lib_id = re.search(r'\(lib_id "([^"]*)"', src).group(1)
            t = _with_cached(t, lib_id, _cached_entry(src_text, lib_id))
        elif ":" in like:
            src, lib_id = None, like
            cached = _cached_entry(t, lib_id)
            body = _library_symbol(d, lib_id)
            _check_placeable(body, lib_id)
            if cached is None:
                t = _with_cached(t, lib_id, _cache_entry(body, lib_id))
            elif _pin_numbers(cached) != _pin_numbers(body):
                raise SystemExit(f"the sheet's cached {lib_id} has pins {_pin_numbers(cached)}, the library's has "
                                 f"{_pin_numbers(body)}; update the symbol in KiCad first. Nothing written.")
        else:
            raise Usage(f"no part {like!r} to copy, and not a LIB:NAME symbol")
        lp = _lib_pins(t, lib_id)
        for num, net in pins.items():
            if num not in lp:
                raise Usage(f"{lib_id} has no pin {num} (it has {sorted(lp)})")
            if net not in power and net not in labels | hier | globals_ and net in elsewhere:
                raise SystemExit(f"{ref}.{num}: net {net!r} is local to another sheet and cannot be reached from "
                                 f"{sh.path.name} by a label; connect it through a sheet pin in KiCad. Nothing written.")
        plan.append((ref, like, value, footprint, pins, lib_id, src if src is not None else body, src is None,
                     _extent(lp, pins)))
    for net in {n for p in plan for n in p[4].values() if n in power}:
        src_text, pb = power[net]
        lid = re.search(r'\(lib_id "([^"]*)"', pb).group(1)
        t = _with_cached(t, lid, _cached_entry(src_text, lid))
    width = sum(ex[2] - ex[0] for *_, ex in plan)
    height = max(ex[3] - ex[1] for *_, ex in plan)
    bx, by = _free_spot(t, width, height)
    pwr_n = max([int(n) for s in all_sheets for n in re.findall(r'"#PWR0*(\d+)"', s.text)] or [0])
    new = []
    for ref, like, value, footprint, pins, lib_id, src, from_lib, (x0, y0, x1, _y1) in plan:
        lp = _lib_pins(t, lib_id)
        x, y = snap(bx - x0), snap(by - y0)
        bx += x1 - x0
        b = _from_library(template, src, lib_id, x, y) if from_lib else _retarget(_fresh(src), x, y)
        if path:
            b = _set_path(b, path)
        for name, val in (("Reference", ref), ("Value", value), ("Footprint", footprint)):
            esc = val.replace("\\", "\\\\").replace('"', '\\"')
            b = re.sub(r'(\(property "%s" )"(?:[^"\\]|\\.)*"' % name, lambda mm: f'{mm.group(1)}"{esc}"', b, count=1)
        b = re.sub(r'\(reference "(?:[^"\\]|\\.)*"\)', f'(reference "{ref}")', b)
        new.append(b)
        for num, net in pins.items():
            px, py, ang = lp[num]
            sx, sy = x + px, y - py                                     # the pin's connection point on the sheet
            dx, dy = _pin_end(ang)                                      # away from the body
            ex, ey = round(sx + dx * 2 * GRID, 4), round(sy + dy * 2 * GRID, 4)
            w = _fresh(wire_t)
            w = re.sub(r"\(pts\s+\(xy [-\d.]+ [-\d.]+\)\s+\(xy [-\d.]+ [-\d.]+\)\s*\)",
                       f"(pts\n\t\t\t(xy {mm_(sx)} {mm_(sy)}) (xy {mm_(ex)} {mm_(ey)})\n\t\t)", w, count=1)
            new.append(w)
            rot = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[(dx, dy)]
            if net in power:
                pwr_n += 1
                src_p = _fresh(power[net][1])
                ppin = _lib_pins(t, re.search(r'\(lib_id "([^"]*)"', src_p).group(1))
                pb = _place_power(src_p, ex, ey, rot, next(iter(ppin.values()), (0.0, 0.0, rot)))
                if path:
                    pb = _set_path(pb, path)
                pref = f"#PWR0{pwr_n}"
                pb = re.sub(r'(\(property "Reference" )"[^"]*"', lambda mm: f'{mm.group(1)}"{pref}"', pb, count=1)
                pb = re.sub(r'\(reference "[^"]*"\)', f'(reference "{pref}")', pb)
                new.append(pb)
                kind = "power symbol"
            else:
                # the kind of label the net already uses here or project-wide; a new net
                # takes local labels where the sheet (or, failing that, the project) has them
                if net in hier:
                    head, tpl = "hierarchical_label", hlabel_t
                elif net in labels or (net not in globals_ and label_t is not None and (label_here or glabel_t is None)):
                    head, tpl = "label", label_t
                else:
                    head, tpl = "global_label", glabel_t
                lb = _fresh(tpl)
                lb = re.sub(r'\(%s "(?:[^"\\]|\\.)*"' % head, lambda mm: f'({head} "{net}"', lb, count=1)
                lb = re.sub(r"\(at [-\d.]+ [-\d.]+ [-\d.]+\)", f"(at {mm_(ex)} {mm_(ey)} {rot})", lb, count=1)
                side = "right" if rot in (180, 270) else "left"
                lb = re.sub(r"\(justify [^)]*\)", f"(justify {side} bottom)" if head == "label" else f"(justify {side})", lb, count=1)
                new.append(lb)
                kind = head.replace("_", " ") + ("" if net in labels | hier | globals_ else " (new net)")
            print(f"{ref}.{num} -> {net}  [{kind}]")
        how = "from its library" if from_lib else f"copied from {like}"
        print(f"added {ref} ({lib_id}, {how}) to {sh.path.name} at ({x:g}, {y:g})")
    # insert before the sheet_instances / embedded_fonts tail, or before the final parenthesis
    tail = re.search(r"\n\t\((?:sheet_instances|embedded_fonts)\b", t)
    k = tail.start() if tail else t.rstrip().rfind(")")
    sh.write(t[:k] + "".join(new) + t[k:])
    if locked(sh):
        print(f"note: {sh.path.name} is open in KiCad; close and reopen it to see the change")
    return 0


# ---- repoint -------------------------------------------------------------

def _expand(uri: str, d: Path, kind: str = "SYMBOL") -> str | None:
    """A library table URI with KiCad's path variables filled in; None if one is unknown.
    kind is SYMBOL or FOOTPRINT: which stock folder ${KICAD*_<kind>_DIR} means."""
    names = {**env.path_variables(), "KIPRJMOD": str(d)}
    for _ in range(5):                                   # variables may name other variables
        uri = re.sub(r"\$\{([^}]*)\}", lambda m: names.get(m.group(1), m.group(0)), uri)
    stock = r"\$\{KICAD\d*_%s_DIR\}" % kind
    if re.search(stock, uri):
        try:
            uri = re.sub(stock, str(env._library("symbols" if kind == "SYMBOL" else "footprints")), uri)
        except SystemExit:
            return None
    return None if "${" in uri else uri


def _in_table(table: Path, nick: str, d: Path, depth: int = 0, kind: str = "SYMBOL") -> tuple[bool, Path | None]:
    """Whether a library table (or a table nested in it, as KiCad allows) names
    `nick`, and what it points at (None when a path variable is unknown)."""
    try:
        text = table.read_text()
    except OSError:
        return False, None
    rows = re.findall(r'\(lib \(name "([^"]*)"\)\s*\(type "([^"]*)"\)\s*\(uri "([^"]*)"\)', text)
    for name, typ, uri in rows:
        if name == nick and typ != "Table":
            p = _expand(uri, d, kind)
            return True, Path(p) if p else None
    for _name, typ, uri in rows:
        if typ == "Table" and depth < 4:
            p = _expand(uri, d, kind)
            found = _in_table(Path(p), nick, d, depth + 1, kind) if p else (False, None)
            if found[0]:
                return found
    return False, None


def fp_dir(d: Path, nick: str) -> Path | None:
    """The .pretty folder a footprint library nickname names, looked up as
    symbol libraries are: fp-lib-table of the project, then KiCad's global one,
    then KiCad's stock footprint folder."""
    cfg = env.kicad_config()
    for table in (d / "fp-lib-table", *([cfg / "fp-lib-table"] if cfg else [])):
        found, path = _in_table(table, nick, d, kind="FOOTPRINT")
        if found:
            return path
    try:
        stock = env.libraries()[1] / f"{nick}.pretty"
    except SystemExit:
        return None
    return stock if stock.is_dir() else None


def _lib_file(d: Path, nick: str) -> Path | None:
    """The .kicad_sym a library nickname names: the project's sym-lib-table first,
    then KiCad's global one (its path variables filled in), then KiCad's stock
    library folder. The first table that names it decides, as in KiCad."""
    cfg = env.kicad_config()
    for table in (d / "sym-lib-table", *([cfg / "sym-lib-table"] if cfg else [])):
        found, path = _in_table(table, nick, d)
        if found:
            return path
    try:
        stock = env.libraries()[0] / f"{nick}.kicad_sym"
    except SystemExit:
        return None
    return stock if stock.exists() else None


def _symbol_blocks(text: str) -> dict[str, str]:
    """Top-level symbols of a .kicad_sym (or the entries of a lib_symbols cache), by name."""
    out = {}
    for s, e in blocks(text, ("symbol",)):
        m = re.match(r'\s*\(symbol "((?:[^"\\]|\\.)*)"', text[s:e])
        out[m.group(1)] = text[s:e]
    return out


def _flatten(syms: dict[str, str], name: str) -> str:
    """A library symbol as KiCad embeds it: an `extends` symbol becomes its parent's
    body under its own name, carrying its own properties."""
    sym = syms[name]
    m = re.search(r'\n\s*\(extends "([^"]*)"\)', sym)
    if not m:
        return sym
    if m.group(1) not in syms:
        raise SystemExit(f"{name} extends {m.group(1)}, which is not in the same library")
    parent = _flatten(syms, m.group(1))
    pname = re.escape(m.group(1))
    body = re.sub(r'\(symbol "%s"' % pname, f'(symbol "{name}"', parent, count=1)
    body = re.sub(r'\(symbol "%s_(\d+_\d+)"' % pname, lambda mm: f'(symbol "{name}_{mm.group(1)}"', body)
    own = "".join(sym[s:e] for s, e in blocks(sym, ("property",)))
    props = blocks(body, ("property",))
    if props:
        body = body[:props[0][0]] + own + "".join(body[e:n] for (_, e), (n, _) in zip(props, props[1:] + [(len(body), 0)]))
    return body


def _pin_numbers(sym: str) -> list[str]:
    return sorted({n for s, e in blocks(sym, ("pin",)) for n in re.findall(r'\(number "([^"]*)"', sym[s:e])})


def repoint(d: Path, old: str, new: str, body: str = "keep") -> int:
    """Point every part that uses library symbol `old` at `new` instead.

    keep: rename the cached symbol and its units; the drawing and pins stay as
    they are. library: replace the cached symbol with `new` from its library.
    Either way the pin numbers of the cached symbol and of `new` must be the
    same set, or nothing is written: changing them changes connectivity."""
    if body not in ("keep", "library"):
        raise Usage(f"--body takes keep or library, not {body!r}")
    if ":" not in old or ":" not in new:
        raise Usage("symbols are named LIB:NAME")
    nick, new_name = new.split(":", 1)
    old_name = old.split(":", 1)[1]
    lib = _lib_file(d, nick)
    if lib is None or not lib.exists():
        raise Usage(f"no library {nick!r} in {d / 'sym-lib-table'}, KiCad's global table or its stock libraries")
    try:
        syms = _symbol_blocks(lib.read_text())
    except OSError as e:
        raise EnvironmentFault(f"cannot read {lib}: {e}") from None
    if new_name not in syms:
        raise Usage(f"{lib.name} has no symbol {new_name!r}")
    target = _flatten(syms, new_name)
    want = _pin_numbers(target)

    plans = []
    for sh in sheets(d):
        t = sh.text
        uses = len(re.findall(r'\(lib_id "%s"\)' % re.escape(old), t))
        cache = blocks(t, ("lib_symbols",))
        entries = _symbol_blocks(t[cache[0][0]:cache[0][1]]) if cache else {}
        if not uses and old not in entries:
            continue
        for s, e in sh.instances():
            b = t[s:e]
            if f'(lib_id "{old}")' in b and "(lib_name " in b:
                raise SystemExit(f"{sh.path.name}: a part using {old} carries a lib_name override; not handled, do this one in KiCad")
        have = entries.get(old)
        if have is not None and _pin_numbers(have) != want:
            gone = sorted(set(_pin_numbers(have)) - set(want))
            added = sorted(set(want) - set(_pin_numbers(have)))
            raise SystemExit(f"{sh.path.name}: {old} has pins {_pin_numbers(have)}, {new} has {want} "
                             f"(missing {gone}, extra {added}); changing them changes connectivity. Nothing written.")
        cached = entries.get(new)
        if cached is not None and new != old and body == "keep" and _pin_numbers(cached) != want:
            raise SystemExit(f"{sh.path.name}: the cached {new} has pins {_pin_numbers(cached)}, the library's has {want}; "
                             f"parts moved onto it would use the cached one. Use --body library to refresh it. Nothing written.")
        plans.append((sh, uses, entries))
    if not plans:
        raise Usage(f"no symbol uses {old}")

    for sh, uses, entries in plans:
        t = sh.text
        cache = blocks(t, ("lib_symbols",))
        if cache and old in entries:
            cs, ce = cache[0]
            region = t[cs:ce]
            old_block = entries[old]
            if body == "library":
                fresh = _cache_entry(target, new)
            else:
                fresh = old_block.replace(f'(symbol "{old}"', f'(symbol "{new}"', 1)
                fresh = re.sub(r'\(symbol "%s_(\d+_\d+)"' % re.escape(old_name),
                               lambda mm: f'(symbol "{new_name}_{mm.group(1)}"', fresh)
            if new in entries and new != old:
                region = region.replace(old_block, "", 1)
                if body == "library":
                    region = region.replace(entries[new], fresh, 1)
            else:
                region = region.replace(old_block, fresh, 1)
            t = t[:cs] + region + t[ce:]
        t = t.replace(f'(lib_id "{old}")', f'(lib_id "{new}")')
        sh.write(t)
        print(f"{sh.path.name}: {uses} part(s) {old} -> {new} ({body} body)")
        if locked(sh):
            print(f"note: {sh.path.name} is open in KiCad; close and reopen it to see the change")
    return 0


# ---- netlist diff --------------------------------------------------------

def ercdiff(a: str, b: str) -> int:
    """ERC findings in report b that were not in report a. An existing schematic
    is rarely ERC-clean, so the question is what an edit added."""
    import json
    def load(p):
        return [(v["type"], v["description"], tuple(sorted(i["description"] for i in v["items"])))
                for s in json.loads(Path(p).read_text())["sheets"] for v in s["violations"] if v.get("severity") != "exclusion"]
    old, new = load(a), load(b)
    left, added = list(old), []
    for f in new:
        if f in left:
            left.remove(f)
        else:
            added.append(f)
    print(f"ERC: {len(new)} finding(s) now, {len(old)} before, {len(added)} new, {len(left)} gone")
    for t, desc, items in added:
        print("  NEW ", t, desc[:90], list(items)[:2])
    for t, desc, items in left:
        print("  GONE", t, desc[:90], list(items)[:2])
    return 1 if added else 0


def cli(argv: list[str]) -> int:
    argv = ["boardwright", *argv]
    a = argv[1:]
    if len(a) >= 3 and a[0] == "ercdiff":
        return (ercdiff(a[1], a[2]))
    if len(a) < 2:
        raise Usage(__doc__)
    d, cmd, rest = Path(a[0]).resolve(), a[1], a[2:]
    if cmd not in ("parts", "set", "remove", "add", "repoint") or (cmd != "parts" and not rest):
        raise Usage(__doc__)
    if cmd == "repoint":
        args, mode = list(rest), "keep"
        if "--body" in args:
            i = args.index("--body")
            mode = args[i + 1] if i + 1 < len(args) else ""
            del args[i:i + 2]
        if len(args) != 2:
            raise Usage(__doc__)
        return repoint(d, args[0], args[1], mode)
    return ({"parts": lambda: parts(d, rest[0] if rest else "*"),
              "set": lambda: set_fields(d, rest[0], rest[1:]),
              "remove": lambda: remove(d, rest),
              "add": lambda: add(d, rest[0])}[cmd]())
