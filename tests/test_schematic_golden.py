"""The schematic `boardwright place` writes for every example board, against
kicad-tools 0.29's output for it, recorded in tests/data/schematic_golden/ when
boardwright still wrote schematics with kicad-tools' Schematic.

kicad-tools gave byte-identical files on two runs, uuids included: it derived
them from the content. The title block's date is a constant ("2025-01"), so
nothing is normalized. The goldens are kicad-tools' output and are not
re-recorded from boardwright's.

`build` keeps the schematic gate's reports when the schematic is unchanged
(build.stage_place), so the same circuit must give the same file every run.
"""

import shutil
from pathlib import Path

import pytest
from conftest import ROOT, needs_libs

from boardwright.cli import main

GOLDEN = Path(__file__).parent / "data" / "schematic_golden"
EXAMPLES = sorted(p.name for p in (ROOT / "examples" / "boards").iterdir() if (p / "board.py").exists())


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
    assert schematic(name, tmp_path) == (GOLDEN / f"{name}.kicad_sch").read_text()


@needs_libs
def test_schematic_is_the_same_every_run(tmp_path):
    assert schematic("esp32c3_min", tmp_path / "a") == schematic("esp32c3_min", tmp_path / "b")
