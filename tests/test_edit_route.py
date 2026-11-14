import types

import pytest
from conftest import board

from boardwright import copper
from boardwright.edits import describe, from_spec
from boardwright.model import Board
from boardwright.preview import ratsnest
from boardwright.route import route


def ripped(ldo_copy, nets):
    pcb = ldo_copy / "ldo_breakout.kicad_pcb"
    text, n = copper.ripup(pcb.read_text(), set(nets))
    pcb.write_text(text)
    return pcb, n


def test_ripup_opens_only_the_named_net(ldo_copy):
    pcb, n = ripped(ldo_copy, ["LED_A"])
    assert n > 0
    opened = {net for *_p, net in ratsnest(Board(pcb), {"GND"})}
    assert opened == {"LED_A"}


def test_router_reconnects_a_ripped_net(ldo_copy):
    pcb, _ = ripped(ldo_copy, ["LED_A"])
    b = Board(pcb)
    r = route(b, "R1.2", "D1.2", width=0.25, clearance=0.2)
    assert r, "no route found"
    assert r.length > 0
    assert all(net == "LED_A" for net, *_ in r.tracks)


def test_crossing_hand_tracks_are_refused():
    m = types.SimpleNamespace(TRACKS=[
        ("A", [(0, 0), (10, 10)], 0.25, "F.Cu"),
        ("B", [(0, 10), (10, 0)], 0.25, "F.Cu"),
    ])
    with pytest.raises(ValueError, match="crosses"):
        copper.check_tracks(m)
    m.TRACKS[1] = ("B", [(0, 10), (10, 0)], 0.25, "B.Cu")
    copper.check_tracks(m)


def test_edit_list_in_absolute_coordinates():
    b = Board(board("ldo_breakout"))
    ox, oy = b.origin
    m = types.SimpleNamespace(MOVE={"R1": (12, 15, 90)}, VIAS=[("GND", 5, 5)])
    doc = from_spec(m, b)
    move = doc["ops"][0]
    assert move == {"op": "move_footprint", "ref": "R1", "x": round(12 + ox, 4), "y": round(15 + oy, 4), "rotation": 90}
    assert doc["ops"][1]["op"] == "add_via"
    assert describe(doc)


def test_edit_list_rejects_unknown_names():
    b = Board(board("ldo_breakout"))
    with pytest.raises(SystemExit, match="no footprint"):
        from_spec(types.SimpleNamespace(MOVE={"R99": (1, 1)}), b)
    with pytest.raises(SystemExit, match="no net"):
        from_spec(types.SimpleNamespace(VIAS=[("NOPE", 1, 1)]), b)
