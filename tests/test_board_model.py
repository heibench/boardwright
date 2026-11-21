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


def _pad(x, y, size=1.0):
    from boardwright.model import Pad

    return Pad("U1", "1", "N", x, y, "F.Cu", size, size, 0.0, False, ["F.Cu"])


@pytest.mark.parametrize("bridge", [0.3, 0.8, 1.5])
def test_neck_measures_the_narrowest_channel(bridge):
    from boardwright.review import neck

    # two 5 mm squares joined by a 2 mm long bridge `bridge` wide
    y0, y1 = 2.5 - bridge / 2, 2.5 + bridge / 2
    poly = [(0, 0), (5, 0), (5, y0), (7, y0), (7, 0), (12, 0), (12, 5), (7, 5), (7, y1), (5, y1), (5, 5), (0, 5)]
    assert neck(poly, _pad(2.5, 2.5), _pad(9.5, 2.5), cap=4.0) == pytest.approx(bridge, abs=0.01)


def test_neck_reports_the_cap_when_wider():
    from boardwright.review import neck

    poly = [(0, 0), (12, 0), (12, 5), (0, 5)]
    assert neck(poly, _pad(2.5, 2.5), _pad(9.5, 2.5), cap=1.0) == 1.0


def test_current_review_fails_a_necked_pour():
    """The buck board's SW pour narrows to about 0.80 mm; asking for more current
    than that carries must fail even though the pour is one piece."""
    spec = types.SimpleNamespace(REVIEW={"current": [("U1.2", "L1.1", 3.0)]})
    fails = review(board("tps54202_buck"), spec)
    assert any("narrows to" in f for f in fails), fails


def test_preview_stays_svg_without_rsvg_convert(tmp_path, monkeypatch, capsys):
    """`doctor` says previews stay SVG without rsvg-convert; the preview must not crash."""
    from conftest import board

    from boardwright import preview

    monkeypatch.setenv("PATH", str(tmp_path))                 # nothing on PATH
    assert preview.write(board("ldo_breakout"), tmp_path / "p.png") == 0
    assert (tmp_path / "p.svg").exists() and not (tmp_path / "p.png").exists()
    assert "preview: " + str(tmp_path / "p.svg") in capsys.readouterr().out


def test_route_path_on_a_net_with_a_through_hole_pad():
    """A through-hole pad is on every layer, so it was once compared with the
    pad nodes already in the graph, and route_path raised TypeError."""
    b = Board(board("stm32f103_min"))
    assert b.pad("J4.4").thru and b.pad("J4.4").net == "GND"
    r = b.route_path("C3.2", "J4.4")
    assert r is None or r[0] > 0
