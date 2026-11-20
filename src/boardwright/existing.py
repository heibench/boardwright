"""Work on a KiCad project that already exists, in place.

    boardwright existing <project dir> info
    boardwright existing <project dir> pads [REF ...]
    boardwright existing <project dir> nets [PATTERN]
    boardwright existing <project dir> review
    boardwright existing <project dir> baseline      # after the first DRC: accept today's findings
    boardwright existing <project dir> verify        # review + no DRC finding that is not in the baseline
    boardwright existing <project dir> stage SNAPSHOT.kicad_pcb   # check a copy of the board (e.g. the one open in KiCad)
    boardwright existing <project dir> verify --staged
    boardwright existing <project dir> apply [--force]   # REMOVE, MOVE, RIPUP, TRACKS, VIAS, ZONES, KEEPOUTS, TEXT
    boardwright existing <project dir> free REF [near REF.PAD | near X,Y]   # clear spots for a part, for MOVE
    boardwright existing <project dir> reroute NET [NET ...]
    boardwright existing <project dir> update [NETLIST.net] [--body keep|library]   # the schematic's parts and nets onto the board

The project keeps its own schematic, libraries and rules; nothing is
regenerated. An optional `boardwright.py` beside the board holds the same names a
generated board's board.py uses (REVIEW, TRACKS, VIAS, ZONES, KEEPOUTS, TEXT,
PLANES, FR_BOTTOM_COST, FR_PASSES) plus

    MOVE  = {"C12": (41.2, 18.0, 90)}       # ref -> x, y, rot[, {"ref": (x, y[, angle]), "value": ...}]
    RIPUP = ["/USB_D+", "/USB_D-"]          # nets whose tracks and vias are removed first
    REMOVE = ["G***", "Logos:OldArt"]       # footprints to take off the board, by reference or LIB:NAME

Coordinates are the board-relative mm that `pads` prints. Outputs go to
<project dir>/boardwright_out/. The board file is edited in place: commit first.
An existing board is not expected to be DRC-clean, so the gate is "review
passes and DRC shows nothing new since `baseline`".
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import math
import re
import subprocess
import sys
import types
from pathlib import Path

from . import copper, env
from . import dsn as dsn_
from . import ses as ses_
from .errors import CannotTell, EnvironmentFault, Usage
from .model import Board
from .preview import ratsnest
from .preview import write as write_preview
from .review import review
from .update import update as update_board


def find(d: Path) -> Path:
    pcbs = [p for p in d.glob("*.kicad_pcb") if not p.name.endswith(".solve.kicad_pcb")]
    if len(pcbs) != 1:
        raise EnvironmentFault(f"{d}: expected exactly one .kicad_pcb, found {[p.name for p in pcbs]}")
    return pcbs[0]


def spec(d: Path):
    f = d / "boardwright.py"
    if not f.exists():
        return types.SimpleNamespace(NAME=find(d).stem)
    sp = importlib.util.spec_from_file_location("boardwright_spec", f)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    if not hasattr(m, "NAME"):
        m.NAME = find(d).stem
    return m


def out_dir(d: Path) -> Path:
    o = d / "boardwright_out"
    o.mkdir(exist_ok=True)
    return o


def info(d: Path) -> int:
    pcb = find(d)
    b = Board(pcb)
    x0, y0, x1, y1 = b.bbox
    print(f"{pcb.name}: {x1 - x0:.1f} x {y1 - y0:.1f} mm, layers {', '.join(b.layers)}")
    print(f"  {len(b.footprints)} footprints, {len(b.pads)} pads, {len(b.tracks)} tracks, {len(b.vias)} vias, "
          f"{len({p.net for p in b.pads if p.net})} nets")
    per: dict[str, float] = {}
    for t in b.tracks:
        per[t.layer] = per.get(t.layer, 0) + t.length
    print("  track length by layer:", {k: round(v) for k, v in per.items()})
    for z in b.zones:
        for layer in z.layers:
            kind = "keep-out" if z.keepout else f"{z.net or '(no net)'}"
            cov = z.area(layer) / b.area if b.area else 0
            print(f"  zone {kind} {layer}: {len(z.fills.get(layer, []))} piece(s), {cov:.0%} of the board, priority {z.priority}")
    write_preview(pcb, out_dir(d) / "preview.png")
    print(f"  origin of board-relative coordinates in the file: {b.origin}")
    return 0


def pads(d: Path, refs: list[str]) -> int:
    for p in sorted(Board(find(d)).pads, key=lambda p: (p.ref, p.num)):
        if not refs or p.ref in refs:
            print(f"{p.ref:<8}{p.num:<6}{p.net:<34}{p.x:>9.3f}{p.y:>9.3f}  {p.layer}")
    return 0


def nets(d: Path, pattern: str) -> int:
    b = Board(find(d))
    L = b.net_lengths()
    vias: dict[str, int] = {}
    for v in b.vias:
        vias[v.net] = vias.get(v.net, 0) + 1
    count: dict[str, int] = {}
    for p in b.pads:
        count[p.net] = count.get(p.net, 0) + 1
    for n in sorted(count):
        if n and fnmatch.fnmatch(n, pattern):
            layers = sorted({t.layer for t in b.tracks if t.net == n})
            print(f"{n:<36}{count[n]:>4} pads {L.get(n, 0):>8.2f} mm {vias.get(n, 0):>3} vias  {'/'.join(layers)}")
    return 0


def _key(text: str) -> str:
    """A DRC description without the track length KiCad puts in it
    ("Track [+3V3] on F.Cu, length 0.2858 mm"), which an edit or a refill
    changes without changing the finding (#44). The unit is whichever the DRC
    ran with: mm, mils or in (KiCad's eda_units.cpp labels)."""
    return re.sub(r", length [-\d.]+ (?:mm|mils|in)\b", "", text or "")


def _findings(report: Path) -> list[tuple]:
    j = json.loads(report.read_text())
    out = []
    for v in j.get("violations", []) + j.get("unconnected_items", []) + j.get("schematic_parity", []):
        if v.get("severity") == "exclusion":
            continue
        out.append((v.get("type"), _key(v.get("description")), tuple(sorted(_key(i.get("description", "")) for i in v.get("items", [])))))
    return out


def do_review(d: Path) -> list[str]:
    print("review:")
    fails = review(find(d), spec(d))
    print(f"{'OK  ' if not fails else 'FAIL'} review", *fails, sep="\n    ")
    return fails


def baseline(d: Path) -> int:
    o = out_dir(d)
    if not (o / "drc.json").exists():
        raise CannotTell("run the DRC first (boardwright_out/drc.json)")
    (o / "drc_baseline.json").write_bytes((o / "drc.json").read_bytes())
    print(f"baseline: {len(_findings(o / 'drc.json'))} existing DRC finding(s) accepted")
    return 0


def verify(d: Path, staged: bool = False) -> int:
    o = out_dir(d)
    pcb = find(d)
    if staged:                      # judge the staged snapshot against the project's own baseline
        base = o / "drc_baseline.json"
        o = o / "staged"
        pcb = o / pcb.name
        print("review:")
        fails = review(pcb, spec(d))
        print(f"{'OK  ' if not fails else 'FAIL'} review", *fails, sep="\n    ")
        ok = not fails
        if (o / "drc.json").exists() and base.exists() and not (o / "drc_baseline.json").exists():
            (o / "drc_baseline.json").write_bytes(base.read_bytes())
    else:
        ok = not do_review(d)
    if not pcb.with_suffix(".kicad_sch").exists():
        # kicad-cli then reports an empty parity list and exits 0: that is "not checked", not "clean"
        print(f"note: no {pcb.stem}.kicad_sch beside the board, so KiCad did not check schematic parity")
    if not (o / "drc.json").exists() or not (o / "drc_baseline.json").exists():
        print("FAIL need boardwright_out/drc.json and a baseline (see module docstring)")
        return 2
    if (o / "drc.json").stat().st_mtime < pcb.stat().st_mtime - 2:
        print("STALE drc.json is older than the board -- rerun the DRC")
        return 2
    old = _findings(o / "drc_baseline.json")
    new = _findings(o / "drc.json")
    left = list(old)
    added = []
    for f in new:
        if f in left:
            left.remove(f)
        else:
            added.append(f)
    print(f"DRC: {len(new)} finding(s) now, {len(old)} in the baseline, {len(added)} new, {len(left)} gone")
    for t, desc, items in added[:40]:
        print("    NEW", t, desc, list(items)[:2])
    ok &= not added
    print("PASS" if ok else "NOT DONE")
    return 0 if ok else 1


def _turn(a: float) -> str:
    """An angle as KiCad writes it: in (-180, 180], no trailing zeros."""
    a = (a + 180) % 360 - 180
    return "180" if a == -180 else copper.num(a)


def move_footprint(t: str, ref: str, x: float, y: float, rot: float, origin: tuple[float, float]) -> str:
    """The board file with footprint `ref` at board-relative (x, y), rotated rot
    degrees, editing only that footprint's block: its (at ...), the absolute
    angles KiCad keeps on its pads and texts, and its own zones, which KiCad
    stores board-absolute and which are carried from the old frame to the new."""
    from .update import _footprints, _prop
    for s, e in _footprints(t):
        fp = t[s:e]
        if _prop(fp, "Reference") != ref:
            continue
        m = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", fp)
        fx, fy, r0 = float(m.group(1)), float(m.group(2)), float(m.group(3) or 0)
        nx, ny, delta = round(x + origin[0], 4), round(y + origin[1], 4), rot - r0
        head = f"\n\t\t(at {copper.num(nx)} {copper.num(ny)}" + (f" {_turn(rot)})" if _turn(rot) != "0" else ")")
        fp = fp[:m.start()] + head + fp[m.end():]
        if delta % 360:
            # pads and texts: (at x y angle) in the footprint's frame, angle absolute
            fp = re.sub(r'(\n\t\t(?:\(pad "[^"]*"[^\n]*|\(property "[^"]*" "(?:[^"\\]|\\.)*"|\(fp_text [^\n]*)\s*\(at )([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)',
                        lambda mm: f"{mm.group(1)}{mm.group(2)} {mm.group(3)} {_turn(float(mm.group(4) or 0) + delta)})", fp)
        a0, a1 = math.radians(r0), math.radians(rot)

        def carry(mm):
            dx, dy = float(mm.group(1)) - fx, float(mm.group(2)) - fy
            lx, ly = dx * math.cos(a0) - dy * math.sin(a0), dx * math.sin(a0) + dy * math.cos(a0)
            px, py = nx + lx * math.cos(a1) + ly * math.sin(a1), ny - lx * math.sin(a1) + ly * math.cos(a1)
            return f"(xy {copper.num(px)} {copper.num(py)})"
        for zs, ze in reversed(copper.blocks(fp, ("zone",))):
            fp = fp[:zs] + re.sub(r"\(xy ([-\d.]+) ([-\d.]+)\)", carry, fp[zs:ze]) + fp[ze:]
        return t[:s] + fp + t[e:]
    raise Usage(f"no footprint {ref}")


def place_field(t: str, ref: str, name: str, at: tuple, origin: tuple[float, float]) -> str:
    """The board file with footprint `ref`'s Reference or Value text at board-relative
    (x, y[, angle]). KiCad keeps a field's position in its footprint's own frame
    (rotated with it) and its angle absolute; the angle stays as it was unless given."""
    from .update import _footprints, _prop
    for s, e in _footprints(t):
        fp = t[s:e]
        if _prop(fp, "Reference") != ref:
            continue
        m = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", fp)
        fx, fy, rot = float(m.group(1)), float(m.group(2)), math.radians(float(m.group(3) or 0))
        dx, dy = at[0] + origin[0] - fx, at[1] + origin[1] - fy
        lx = dx * math.cos(rot) - dy * math.sin(rot)
        ly = dx * math.sin(rot) + dy * math.cos(rot)
        pm = re.search(r'(\n\t\t\(property "%s" "(?:[^"\\]|\\.)*"\s*)\(at [-\d.]+ [-\d.]+(?: ([-\d.]+))?\)' % name, fp)
        if pm is None:
            raise Usage(f"{ref} has no {name} text to move")
        ang = at[2] if len(at) > 2 else float(pm.group(2) or 0)
        fp = fp[:pm.start()] + pm.group(1) + f"(at {copper.num(round(lx, 4))} {copper.num(round(ly, 4))} {copper.num(ang)})" + fp[pm.end():]
        return t[:s] + fp + t[e:]
    raise Usage(f"no footprint {ref}")


def free(d: Path, args: list[str]) -> int:
    """Clear spots for a part: its own pads and courtyard against everything else."""
    from .placement import Clearance
    if not args:
        raise Usage("free REF [near REF.PAD | near X,Y]")
    ref, near = args[0], None
    b = Board(find(d))
    if len(args) == 3 and args[1] == "near":
        if "," in args[2]:
            near = tuple(float(v) for v in args[2].split(","))
        else:
            near = (b.pad(args[2]).x, b.pad(args[2]).y)
    elif len(args) != 1:
        raise Usage("free REF [near REF.PAD | near X,Y]")
    c = Clearance(b)
    if ref not in c.fps:
        raise Usage(f"no footprint {ref}")
    spots = c.free(ref, near)
    if not spots:
        print(f"no clear spot for {ref} on the board")
        return 1
    for x, y, r in spots:
        print(f'"{ref}": ({copper.num(x)}, {copper.num(y)}, {r}),')
    return 0


def stage(d: Path, snapshot: Path) -> int:
    """Set a board file up for KiCad's checks as if it were the project's board.

    A snapshot of the board that is open in KiCad is not the file on disk, and
    DRC needs the project's rules, libraries and schematic beside the board it
    checks. This makes <project>/boardwright_out/staged/ holding the snapshot under
    the project's board name, copies of the project's small files, and links
    to its directories. Run the DRC there, then `verify --staged`.
    """
    pcb = find(d)
    st = out_dir(d) / "staged"
    if st.exists():
        import shutil
        shutil.rmtree(st)
    st.mkdir()
    import shutil
    for f in d.iterdir():
        if f.name in ("boardwright_out", ".git", ".history") or f.name.startswith("~") or f.name.endswith((".lck", ".kicad_prl")):
            continue
        if f == pcb:
            continue
        if f.is_dir():
            (st / f.name).symlink_to(f.resolve(), target_is_directory=True)
        else:
            shutil.copy2(f, st / f.name)
    shutil.copy2(snapshot, st / pcb.name)
    print(f"staged {snapshot.name} as {st / pcb.name}")
    print(f"run KiCad's DRC on it with the report at {st / 'drc.json'}, then: boardwright existing {d} verify --staged")
    return 0


def remove_footprints(t: str, names: list[str], force: bool = False) -> tuple[str, list[str], list[str]]:
    """The board file without the footprints matching `names` (a reference or
    LIB:NAME each), the removed footprints, and the refusals: a footprint with a
    pad on a net or a link to a schematic symbol is kept unless `force`.
    Each footprint is cut as its own block and its uuid dropped from any group."""
    from .update import _footprints, _pads, _prop
    hits, gone, refused = [], [], []
    for s, e in _footprints(t):
        fp = t[s:e]
        ref, lib_id = _prop(fp, "Reference"), re.match(r'\n\t\(footprint "((?:[^"\\]|\\.)*)"', fp).group(1)
        if ref in names or lib_id in names:
            hits.append((s, e, ref, lib_id))
    for name in names:
        if not any(name in (ref, lib_id) for *_se, ref, lib_id in hits):
            raise Usage(f"REMOVE {name!r}: no footprint with that reference or LIB:NAME on the board")
    for s, e, ref, lib_id in hits:
        fp = t[s:e]
        nets_ = sorted({n for *_x, n in _pads(fp) if n})
        why = ([f"pads on {', '.join(nets_)}"] if nets_ else []) + \
              (["linked to a schematic symbol"] if re.search(r'\n\t\t\(path "', fp) else [])
        if why and not force:
            refused.append(f"{ref} ({lib_id}): {', '.join(why)}")
        gone.append(f"{ref} ({lib_id})" + (f", {', '.join(why)}" if why else ""))
    if refused:
        return t, [], refused
    for s, e, *_x in sorted(hits, reverse=True):
        uid = re.search(r'\n\t\t\(uuid "([^"]*)"\)', t[s:e])
        t = t[:s] + t[e:]
        if uid:
            t = re.sub(r'[ \t]*"%s"' % re.escape(uid.group(1)), "", t)
    return t, gone, []


def apply(d: Path, force: bool = False) -> int:
    pcb, m = find(d), spec(d)
    env.warn_if_open_in_kicad(pcb)
    copper.check_vias(m)
    rm = list(getattr(m, "REMOVE", []))
    if rm:
        original = pcb.read_text()
        t, gone, refused = remove_footprints(original, rm, force)
        for r in refused:
            print("REFUSED", r)
        if refused:
            print("nothing written: REMOVE takes a footprint with a pad on a net or a schematic symbol only with --force")
            return 1
        if t.count("(") != t.count(")"):
            raise SystemExit("the removal would unbalance the board file; nothing written")
        if pcb.read_text() != original:
            raise SystemExit(f"{pcb.name} changed on disk since it was read; nothing written")
        pcb.write_text(t)
        for g in gone:
            print("removed", g)
    moves = getattr(m, "MOVE", {})
    if moves:
        from .placement import Clearance
        original = pcb.read_text()
        t, origin = original, Board(pcb).origin
        for ref, mv in moves.items():
            t = move_footprint(t, ref, *mv[:3], origin)
            for key, at in (mv[3] if len(mv) > 3 else {}).items():
                name = {"ref": "Reference", "value": "Value"}.get(key)
                if name is None:
                    raise Usage(f"MOVE {ref}: unknown field {key!r} (ref or value)")
                t = place_field(t, ref, name, at, origin)
        pcb.write_text(t)
        clear = Clearance(Board(pcb))
        found = [c for ref in moves for c in clear.clashes(ref)]
        for c in found:
            print("CLASH", c)
        if found and not force:
            pcb.write_text(original)
            print(f"nothing written: a moved part touches other copper or courtyards. "
                  f"`boardwright existing {d} free REF [near REF.PAD]` lists clear spots; --force applies anyway")
            return 1
        print(f"moved {len(moves)} footprint(s)")
    rip = set(getattr(m, "RIPUP", []))
    if rip:
        text, n = copper.ripup(pcb.read_text(), rip)
        pcb.write_text(text)
        print(f"ripped up {n} track/via item(s) on {sorted(rip)}")
    if getattr(m, "ROUTES", None):                   # pad-to-pad routes, worked out after the moves and rip-up
        from .route import expand
        rt, rv = expand(m, Board(pcb))
        m.TRACKS = list(getattr(m, "TRACKS", [])) + rt
        m.VIAS = list(getattr(m, "VIAS", [])) + rv
        print(f"routed {len(m.ROUTES)} connection(s): {len(rt)} track run(s), {len(rv)} via(s)")
    before = len(pcb.read_text())
    copper.apply(pcb, m, "pre")
    copper.apply(pcb, m, "post")
    text, n = dedupe(pcb.read_text())
    pcb.write_text(text)
    print(f"applied hand copper ({len(text) - before:+d} bytes; {n} exact duplicate(s) dropped, so apply is repeatable)")
    write_preview(pcb, out_dir(d) / "preview.png")
    return 0


def dedupe(text: str) -> tuple[str, int]:
    """Drop tracks and vias that are exact geometric duplicates of an earlier one."""
    seen, drop = set(), []
    for s0, e0 in copper.blocks(text, ("segment", "via", "gr_text")):
        blk = text[s0:e0]
        if blk.lstrip().startswith("(gr_text"):
            key = ("txt", re.sub(r'\(uuid "[^"]*"\)', "", re.sub(r"\s+", " ", blk)))
            if key in seen:
                drop.append((s0, e0))
            seen.add(key)
            continue
        nums = re.findall(r"\((?:start|end|at) ([-\d.]+) ([-\d.]+)", blk)
        layer = re.search(r'\(layers? ([^)]*)\)', blk)
        key = (blk.lstrip()[1:4], frozenset((round(float(a), 3), round(float(b), 3)) for a, b in nums), layer.group(1) if layer else "")
        if key in seen:
            drop.append((s0, e0))
        seen.add(key)
    for s0, e0 in reversed(drop):
        text = text[:s0] + text[e0:]
    return text, len(drop)


def _net_of(blk: str, names: dict) -> str:
    n = re.search(r'\(net (?:(\d+)(?: "([^"]*)")?|"([^"]*)")', blk)
    if not n:
        return ""
    return n.group(3) if n.group(3) is not None else (n.group(2) or names.get(n.group(1), ""))


def reroute(d: Path, nets_: list[str]) -> int:
    """Rip up the named nets and let Freerouting route only them.

    Every other net's copper ends up byte-identical to before: the routed
    result is used only as a source for the named nets' new tracks and vias,
    which are grafted onto the pre-routing file.
    """
    pcb, m = find(d), spec(d)
    env.warn_if_open_in_kicad(pcb)
    o = out_dir(d)
    b0 = Board(pcb)
    known = {p.net for p in b0.pads}
    for n in nets_:
        if n not in known:
            raise Usage(f"no net {n!r} (see `nets`)")
    original = pcb.read_text()
    names0 = dict(re.findall(r'\n\s*\(net (\d+) "([^"]*)"\)', original))
    was_open = {n for *_p, n in ratsnest(b0, set())}
    text0, n = copper.ripup(original, set(nets_))
    pcb.write_text(text0)
    print(f"ripped up {n} item(s)")
    try:
        kept, arcs = _route_and_graft(pcb, m, o, nets_, original, names0, was_open, text0)
    except BaseException:
        # nothing lands unless the route does: a failure leaves the board as it was read (#104)
        if pcb.read_text() != original:
            pcb.write_text(original)
        print(f"{pcb.name} restored as it was read; nothing changed", file=sys.stderr)
        raise
    b1 = Board(pcb)
    for net in nets_:
        L = sum(t.length for t in b1.tracks if t.net == net)
        print(f"  {net}: {L:.2f} mm routed, {sum(1 for v in b1.vias if v.net == net)} via(s)")
    left = len(ratsnest(b1, {z.net for z in b1.zones if not z.keepout}))
    print(f"kept {kept} new item(s) on the named nets; {arcs} curved track(s) shown to the router as fixed; "
          f"tracks {len(b0.tracks)} -> {len(b1.tracks)}; unrouted connections on unpoured nets: {left}")
    write_preview(pcb, o / "preview.png")
    return 0


def _route_and_graft(pcb, m, o, nets_, original, names0, was_open, text0) -> tuple[int, int]:
    """reroute's routing half, on the board with the named nets ripped up: export,
    Freerouting, and the graft of its result. Any failure raises; reroute then
    puts the board back as it was read. Returns the items grafted and the arcs
    the router was shown as fixed."""
    dsn, ses = o / f"{m.NAME}.dsn", o / f"{m.NAME}.ses"
    if ses.exists():
        ses.unlink()
    arcs = dsn_.export(pcb, dsn)
    cmd = [*env.freerouting(), "-de", str(dsn), "-do", str(ses), "-mp", str(getattr(m, "FR_PASSES", 5))]
    limit = getattr(m, "FR_TIMEOUT", 900)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=limit)
    except subprocess.TimeoutExpired as e:
        raise EnvironmentFault(f"freerouting did not finish in FR_TIMEOUT = {limit} s") from e
    (o / "freerouting.log").write_text(r.stdout + r.stderr)
    if not ses.exists():
        raise EnvironmentFault("freerouting produced no SES; see boardwright_out/freerouting.log")
    layers = ses_.copper_layers(text0)
    tracks, vias = ses_.read(ses, layers)
    # Freerouting necks tracks down; never below the project's own minimum
    minw = 0.0
    pro = pcb.with_suffix(".kicad_pro")
    if pro.exists():
        minw = json.loads(pro.read_text()).get("board", {}).get("design_settings", {}).get("rules", {}).get("min_track_width", 0.0)
    graft = ([ses_.track_block(text0, (*t[:6], max(t[6], minw))) for t in tracks if t[0] in nets_]
             + [ses_.via_block(text0, v, layers) for v in vias if v[0] in nets_])
    copper.append(pcb, graft)
    text, dup = dedupe(pcb.read_text())
    pcb.write_text(text)
    # a net the router could not finish gets its original routing back
    failed = sorted({n for *_p, n in ratsnest(Board(pcb), set())} & set(nets_) - was_open)
    if failed:
        text, _n = copper.ripup(text, set(failed))
        old = [original[s0:e0] for s0, e0 in copper.blocks(original, ("segment", "arc", "via"))
               if _net_of(original[s0:e0], names0) in failed]
        text = text.rstrip()[:-1].rstrip() + "".join(old) + "\n)\n"
        pcb.write_text(text)
        print(f"  the router could not finish {failed}: original routing restored")
    return len(graft), arcs


def cli(argv: list[str]) -> int:
    argv = ["boardwright", *argv]
    if len(argv) < 3:
        raise Usage(__doc__)
    d, step, rest = Path(argv[1]).resolve(), argv[2], argv[3:]
    if step not in ("info", "pads", "nets", "review", "baseline", "verify", "stage", "apply", "reroute", "update", "free"):
        raise Usage(f"unknown step {step!r}\n{__doc__}")
    return ({"info": lambda: info(d), "pads": lambda: pads(d, rest), "nets": lambda: nets(d, rest[0] if rest else "*"),
              "review": lambda: 1 if do_review(d) else 0, "baseline": lambda: baseline(d),
              "verify": lambda: verify(d, "--staged" in rest), "stage": lambda: stage(d, Path(rest[0]).resolve()),
              "apply": lambda: apply(d, "--force" in rest), "reroute": lambda: reroute(d, rest),
              "free": lambda: free(d, rest),
              "update": lambda: _update(d, rest)}[step]())


def _update(d: Path, rest: list[str]) -> int:
    body = "keep"
    if "--body" in rest:
        i = rest.index("--body")
        if i + 1 >= len(rest) or rest[i + 1] not in ("keep", "library"):
            raise Usage("update [NETLIST.net] [--body keep|library]")
        body = rest[i + 1]
        rest = rest[:i] + rest[i + 2:]
    if len(rest) > 1:
        raise Usage("update [NETLIST.net] [--body keep|library]")
    return update_board(d, find(d), rest[0] if rest else None, body)
