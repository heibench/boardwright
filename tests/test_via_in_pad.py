"""REVIEW "via_in_pad": vias standing in, or on the edge of, an SMD pad (#177),
on copies of rp2040_min, whose file coordinates have their origin at (118.5, 82).
R9.1 (GPIO25) is a 0.54 x 0.64 mm pad at (162.99, 117.0); U1.57 (GND) is the
RP2040's 3.2 mm exposed pad at (148.5, 106.0); J4.3 (GND) is a through-hole pin
at (122.0, 115.08)."""

from types import SimpleNamespace

from conftest import BOARDS

from boardwright.model import Board
from boardwright.review import review
from boardwright.via_in_pad import via_in_pad_check

RP = BOARDS / "rp2040_min" / "rp2040_min.kicad_pcb"


def _via(x, y, net, n=0):
    return (f'\t(via\n\t\t(at {x:g} {y:g})\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n'
            f'\t\t(net "{net}")\n\t\t(uuid "00000000-0000-0000-0000-00000000060{n}")\n\t)\n')


def _part(ref, pads, net_tie=False):
    """A footprint at (125, 90) with pads given as (number, dx, net)."""
    tie = '\t\t(net_tie_pad_groups "1, 2")\n' if net_tie else ""
    body = "".join(f'\t\t(pad "{num}" smd rect (at {dx:g} 0) (size 1.5 1.5) (layers "F.Cu" "F.Mask") (net "{net}") '
                   f'(uuid "00000000-0000-0000-0000-0000000007{i}{num}"))\n' for i, (num, dx, net) in enumerate(pads))
    return (f'\t(footprint "Test:{ref}" (layer "F.Cu") (uuid "00000000-0000-0000-0000-000000000700") (at 125 90)\n'
            f'\t\t(property "Reference" "{ref}" (at 0 0 0) (layer "F.SilkS") (uuid "00000000-0000-0000-0000-000000000701"))\n'
            f'{tie}{body}\t)\n')


def _check(tmp_path, *add, nets=("*",)):
    pcb = tmp_path / RP.name
    t = RP.read_text()
    end = t.rstrip().rfind(")")
    pcb.write_text(t[:end] + "".join(add) + t[end:])
    return via_in_pad_check(Board(pcb), {"via_in_pad": list(nets)})


def test_the_example_has_none(tmp_path):
    assert _check(tmp_path) == (["via_in_pad 59 net(s): 0 via(s) in or on an SMD pad"], [])


def test_a_via_in_a_passive_pad_is_named(tmp_path):
    fails = _check(tmp_path, _via(162.99, 117.0, "GPIO25"))[1]
    assert fails == ["via at (44.49, 35.00) on GPIO25 stands in R9.1 (0.54 x 0.64 mm)"]


def test_a_via_over_a_pad_edge_is_named_with_the_overlap(tmp_path):
    """R9.1's west edge is at x 162.72; a 0.6 mm via 0.2 mm west of it overlaps by 0.1."""
    fails = _check(tmp_path, _via(162.52, 117.0, "GPIO25"))[1]
    assert fails == ["via at (44.02, 35.00) on GPIO25 overlaps the edge of R9.1 by 0.10 mm"]


def test_a_via_in_an_exposed_pad_is_not_named(tmp_path):
    assert _check(tmp_path, _via(148.5, 106.0, "GND"))[1] == []


def test_a_via_in_a_footprints_only_pad_is_not_named(tmp_path):
    assert _check(tmp_path, _part("HS9", [("1", 0, "GND")]), _via(125, 90, "GND"))[1] == []


def test_a_via_in_a_net_tie_is_not_named(tmp_path):
    pads = [("1", 0, "GND"), ("2", 1.6, "+3V3")]
    assert _check(tmp_path, _part("NT9", pads, net_tie=True), _via(125, 90, "GND"))[1] == []
    fails = _check(tmp_path, _part("NT9", pads), _via(125, 90, "GND"))[1]
    assert fails == ["via at (6.50, 8.00) on GND stands in NT9.1 (1.50 x 1.50 mm)"]


def test_a_through_hole_pin_is_not_named(tmp_path):
    assert _check(tmp_path, _via(122.0, 115.08, "GND"))[1] == []


def test_only_named_nets_are_judged(tmp_path):
    assert _check(tmp_path, _via(162.99, 117.0, "GPIO25"), nets=("GND",))[1] == []


def test_an_unknown_net_fails(tmp_path):
    assert _check(tmp_path, nets=("NOPE",))[1] == ["via_in_pad NOPE: no such net"]


def test_review_runs_the_via_in_pad_check(tmp_path):
    pcb = tmp_path / RP.name
    t = RP.read_text()
    end = t.rstrip().rfind(")")
    pcb.write_text(t[:end] + _via(162.99, 117.0, "GPIO25") + t[end:])
    fails = review(pcb, SimpleNamespace(REVIEW={"via_in_pad": ["GPIO25"]}))
    assert "via at (44.49, 35.00) on GPIO25 stands in R9.1 (0.54 x 0.64 mm)" in fails
