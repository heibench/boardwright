"""The whole loop on the LDO example: generate, KiCad gate, verify.

Needs KiCad's libraries, kicad-cli and Freerouting; skipped where they are missing.
"""

import pytest
from conftest import needs_freerouting, needs_kicad, needs_libs

from boardwright.cli import main


@pytest.mark.kicad
@needs_libs
@needs_freerouting
@needs_kicad
def test_generate_gate_verify(ldo_copy):
    assert main(["gen", str(ldo_copy)]) == 0
    assert main(["check", str(ldo_copy)]) == 0
    assert main(["verify", str(ldo_copy)]) == 0
    assert (ldo_copy / "out" / "gerbers").is_dir()


@needs_libs
@needs_freerouting
def test_generate_without_kicad(ldo_copy):
    pcb = ldo_copy / "ldo_breakout.kicad_pcb"
    pcb.unlink()
    assert main(["gen", str(ldo_copy)]) == 0
    from boardwright.model import Board
    from boardwright.preview import ratsnest

    b = Board(pcb)
    assert ratsnest(b, {z.net for z in b.zones}) == []


@needs_libs
def test_place_with_a_custom_library(tmp_path):
    import shutil

    from conftest import ROOT

    shutil.copytree(ROOT / "examples" / "boards" / "customlib_test", tmp_path / "boards" / "customlib_test")
    shutil.copytree(ROOT / "examples" / "libs", tmp_path / "libs")
    d = tmp_path / "boards" / "customlib_test"
    assert main(["place", str(d)]) == 0
    assert (d / "out" / "preview.svg").exists() or (d / "out" / "preview.png").exists()
    assert "Custom:MYLDO-3.3" in (d / "customlib_test.kicad_sch").read_text()
