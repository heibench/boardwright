"""REVIEW "apart" and "clear_under": quiet copper kept from noise (#125).
Boards are copies of the examples, edited: one that passes, one that fails
with the named finding, and one with what the check reads removed."""

import re
from types import SimpleNamespace

from conftest import BOARDS
from test_placement_review import _fp

from boardwright.model import Board
from boardwright.review import apart_check, review

BUCK = BOARDS / "tps54202_buck" / "tps54202_buck.kicad_pcb"
STM = BOARDS / "stm32f103_min" / "stm32f103_min.kicad_pcb"
STM4 = BOARDS / "stm32f103_4l" / "stm32f103_4l.kicad_pcb"


def _board(tmp_path, src, edit=None):
    pcb = tmp_path / src.name
    text = src.read_text()
    pcb.write_text(edit(text) if edit else text)
    return Board(pcb)


def _under_boot0(layer):
    """A NOISE track on `layer` right under BOOT0's F.Cu track (file coordinates;
    BOOT0 has no via, so its copper is on F.Cu alone)."""
    seg = (f'\t(segment (start 139.92 95.3) (end 145.68 95.3) (width 0.2) (layer "{layer}") (net "NOISE") '
           f'(uuid "00000000-0000-0000-0000-000000000002"))\n')
    return lambda t: t[:t.rstrip().rfind(")")] + seg + t[t.rstrip().rfind(")"):]


def test_feedback_clear_of_the_switch_node_passes(tmp_path):
    lines, fails = apart_check(_board(tmp_path, BUCK), {"apart": [("FB", ["SW"], 0.9)]})
    assert fails == []
    assert lines == ["apart FB | SW: 1.00 mm (FB to SW, F.Cu) (>= 0.9)"]


def test_feedback_near_the_switch_node_fails(tmp_path):
    fails = apart_check(_board(tmp_path, BUCK), {"apart": [("FB", "SW", 1.2)]})[1]
    assert len(fails) == 1 and re.fullmatch(
        r"FB comes within 1\.00 mm of SW on F\.Cu, near \([\d.]+, [\d.]+\), limit 1\.2", fails[0])


def test_a_quiet_net_with_no_copper_cannot_judge(tmp_path):
    fails = apart_check(_board(tmp_path, BUCK), {"apart": [("NOPE", "SW", 1.2)]})[1]
    assert fails == ["apart NOPE | SW: cannot judge, no copper on NOPE"]


def test_noise_on_the_adjacent_layer_counts(tmp_path):
    fails = apart_check(_board(tmp_path, STM4, _under_boot0("In1.Cu")), {"apart": [("BOOT0", "NOISE", 0.5)]})[1]
    assert len(fails) == 1 and fails[0].startswith("BOOT0 comes within 0.00 mm of NOISE on F.Cu/In1.Cu")


def test_noise_two_layers_down_does_not(tmp_path):
    lines, fails = apart_check(_board(tmp_path, STM4, _under_boot0("In2.Cu")), {"apart": [("BOOT0", "NOISE", 0.5)]})
    assert fails == [] and lines == ["apart BOOT0 | NOISE: no copper on the same or an adjacent layer"]


def test_nothing_under_a_part_passes(tmp_path):
    lines, fails = apart_check(_board(tmp_path, STM), {"clear_under": [("R1", 0.2)]})
    assert fails == [] and lines == ["clear_under R1 (+0.2 mm): clear"]


def test_tracks_under_the_crystal_fail(tmp_path):
    fails = apart_check(_board(tmp_path, STM), {"clear_under": [("Y1", 0.2)]})[1]
    assert fails == ["PA1, PA2, PA4, PC15 run under Y1 (courtyard + 0.2 mm)"]


def test_a_part_with_no_courtyard_cannot_judge(tmp_path):
    strip = lambda blk: re.sub(r'\n\t\t\(fp_(?:line|rect|poly|circle)(?:(?!\n\t\t\().)*?\(layer "F\.CrtYd"\).*?\n\t\t\)', "", blk, flags=re.S)  # noqa: E731
    b = _board(tmp_path, STM, lambda t: _fp(t, "Y1", strip))
    assert apart_check(b, {"clear_under": [("Y1", 0.2)]})[1] == ["clear_under Y1: cannot judge, no courtyard"]


def test_review_runs_both_keys(tmp_path):
    b = _board(tmp_path, BUCK)
    fails = review(b.path, SimpleNamespace(REVIEW={"apart": [("FB", "SW", 1.2)], "clear_under": [("U1", 99)]}))
    assert any(f.startswith("FB comes within 1.00 mm of SW") for f in fails)
    assert any(f.endswith("under U1 (courtyard + 99 mm)") for f in fails)


def test_two_pads_of_one_part_are_left_out(tmp_path):
    """PA1 stripped to its pad: its nearest PA2 copper is PA2's track at 0.25 mm,
    not PA2's pad beside it on U1 at 0.20 mm, which the pinout fixes."""
    from test_loop import _no_tracks

    def edit(t):
        t = _no_tracks("PA1")(t)
        return re.sub(r'\n\t\(via(?:(?!\n\t\().)*?\(net "PA1"\).*?\n\t\)', "", t, flags=re.S)
    lines = apart_check(_board(tmp_path, STM, edit), {"apart": [("PA1", "PA2", 0)]})[0]
    assert lines == ["apart PA1 | PA2: 0.25 mm (PA1 to PA2, F.Cu) (>= 0)"]


def test_ground_under_a_part_is_allowed(tmp_path):
    """A GND track crosses SW1's courtyard; it is not listed."""
    assert apart_check(_board(tmp_path, STM), {"clear_under": [("SW1", 0.3)]})[0] == [
        "clear_under SW1 (+0.3 mm): NRST, PC13, PC14, PC15, VBUS"]


def test_another_parts_pads_under_are_not_tracks(tmp_path):
    """C3 sits on the back under U1: U1's PB12 and PB13 pads are inside its
    courtyard, and are the IC it decouples; only the PB14 track counts."""
    assert apart_check(_board(tmp_path, STM), {"clear_under": [("C3", 0.2)]})[0] == ["clear_under C3 (+0.2 mm): PB14"]
