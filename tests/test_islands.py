"""REVIEW "islands": pour pieces cut off from the rest of their net (#150).
rp2040_min's F.Cu GND pour has a pocket around D2.1 that reaches the net only
through D2.1's thermal spokes; the origin of its file coordinates is (118.5, 82)."""

from types import SimpleNamespace

from conftest import BOARDS

from boardwright.islands import islands_check
from boardwright.model import Board
from boardwright.review import review

RP = BOARDS / "rp2040_min" / "rp2040_min.kicad_pcb"
LDO = BOARDS / "ldo_breakout" / "ldo_breakout.kicad_pcb"
BUCK = BOARDS / "tps54202_buck" / "tps54202_buck.kicad_pcb"
D2 = "GND island on F.Cu (45.8, 34.7, 48.2, 35.8), 1.58 mm2 reaches the net only through D2.1: a via at (47.02, 35.21) joins it to B.Cu"


def _board(tmp_path, src, add=""):
    pcb = tmp_path / src.name
    t = src.read_text()
    end = t.rstrip().rfind(")")
    pcb.write_text(t[:end] + add + t[end:])
    pcb.with_suffix(".kicad_pro").write_text(src.with_suffix(".kicad_pro").read_text())   # its net classes size the via
    return Board(pcb)


def _via(x, y):
    """A GND via at board (x, y)."""
    return (f'\t(via\n\t\t(at {x + 118.5:g} {y + 82:g})\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n'
            f'\t\t(net "GND")\n\t\t(uuid "00000000-0000-0000-0000-000000000300")\n\t)\n')


def test_an_island_is_named_with_a_via_spot(tmp_path):
    lines, fails = islands_check(_board(tmp_path, RP), {"islands": ["GND"]})
    assert D2 in fails
    assert lines[0] == "islands GND: 4"


def test_a_sliver_too_small_for_a_via_is_reported_not_failed(tmp_path):
    lines, fails = islands_check(_board(tmp_path, RP), {"islands": ["GND"]})
    assert "  GND sliver on B.Cu (33.0, 5.8, 33.9, 6.4), 0.4 mm2 through J1.SH: no room for a via" in lines
    assert not any("J1.SH" in f for f in fails)


def test_a_via_at_the_spot_joins_the_island(tmp_path):
    fails = islands_check(_board(tmp_path, RP, _via(47.02, 35.21)), {"islands": ["GND"]})[1]
    assert D2 not in fails and not any("D2.1" in f for f in fails)


def _zone(layer, x0, y0, x1, y1, n):
    """A filled GND zone, a rectangle in board coordinates, on layer."""
    pts = f"(pts (xy {x0 + 118.5:g} {y0 + 82:g}) (xy {x1 + 118.5:g} {y0 + 82:g}) (xy {x1 + 118.5:g} {y1 + 82:g}) (xy {x0 + 118.5:g} {y1 + 82:g}))"
    return (f'\t(zone (net "GND") (layer "{layer}") (uuid "00000000-0000-0000-0000-00000000040{n}") (hatch edge 0.5) '
            f'(connect_pads (clearance 0.3)) (min_thickness 0.25) (fill yes) (polygon {pts}) '
            f'(filled_polygon (layer "{layer}") {pts}))\n')


def _own_pours(tmp_path, *add):
    """rp2040_min with its GND zones replaced by the zones given."""
    from boardwright import copper
    pcb = tmp_path / RP.name
    t = RP.read_text()
    for s0, e0 in reversed(copper.blocks(t, ("zone",))):
        if t[s0:s0 + 3] == "\n\t(" and '(net "GND")' in t[s0:e0]:
            t = t[:s0] + t[e0:]
    end = t.rstrip().rfind(")")
    pcb.write_text(t[:end] + "".join(add) + t[end:])
    pcb.with_suffix(".kicad_pro").write_text(RP.with_suffix(".kicad_pro").read_text())
    return Board(pcb)


# a 2 x 2 mm F.Cu square at the board's top-left corner, clear of every pad,
# and a B.Cu square far from it, so that GND is poured on two layers
SQUARE, FAR = _zone("F.Cu", 1.5, 2, 3.5, 4, 1), _zone("B.Cu", 40, 40, 42, 42, 2)


def test_a_piece_with_no_pad_is_dead_copper_with_a_via_spot(tmp_path):
    fails = islands_check(_own_pours(tmp_path, SQUARE, FAR), {"islands": ["GND"]})[1]
    assert ("GND island on F.Cu (1.5, 2.0, 3.5, 4.0), 4.0 mm2 connects to nothing: dead copper; a via at "
            "(2.5, 3.0) joins it, but no other layer has its fill there") in fails


def test_a_via_over_fill_on_the_far_side_joins_dead_copper(tmp_path):
    under = _zone("B.Cu", 1, 1.5, 4, 4.5, 3)
    b = _own_pours(tmp_path, SQUARE, FAR, under)
    assert any("dead copper; a via at (2.5, 3.0) joins it to B.Cu" in f for f in islands_check(b, {"islands": ["GND"]})[1])
    b = _own_pours(tmp_path, SQUARE, FAR, under, _via(2.5, 3.0))
    assert not any("(1.5, 2.0, 3.5, 4.0)" in f for f in islands_check(b, {"islands": ["GND"]})[1])


def test_a_via_over_no_fill_on_the_far_side_joins_nothing(tmp_path):
    """A via spans both layers but reaches only copper it touches: with no B.Cu
    fill under it, the square is still dead copper (#170)."""
    b = _own_pours(tmp_path, SQUARE, FAR, _via(2.5, 3.0))
    assert any("(1.5, 2.0, 3.5, 4.0), 4.0 mm2 connects to nothing" in f for f in islands_check(b, {"islands": ["GND"]})[1])


def test_pours_tied_at_two_or_more_pads_are_not_islands(tmp_path):
    """The LDO example's GND pours meet only at the connectors' through-hole pins."""
    assert islands_check(_board(tmp_path, LDO), {"islands": ["GND"]}) == (["islands GND: 0"], [])


def test_a_net_poured_on_one_layer_cannot_be_judged(tmp_path):
    fails = islands_check(_board(tmp_path, BUCK), {"islands": ["SW"]})[1]
    assert fails == ["islands SW: cannot judge, SW is not poured on two or more layers"]


def test_review_runs_the_islands_check(tmp_path):
    b = _board(tmp_path, RP)
    fails = review(b.path, SimpleNamespace(REVIEW={"islands": ["GND"]}))
    assert D2 in fails


def test_stitching_vias_in_their_reliefs_join_their_pieces(tmp_path):
    """stm32f103_min's pours are held by stitching vias that sit in thermal-relief
    cut-outs, not touching the fill: across that gap they still join."""
    src = BOARDS / "stm32f103_min" / "stm32f103_min.kicad_pcb"
    assert islands_check(_board(tmp_path, src), {"islands": ["GND"]}) == (["islands GND: 0"], [])


def test_overlapping_fills_of_the_net_are_one_copper(tmp_path):
    """A second F.Cu GND fill overlapping the square, tied to a B.Cu fill by a
    via: through the overlap, the square is no longer dead."""
    over = _zone("F.Cu", 3, 2.5, 7, 3.5, 4)
    under = _zone("B.Cu", 5, 2, 7, 4, 5)
    b = _own_pours(tmp_path, SQUARE, FAR, over, under, _via(6.0, 3.0))
    assert not any("(1.5, 2.0, 3.5, 4.0)" in f for f in islands_check(b, {"islands": ["GND"]})[1])

