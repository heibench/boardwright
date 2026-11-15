"""Work on a KiCad project that already exists, in place.

    boardwright existing <project dir> info
    boardwright existing <project dir> pads [REF ...]
    boardwright existing <project dir> nets [PATTERN]
    boardwright existing <project dir> review
    boardwright existing <project dir> baseline      # after the first DRC: accept today's findings
    boardwright existing <project dir> verify        # review + no DRC finding that is not in the baseline
    boardwright existing <project dir> stage SNAPSHOT.kicad_pcb   # check a copy of the board (e.g. the one open in KiCad)
    boardwright existing <project dir> verify --staged
    boardwright existing <project dir> apply [--force]   # MOVE, RIPUP, TRACKS, VIAS, ZONES, KEEPOUTS, TEXT
    boardwright existing <project dir> free REF [near REF.PAD | near X,Y]   # clear spots for a part, for MOVE
    boardwright existing <project dir> reroute NET [NET ...]
    boardwright existing <project dir> update [NETLIST.net]   # the schematic's parts and nets onto the board

The project keeps its own schematic, libraries and rules; nothing is
regenerated. An optional `boardwright.py` beside the board holds the same names a
generated board's board.py uses (REVIEW, TRACKS, VIAS, ZONES, KEEPOUTS, TEXT,
PLANES, FR_BOTTOM_COST, FR_PASSES) plus

    MOVE  = {"C12": (41.2, 18.0, 90)}       # ref -> x, y, rot
    RIPUP = ["/USB_D+", "/USB_D-"]          # nets whose tracks and vias are removed first

Coordinates are the board-relative mm that `pads` prints. Outputs go to
<project dir>/boardwright_out/. The board file is edited in place: commit first.
An existing board is not expected to be DRC-clean, so the gate is "review
passes and DRC shows nothing new since `baseline`".
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import re
import subprocess
import types
from pathlib import Path

from . import board as B
from . import copper, env
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
    print(f"  {len(b.pcb.footprints)} footprints, {len(b.pads)} pads, {len(b.tracks)} tracks, {len(b.vias)} vias, "
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


def _findings(report: Path) -> list[tuple]:
    j = json.loads(report.read_text())
    out = []
    for v in j.get("violations", []) + j.get("unconnected_items", []) + j.get("schematic_parity", []):
        if v.get("severity") == "exclusion":
            continue
        out.append((v.get("type"), v.get("description"), tuple(sorted(i.get("description", "") for i in v.get("items", [])))))
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
        print(f'"{ref}": ({x:g}, {y:g}, {r}),')
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


def apply(d: Path, force: bool = False) -> int:
    pcb, m = find(d), spec(d)
    moves = getattr(m, "MOVE", {})
    if moves:
        from kicad_tools.schema.pcb import PCB

        from .placement import Clearance
        original = pcb.read_text()
        p = PCB.load(str(pcb))
        for ref, (x, y, rot) in moves.items():
            if not p.update_footprint_position(ref, x, y, rot):
                raise Usage(f"no footprint {ref}")
        p.save(str(pcb))
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


def add_arcs_to_dsn(dsn: Path, b: Board) -> int:
    """kicad-tools' DSN export leaves out curved tracks. Without them the router
    sees those nets as open and routes them again, through copper it cannot see.
    Each arc goes in as a fixed polyline."""
    ox, oy = b.origin
    text = dsn.read_text()
    quoted = {name: q for q, name in re.findall(r'\(net ("?)([^\s")]+)\1', text)}
    add = []
    for t in b.tracks:
        if len(t.pts) <= 2:
            continue
        coords = " ".join(f"{(x + ox) * 1000:.1f} {(y + oy) * 1000:.1f}" for x, y in t.pts)
        net = t.net if (t.net in quoted and not quoted[t.net]) or not re.search(r"[\s()\"]", t.net) else f'"{t.net}"'
        add.append(f"    (wire\n      (path {t.layer} {t.width * 1000:.1f} {coords})\n      (net {net})\n      (type protect)\n    )\n")
    if not add:
        return 0
    i = text.rfind("(wiring")
    if i < 0:
        j = text.rstrip().rfind(")")
        text = text[:j] + "  (wiring\n" + "".join(add) + "  )\n" + text[j:]
    else:
        k = text.index("\n", i) + 1
        text = text[:k] + "".join(add) + text[k:]
    dsn.write_text(text)
    return len(add)


def reroute(d: Path, nets_: list[str]) -> int:
    """Rip up the named nets and let Freerouting route only them.

    Every other net's copper ends up byte-identical to before: the routed
    result is used only as a source for the named nets' new tracks and vias,
    which are grafted onto the pre-routing file.
    """
    pcb, m = find(d), spec(d)
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
    dsn, ses = o / f"{m.NAME}.dsn", o / f"{m.NAME}.ses"
    if ses.exists():
        ses.unlink()
    B.kct("pcb", "export-dsn", str(pcb), "-o", str(dsn))
    arcs = add_arcs_to_dsn(dsn, Board(pcb))
    cmd = [*env.freerouting(), "-de", str(dsn), "-do", str(ses), "-mp", str(getattr(m, "FR_PASSES", 5))]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=getattr(m, "FR_TIMEOUT", 900))
    (o / "freerouting.log").write_text(r.stdout + r.stderr)
    if not ses.exists():
        pcb.write_text(text0)
        raise EnvironmentFault("freerouting produced no SES; see boardwright_out/freerouting.log")
    routed = pcb.with_suffix(".solve.kicad_pcb")
    B.kct("pcb", "import-ses", str(pcb), str(ses), "-o", str(routed))
    rt = routed.read_text()
    routed.unlink()
    names = dict(re.findall(r'\n\s*\(net (\d+) "([^"]*)"\)', rt))
    graft = [rt[s0:e0] for s0, e0 in copper.blocks(rt, ("segment", "arc", "via")) if _net_of(rt[s0:e0], names) in set(nets_)]
    # Freerouting necks tracks down; never below the project's own minimum
    minw = 0.0
    pro = pcb.with_suffix(".kicad_pro")
    if pro.exists():
        minw = json.loads(pro.read_text()).get("board", {}).get("design_settings", {}).get("rules", {}).get("min_track_width", 0.0)
    if minw:
        graft = [re.sub(r"\(width ([0-9.]+)\)", lambda mm: f"(width {max(float(mm.group(1)), minw)})", g) for g in graft]
    base = text0.rstrip()
    pcb.write_text(base[:-1].rstrip() + "".join(graft) + "\n)\n")
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
    b1 = Board(pcb)
    for net in nets_:
        L = sum(t.length for t in b1.tracks if t.net == net)
        print(f"  {net}: {L:.2f} mm routed, {sum(1 for v in b1.vias if v.net == net)} via(s)")
    left = len(ratsnest(b1, {z.net for z in b1.zones if not z.keepout}))
    print(f"kept {len(graft)} new item(s) on the named nets; {arcs} curved track(s) shown to the router as fixed; "
          f"tracks {len(b0.tracks)} -> {len(b1.tracks)}; unrouted connections on unpoured nets: {left}")
    write_preview(pcb, o / "preview.png")
    return 0


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
              "update": lambda: update_board(d, find(d), rest[0] if rest else None)}[step]())
