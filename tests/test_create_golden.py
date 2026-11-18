"""board.create on every example board, against kicad-tools 0.29's `create-pcb`
output for it, recorded in tests/data/create_golden/ when boardwright still ran
create-pcb: the board as `place` creates it, before anything is placed.

Each golden has the title block's date replaced by "~" (it is today's).
kicad-tools gave byte-identical files on two runs. They were recorded where it
found no working kicad-cli and read the schematic itself, so the footprints and
nets are in the circuit's order. The goldens are kicad-tools' output and are
not re-recorded from boardwright's.

The board must equal its golden once both are normalized (normalize):
- every (uuid ...) is dropped. kicad-tools derived uuids from the content,
  kept the library's uuids on a footprint's items (so every copy of a footprint
  shared them), gave each pad one and wrote the footprint's own last;
  boardwright writes fresh ones where the library has them and the footprint's
  after its layer, as `existing update` adds a footprint.
- the board's generator lines are dropped: kicad-tools wrote "kicad_tools"
  "10.0", boardwright writes "boardwright" alone.
- a footprint's own version, generator and position lines are dropped.
  kicad-tools kept the library's version and generator in each footprint,
  which KiCad does not keep in a board, and laid the footprints out on a grid
  in the outline. Every footprint is now at (0, 0), for `place` to move
  (test_footprints_wait_at_the_sheet_origin).
- kicad-tools' "Net-(REF-PIN)" nets are dropped from the net list and the
  pads. Its schematic reader gave each no-connect pin a net of its own, which
  set_pad_nets then replaced with KiCad's "unconnected-(...)" name, leaving the
  "Net-(...)" entry in the net list with no pad on it. A no-connect pad is now
  on no net until set_pad_nets names it.
- whitespace is collapsed, and dropped next to a parenthesis: kicad-tools
  rewrote some library items on one line (fp_rect, fp_poly, a model's offset);
  boardwright keeps the library's own lines.
"""

import os
import re
import shutil
from pathlib import Path
from unittest import mock

import pytest
from conftest import ROOT, needs_libs

from boardwright import board, build

GOLDEN = Path(__file__).parent / "data" / "create_golden"
EXAMPLES = sorted(p.name for p in (ROOT / "examples" / "boards").iterdir() if (p / "board.py").exists())


def normalize(t: str) -> str:
    t = re.sub(r'(\n\t\t\(date )"[^"]*"\)', r'\1"~")', t, count=1)
    t = re.sub(r'\(uuid "[^"]*"\)', "", t)
    t = re.sub(r"\n\t\((?:generator|generator_version) [^\n]*\)", "", t)
    t = re.sub(r"\n\t\t\((?:version|generator|generator_version|at) [^\n]*\)", "", t)   # a footprint's own
    t = re.sub(r'\(net \d+ "Net-\([^"]*\)"\)', "", t)
    return re.sub(r"\s+", " ", re.sub(r"\s*([()])\s*", r"\1", t))


class _Created(Exception):
    pass


def create(name: str, tmp: Path) -> str:
    """The example's board as `place` creates it, before anything is placed."""
    d = tmp / "boards" / name
    shutil.copytree(ROOT / "examples" / "boards" / name, d, ignore=shutil.ignore_patterns("out", "__pycache__"))
    shutil.copytree(ROOT / "examples" / "libs", tmp / "libs")        # customlib_test's LIBS = ["../../libs"]
    real = board.create

    def create_then_stop(*args, **kwargs):
        real(*args, **kwargs)
        raise _Created
    saved = dict(os.environ)          # a LIBS board points KICAD_*_DIR at its merged view under tmp
    try:
        with mock.patch.object(board, "create", create_then_stop), pytest.raises(_Created):
            build.stage_place(d, build.load(d))
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return (d / f"{name}.kicad_pcb").read_text()


@needs_libs
@pytest.mark.parametrize("name", EXAMPLES)
def test_create_matches_its_golden(tmp_path, name):
    assert normalize(create(name, tmp_path)) == normalize((GOLDEN / f"{name}.kicad_pcb").read_text())


@needs_libs
@pytest.mark.parametrize("name", ["esp32c3_min", "stm32f103_4l"])
def test_footprints_wait_at_the_sheet_origin(tmp_path, name):
    """Every footprint at (0, 0) on the sheet, unrotated, where its library
    coordinates are its board coordinates: `place` turns them over and moves
    them, zones included, from there."""
    t = create(name, tmp_path)
    fps = re.findall(r'\n\t\(footprint "[^"]*"\n\t\t\(layer "([^"]*)"\)\n\t\t\(uuid "[^"]*"\)\n\t\t\(at ([^)]*)\)', t)
    assert len(fps) == t.count("\n\t(footprint ") > 0
    assert set(fps) == {("F.Cu", "0 0")}
