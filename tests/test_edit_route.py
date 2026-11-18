import itertools
import math
import types

import pytest
from conftest import board

from boardwright import copper
from boardwright.edits import describe, from_spec
from boardwright.model import Board
from boardwright.preview import ratsnest
from boardwright.route import route, route_all


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


@pytest.mark.parametrize("routes", [
    [("R9.1", "J3.1"), ("R9.1", "J2.1")],
    [("R8.1", "J3.1"), ("R8.1", "J2.1")],
    [("C2.1", "J3.1"), ("C2.1", "J2.18")],
    [("R5.1", "J2.1"), ("R5.1", "J3.1")],
])
def test_routes_from_one_pad_share_a_via(routes):
    """Two +3V3 routes from one SMD pad on the four-layer example both change layer
    near it. The second reuses the first one's via instead of stacking its own
    (it used to put a second via 0 to 0.3 mm away: KiCad's hole_to_hole), so no
    hole comes nearer another than the project's min_hole_to_hole (0.25 mm)."""
    from boardwright.route import defaults_for

    b = Board(board("stm32f103_4l"))
    o = defaults_for(b, None, "+3V3")
    tracks, vias, failed = route_all(b, [(a, c, o) for a, c in routes])
    assert not failed and len(vias) == 1
    drill = {(fp.reference, str(q.number)): q.drill for fp in b.footprints for q in fp.pads if q.drill}
    holes = [(v.x, v.y, v.drill) for v in b.vias] + [(p.x, p.y, drill[(p.ref, p.num)]) for p in b.pads if (p.ref, p.num) in drill]
    holes += [(v[1], v[2], v[4]) for v in vias]
    gaps = [math.dist(a[:2], c[:2]) - a[2] / 2 - c[2] / 2 for a, c in itertools.combinations(holes, 2)]
    assert min(gaps) >= 0.25 - 1e-6
