"""REVIEW "jogs": short sideways steps in a route (#138). Most cases use a small
board built in memory, so every step and offset is exact."""

from pathlib import Path
from types import SimpleNamespace

from conftest import BOARDS
from test_bends import END, _path
from test_segments import A

from boardwright.jogs import jogs_check
from boardwright.model import Pad, Track
from boardwright.review import review


def _board(tracks, pads=()):
    return SimpleNamespace(tracks=[Track([a, b], 0.25, "F.Cu", "N") for a, b in tracks], pads=list(pads), vias=[],
                           layers=["F.Cu", "B.Cu"], path=Path("/nonexistent/board.kicad_pcb"))


def _pad(x, y):
    return Pad("R1", "1", "N", x, y, "F.Cu", 0.6, 0.6, 0, False, ["F.Cu"])


def _check(tracks, mm=1.0, pads=()):
    return jogs_check(_board(tracks, pads), {"jogs": [("N", mm)]})


STEP = [((0, 0), (5, 0)), ((5, 0), (5.5, 0.5)), ((5.5, 0.5), (10, 0.5))]     # east, a 45 degree step down, east


def test_a_short_step_between_parallel_runs_is_a_jog():
    assert _check(STEP) == (["jogs 1 net(s), steps under 1.0 mm: 1"],
                            ["jog on N F.Cu at (5.25, 0.25): a 0.707 mm step moves the run 0.500 mm sideways"])


def test_a_step_as_long_as_the_limit_passes():
    assert _check(STEP, mm=0.7)[1] == []


def test_a_bend_is_not_a_jog():
    assert _check([((0, 0), (5, 0)), ((5, 0), (5.5, 0.5)), ((5.5, 0.5), (5.5, 5))])[1] == []


def test_a_turn_back_is_not_a_jog():
    assert _check([((0, 0), (5, 0)), ((5, 0), (5, 0.5)), ((5, 0.5), (0, 0.5))])[1] == []


def test_a_straight_run_split_in_three_is_not_a_jog():
    assert _check([((0, 0), (5, 0)), ((5, 0), (5.5, 0)), ((5.5, 0), (10, 0))])[1] == []


def test_a_step_at_a_junction_is_not_judged():
    assert _check(STEP + [((5, 0), (5, -3))])[1] == []


def test_a_short_step_into_a_pad_the_run_misses_is_an_end_jog():
    fails = _check([((0, 0), (9.9, 0)), ((9.9, 0), (10, 0.1))], pads=[_pad(10, 0.1)])[1]
    assert fails == ["end jog on N F.Cu at (10.00, 0.10): a 0.141 mm step into a pad or via moves the run 0.100 mm sideways"]


def test_a_run_that_misses_its_pad_by_END_or_more_is_not_an_end_jog():
    assert _check([((0, 0), (9.7, 0)), ((9.7, 0), (10, 0.3))], pads=[_pad(10, 0.3)])[1] == []


def test_a_run_straight_into_its_pad_is_not_an_end_jog():
    assert _check([((0, 0), (9.9, 0)), ((9.9, 0), (10, 0))], pads=[_pad(10, 0)])[1] == []


def test_a_step_ending_off_any_pad_is_not_an_end_jog():
    assert _check([((0, 0), (9.9, 0)), ((9.9, 0), (10, 0.1))])[1] == []


def test_an_unknown_net_fails():
    assert jogs_check(_board(STEP), {"jogs": [("NOPE", 1.0)]})[1] == ["jogs NOPE: no such net"]


def test_review_runs_the_jogs_check(tmp_path):
    """rp2040_min's GPIO25 run stepped down 0.5 mm and back up, each step 0.707 mm."""
    rp = BOARDS / "rp2040_min" / "rp2040_min.kicad_pcb"
    pcb = tmp_path / rp.name
    pcb.write_text(_path(A, (155, 105.4), (155.5, 105.9), (157, 105.9), (157.5, 105.4), END[2])(rp.read_text()))
    fails = review(pcb, SimpleNamespace(REVIEW={"jogs": [("GPIO25", 1.0)]}))
    assert sum(f.startswith("jog on GPIO25 F.Cu") and "0.707 mm step" in f for f in fails) == 2
