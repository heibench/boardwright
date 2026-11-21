"""The placement checks REVIEW runs before routing (#47). Each has three boards,
edited from an example: one that passes, one that fails with the named
finding, and one with the mechanism the check reads removed, which must fail
("cannot judge") rather than pass on nothing."""

import re

import pytest
from conftest import BOARDS

from boardwright import copper
from boardwright.model import Board
from boardwright.placement_review import placement_review

STM = BOARDS / "stm32f103_min" / "stm32f103_min.kicad_pcb"
LDO = BOARDS / "ldo_breakout" / "ldo_breakout.kicad_pcb"


def _board(tmp_path, src, edit=None):
    d = tmp_path / src.parent.name
    d.mkdir()
    pcb, pro = d / src.name, d / src.with_suffix(".kicad_pro").name
    text = src.read_text()
    pcb.write_text(edit(text) if edit else text)
    pro.write_text(src.with_suffix(".kicad_pro").read_text())
    return Board(pcb)


def _fp(text, ref, fn):
    """text with footprint `ref`'s block replaced by fn(block)."""
    for s, e in copper.blocks(text, ("footprint",)):
        if f'(property "Reference" "{ref}"' in text[s:e]:
            return text[:s] + fn(text[s:e]) + text[e:]
    raise AssertionError(f"no footprint {ref}")


def _pad_net(block, num, net):
    i = block.index(f'(pad "{num}"')
    j = block.index("(net ", i)
    k = block.index(")", j)
    return block[:j] + f'(net "{net}"' + block[k:]


def _swap_nets(block, a, b):
    na = re.search(r'\(net "([^"]*)"', block[block.index(f'(pad "{a}"'):]).group(1)
    nb = re.search(r'\(net "([^"]*)"', block[block.index(f'(pad "{b}"'):]).group(1)
    return _pad_net(_pad_net(block, a, nb), b, na)


def _move(block, dx, dy):
    return re.sub(r"(\n\t\t\(at )([-\d.]+) ([-\d.]+)",
                  lambda m: f"{m.group(1)}{float(m.group(2)) + dx:g} {float(m.group(3)) + dy:g}", block, count=1)


def _strip_nets(block):
    return re.sub(r'\n\t\t\t\(net "[^"]*"\)', "", block)


def _run(b, spec):
    return placement_review(b, spec)


# orient: C5 decouples U1.1

ORIENT = {"orient": [("C5", "U1.1")]}


def test_orient_passes_a_decoupler_facing_its_pin(tmp_path):
    lines, fails = _run(_board(tmp_path, STM), ORIENT)
    assert fails == [] and "orient C5 -> U1.1" in lines[0]


def test_orient_finds_a_decoupler_turned_round(tmp_path):
    b = _board(tmp_path, STM, lambda t: _fp(t, "C5", lambda blk: _swap_nets(blk, "1", "2")))
    _, fails = _run(b, ORIENT)
    assert len(fails) == 1 and fails[0].startswith("C5 is turned round: its ground pad is")


def test_orient_cannot_judge_a_cap_with_no_ground_pad(tmp_path):
    b = _board(tmp_path, STM, lambda t: _fp(t, "C5", lambda blk: _pad_net(blk, "2", "SPARE")))
    assert _run(b, ORIENT)[1] == ["orient C5 U1.1: cannot judge, C5 has no pad on GND"]


# balance: crystal Y1 across U1.5 (OSC_IN) and U1.6 (OSC_OUT); as built its gaps are 1.21 and 3.40 mm

BALANCE = {"balance": [("Y1", "U1.5", "U1.6", 1.0)]}


def test_balance_passes_a_crystal_with_even_gaps(tmp_path):
    """Its OSC_OUT pad swapped with the GND pad beside the MCU: both signal pads face U1."""
    b = _board(tmp_path, STM, lambda t: _fp(t, "Y1", lambda blk: _swap_nets(blk, "3", "4")))
    lines, fails = _run(b, BALANCE)
    assert fails == [], lines


def test_balance_finds_uneven_gaps(tmp_path):
    _, fails = _run(_board(tmp_path, STM), BALANCE)
    assert len(fails) == 1 and fails[0].startswith("Y1's gaps to U1.5 and U1.6 differ by 2.19 mm")


def test_balance_cannot_judge_a_part_off_one_pin_s_net(tmp_path):
    b = _board(tmp_path, STM, lambda t: _fp(t, "Y1", lambda blk: _pad_net(blk, "3", "SPARE")))
    assert _run(b, BALANCE)[1] == ["balance Y1: cannot judge, Y1 has no pad on OSC_OUT"]


# fronts: U1's signal pins; as built, Y1, R4 and R3 sit in front of pins they do not connect to

FRONTS = {"fronts": [("U1", 1.0)]}


def test_fronts_passes_when_nothing_is_parked_in_front(tmp_path):
    def away(t):
        for ref in ("Y1", "R3", "R4"):
            t = _fp(t, ref, lambda blk: _move(blk, 40, 0))
        return t
    lines, fails = _run(_board(tmp_path, STM, away), FRONTS)
    assert fails == [] and "44 of 44 signal pins" in lines[0]


def test_fronts_finds_a_part_parked_in_front_of_a_pin(tmp_path):
    _, fails = _run(_board(tmp_path, STM), FRONTS)
    assert "U1.31 (PA10) has no clear channel out, straight or at 45 degrees, for 1.0 mm" in fails


def test_fronts_cannot_judge_an_ic_with_no_signal_pin(tmp_path):
    b = _board(tmp_path, STM, lambda t: _fp(t, "U1", _strip_nets))
    assert _run(b, FRONTS)[1] == ["fronts U1: cannot judge, U1 has no signal pin"]


# via_site: C5's ground pad has room; U1.23, a GND pin of the QFP, has none
# within 0.8 mm, because of its neighbours' pads alone (ignoring them, it has)

VIA = {"via_site": [("C5.2", 1.2)]}


def test_via_site_finds_room_for_a_via(tmp_path):
    lines, fails = _run(_board(tmp_path, STM), VIA)
    assert fails == [] and "a 0.6 mm via fits" in lines[0]


def test_via_site_finds_no_room_between_other_nets_pads(tmp_path):
    _, fails = _run(_board(tmp_path, STM), {"via_site": [("U1.23", 0.8)]})
    assert fails == ["U1.23 (GND) has no legal spot for a 0.6 mm via within 0.8 mm"]


def test_via_site_cannot_judge_a_pad_with_no_net(tmp_path):
    b = _board(tmp_path, STM, lambda t: _fp(t, "C5", lambda blk: _strip_nets(blk)))
    assert _run(b, VIA)[1] == ["via_site C5.2: cannot judge, C5.2 has no net"]


# chain: U1.2 (+3V3) -> R1 -> D1.2 on the LDO example, with C2 as the shunt on +3V3

CHAIN = {"chain": [("U1.2", ["R1"], "D1.2")]}


def test_chain_passes_a_shunt_on_the_path(tmp_path):
    b0 = Board(LDO)
    a, r = b0.pad("U1.2"), b0.pad("R1.1")
    c2 = [p for p in b0.pads if p.ref == "C2" and p.net == "+3V3"][0]
    mx, my = (a.x + r.x) / 2, (a.y + r.y) / 2                # the +3V3 pad onto the path's midpoint
    b = _board(tmp_path, LDO, lambda t: _fp(t, "C2", lambda blk: _move(blk, mx - c2.x, my - c2.y)))
    lines, fails = _run(b, CHAIN)
    assert fails == [] and "shunt C2 on +3V3 inline" in lines[0]


def test_chain_finds_a_shunt_off_the_path(tmp_path):
    _, fails = _run(_board(tmp_path, LDO), CHAIN)
    assert fails == ["shunt C2's +3V3 pad is 5.48 mm off the U1.2 -> D1.2 path, limit 0.0"]


def test_chain_cannot_judge_a_chain_with_no_shunt(tmp_path):
    b = _board(tmp_path, LDO, lambda t: _fp(t, "C2", lambda blk: _pad_net(blk, "2", "SPARE")))
    assert _run(b, CHAIN)[1] == ["chain U1.2 -> D1.2: cannot judge, no shunt to ground on its nodes (+3V3, LED_A)"]


def test_review_runs_the_placement_checks(tmp_path):
    """verify's review reports a placement finding like any other."""
    from types import SimpleNamespace

    from boardwright.review import review
    b = _board(tmp_path, STM, lambda t: _fp(t, "C5", lambda blk: _swap_nets(blk, "1", "2")))
    fails = review(b.path, SimpleNamespace(REVIEW=ORIENT))
    assert any(f.startswith("C5 is turned round") for f in fails)


@pytest.mark.parametrize("name", ["near", "orient", "balance", "fronts", "via_site", "chain"])
def test_an_absent_key_reports_nothing(tmp_path, name):
    assert _run(_board(tmp_path, LDO), {name: []}) == ([], [])
