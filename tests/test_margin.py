"""REVIEW "margin": copper within a margin of the clearance rule (#176).

Most cases use a small board built in memory, with no project file, so every
net's clearance is the 0.2 mm default and each gap is exact."""

import math
from pathlib import Path
from types import SimpleNamespace

from conftest import BOARDS

from boardwright.margin import margin_check
from boardwright.model import Board, Pad, Track
from boardwright.review import review


def _board(pads=(), tracks=()):
    return SimpleNamespace(pads=list(pads), tracks=list(tracks), vias=[], layers=["F.Cu", "B.Cu"],
                           path=Path("/nonexistent/board.kicad_pcb"))


def _track(net, a, b, w=0.2):
    return Track([a, b], w, "F.Cu", net)


def _pad(ref, num, net, x, y, w, h, shape="rect", rratio=0.0):
    return Pad(ref, num, net, x, y, "F.Cu", w, h, 0, False, ["F.Cu"], shape, rratio)


PARALLEL = [_track("A", (0, 0), (10, 0)), _track("B", (0, 0.41), (10, 0.41))]     # edges 0.21 mm apart


def test_two_tracks_closer_than_rule_plus_margin_fail_once(tmp_path):
    lines, fails = margin_check(_board(tracks=PARALLEL), {"margin": [("A", 0.05)]})
    assert lines == ["margin 1 net(s), rule + 0.05 mm: 1 pair(s) closer"]
    assert fails == ["A within 0.210 mm of B (rule 0.2) on F.Cu near (5.00, 0.31), 10.00 mm of track that close"]


def test_a_gap_that_meets_rule_plus_margin_passes():
    assert margin_check(_board(tracks=PARALLEL), {"margin": [("A", 0.005)]}) == (
        ["margin 1 net(s), rule + 0.005 mm: 0 pair(s) closer"], [])


def test_a_pair_takes_the_larger_clearance_of_its_two_nets(tmp_path):
    """W is in a 0.5 mm class: A at 0.3 mm from it fails against 0.5, and the
    wider search W needs does not make A and B, 0.21 mm apart, fail at 0.005."""
    import json
    pro = tmp_path / "board.kicad_pro"
    pro.write_text(json.dumps({"net_settings": {
        "classes": [{"name": "Default", "clearance": 0.2}, {"name": "Wide", "clearance": 0.5}],
        "netclass_assignments": {"W": "Wide"}}}))
    b = _board(tracks=PARALLEL + [_track("W", (0, -0.5), (10, -0.5))])
    b.path = tmp_path / "board.kicad_pcb"
    fails = margin_check(b, {"margin": [("A", 0.005)]})[1]
    assert fails == ["A within 0.300 mm of W (rule 0.5) on F.Cu near (5.00, -0.40), 10.00 mm of track that close"]


def test_only_pairs_with_a_named_net_are_judged():
    tracks = PARALLEL + [_track("C", (0, 5), (10, 5)), _track("D", (0, 5.41), (10, 5.41))]
    fails = margin_check(_board(tracks=tracks), {"margin": [("A", 0.05)]})[1]
    assert len(fails) == 1 and fails[0].startswith("A within")


def test_a_rounded_pad_corner_is_measured_round():
    """A track passes a 1 x 1 mm pad's corner 0.22 mm from where a square
    corner would be. The pad's corners are rounded (radius 0.25), so the real
    gap is 0.22 + 0.25 * (sqrt 2 - 1) = 0.324 mm, over rule + 0.05."""
    off = (0.22 + 0.1) / math.sqrt(2)               # the track's centreline, out along the corner's diagonal
    cx, cy = 0.5 + off, -0.5 - off
    track = _track("T", (cx - 2, cy - 2), (cx + 2, cy + 2))
    rounded = _pad("U1", "1", "P", 0, 0, 1, 1, "roundrect", 0.25)
    assert margin_check(_board([rounded], [track]), {"margin": [("T", 0.05)]})[1] == []
    square = _pad("U1", "1", "P", 0, 0, 1, 1)
    assert margin_check(_board([square], [track]), {"margin": [("T", 0.05)]})[1][0].startswith("T within 0.220 mm of P")


J1 = [_pad("J1", "1", "X", 0, 0, 1.9, 1.0), _pad("J1", "2", "Y", 2.54, 0, 1.9, 1.0)]     # edges at 0.95 and 1.59
# A track at x 1.27 is within rule + 0.05 + its half-width (0.35 mm) of each pad
# over the pad's 1.0 mm side and 0.14 mm past each corner: 1.28 mm.


def test_a_tight_track_between_two_pads_of_a_part_is_a_squeeze():
    fails = margin_check(_board(J1, [_track("T", (1.27, -2), (1.27, 2))]), {"margin": [("T", 0.05)]})[1]
    assert fails == ["T within 0.220 mm of X (rule 0.2) on F.Cu near (0.95, 0.00), 1.28 mm of track that close, "
                     "squeezed between J1.1/2",
                     "T within 0.220 mm of Y (rule 0.2) on F.Cu near (1.59, 0.00), 1.28 mm of track that close, "
                     "squeezed between J1.2/1"]


def test_a_track_leaving_its_own_pad_is_not_squeezed():
    fails = margin_check(_board(J1, [_track("X", (0, 0), (1.27, 0)), _track("X", (1.27, 0), (1.27, 2))]),
                         {"margin": [("X", 0.05)]})[1]
    assert fails and not any("squeezed" in f for f in fails)


def test_pads_with_another_pad_between_are_not_neighbours():
    """J1.1 and J1.3 are 2.5 mm apart, but J1.2 sits between them: a track
    between J1.2 and J1.3 is squeezed between those two only."""
    pads = [_pad("J1", "1", "X", 0, 0, 0.6, 1.0), _pad("J1", "2", "Z", 1.25, 0, 0.6, 1.0),
            _pad("J1", "3", "Y", 2.5, 0, 0.6, 1.0)]
    fails = margin_check(_board(pads, [_track("T", (1.875, -2), (1.875, 2))]), {"margin": [("T", 0.2)]})[1]
    assert fails and all("J1.1" not in f and "/1" not in f for f in fails)


def test_two_pads_close_together_are_not_measured():
    pads = [_pad("R1", "1", "A", 0, 0, 1, 1), _pad("R2", "1", "B", 1.1, 0, 1, 1)]    # 0.1 mm apart
    assert margin_check(_board(pads), {"margin": [("A", 0.05)]})[1] == []


def test_an_unknown_net_fails():
    assert margin_check(_board(tracks=PARALLEL), {"margin": [("NOPE", 0.05)]})[1] == ["margin NOPE: no such net"]


LDO = BOARDS / "ldo_breakout" / "ldo_breakout.kicad_pcb"


def test_an_example_reports_the_pairs_at_its_rule():
    """ldo_breakout's project sets a 0.2 mm clearance; Freerouting packed two
    pairs just over it."""
    b = Board(LDO)
    assert margin_check(b, {"margin": [("*", 0.001)]})[1] == []
    assert margin_check(b, {"margin": [("*", 0.05)]})[1] == [
        "VIN within 0.202 mm of GND (rule 0.2) on F.Cu near (9.20, 8.68), 3.33 mm of track that close",
        "GND within 0.232 mm of +3V3 (rule 0.2) on F.Cu near (14.31, 6.02), 1.08 mm of track that close"]


def test_review_runs_the_margin_check(tmp_path):
    pcb = tmp_path / LDO.name
    pcb.write_text(LDO.read_text())
    (tmp_path / "ldo_breakout.kicad_pro").write_text(LDO.with_suffix(".kicad_pro").read_text())
    fails = review(pcb, SimpleNamespace(REVIEW={"margin": [("VIN", 0.05)]}))
    assert any(f.startswith("VIN within 0.202 mm of GND") for f in fails)
