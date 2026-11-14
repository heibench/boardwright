"""Talk to a running KiCad through its IPC API: look at the board that is open,
and change it inside one undo step.

    boardwright live status                 # version, open board, counts, what is selected
    boardwright live snapshot [OUT_DIR]     # live board -> OUT_DIR/live.kicad_pcb + preview; nothing is saved in KiCad
    boardwright live review [SPEC.py]       # snapshot, then the engineering review on it
    boardwright live selection              # what you have selected, in boardwright coordinates
    boardwright live select NET|REF ...     # select those items in KiCad, so you can see what I mean
    boardwright live apply SPEC.py|EDITS.json [--dry-run] [--save]
    boardwright live refill                 # refill zones

SPEC.py uses the names an existing-board boardwright.py uses: MOVE, RIPUP, TRACKS,
VIAS, REVIEW. `apply` turns it into an edit list (boardwright/edits.py), or takes
one as EDITS.json, and runs it as ONE commit: one Ctrl+Z in KiCad undoes all
of it. It does not save unless --save is given; look at it first.

Coordinates are the board-relative mm that `pads` and `selection` print.

Needs KiCad running with the PCB editor open and Preferences > Plugins >
"Enable KiCad API" on. The socket is found the way kicad-python finds it;
set KICAD_API_SOCKET to override. `apply --dry-run` needs no connection.

Known traps (learned from other IPC API clients):
items are built as typed objects, never parsed from strings (KiCad reports
success and creates nothing); deleting returns no per-item result, so the
result is read back; no access to the interactive router exists in the API.
"""

from __future__ import annotations

import importlib.util
import types
from pathlib import Path

from .model import Board


def _load(path: str | None):
    if not path:
        return types.SimpleNamespace()
    sp = importlib.util.spec_from_file_location("live_spec", path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def connect():
    from kipy import KiCad
    try:
        k = KiCad(timeout_ms=5000)
        k.ping()
    except Exception as e:
        hint = ("The socket exists but this process may not open it."
                if isinstance(e, PermissionError) or "ermission" in str(e) else
                "Is KiCad running with the PCB editor open and Preferences > Plugins > Enable KiCad API switched on?")
        raise SystemExit(f"cannot reach KiCad ({type(e).__name__}: {e}). {hint}") from e
    return k


def board_of(k):
    try:
        return k.get_board()
    except Exception as e:
        raise SystemExit(f"KiCad is running but no board is open in the PCB editor ({type(e).__name__}: {e})") from e


def snapshot(b, out: Path) -> Path:
    """Write the live board (unsaved edits included) to a file our tools can read."""
    out.mkdir(parents=True, exist_ok=True)
    f = out / "live.kicad_pcb"
    f.write_text(b.get_as_string())
    return f


def _out_default(b) -> Path:
    try:
        return Path(b.get_project().path) / "boardwright_out"
    except Exception:
        return Path.cwd() / "boardwright_out"


def _layer(name: str):
    from kipy.board_types import BoardLayer
    return BoardLayer.Value("BL_" + name.replace(".", "_"))


def edit_list(arg: str, board_file: Path) -> dict:
    """An edit list from a .json file as is, or built from a spec .py against the board."""
    import json

    from . import edits
    if arg.endswith(".json"):
        return json.loads(Path(arg).read_text())
    return edits.from_spec(edits.load_spec(arg), Board(board_file))


def apply(k, b, doc: dict, save: bool) -> None:
    """Run an edit list (see boardwright/edits.py) against the open board as one commit."""
    from kipy.board_types import Track, Via
    from kipy.geometry import Angle, Vector2
    from kipy.proto.board.board_types_pb2 import ViaType
    from kipy.util.units import from_mm
    P = Vector2.from_xy_mm
    nets = {n.name: n for n in b.get_nets()}
    def net(name):
        if name not in nets:
            raise SystemExit(f"no net {name!r} on the open board")
        return nets[name]
    # kicad-python 0.8.0 cannot name the document in BeginCommit, and KiCad
    # refuses an unnamed one while the schematic editor is also open. Then the
    # edit still goes in, as separate undo steps, and we say so.
    try:
        commit = b.begin_commit()
    except Exception as e:
        if "multiple editors" not in str(e):
            raise
        commit = None
        print("note: the schematic editor is open too, so KiCad will not group this as one undo step "
              "(close the schematic editor to get a single Ctrl+Z)")
    moved = gone = made = 0
    try:
        for o in doc["ops"]:
            kind = o["op"]
            if kind == "move_footprint":
                hits = [fp for fp in b.get_footprints() if fp.reference_field.text.value == o["ref"]]
                if len(hits) != 1:
                    raise SystemExit(f"{len(hits)} footprints are called {o['ref']!r}")
                fp = hits[0]
                fp.position = P(o["x"], o["y"])
                if "rotation" in o:
                    fp.orientation = Angle.from_degrees(o["rotation"])
                b.update_items([fp])
                moved += 1
            elif kind == "remove_routing":
                rip = {net(n).name for n in o["nets"]}
                doomed = [t for t in b.get_tracks() if t.net.name in rip] + [v for v in b.get_vias() if v.net.name in rip]
                if doomed:
                    b.remove_items(doomed)
                gone += len(doomed)
            elif kind == "add_via":
                via = Via()
                via.type = ViaType.VT_THROUGH
                via.position = P(o["x"], o["y"])
                via.net = net(o["net"])
                via.diameter = from_mm(o["diameter"])
                via.drill_diameter = from_mm(o["drill"])
                made += len(b.create_items([via]))
            elif kind == "add_track":
                tr = Track()
                tr.start, tr.end = P(o["x1"], o["y1"]), P(o["x2"], o["y2"])
                tr.width, tr.layer, tr.net = from_mm(o["width"]), _layer(o["layer"]), net(o["net"])
                made += len(b.create_items([tr]))
            else:
                raise SystemExit(f"unknown op {kind!r}")
    except BaseException:
        if commit is not None:
            b.drop_commit(commit)
        raise
    msg = f"boardwright: {moved} moved, {gone} removed, {made} created"
    if commit is not None:
        b.push_commit(commit, msg)
    print(msg + ("  (one undo step in KiCad)" if commit is not None else "  (several undo steps)"))
    if save:
        b.save()
        print("saved")
    else:
        print("not saved: look at it in KiCad, undo if wrong, save it yourself or rerun with --save")


def main(argv: list[str]) -> int:
    try:
        import kipy  # noqa: F401
    except ImportError:
        raise SystemExit('boardwright live needs the live extra: pip install "boardwright[live]"') from None
    if not argv:
        raise SystemExit(__doc__)
    cmd, rest = argv[0], argv[1:]
    flags = {a for a in rest if a.startswith("--")}
    args = [a for a in rest if not a.startswith("--")]

    if cmd == "apply" and "--dry-run" in flags:      # no connection needed
        from . import edits
        if not args[0].endswith(".json") and len(args) < 2:
            raise SystemExit("a dry run from a spec needs the board file too: apply SPEC.py BOARD.kicad_pcb --dry-run")
        doc = edit_list(args[0], Path(args[1]) if len(args) > 1 else None)
        print(*("  " + l for l in edits.describe(doc)), sep="\n")
        return 0

    k = connect()
    if cmd == "status":
        print("KiCad", k.get_version())
        b = board_of(k)
        print("board:", b.name, "| copper layers:", b.get_copper_layer_count())
        print(f"  {len(b.get_footprints())} footprints, {len(b.get_tracks())} tracks, {len(b.get_vias())} vias, "
              f"{len(b.get_zones())} zones, {len(b.get_nets())} nets")
        sel = b.get_selection()
        print(f"  selected: {len(sel)} item(s)")
        return 0
    b = board_of(k)
    if cmd == "refill":
        b.refill_zones()
        print("zones refilled")
        return 0
    if cmd in ("snapshot", "review"):
        out = Path(args[0]) if cmd == "snapshot" and args else _out_default(b)
        if "--refill" in flags or cmd == "review":
            b.refill_zones()
        f = snapshot(b, out)
        from .preview import write
        write(f, out / "live_preview.png")
        print("snapshot:", f)
        if cmd == "review":
            from .review import review
            m = _load(args[0] if args else None)
            print("review:")
            fails = review(f, m)
            print(f"{'OK  ' if not fails else 'FAIL'} review", *fails, sep="\n    ")
            return 1 if fails else 0
        return 0
    if cmd == "selection":
        from kipy.util.units import to_mm
        f = snapshot(b, _out_default(b))
        ox, oy = Board(f).origin
        rel = lambda v: f"({to_mm(v.x) - ox:.3f}, {to_mm(v.y) - oy:.3f})"
        for it in b.get_selection():
            kind = type(it).__name__
            if kind == "FootprintInstance":
                print(f"footprint {it.reference_field.text.value} at {rel(it.position)} rot {it.orientation.degrees:g}")
            elif kind in ("Track", "ArcTrack"):
                print(f"track {it.net.name} {rel(it.start)} -> {rel(it.end)} w={to_mm(it.width):g}")
            elif kind == "Via":
                print(f"via {it.net.name} at {rel(it.position)}")
            elif kind == "Pad":
                print(f"pad {it.number} {it.net.name} at {rel(it.position)}")
            else:
                print(kind)
        return 0
    if cmd == "select":
        want = set(args)
        items = [t for t in b.get_tracks() if t.net.name in want] + [v for v in b.get_vias() if v.net.name in want] \
            + [fp for fp in b.get_footprints() if fp.reference_field.text.value in want]
        b.clear_selection()
        if items:
            b.add_to_selection(items)
        print(f"selected {len(items)} item(s) in KiCad for {sorted(want)}")
        return 0
    if cmd == "apply":
        from . import edits
        f = snapshot(b, _out_default(b))
        doc = edit_list(args[0], f)
        print(*("  " + l for l in edits.describe(doc)), sep="\n")
        apply(k, b, doc, "--save" in flags)
        return 0
    raise SystemExit(__doc__)


cli = main
