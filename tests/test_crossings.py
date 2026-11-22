"""Airwire crossings for a placement (#149), on copies of rp2040_min, whose
LED chain runs U1.37 -> R9 -> D2.2 on nets GPIO25 and LED_25."""

import re

from conftest import BOARDS
from test_placement_review import _fp

from boardwright.model import Board
from boardwright.placement_review import placement_review
from boardwright.preview import crossings

RP = BOARDS / "rp2040_min" / "rp2040_min.kicad_pcb"
LED = {"crossings": [(["GPIO25", "LED_25"], 0)]}


def _board(tmp_path, edit=None):
    pcb = tmp_path / RP.name
    t = RP.read_text()
    pcb.write_text(edit(t) if edit else t)
    return Board(pcb)


def _turn(ref):
    def turn(blk):
        return re.sub(r"(\n\t\t\(at )([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)",
                      lambda m: f"{m.group(1)}{m.group(2)} {m.group(3)} {(float(m.group(4) or 0) + 180) % 360:g})",
                      blk, count=1)
    return lambda t: _fp(t, ref, turn)


def _no_copper(t):
    return re.sub(r'\n\t\((?:segment|arc|via)(?:(?!\n\t\().)*?\n\t\)', "", t, flags=re.S)


def test_the_named_nets_crossings_are_counted(tmp_path):
    lines, fails = placement_review(_board(tmp_path), LED)
    assert lines == ["crossings GPIO25/LED_25: 7 (<= 0)"]
    assert len(fails) == 1 and fails[0].startswith("GPIO25/LED_25: 7 airwire crossings, limit 0: ")


def test_a_part_turned_round_crosses_more(tmp_path):
    """R9 turned 180 degrees: its two nets now loop past each other's neighbours."""
    assert placement_review(_board(tmp_path, _turn("R9")), LED)[0] == ["crossings GPIO25/LED_25: 11 (<= 0)"]


def test_the_count_is_the_placements_not_the_routings(tmp_path):
    b = _board(tmp_path, _no_copper)
    assert not b.tracks and not b.vias
    assert placement_review(b, LED)[0] == ["crossings GPIO25/LED_25: 7 (<= 0)"]


def test_within_the_limit_passes(tmp_path):
    assert placement_review(_board(tmp_path), {"crossings": [(["GPIO25", "LED_25"], 7)]})[1] == []


def test_wires_meeting_at_a_pad_do_not_cross(tmp_path):
    """Every net's tree meets other nets only at shared ends here: two
    two-pad nets that share no pad position and lie apart cross nowhere."""
    b = _board(tmp_path)
    found = crossings(b, set())
    assert all(x != y for x, y, _at in found)
    pads = {(round(p.x, 6), round(p.y, 6)) for p in b.pads}
    assert all((round(px, 6), round(py, 6)) not in pads for _x, _y, (px, py) in found)


def test_poured_and_ground_nets_cannot_be_judged(tmp_path):
    fails = placement_review(_board(tmp_path), {"crossings": [("GND", 0), ("NOPE", 0)]})[1]
    assert fails == ["crossings GND: cannot judge, no named net with two or more pads outside the pours",
                     "crossings NOPE: cannot judge, no named net with two or more pads outside the pours"]


def test_ground_is_left_out_of_the_count(tmp_path):
    b = _board(tmp_path)
    assert all("GND" not in (x, y) for x, y, _at in crossings(b, {"GND"}))
    assert any("GND" in (x, y) for x, y, _at in crossings(b, set()))


def test_ground_is_left_out_even_when_unpoured(tmp_path):
    """With the pours removed, GND is no longer skipped as a pour; the review
    still leaves it out as ground. VBUS crosses GND's tree 8 times there, so
    counting ground would give 16, not 8."""
    from boardwright import copper

    def no_zones(t):
        for s, e in reversed(copper.blocks(t, ("zone",))):
            t = t[:s] + t[e:]
        return t
    b = _board(tmp_path, no_zones)
    assert not b.zones
    assert placement_review(b, {"crossings": [("VBUS", 99)]})[0] == ["crossings VBUS: 8 (<= 99)"]

