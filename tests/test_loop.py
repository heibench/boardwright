"""REVIEW "loop": a decoupler's copper to its via, and the pin fed by the
capacitor before the plane (#122). Boards are copies of the examples, edited:
one that passes, one that fails with the named finding, and one with what the
check reads removed."""

import re
from types import SimpleNamespace

from conftest import BOARDS
from test_placement_review import _fp, _pad_net

from boardwright import copper
from boardwright.model import Board
from boardwright.review import loop_check, review

STM = BOARDS / "stm32f103_min" / "stm32f103_min.kicad_pcb"
STM4 = BOARDS / "stm32f103_4l" / "stm32f103_4l.kicad_pcb"
RECT = "(pts (xy 133.2 74) (xy 163.8 74) (xy 163.8 136) (xy 133.2 136))"
PLANE = (f'\t(zone (net "+3V3") (layer "In2.Cu") (uuid "00000000-0000-0000-0000-000000000001") (hatch edge 0.5) '
         f'(connect_pads (clearance 0.3)) (min_thickness 0.25) (fill yes) (polygon {RECT}) '
         f'(filled_polygon (layer "In2.Cu") {RECT}))\n')


def _board(tmp_path, src, edit=None):
    pcb = tmp_path / src.name
    text = src.read_text()
    pcb.write_text(edit(text) if edit else text)
    return Board(pcb)


def _plane(t):
    """A +3V3 plane filling In2.Cu (the 4-layer example's +3V3 has none)."""
    i = t.rstrip().rfind(")")
    return t[:i] + PLANE + t[i:]


def _no_tracks(net):
    def edit(t):
        cut = [(s, e) for s, e in copper.blocks(t, ("segment", "arc")) if f'(net "{net}")' in t[s:e]]
        for s, e in reversed(cut):
            t = t[:s] + t[e:]
        return t
    return edit


def test_a_ground_pad_near_its_via_passes(tmp_path):
    lines, fails = loop_check(_board(tmp_path, STM), {"loop": [("C3", "U1.24", 1.5)]})
    assert fails == []
    assert "loop C3.2 (GND): 0.75 mm to a via, 1 within (<= 1.5)" in lines


def test_a_ground_pad_far_from_its_via_fails(tmp_path):
    fails = loop_check(_board(tmp_path, STM), {"loop": [("C7", "U1.1", 1.5)]})[1]
    assert fails == ["C7.2 (GND) is 2.38 mm of copper from its nearest GND via, limit 1.5"]


def test_a_cap_with_no_ground_pad_cannot_judge(tmp_path):
    b = _board(tmp_path, STM, lambda t: _fp(t, "C3", lambda blk: _pad_net(blk, "2", "SPARE")))
    assert loop_check(b, {"loop": [("C3", "U1.24", 1.5)]})[1] == ["loop C3 -> U1.24: cannot judge, C3 has no GND pad"]


def test_a_net_with_no_plane_has_nothing_to_feed_through(tmp_path):
    lines = loop_check(_board(tmp_path, STM4), {"loop": [("C3", "U1.24", 1.5)]})[0]
    assert "loop U1.24 -> C3: +3V3 has no pour, no plane to feed through" in lines


def test_a_via_shared_with_a_cap_on_the_back_is_on_the_way(tmp_path):
    lines, fails = loop_check(_board(tmp_path, STM4, _plane), {"loop": [("C6", "U1.9", 1.5)]})
    assert fails == []
    assert "loop U1.9 -> C6: 2.97 mm, no plane via off that path nearer" in lines


def test_a_pin_fed_through_the_plane_first_fails(tmp_path):
    fails = loop_check(_board(tmp_path, STM4, _plane), {"loop": [("C7", "U1.1", 3.0)]})[1]
    assert len(fails) == 1 and re.fullmatch(
        r"U1\.1 reaches a \+3V3 plane via at \([\d.]+, [\d.]+\) 4\.48 mm out, before C7 at 72\.67 mm: "
        r"the pin is fed through the plane, not the capacitor", fails[0])


def test_a_pin_joined_to_its_cap_only_by_the_plane_fails(tmp_path):
    b = _board(tmp_path, STM4, lambda t: _no_tracks("+3V3")(_plane(t)))
    fails = loop_check(b, {"loop": [("C6", "U1.9", 99)]})[1]
    assert "U1.9 reaches C6 only through the +3V3 pour: the pin is fed through the plane, not the capacitor" in fails


def test_the_plane_pad_is_held_to_the_limit_too(tmp_path):
    fails = loop_check(_board(tmp_path, STM4, _plane), {"loop": [("C3", "U1.24", 1.5)]})[1]
    assert fails == ["C3.1 (+3V3) is 2.90 mm of copper from its nearest +3V3 via, limit 1.5"]


def test_review_runs_the_loop_check(tmp_path):
    b = _board(tmp_path, STM)
    fails = review(b.path, SimpleNamespace(REVIEW={"loop": [("C7", "U1.1", 1.5)]}))
    assert "C7.2 (GND) is 2.38 mm of copper from its nearest GND via, limit 1.5" in fails
