"""Print a stock symbol's pins (and its default footprint's pads).

    boardwright pins Regulator_Switching:TPS54202DDC [Lib:Footprint] [--libs dir ...]

--libs adds custom library directories (the same ones a board lists in LIBS).
"""
import re
import tempfile
from pathlib import Path

from . import env
from .circuit import library_symbol


def main(lib_id: str, fp: str | None = None) -> None:
    sd = library_symbol(lib_id)
    print(lib_id)
    for p in sorted(sd.pins, key=lambda p: (len(p.number), p.number)):
        print(f"  {p.number:>4} {p.name:<22} {p.pin_type:<14} unit={sd.get_pin_unit(p.number)}")
    lib, name = lib_id.split(":")
    text = (env.libraries()[0] / f"{lib}.kicad_sym").read_text(encoding="utf-8")
    i = text.find(f'(symbol "{name}"')
    blk = text[i:text.find('\n\t(symbol "', i + 1)]
    for prop in ("Footprint", "Datasheet", "Description", "ki_fp_filters"):
        m = re.search(rf'\(property "{prop}" "([^"]*)"', blk)
        print(f"  {prop}: {m.group(1) if m else '-'}")
    ext = re.search(r'\(extends "([^"]+)"', blk)
    if ext:
        print("  extends:", ext.group(1))
    if fp:
        nick, n = fp.split(":")
        t = (env.libraries()[1] / f"{nick}.pretty" / f"{n}.kicad_mod").read_text(encoding="utf-8")
        print(fp)
        for m in re.finditer(r'\(pad "([^"]*)" (\w+) (\w+)\s+\(at ([-\d.]+) ([-\d.]+)[^)]*\)\s+\(size ([-\d.]+) ([-\d.]+)', t):
            print("  pad", *m.groups())


def cli(argv: list[str]) -> int:
    argv = ["boardwright", *argv]
    args = argv[1:]
    if "--libs" in args:
        i = args.index("--libs")
        from .project import merge_libs
        merge_libs([Path(a).resolve() for a in args[i + 1:]], Path(tempfile.mkdtemp()))
        args = args[:i]
    main(*args[:2])
    return 0
