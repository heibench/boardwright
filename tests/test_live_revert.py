"""`live revert` takes back boardwright's own last unsaved apply, and refuses
anything else (#94). The open board is a stand-in returning KiCad 10.0.8's
get_as_string() for the LDO example (tests/data/live_unsaved): untouched, and
with R1 moved as an unsaved `live apply` left it."""

import shutil
from types import SimpleNamespace

import pytest
from conftest import ROOT

from boardwright import live
from boardwright.errors import Outcome

DISK = ROOT / "examples" / "boards" / "ldo_breakout" / "ldo_breakout.kicad_pcb"
DATA = ROOT / "tests" / "data" / "live_unsaved"
UNTOUCHED = (DATA / "untouched.kicad_pcb.txt").read_text()
MOVED = (DATA / "r1_moved.kicad_pcb.txt").read_text()


@pytest.fixture
def proj(tmp_path):
    shutil.copy(DISK, tmp_path / "ldo_breakout.kicad_pcb")
    (tmp_path / "boardwright_out").mkdir()
    return tmp_path


def _board(proj, text):
    return SimpleNamespace(get_project=lambda: SimpleNamespace(path=str(proj)), name="ldo_breakout.kicad_pcb",
                           get_as_string=lambda: text)


def _applied(proj, before=UNTOUCHED, after=MOVED):
    """The record an apply without --save leaves: R1 moved, from `before`."""
    snap = proj / "boardwright_out" / "live.kicad_pcb"
    snap.write_text(before)
    live.record_apply(_board(proj, after), snap, proj / "boardwright_out")
    return proj / "boardwright_out"


def test_the_board_as_the_apply_left_it_may_be_reverted(proj):
    out = _applied(proj)
    live.revert_check(_board(proj, MOVED), out, MOVED)


def _refused(proj, out, live_text, says):
    with pytest.raises(Outcome) as e:
        live.revert_check(_board(proj, live_text), out, live_text)
    assert e.value.exit == 1 and says in e.value.message and "Nothing was changed" in e.value.message


def test_nothing_recorded_is_refused(proj):
    _refused(proj, proj / "boardwright_out", MOVED, "no unsaved apply is recorded")


def test_edits_unsaved_before_the_apply_are_refused(proj):
    """A revert reloads the file, so it would drop those too."""
    out = _applied(proj, before=MOVED)
    _refused(proj, out, MOVED, "had edits not saved before the apply")


def test_a_change_in_kicad_since_the_apply_is_refused(proj):
    """Here the person undid R1's move by hand: the board is not what the apply left."""
    out = _applied(proj)
    _refused(proj, out, UNTOUCHED, "the board changed in KiCad since the apply (footprint R1)")


def test_a_file_saved_since_the_apply_is_refused(proj):
    out = _applied(proj)
    f = proj / "ldo_breakout.kicad_pcb"
    f.write_text(f.read_text() + "\n")
    _refused(proj, out, MOVED, "changed on disk since the apply")


def test_another_board_s_record_is_refused(proj, tmp_path_factory):
    other = tmp_path_factory.mktemp("other")
    shutil.copy(DISK, other / "ldo_breakout.kicad_pcb")
    (other / "boardwright_out").mkdir()
    out = _applied(other)
    _refused(proj, out, MOVED, "was on")


def test_a_saved_apply_leaves_nothing_to_revert(proj):
    out = _applied(proj)
    live.forget_apply(out)
    assert not (out / live.APPLIED).exists() and not (out / live.APPLIED_META).exists()
    _refused(proj, out, MOVED, "no unsaved apply is recorded")
