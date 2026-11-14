"""Make a board directory a self-contained KiCad project.

Every symbol and footprint a design uses is copied into <board>/libs and wired
up through project-local sym-lib-table / fp-lib-table, so the project opens
and checks the same on any machine, whatever libraries are installed there.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import env
from .circuit import Circuit


def _dirs() -> tuple[Path, Path]:
    return env.libraries()


def merge_libs(extra: list[Path], board_dir: Path) -> None:
    """Make custom libraries visible next to the stock ones.

    extra: directories holding *.kicad_sym files and/or *.pretty folders (yours,
    or a project's own). A merged view of links is built under the repo's
    <board>/.libmerge/ and the KICAD_*_DIR variables point at it, so lookup, vendoring
    and the pin lister all see one library set. A custom library with the same
    name as a stock one replaces it.
    """
    stock_sym, stock_fp = _dirs()
    root = board_dir / ".libmerge"
    if root.exists():
        shutil.rmtree(root)
    sym, fp = root / "symbols", root / "footprints"
    sym.mkdir(parents=True)
    fp.mkdir(parents=True)
    def link(src: Path, dst_dir: Path):
        dst = dst_dir / src.name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src)
    for f in stock_sym.glob("*.kicad_sym"):
        link(f, sym)
    for f in stock_fp.glob("*.pretty"):
        link(f, fp)
    for e in extra:
        if not e.is_dir():
            raise FileNotFoundError(f"LIBS entry {e} is not a directory")
        for f in e.rglob("*.kicad_sym"):
            link(f.resolve(), sym)
        for f in e.rglob("*.pretty"):
            link(f.resolve(), fp)
    env.use_libraries(sym, fp)


def _top_symbols(text: str) -> tuple[str, dict[str, str]]:
    """Split a .kicad_sym into its header and its top-level (symbol ...) blocks."""
    blocks, depth, i, start, header_end = {}, 0, 0, None, None
    in_str = False
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
            if depth == 2 and text.startswith("(symbol ", i):
                start = i
                header_end = header_end or i
        elif ch == ")":
            if depth == 2 and start is not None:
                blk = text[start:i + 1]
                name = blk.split('"', 2)[1]
                blocks[name] = blk
                start = None
            depth -= 1
        i += 1
    return text[:header_end].rstrip(), blocks


def _trim_sym_lib(text: str, names: set[str]) -> str:
    header, blocks = _top_symbols(text)
    keep, todo = [], list(names)
    while todo:
        n = todo.pop()
        if n in keep:
            continue
        if n not in blocks:
            raise KeyError(f"symbol {n} not in library")
        keep.append(n)
        if '(extends "' in blocks[n]:
            todo.append(blocks[n].split('(extends "', 1)[1].split('"', 1)[0])
    return header + "\n\t" + "\n\t".join(blocks[n] for n in sorted(keep)) + "\n)\n"


def vendor_libs(c: Circuit, board_dir: Path, extra_sym_libs=("power",)) -> None:
    sym_dir, fp_dir = _dirs()
    libs = board_dir / "libs"
    libs.mkdir(exist_ok=True)
    used: dict[str, set[str]] = {n: set() for n in extra_sym_libs}
    used.setdefault("power", set()).add("PWR_FLAG")
    for p in c.parts:
        nick, name = p.lib_id.split(":")
        used.setdefault(nick, set()).add(name)
    fps: dict[str, set[str]] = {}
    for p in c.parts:
        if p.footprint:
            nick, name = p.footprint.split(":")
            fps.setdefault(nick, set()).add(name)
    for nick, names in sorted(used.items()):
        src = sym_dir / f"{nick}.kicad_sym"
        if src.exists():
            (libs / src.name).write_text(_trim_sym_lib(src.read_text(), names))
        elif not (libs / src.name).exists():
            raise FileNotFoundError(src)
    for nick, names in fps.items():
        dst = libs / f"{nick}.pretty"
        dst.mkdir(exist_ok=True)
        for n in names:
            src = fp_dir / f"{nick}.pretty" / f"{n}.kicad_mod"
            if src.exists():
                shutil.copy2(src, dst / src.name)
            elif not (dst / src.name).exists():
                raise FileNotFoundError(src)
    sym_nicks = sorted(f.stem for f in libs.glob("*.kicad_sym"))
    fp_nicks = sorted(d.stem for d in libs.glob("*.pretty"))
    (board_dir / "sym-lib-table").write_text(
        "(sym_lib_table\n  (version 7)\n"
        + "".join(f'  (lib (name "{n}")(type "KiCad")(uri "${{KIPRJMOD}}/libs/{n}.kicad_sym")(options "")(descr ""))\n' for n in sym_nicks)
        + ")\n")
    (board_dir / "fp-lib-table").write_text(
        "(fp_lib_table\n  (version 7)\n"
        + "".join(f'  (lib (name "{n}")(type "KiCad")(uri "${{KIPRJMOD}}/libs/{n}.pretty")(options "")(descr ""))\n' for n in fp_nicks)
        + ")\n")


def _netclass(name, clearance, track, via_d, via_drill, priority):
    return {"name": name, "clearance": clearance, "track_width": track,
            "via_diameter": via_d, "via_drill": via_drill, "wire_width": 6, "bus_width": 12,
            "diff_pair_gap": 0.2, "diff_pair_width": 0.2, "diff_pair_via_gap": 0.25,
            "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1,
            "pcb_color": "rgba(0, 0, 0, 0.000)", "schematic_color": "rgba(0, 0, 0, 0.000)",
            "priority": priority}


def write_project(board_dir: Path, name: str, rules: dict | None = None,
                  classes: dict | None = None, severities: dict | None = None) -> Path:
    """Minimal .kicad_pro with board design rules (JLCPCB 2-layer capable).

    classes: {"Default": (clearance, track, via_d, via_drill),
              "Power": (clearance, track, via_d, via_drill, [net names])}
    """
    r = {"min_clearance": 0.15, "min_track_width": 0.15, "min_via_diameter": 0.6,
         "min_through_hole_diameter": 0.3, "min_copper_edge_clearance": 0.3,
         "min_hole_to_hole": 0.25, "min_hole_clearance": 0.15,
         # GND is routed as traces before the pour goes in, so a pad's spokes into
         # the pour are extra copper, not its only connection: one is enough.
         "min_resolved_spokes": 1}
    r.update(rules or {})
    classes = classes or {}
    d = classes.get("Default", (0.2, 0.25, 0.6, 0.3))
    ncs = [_netclass("Default", *d[:4], 2147483647)]
    patterns = []
    for i, (cname, spec) in enumerate((k, v) for k, v in classes.items() if k != "Default"):
        ncs.append(_netclass(cname, *spec[:4], i))
        patterns += [{"netclass": cname, "pattern": n} for n in spec[4]]
    pro = {
        "board": {"design_settings": {
            "rules": r,
            "defaults": {},
            "rule_severities": severities or {},
        }},
        "meta": {"filename": f"{name}.kicad_pro", "version": 3},
        "net_settings": {"classes": ncs, "meta": {"version": 4},
                         "netclass_patterns": patterns},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [], "text_variables": {},
    }
    p = board_dir / f"{name}.kicad_pro"
    p.write_text(json.dumps(pro, indent=2))
    return p
