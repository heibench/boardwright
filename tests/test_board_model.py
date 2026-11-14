import types

import pytest
from conftest import BOARDS, board

from boardwright.model import Board
from boardwright.preview import ratsnest
from boardwright.review import review, via_current, width_for_current

EXAMPLES = sorted(p.name for p in BOARDS.iterdir() if (p / f"{p.name}.kicad_pcb").exists())


def test_examples_present():
    assert "ldo_breakout" in EXAMPLES and "stm32f103_4l" in EXAMPLES


@pytest.mark.parametrize("name", EXAMPLES)
def test_every_example_is_fully_routed(name):
    b = Board(board(name))
    assert b.pads and b.tracks
    poured = {z.net for z in b.zones}
    assert ratsnest(b, poured) == []


@pytest.mark.parametrize("name", EXAMPLES)
def test_generic_review_passes_on_every_example(name):
    assert review(board(name), types.SimpleNamespace()) == []


def test_layers_and_pads():
    b = Board(board("stm32f103_4l"))
    assert b.layers == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    u1 = [p for p in b.pads if p.ref == "U1"]
    assert len(u1) == 48
    b2 = Board(board("ldo_breakout"))
    assert b2.layers == ["F.Cu", "B.Cu"]
    assert {p.net for p in b2.pads} >= {"VIN", "GND", "+3V3", "LED_A"}


def test_route_path_length_is_positive_and_bounded():
    b = Board(board("ldo_breakout"))
    lengths = b.net_lengths()
    assert lengths["LED_A"] > 0
    x0, y0, x1, y1 = b.bbox
    assert lengths["LED_A"] < 2 * ((x1 - x0) + (y1 - y0))


def test_review_flags_a_path_over_its_limit():
    spec = types.SimpleNamespace(REVIEW={"maxlen": {"LED_A": 0.1}})
    fails = review(board("ldo_breakout"), spec)
    assert any("LED_A" in f for f in fails)


def test_current_rules_of_thumb():
    # IPC-2221 external layer, 1 oz, 10 C rise: 1 A needs roughly 0.3 mm
    assert 0.2 < width_for_current(1.0) < 0.45
    assert width_for_current(2.0) > width_for_current(1.0)
    assert width_for_current(1.0, inner=True) > width_for_current(1.0)
    assert via_current(0.3) > via_current(0.2) > 0
