"""The schematic `boardwright place` writes for every example board, against
kicad-tools 0.29's output for it, recorded in tests/data/schematic_golden/ when
boardwright still wrote schematics with kicad-tools' Schematic.

kicad-tools gave byte-identical files on two runs, uuids included: it derived
them from the content. The title block's date is a constant ("2025-01"). The
goldens are kicad-tools' output and are not re-recorded from boardwright's.

Everything outside the symbol cache (lib_symbols) must match byte for byte:
header, placed symbols and their uuids, wires, no-connects, labels, PWR_FLAGs.
The cache entries must be the same symbols in the same order, each compared
as its properties and unit symbols in order, whitespace aside, and the set of
its other items (normalize):
- whitespace: kicad-tools re-wrote each library symbol in its own layout
  (a pin's `at` and `length` on the pin's line, `(fill (type ...)` split over
  two lines); boardwright copies the library's own lines, as `sch add` does.
- the order and repeats of an entry's other items, on a symbol that `extends`
  another (AMS1117-3.3, AP2112K-3.3, USBLC6-2SC6, W25Q128JVS, STM32F103C8Tx,
  TPS54202DDC, Custom:MYLDO-3.3): kicad-tools moved `in_pos_files` and
  `duplicate_pin_numbers_are_jumpers` after the properties and wrote
  `(embedded_fonts no)` twice, the parent's and the child's; sch._flatten
  keeps the parent's order and one `embedded_fonts`.

`build` keeps the schematic gate's reports when the schematic is unchanged
(build.stage_place), so the same circuit must give the same file every run.
"""

import re
import shutil
from pathlib import Path

import pytest
from conftest import ROOT, needs_libs

from boardwright.cli import main
from boardwright.copper import blocks

GOLDEN = Path(__file__).parent / "data" / "schematic_golden"
EXAMPLES = sorted(p.name for p in (ROOT / "examples" / "boards").iterdir() if (p / "board.py").exists())


def _tree(tokens: list[str]) -> list:
    stack = [[]]
    for tk in tokens:
        if tk == "(":
            stack.append([])
        elif tk == ")":
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(tk)
    return stack[0]


def normalize(t: str) -> tuple[str, list]:
    """The file with its symbol cache taken out, and each cache entry as (name,
    the set of its items other than properties and unit symbols, those in order)."""
    s, e = blocks(t, ("lib_symbols",))[0]
    cache = _tree(re.findall(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+', t[s:e]))[0]
    entries = [(sym[1], sorted({repr(k) for k in sym[2:] if k[0] not in ("property", "symbol")}),
                [k for k in sym[2:] if k[0] in ("property", "symbol")]) for sym in cache[1:]]
    return t[:s] + "\n\t(lib_symbols ~)" + t[e:], entries


def schematic(name: str, tmp: Path) -> str:
    """The example's schematic as `boardwright place` writes it."""
    d = tmp / "boards" / name
    shutil.copytree(ROOT / "examples" / "boards" / name, d, ignore=shutil.ignore_patterns("out", "__pycache__", ".libmerge"))
    shutil.copytree(ROOT / "examples" / "libs", tmp / "libs")        # customlib_test's LIBS = ["../../libs"]
    assert main(["place", str(d)]) == 0
    return (d / f"{name}.kicad_sch").read_text()


@needs_libs
@pytest.mark.parametrize("name", EXAMPLES)
def test_schematic_matches_its_golden(tmp_path, name):
    got_rest, got_cache = normalize(schematic(name, tmp_path))
    want_rest, want_cache = normalize((GOLDEN / f"{name}.kicad_sch").read_text())
    assert got_rest == want_rest, "the schematic differs outside its symbol cache"
    assert [n for n, *_ in got_cache] == [n for n, *_ in want_cache]
    for got, want in zip(got_cache, want_cache):
        assert got == want, f"cache entry {want[0]} differs from its golden"


@needs_libs
def test_schematic_is_the_same_every_run(tmp_path):
    assert schematic("esp32c3_min", tmp_path / "a") == schematic("esp32c3_min", tmp_path / "b")
