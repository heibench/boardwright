"""boardwright: generate and edit KiCad boards from a short Python description.

New board (a directory holding board.py):
  boardwright place DIR              place parts, write an instant preview with ratsnest
  boardwright gen DIR                schematic, board, routing, pours
  boardwright check DIR [--quick]    KiCad gate: ERC, DRC, netlist, fab outputs, plots
  boardwright verify DIR             read the gate's reports and the engineering review
  boardwright pads DIR               every pad with its net and position

Any board:
  boardwright existing DIR STEP ...  inspect, baseline, edit in place, reroute (see `existing`)
  boardwright sch DIR CMD ...        edit a schematic in place (see `sch`)
  boardwright review PCB [SPEC.py]   engineering review of any board file
  boardwright preview PCB [OUT.png]  placement view with ratsnest, no KiCad needed
  boardwright edits SPEC.py PCB OUT.json [PRO]   a plain list of board edits
  boardwright selection SEL PCB      describe text copied from KiCad's board editor
  boardwright live CMD ...           read and edit the board open in KiCad (needs [live])

Lookups:
  boardwright pins LIB:SYMBOL [LIB:FOOTPRINT] [--libs DIR ...]
  boardwright impedance [STACKUP [Z | Z W]]
  boardwright doctor                 what this machine has for each step
"""

from __future__ import annotations

import importlib
import importlib.metadata
import shutil
import sys

from . import __version__

_BUILD = {"gen", "place", "verify", "pads"}
_MODULES = {
    "check": "check", "existing": "existing", "sch": "sch", "review": "review",
    "preview": "preview", "edits": "edits", "selection": "selection", "live": "live",
    "pins": "pins", "impedance": "si",
}
_NEEDS_LIBS = {"gen", "place", "pins", "sch"}


def doctor() -> int:
    from . import env

    ok = True

    def row(name: str, fn) -> None:
        nonlocal ok
        try:
            print(f"ok    {name:<12} {fn()}")
        except (SystemExit, Exception) as e:
            ok = False
            print(f"MISS  {name:<12} {e}")

    row("symbols", lambda: env.libraries()[0])
    row("footprints", lambda: env.libraries()[1])
    row("kicad-cli", lambda: " ".join(env.kicad_cli()))
    row("freerouting", lambda: " ".join(env.freerouting()))
    row("kicad-tools", lambda: importlib.metadata.version("kicad-tools"))
    try:
        print(f"ok    {'kicad-python':<12} {importlib.metadata.version('kicad-python')} (live)")
    except importlib.metadata.PackageNotFoundError:
        print(f"-     {'kicad-python':<12} not installed; `live` needs boardwright[live]")
    rsvg = shutil.which("rsvg-convert")
    print(f"{'ok' if rsvg else '-':<5} {'rsvg-convert':<12} {rsvg or 'not found; previews stay SVG'}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "--version":
        print(f"boardwright {__version__}")
        return 0
    if cmd == "doctor":
        return doctor()
    if cmd in _NEEDS_LIBS:
        from . import env

        env.use_libraries()
    if cmd in _BUILD:
        if not rest:
            raise SystemExit(f"usage: boardwright {cmd} DIR")
        from . import build

        return build.cli([rest[0], cmd])
    if cmd in _MODULES:
        mod = importlib.import_module(f".{_MODULES[cmd]}", __package__)
        return mod.cli(rest) or 0
    print(f"unknown command {cmd!r}\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
