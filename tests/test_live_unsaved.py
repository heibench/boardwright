"""`live apply --save` refuses when the open board has edits not saved to its
file (#46, item 1).

The two files in tests/data/live_unsaved are KiCad 10.0.8's get_as_string()
for examples/boards/ldo_breakout opened in the PCB editor: untouched, and
after a `live apply` (no --save) moved R1 from (145.5, 111.5) to (145.5, 113).
"""

import shutil
from types import SimpleNamespace

import pytest
from conftest import ROOT

from boardwright import live
from boardwright.errors import Outcome

DISK = ROOT / "examples" / "boards" / "ldo_breakout" / "ldo_breakout.kicad_pcb"
DATA = ROOT / "tests" / "data" / "live_unsaved"


def test_an_untouched_board_differs_from_its_file_byte_for_byte():
    """Why the check compares items: a byte comparison would see edits on every board."""
    assert (DATA / "untouched.kicad_pcb.txt").read_text() != DISK.read_text()


def test_an_untouched_board_has_no_unsaved_edits():
    assert live.unsaved_edits((DATA / "untouched.kicad_pcb.txt").read_text(), DISK.read_text()) == []


def test_an_unsaved_move_is_named_by_its_reference():
    assert live.unsaved_edits((DATA / "r1_moved.kicad_pcb.txt").read_text(), DISK.read_text()) == ["footprint R1"]


def _open(board_dir):
    return SimpleNamespace(get_project=lambda: SimpleNamespace(path=str(board_dir)), name="ldo_breakout.kicad_pcb")


@pytest.mark.parametrize("live_board, refused", [("untouched", False), ("r1_moved", True)])
def test_save_is_refused_only_over_unsaved_edits(tmp_path, live_board, refused):
    shutil.copy(DISK, tmp_path / "ldo_breakout.kicad_pcb")
    snap = DATA / f"{live_board}.kicad_pcb.txt"
    if not refused:
        live._refuse_unsaved(_open(tmp_path), snap)
        return
    with pytest.raises(Outcome) as e:
        live._refuse_unsaved(_open(tmp_path), snap)
    assert e.value.exit == 1
    assert "edits not saved to ldo_breakout.kicad_pcb (footprint R1)" in e.value.message
    assert "Nothing was changed" in e.value.message
