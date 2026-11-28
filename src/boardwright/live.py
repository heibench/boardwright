"""Talk to a running KiCad through its IPC API: look at the board that is open,
and change it inside one undo step.

    boardwright live status                 # version, open board, counts, what is selected
    boardwright live snapshot [OUT_DIR]     # live board -> OUT_DIR/live.kicad_pcb + preview; nothing is saved in KiCad
    boardwright live review [SPEC.py]       # snapshot, then the engineering review on it
    boardwright live selection              # what you have selected, in boardwright coordinates
    boardwright live select NET|REF ...     # select those items in KiCad, so you can see what I mean
    boardwright live apply SPEC.py|EDITS.json [--dry-run] [--save]
    boardwright live refill                 # refill zones
    boardwright live revert                 # take back boardwright's own last unsaved apply, and nothing else
    boardwright live open BOARD             # start the PCB editor on BOARD and wait until it answers

SPEC.py uses the names an existing-board boardwright.py uses: MOVE, RIPUP, TRACKS,
VIAS, REVIEW. `apply` turns it into an edit list (boardwright/edits.py), or takes
one as EDITS.json, and runs it as ONE commit: one Ctrl+Z in KiCad undoes all
of it. It does not save unless --save is given; look at it first. With
--save, an edit that changed copper refills the zones before the save, and
a board whose open copy holds edits its file does not is refused (exit 1)
before anything changes: the save would keep them too.
An apply without --save is recorded, so `revert` can take it back: it reloads
the board from its file (KiCad's RevertDocument), and does so only when the
open board is exactly what that apply left, the file is unchanged, and
nothing else was unsaved before it. Anything else is refused (exit 1), since
a revert would drop it too.
A KiCad that stays busy (refilling, checking) is waited on for at most
BUSY_WAIT_S, then reported as an environment fault (exit 4).

Coordinates are the board-relative mm that `pads` and `selection` print.

Needs KiCad running with the PCB editor open and Preferences > Plugins >
"Enable KiCad API" on. The socket is found the way kicad-python finds it;
set KICAD_API_SOCKET to override. `apply --dry-run` needs no connection.

--board FILE (any verb) picks the KiCad that has FILE open: a second KiCad
gets api-<pid>.sock, so the default socket may be one without the board.
Every socket in KiCad's socket folders is asked (env.kicad_api_sockets);
none with FILE open is exit 4, more than one is exit 1.

`open BOARD` is how a board gets in front of `live` on KiCad 10, whose API
cannot open a document: the project manager serves no OpenDocument or
RunAction, while a standalone PCB editor serves the API. It does nothing if a
KiCad already has BOARD open; otherwise it starts the editor (env.pcbnew)
detached and waits up to OPEN_WAIT_S for a socket to answer with BOARD open.
With the Flatpak editor it refuses while any api-*.sock exists in the Flatpak
socket folder (see open_board).

Known traps (learned from other IPC API clients):
items are built as typed objects, never parsed from strings (KiCad reports
success and creates nothing); deleting returns no per-item result, so the
result is read back; no access to the interactive router exists in the API.
"""

from __future__ import annotations

import re
import subprocess
import time
import types
from collections import Counter
from pathlib import Path

from . import env
from .errors import EnvironmentFault, Outcome, Usage
from .model import Board


def _load(path: str | None):
    if not path:
        return types.SimpleNamespace()
    m = env.load_source(path, "live_spec")
    return m


def _open(socket, timeout_ms: int):
    from kipy import KiCad
    return KiCad(socket_path=None if socket is None else f"ipc://{socket}", timeout_ms=timeout_ms)


def _ready(k):
    """k, once it answers a ping. KiCad replies "not ready" while it is still
    loading, so that reply (and busy) is asked again for the same bound as the
    busy wait; a socket that does not answer at all is not waited on."""
    from kipy.proto.common import ApiStatusCode
    clock, sleep = _clock
    _when_idle(k.ping, "waiting for KiCad to be ready", codes=(ApiStatusCode.AS_NOT_READY, ApiStatusCode.AS_BUSY),
               no_reply=False, clock=clock, sleep=sleep)
    return k


def connect(socket=None, timeout_ms: int = 5000):
    try:
        return _ready(_open(socket, timeout_ms))
    except EnvironmentFault:
        raise
    except Exception as e:
        hint = ("The socket exists but this process may not open it."
                if isinstance(e, PermissionError) or "ermission" in str(e) else
                "Is KiCad running with the PCB editor open and Preferences > Plugins > Enable KiCad API switched on?")
        raise EnvironmentFault(f"cannot reach KiCad ({type(e).__name__}: {e}). {hint}") from e


# kicad-python 0.8.0's own request timeout (kipy/kicad.py, KiCad.__init__).
# Asking a socket nobody listens on fails at once; this bounds a hung one.
PROBE_TIMEOUT_MS = 2000


def find_board(board: str, sockets=None, opener=None):
    """(KiCad, document) for the one running KiCad that has `board` open, asking
    every socket env.kicad_api_sockets() lists. The open board's path is the
    document's project.path joined with its board_filename (kicad-python 0.8.0
    DocumentSpecifier; kipy.board.Board.name and Project.path read the same)."""
    return _locate(board, sockets, opener)[1:]


def _locate(board: str, sockets=None, opener=None):
    """(socket, KiCad, document): find_board, naming the socket too."""
    from kipy.errors import ApiError
    from kipy.proto.common import ApiStatusCode
    from kipy.proto.common.types import DocumentType

    from . import env
    want = Path(board).resolve()
    sockets = env.kicad_api_sockets() if sockets is None else sockets
    opener = opener or _open
    clock, sleep = _clock
    asked, hits = [], []
    for s in sockets:
        try:
            k = _ready(opener(s, PROBE_TIMEOUT_MS))
            docs = _when_idle(lambda: k.get_open_documents(DocumentType.DOCTYPE_PCB), "listing open boards",
                              no_reply=False, clock=clock, sleep=sleep)
        except EnvironmentFault as e:
            asked.append(f"{s}: {e.message}")
            continue
        except ApiError as e:
            why = "no PCB editor (a project manager)" if e.code == ApiStatusCode.AS_UNHANDLED else "refused"
            asked.append(f"{s}: {why}: {e}")
            continue
        except Exception as e:
            asked.append(f"{s}: does not answer ({type(e).__name__}: {e})")
            continue
        paths = [Path(d.project.path) / d.board_filename for d in docs]
        asked.append(f"{s}: " + (", ".join(map(str, paths)) or "no board open"))
        hits += [(s, k, d) for d, p in zip(docs, paths) if p.resolve() == want]
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise Outcome(f"{len(hits)} running KiCads have {want} open; close all but one. They are:\n  "
                      + "\n  ".join(str(s) for s, _, _ in hits))
    raise EnvironmentFault(f"no running KiCad has {want} open. Asked:\n  "
                           + ("\n  ".join(asked) or "no KiCad API socket found (set KICAD_API_SOCKET)"))


# Chosen, not measured: the Flatpak editor's start on this machine has not been
# timed. A cold start loads the libraries, so it gets longer than BUSY_WAIT_S,
# which bounds one busy reply.
OPEN_WAIT_S, OPEN_POLL_S = 60.0, 1.0


def open_board(board: str) -> int:
    """Start the PCB editor on `board`, detached, and wait until a running KiCad
    answers with it open. Nothing is started if one already has it."""
    from . import env
    path = Path(board).resolve()
    if path.suffix != ".kicad_pcb" or not path.is_file():
        raise Usage(f"live open needs an existing .kicad_pcb file: {board}")
    try:
        s, _, _ = _locate(str(path))
        print(f"already open: {path} on {s}")
        return 0
    except EnvironmentFault:
        pass                                    # not open anywhere; a KiCad open in two is exit 1, raised as is
    cmd, flatpak = env.pcbnew()
    if flatpak:
        # Inside each Flatpak instance the pid is namespaced, so a new instance
        # may name its socket api-<pid>.sock exactly as a running one did, and
        # `--board` could no longer tell them apart. Inferred from the
        # namespacing, not measured: refuse rather than risk it. A project
        # manager on api.sock is fine (measured: the editor got api-2.sock).
        taken = sorted(env.flatpak_socket_dir().glob("api-*.sock"))
        if taken:
            raise Outcome(
                "not starting a Flatpak PCB editor while another Flatpak KiCad holds a numbered socket ("
                + ", ".join(map(str, taken)) + "): inside Flatpak the pid in api-<pid>.sock is namespaced, so a "
                "new instance may take the same name. Close that KiCad (or remove the file if no KiCad is running), "
                "or open the board in it.")
    argv = [*cmd, str(path)]
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
    except (OSError, subprocess.SubprocessError) as e:
        raise EnvironmentFault(f"could not start the PCB editor: {' '.join(argv)} ({type(e).__name__}: {e})") from e
    print("started:", " ".join(argv))
    clock, sleep = _clock
    deadline = clock() + OPEN_WAIT_S
    while True:
        try:
            s, _, _ = _locate(str(path))
            print(f"open: {path} on {s}")
            return 0
        except EnvironmentFault as e:
            last = e.message
        code = proc.poll()
        exited = "" if code is None else f"; the editor exited with exit code {code}"
        if (code not in (None, 0)) or clock() >= deadline:
            waited = "" if code not in (None, 0) else f" after {OPEN_WAIT_S:g} s"
            raise EnvironmentFault(f"{path} did not appear in a running KiCad{waited} (started: {' '.join(argv)}"
                                   f"{exited}). Last look: {last}")
        sleep(OPEN_POLL_S)


def _board(k, doc):
    """The board for that document, built as kipy's KiCad.get_board builds its first one."""
    from kipy.board import Board as KiBoard
    return KiBoard(k._client, doc)


def board_of(k):
    try:
        return k.get_board()
    except Exception as e:
        raise EnvironmentFault(f"KiCad is running but no board is open in the PCB editor ({type(e).__name__}: {e})") from e


# kicad-python 0.8.0's Board.refill_zones defaults (kipy/board.py:1417-1418).
# Its blocking loop never counts its sleeps, so a KiCad that stays busy hangs
# it forever, and a transport timeout escapes it; we poll ourselves.
BUSY_WAIT_S, BUSY_POLL_S = 30.0, 0.5
_clock = (time.monotonic, time.sleep)


def _when_idle(call, what: str, wait: float = BUSY_WAIT_S, poll: float = BUSY_POLL_S,
               clock=time.monotonic, sleep=time.sleep, codes=None, no_reply: bool = True):
    """call(), retried while KiCad answers with one of `codes` (default: busy) or,
    if no_reply, does not answer, for at most `wait` seconds."""
    from kipy.errors import ApiError
    from kipy.errors import ConnectionError as NoReply
    from kipy.proto.common import ApiStatusCode
    codes = (ApiStatusCode.AS_BUSY,) if codes is None else codes
    deadline = clock() + wait
    while True:
        try:
            return call()
        except ApiError as e:
            if e.code not in codes:
                raise
            last = e
        except NoReply as e:
            if not no_reply:
                raise
            last = e
        if clock() >= deadline:
            raise EnvironmentFault(f"KiCad was still busy, not ready or not answering after {wait:g} s of {what} "
                                   f"({type(last).__name__}: {last})") from last
        sleep(poll)


def refill(k, b) -> None:
    """Refill every zone and wait, bounded, until KiCad answers again."""
    _when_idle(lambda: b.refill_zones(block=False), "starting the zone refill")
    _when_idle(k.ping, "refilling zones")


def board_path(b) -> str:
    """The open board's full path, so a user can see which copy is about to change."""
    try:
        return str(Path(b.get_project().path) / b.name)
    except Exception:
        return b.name


def snapshot(b, out: Path) -> Path:
    """Write the live board (unsaved edits included) to a file our tools can read."""
    out.mkdir(parents=True, exist_ok=True)
    f = out / "live.kicad_pcb"
    f.write_text(b.get_as_string())
    return f


_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+')
_FOOTPRINT_STAMP = re.compile(r'\( (?:version \d+|generator "[^"]*"|generator_version "[^"]*") \) ')


def _items(text: str) -> Counter:
    """A board file's top-level items, each as one whitespace-normalised
    string, counted. KiCad 10.0.8's get_as_string() writes an unchanged board
    differently from the file it loaded: items in another order, fonts on one
    line, and a version stamp in each footprint (938 diff lines on
    examples/boards/ldo_breakout, #46). As items, without the stamp, the two
    are equal."""
    toks = _TOKEN.findall(text)
    out, depth, cur = [], 0, []
    for t in toks[2:-1]:                    # inside (kicad_pcb ...)
        depth += t == "("
        cur.append(t)
        if t == ")":
            depth -= 1
            if depth == 0:
                item = " ".join(cur)
                out.append(_FOOTPRINT_STAMP.sub("", item) if item.startswith("( footprint") else item)
                cur = []
    return Counter(out)


def unsaved_edits(live_text: str, disk_text: str) -> list[str]:
    """What the board open in KiCad has that its file does not: one line per
    item, a footprint by its reference. Empty when KiCad holds the file as saved."""
    def name(item: str) -> str:
        ref = re.search(r'\( property "Reference" "([^"]*)"', item)
        return f"footprint {ref.group(1)}" if ref else item.split(" ", 2)[1]
    return sorted(name(i) for i in (_items(live_text) - _items(disk_text)).elements())


def _refuse_unsaved(b, live_file: Path) -> None:
    """`apply --save` saves the whole open board, so a person's unsaved edits
    would be saved with ours (#46). Refuse before changing anything."""
    disk = Path(board_path(b))
    if not disk.is_file():
        return
    extra = unsaved_edits(live_file.read_text(), disk.read_text())
    if extra:
        shown = ", ".join(dict.fromkeys(extra[:5])) + (", ..." if len(extra) > 5 else "")
        raise Outcome(f"refused: the board open in KiCad has edits not saved to {disk.name} ({shown}); "
                      "--save would save them with mine. Save or undo them in KiCad, or rerun without --save. "
                      "Nothing was changed.")


APPLIED = "live.applied.kicad_pcb"     # the board as an unsaved apply left it (#94)
APPLIED_META = "live.applied.json"


def _sha(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def record_apply(b, before: Path, out: Path) -> None:
    """After an apply without --save: what revert needs to tell boardwright's
    own edit from anyone else's."""
    import json
    disk = Path(board_path(b))
    disk_text = disk.read_text() if disk.is_file() else ""
    (out / APPLIED).write_text(b.get_as_string())
    (out / APPLIED_META).write_text(json.dumps({
        "board": str(disk), "disk_sha256": _sha(disk_text),
        "clean_before": bool(disk_text) and not unsaved_edits(before.read_text(), disk_text)}, indent=1))


def forget_apply(out: Path) -> None:
    for name in (APPLIED, APPLIED_META):
        (out / name).unlink(missing_ok=True)


def revert_check(b, out: Path, live_text: str) -> None:
    """Refuse (exit 1) unless the open board holds boardwright's last unsaved
    apply and nothing else; a revert drops every unsaved change (#94)."""
    import json
    meta = out / APPLIED_META
    disk = Path(board_path(b))
    if not meta.is_file():
        raise Outcome(f"refused: no unsaved apply is recorded for {disk.name}; nothing to take back. Nothing was changed.")
    rec = json.loads(meta.read_text())
    if rec.get("board") != str(disk):
        raise Outcome(f"refused: the recorded apply was on {rec.get('board')}, not {disk}. Nothing was changed.")
    if not rec.get("clean_before"):
        raise Outcome(f"refused: {disk.name} had edits not saved before the apply; a revert would drop those too. "
                      "Undo the apply with Ctrl+Z in KiCad instead. Nothing was changed.")
    if not disk.is_file() or _sha(disk.read_text()) != rec.get("disk_sha256"):
        raise Outcome(f"refused: {disk.name} changed on disk since the apply; a revert would load that instead. "
                      "Nothing was changed.")
    after = (out / APPLIED).read_text()
    extra = sorted(set(unsaved_edits(live_text, after)) | set(unsaved_edits(after, live_text)))
    if extra:
        raise Outcome(f"refused: the board changed in KiCad since the apply ({', '.join(dict.fromkeys(extra[:5]))}"
                      f"{', ...' if len(extra) > 5 else ''}); a revert would drop that too. Nothing was changed.")


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
            raise Usage(f"no net {name!r} on the open board")
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
                raise Usage(f"unknown op {kind!r}")
    except BaseException:
        if commit is not None:
            b.drop_commit(commit)
        raise
    msg = f"boardwright: {moved} moved, {gone} removed, {made} created"
    if commit is not None:
        b.push_commit(commit, msg)
    print(msg + ("  (one undo step in KiCad)" if commit is not None else "  (several undo steps)"))
    if save:
        if moved + gone + made:
            refill(k, b)
            print("zones refilled")
        _when_idle(b.save, "saving")
        print("saved")
    else:
        # not "rerun with --save": this edit is now unsaved in KiCad, so that rerun is refused (#46)
        print("not saved: look at it in KiCad, then save it there (Ctrl+S) to keep it, "
              "or undo it (Ctrl+Z) before applying again")


def main(argv: list[str]) -> int:
    try:
        import kipy  # noqa: F401
    except ImportError:
        raise EnvironmentFault('boardwright live needs the live extra: pip install "boardwright[live]"') from None
    board, words = None, []
    it = iter(argv)
    for a in it:
        if a == "--board" or a.startswith("--board="):
            board = a.partition("=")[2] if "=" in a else next(it, "")
            if not board or board.startswith("--"):
                raise Usage("--board needs a board file: --board FILE.kicad_pcb")
        else:
            words.append(a)
    if not words:
        raise Usage(__doc__)
    cmd, rest = words[0], words[1:]
    flags = {a for a in rest if a.startswith("--")}
    args = [a for a in rest if not a.startswith("--")]

    if cmd == "apply" and "--dry-run" in flags:      # no connection needed
        from . import edits
        if not args[0].endswith(".json") and len(args) < 2:
            raise Usage("a dry run from a spec needs the board file too: apply SPEC.py BOARD.kicad_pcb --dry-run")
        doc = edit_list(args[0], Path(args[1]) if len(args) > 1 else None)
        print(*("  " + l for l in edits.describe(doc)), sep="\n")
        return 0

    if cmd == "open":
        if len(args) > 1 or (args and board and Path(args[0]).resolve() != Path(board).resolve()) \
                or not (args or board):
            raise Usage("live open BOARD.kicad_pcb (or live --board BOARD.kicad_pcb open)")
        return open_board(args[0] if args else board)

    if board:
        k, d = find_board(board)
        b = _board(k, d)
    else:
        k, b = connect(), None
    if cmd == "status":
        print("KiCad", k.get_version())
        b = b if b is not None else board_of(k)
        print("board:", board_path(b), "| copper layers:", b.get_copper_layer_count())
        print(f"  {len(b.get_footprints())} footprints, {len(b.get_tracks())} tracks, {len(b.get_vias())} vias, "
              f"{len(b.get_zones())} zones, {len(b.get_nets())} nets")
        sel = b.get_selection()
        print(f"  selected: {len(sel)} item(s)")
        return 0
    b = b if b is not None else board_of(k)
    if cmd == "refill":
        refill(k, b)
        print("zones refilled")
        return 0
    if cmd == "revert":
        out = _out_default(b)
        revert_check(b, out, b.get_as_string())
        _when_idle(b.revert, "reverting")
        disk = Path(board_path(b))
        left = unsaved_edits(b.get_as_string(), disk.read_text())
        forget_apply(out)
        if left:
            raise EnvironmentFault(f"KiCad reverted {disk.name} but the open board still differs from it ({', '.join(left[:5])})")
        print(f"reverted {disk.name} to its file: boardwright's last apply is gone")
        return 0
    if cmd in ("snapshot", "review"):
        out = Path(args[0]) if cmd == "snapshot" and args else _out_default(b)
        if "--refill" in flags or cmd == "review":
            refill(k, b)
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
        if "--save" in flags:
            _refuse_unsaved(b, f)
        doc = edit_list(args[0], f)
        print("editing", board_path(b))
        print(*("  " + l for l in edits.describe(doc)), sep="\n")
        apply(k, b, doc, "--save" in flags)
        if "--save" in flags:
            forget_apply(_out_default(b))
        else:
            record_apply(b, f, _out_default(b))
        return 0
    raise Usage(__doc__)


cli = main
