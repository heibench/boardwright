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


def test_footprint_zone_is_put_back_on_its_footprint(tmp_path):
    import re
    import shutil

    from conftest import BOARDS

    from boardwright.board import place_footprint_zones
    from boardwright.copper import blocks

    d = tmp_path / "esp32c3_min"
    shutil.copytree(BOARDS / "esp32c3_min", d)
    pcb = d / "esp32c3_min.kicad_pcb"
    t = pcb.read_text()
    fs, fe = next((s, e) for s, e in blocks(t, ("footprint",)) if '"RF_Module:ESP32-C3-WROOM-02"' in t[s:s + 200])
    fp = t[fs:fe]
    zs, ze = blocks(fp, ("zone",))[0]
    shifted = re.sub(r"\(xy ([-\d.]+) ([-\d.]+)\)", lambda m: f"(xy {float(m.group(1)) + 10:g} {m.group(2)})", fp[zs:ze])
    pcb.write_text(t[:fs] + fp[:zs] + shifted + fp[ze:] + t[fe:])

    assert place_footprint_zones(pcb, d) == 1
    t = pcb.read_text()
    fp = next(t[s:e] for s, e in blocks(t, ("footprint",)) if '"RF_Module:ESP32-C3-WROOM-02"' in t[s:s + 200])
    fx, fy = map(float, re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)", fp).groups())
    got = [(float(x), float(y)) for x, y in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", fp[slice(*blocks(fp, ("zone",))[0])])]
    lib = (d / "libs/RF_Module.pretty/ESP32-C3-WROOM-02.kicad_mod").read_text()
    want = [(float(x) + fx, float(y) + fy) for x, y in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", lib[slice(*blocks(lib, ("zone",))[0])])]
    assert [c for p in got for c in p] == pytest.approx([c for p in want for c in p])
