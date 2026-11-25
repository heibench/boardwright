"""`sch move REF.PIN NET` (#193): one pin goes to another net by renaming the
label on its own stub, or by swapping its power symbol."""
import re
import subprocess
import xml.etree.ElementTree as ET

import pytest
from conftest import demo_copy, needs_demos, needs_kicad

from boardwright import sch
from boardwright.cli import main

SCH = "ldo_breakout.kicad_sch"
LED_A_AT_R1 = '(global_label "LED_A" (shape bidirectional) (at 222.25 22.86 0)'      # the label on R1.2's stub


def _move(d, *args):
    return main(["sch", str(d), "move", *args])


def _wire(text, a, b):
    """text with one more wire, from a to b, in the file's own format."""
    s, e = sch.blocks(text, ("wire",))[0]
    w = re.sub(r"\(pts \(xy [-\d.]+ [-\d.]+\) \(xy [-\d.]+ [-\d.]+\)\)", f"(pts (xy {a[0]} {a[1]}) (xy {b[0]} {b[1]}))",
               text[s:e], count=1)
    return text[:e] + w + text[e:]


def _pin(text, ref, num):
    b = next(text[s:e] for s, e in sch.blocks(text, ("symbol",)) if f'(reference "{ref}")' in text[s:e])
    return sch._placed_pins(text, b)[num][:2]


def test_the_pins_own_label_is_renamed_and_nothing_else(ldo_copy, capsys):
    f = ldo_copy / SCH
    before = f.read_text()
    assert before.count(LED_A_AT_R1) == 1 and before.count('(global_label "LED_A"') == 2      # D1 keeps its own
    assert _move(ldo_copy, "R1.2", "NEWNET") == 0
    assert capsys.readouterr().out == "R1.2: LED_A -> NEWNET  [global label (new net)]\n"
    assert f.read_text() == before.replace(LED_A_AT_R1, LED_A_AT_R1.replace("LED_A", "NEWNET"))


def test_a_net_that_exists_is_named_without_new_net(ldo_copy, capsys):
    assert _move(ldo_copy, "R1.2", "GND") == 0
    assert capsys.readouterr().out == "R1.2: LED_A -> GND  [global label]\n"


def test_a_pin_already_on_the_net_writes_nothing(ldo_copy, capsys):
    before = (ldo_copy / SCH).read_text()
    assert _move(ldo_copy, "R1.2", "LED_A") == 0
    assert capsys.readouterr().out == "R1.2: already on LED_A; nothing written\n"
    assert (ldo_copy / SCH).read_text() == before


@pytest.mark.parametrize("args,says", [
    (["R1", "X"], "write REF.PIN"),
    (["Q9.1", "X"], "no part 'Q9'"),
    (["R1.9", "X"], "R1 has no pin 9 (it has ['1', '2'])"),
    (["R1.2"], "move REF.PIN NET"),
    (["R1.2", "X", "Y"], "move REF.PIN NET"),
])
def test_a_bad_pin_or_argument_is_a_usage_error(ldo_copy, capsys, args, says):
    before = (ldo_copy / SCH).read_text()
    assert _move(ldo_copy, *args) == 64
    assert says in capsys.readouterr().err
    assert (ldo_copy / SCH).read_text() == before


def test_a_pin_wired_to_another_pin_is_refused(ldo_copy, capsys):
    f = ldo_copy / SCH
    t = f.read_text()
    f.write_text(_wire(t, _pin(t, "R1", "1"), _pin(t, "J2", "1")))
    before = f.read_text()
    assert _move(ldo_copy, "R1.1", "X") == 1
    assert "R1.1 is wired to J2.1: moving it would split that net" in capsys.readouterr().err
    assert f.read_text() == before


def test_a_pin_with_no_label_on_its_stub_is_a_usage_error(ldo_copy, capsys):
    f = ldo_copy / SCH
    t = f.read_text()
    s, e = next((s, e) for s, e in sch.blocks(t, ("global_label",)) if LED_A_AT_R1 in t[s:e])
    f.write_text(t[:s] + t[e:])
    assert _move(ldo_copy, "R1.2", "X") == 64
    assert "R1.2 reaches its net through no label or power symbol" in capsys.readouterr().err


def test_two_labels_on_one_stub_are_refused(ldo_copy, capsys):
    f = ldo_copy / SCH
    t = f.read_text()
    s, e = next((s, e) for s, e in sch.blocks(t, ("global_label",)) if LED_A_AT_R1 in t[s:e])
    f.write_text(t[:e] + t[s:e] + t[e:])
    before = f.read_text()
    assert _move(ldo_copy, "R1.2", "X") == 1
    assert "through 2 labels or power symbols" in capsys.readouterr().err
    assert f.read_text() == before


# ---- where a placed pin is -------------------------------------------------

CACHE = """(kicad_sch
\t(lib_symbols
\t\t(symbol "X:P"
\t\t\t(symbol "P_0_1"
\t\t\t\t(pin passive line (at 2.54 0 180) (length 2.54) (number "8"))
\t\t\t)
\t\t\t(symbol "P_1_1"
\t\t\t\t(pin passive line (at 3.81 0 180) (length 2.54) (number "1"))
\t\t\t)
\t\t\t(symbol "P_2_1"
\t\t\t\t(pin passive line (at 0 -2.54 90) (length 2.54) (number "5"))
\t\t\t)
\t\t)
\t)
)
"""


def _placed(at, extra=""):
    return f'\n\t(symbol\n\t\t(lib_id "X:P")\n\t\t(at {at}){extra}\n\t)'


def test_a_pin_is_turned_then_mirrored():
    """KiCad turns a symbol by its angle, then mirrors it. Mirroring first would
    put pin 1 of this part at (100, 96.19)."""
    b = _placed("100 100 90", "\n\t\t(mirror x)\n\t\t(unit 1)")
    assert sch._placed_pins(CACHE, b) == {"8": (100.0, 102.54, 90.0), "1": (100.0, 103.81, 90.0)}


def test_a_pin_comes_from_its_own_unit_and_the_common_one():
    b = _placed("50 50 270", "\n\t\t(unit 2)")
    assert sch._placed_pins(CACHE, b) == {"8": (50.0, 52.54, 90.0), "5": (47.46, 50.0, 0.0)}


def test_wires_that_cross_join_only_at_a_junction():
    wire = '\n\t(wire\n\t\t(pts (xy {} {}) (xy {} {}))\n\t)'
    t = "(kicad_sch" + wire.format(0, 0, 10, 0) + wire.format(5, -5, 5, 5) + wire.format(10, 0, 10, 8) + "\n)"
    assert sorted(sch._stub(t, (0, 0))) == [((0, 0), (10, 0)), ((10, 0), (10, 8))]   # an end on it joins; a crossing does not
    dotted = t[:-2] + "\n\t(junction (at 5 0) (diameter 0))\n)"
    assert len(sch._stub(dotted, (0, 0))) == 3


def test_pwr_flag_names_no_net(ldo_copy):
    """KiCad names a net after a power symbol whose pin is power_in (GND);
    PWR_FLAG's pin is power_out, and it names nothing."""
    sh = sch.Sheet(ldo_copy / SCH)
    flags = [sh.text[s:e] for s, e in sh.instances() if sch.prop(sh.text[s:e], "Value") == "PWR_FLAG"]
    assert len(flags) == 2 and not any(sch._names_net(sh.text, b) for b in flags)


# ---- power symbols and sheets, on KiCad's own demos -------------------------

PIC = "pic_programmer.kicad_sch"


@needs_demos
def test_a_power_symbol_is_swapped_for_the_new_nets(tmp_path, capsys):
    """D2.1's stub ends in a VCC symbol: moving it to GND puts a GND symbol
    there, its pin on the same point."""
    pic = demo_copy(tmp_path, "pic_programmer")
    sh = sch.Sheet(pic / PIC)
    t = sh.text
    p = _pin(t, "D2", "1")
    stub = sch._stub(t, p)
    vcc = [t[s:e] for s, e in sh.instances() if sch.prop(t[s:e], "Value") == "VCC"]
    old = [b for b in vcc for q in sch._placed_pins(t, b).values()
           if q[:2] == p or any(sch._on(q[:2], *w) for w in stub)]
    assert len(old) == 1 and sch._names_net(t, old[0])
    at = next(iter(sch._placed_pins(t, old[0]).values()))
    assert _move(pic, "D2.1", "GND") == 0
    assert capsys.readouterr().out == "D2.1: VCC -> GND  [power symbol]\n"
    after = sch.Sheet(pic / PIC)
    new = [after.text[s:e] for s, e in after.instances() if after.text[s:e] not in t]
    assert len(new) == 1 and sch.prop(new[0], "Value") == "GND"
    assert next(iter(sch._placed_pins(after.text, new[0]).values())) == at     # same point, body the same way
    assert old[0] not in after.text


@needs_demos
def test_a_symbol_with_a_hidden_power_pin_names_its_net(tmp_path, capsys):
    """pic_programmer's VPP has no power flag, but its one pin is a hidden
    power_in, which names the net after it."""
    pic = demo_copy(tmp_path, "pic_programmer")
    assert _move(pic, "Q2.3", "X") == 0
    assert capsys.readouterr().out == "Q2.3: VPP -> X  [label (new net)]\n"


@needs_demos
def test_a_pin_drawn_on_every_unit_is_refused(tmp_path, capsys):
    """Pin 14 of the 74LS125 (VCC) is common to its four gates, each drawing it
    with its own VCC symbol. Moving one drawing would join VCC and GND."""
    pic = demo_copy(tmp_path, "pic_programmer")
    before = (pic / PIC).read_text()
    assert _move(pic, "U2.14", "GND") == 1
    assert "U2.14 is drawn on 4 units of U2, all one pin" in capsys.readouterr().err
    assert (pic / PIC).read_text() == before


@needs_demos
def test_a_label_becomes_a_power_symbol_and_back(tmp_path, capsys):
    pic = demo_copy(tmp_path, "pic_programmer")
    assert _move(pic, "R13.2", "VCC") == 0
    assert _move(pic, "R13.2", "BACK") == 0
    assert capsys.readouterr().out == ("R13.2: CLOCK-RB6 -> VCC  [power symbol]\n"
                                       "R13.2: VCC -> BACK  [label (new net)]\n")
    t = (pic / PIC).read_text()
    assert t.count('(label "BACK"') == 1


@needs_demos
def test_a_net_local_to_another_sheet_is_refused(tmp_path, capsys):
    pic = demo_copy(tmp_path, "pic_programmer")
    before = (pic / PIC).read_text()
    assert _move(pic, "R13.2", "VPP-MCLR") == 1                 # a local label on pic_sockets only
    assert "local to another sheet" in capsys.readouterr().err
    assert (pic / PIC).read_text() == before


@needs_demos
def test_a_part_on_a_sheet_used_twice_is_refused(tmp_path, capsys):
    d = demo_copy(tmp_path, "complex_hierarchy")
    before = (d / "ampli_ht.kicad_sch").read_text()
    assert _move(d, "R203.1", "X") == 1
    assert "on a sheet used more than once (R203, R303)" in capsys.readouterr().err
    assert (d / "ampli_ht.kicad_sch").read_text() == before


def _nets(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    return {(x.get("ref"), x.get("pin")): n.get("name") for n in root.iter("net") for x in n.iter("node")}


@pytest.mark.kicad
@needs_kicad
@needs_demos
def test_kicad_sees_only_the_moved_pins_change(tmp_path):
    from boardwright import env

    pic = demo_copy(tmp_path, "pic_programmer")

    def nets(name):
        out = tmp_path / f"{name}.xml"
        subprocess.run([*env.kicad_cli(), "sch", "export", "netlist", "--format", "kicadxml", "-o", str(out),
                        str(pic / PIC)], check=True, capture_output=True)
        return _nets(out.read_text())

    before = nets("before")
    for where, net in (("D2.1", "GND"), ("R13.2", "VCC"), ("J1.5", "NEWNET")):
        assert _move(pic, where, net) == 0
    after = nets("after")
    moved = {("D2", "1"): "GND", ("R13", "2"): "VCC", ("J1", "5"): "/NEWNET"}
    assert {k: after[k] for k in moved} == moved
    assert {k: v for k, v in after.items() if k not in moved} == {k: v for k, v in before.items() if k not in moved}
