import re
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import BOARDS, demo_copy, needs_demos, needs_kicad

from boardwright import update
from boardwright.cli import main

NETLIST = """(export
\t(version "E")
\t(components
\t\t(comp
\t\t\t(ref "U2")
\t\t\t(value "74HC00 \\"quad\\"")
\t\t\t(footprint "Package_DIP:DIP-14_W7.62mm")
\t\t\t(property
\t\t\t\t(name "Sheetname")
\t\t\t\t(value "sub")
\t\t\t)
\t\t\t(property
\t\t\t\t(name "exclude_from_board")
\t\t\t)
\t\t\t(sheetpath
\t\t\t\t(names "/sub/")
\t\t\t\t(tstamps "/aaaa/")
\t\t\t)
\t\t\t(tstamps "u1" "u2"
\t\t\t)
\t\t)
\t)
\t(nets
\t\t(net
\t\t\t(code "1")
\t\t\t(name "/VPP{slash}MCLR")
\t\t\t(class "Default")
\t\t\t(node
\t\t\t\t(ref "U2")
\t\t\t\t(pin "3")
\t\t\t)
\t\t)
\t)
)
"""


def test_the_netlist_keeps_net_names_as_the_board_writes_them(tmp_path):
    f = tmp_path / "n.net"
    f.write_text(NETLIST)
    comps, pins = update.read_netlist(f)
    # a multi-unit symbol lists one uuid per unit; the board links the first
    assert list(comps) == ["/aaaa/u1"]
    assert comps["/aaaa/u1"]["ref"] == "U2" and comps["/aaaa/u1"]["skip"] is True
    assert comps["/aaaa/u1"]["value"] == '74HC00 "quad"'       # read as the text it stands for
    assert pins == {("U2", "3"): "/VPP{slash}MCLR"}


def test_an_xml_netlist_is_refused(tmp_path):
    f = tmp_path / "n.xml"
    f.write_text("<export/>")
    with pytest.raises(SystemExit):
        update.read_netlist(f)


MOD = """(footprint "Thing"
\t(version 20260206)
\t(generator "pcbnew")
\t(generator_version "10.0")
\t(layer "F.Cu")
\t(property "Reference" "REF**"
\t\t(at 0 -2 0)
\t\t(uuid "11111111-1111-1111-1111-111111111111")
\t)
\t(property "Value" "Thing"
\t\t(at 0 2 0)
\t)
\t(pad "1" smd rect
\t\t(at -1 0)
\t\t(size 1 1)
\t\t(layers "F.Cu")
\t\t(uuid "22222222-2222-2222-2222-222222222222")
\t)
\t(pad "2" smd rect
\t\t(at 1 0)
\t\t(size 1 1)
\t\t(layers "F.Cu")
\t)
\t(zone
\t\t(polygon
\t\t\t(pts
\t\t\t\t(xy -3 -3) (xy 3 -3) (xy 3 3)
\t\t\t)
\t\t)
\t)
)
"""


def test_a_library_footprint_becomes_a_board_footprint():
    sym = {"ref": "U7", "value": "THING", "sheetname": "sub", "sheetfile": "sub.kicad_sch"}
    b = update.new_footprint(MOD, "Lib:Thing", sym, "/aaaa/u1", 100, 50, {"1": "GND", "2": "/A{slash}B"})
    assert b.startswith('\n\t(footprint "Lib:Thing"\n\t\t(layer "F.Cu")\n\t\t(uuid "')
    assert "\n\t\t(at 100 50)" in b and "(version" not in b and "(generator" not in b
    assert '(property "Reference" "U7"' in b and '(property "Value" "THING"' in b
    assert '\n\t\t(path "/aaaa/u1")\n\t\t(sheetname "sub")\n\t\t(sheetfile "sub.kicad_sch")' in b
    pads = re.findall(r'\(pad "(\d)"[\s\S]*?\n\t\t\)', b)
    assert pads == ["1", "2"]
    assert '\n\t\t\t(net "GND")\n\t\t\t(uuid "' in b                  # before the pad's uuid, at the pad's item depth
    assert '\n\t\t\t(net "/A{slash}B")\n\t\t)' in b                  # a pad with no uuid: at its end
    assert "(xy 97 47) (xy 103 47) (xy 103 53)" in b                  # its zone moved with it
    assert "11111111" not in b and b.count("(") == b.count(")")


def test_a_pad_net_is_replaced_in_place():
    pad = '\n\t\t(pad "1" smd rect\n\t\t\t(at 0 0)\n\t\t\t(net "OLD")\n\t\t\t(uuid "x")\n\t\t)'
    assert update._set_pad_net(pad, "NEW") == pad.replace('"OLD"', '"NEW"')


@pytest.fixture
def ldo(tmp_path):
    dst = tmp_path / "ldo_breakout"
    shutil.copytree(BOARDS / "ldo_breakout", dst, ignore=shutil.ignore_patterns("out", "boardwright_out", ".libmerge"))
    return dst


def _gate(ldo, tmp_path, name):
    from boardwright import env

    out = tmp_path / f"{name}.json"
    subprocess.run([*env.kicad_cli(), "pcb", "drc", "--format", "json", "--schematic-parity", "-o", str(out),
                    str(ldo / "ldo_breakout.kicad_pcb")], check=True, capture_output=True)
    import json

    return json.loads(out.read_text())


@pytest.mark.kicad
@needs_kicad
def test_kicad_finds_no_parity_issue_after_an_update(ldo, tmp_path):
    """A new part and a changed value in the schematic: the update brings both
    over, and KiCad's parity check, which flagged them, is clean."""
    spec = tmp_path / "add.py"
    spec.write_text('ADD = [("R50", "R1", "4.7k", "Resistor_SMD:R_0805_2012Metric", {1: "VIN", 2: "LED_A"})]\n')
    assert main(["sch", str(ldo), "add", str(spec)]) == 0
    assert main(["sch", str(ldo), "set", "C1", "Value=22u"]) == 0
    assert len(_gate(ldo, tmp_path, "before")["schematic_parity"]) == 2
    board = ldo / "ldo_breakout.kicad_pcb"
    old = board.read_text()
    assert main(["existing", str(ldo), "update"]) == 0
    assert _gate(ldo, tmp_path, "after")["schematic_parity"] == []
    new = board.read_text()
    added = [new[s:e] for s, e in update._footprints(new) if '(property "Reference" "R50"' in new[s:e]]
    assert len(added) == 1
    # without the new footprint, the board differs from before only in C1's value line
    rest = new.replace(added[0], "", 1).split("\n")
    assert len(rest) == len(old.split("\n"))
    changed = [(a, b) for a, b in zip(old.split("\n"), rest) if a != b]
    assert len(changed) == 1 and '"Value" "22u"' in changed[0][1]


@pytest.mark.kicad
@needs_kicad
def test_a_swapped_footprint_is_refused_and_nothing_written(ldo, capsys):
    assert main(["sch", str(ldo), "set", "R1", "Footprint=Resistor_SMD:R_0603_1608Metric"]) == 0
    board = ldo / "ldo_breakout.kicad_pcb"
    old = board.read_text()
    assert main(["existing", str(ldo), "update"]) == 1
    assert "swap it in KiCad" in capsys.readouterr().out
    assert board.read_text() == old


@pytest.mark.kicad
@needs_kicad
@needs_demos
def test_a_board_linked_by_path_with_a_sub_sheet_and_multi_unit_parts(tmp_path):
    """KiCad's pic_programmer: footprints linked to symbols by path, a sub-sheet,
    and multi-unit gates (U2, a 74HC00). Parts added on the sub-sheet and a value
    changed on the root: the update leaves no parity issue and moves nothing else."""
    import json

    from boardwright import env

    pic = demo_copy(tmp_path, "pic_programmer")
    spec = tmp_path / "add.py"
    spec.write_text('SHEET = "pic_sockets.kicad_sch"\nADD = [("R90", "R1", "10k", '
                    '"Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal", {1: "VCC_PIC", 2: "GND"})]\n')
    assert main(["sch", str(pic), "add", str(spec)]) == 0
    assert main(["sch", str(pic), "set", "R1", "Value=22k"]) == 0
    assert main(["existing", str(pic), "update"]) == 0
    out = tmp_path / "drc.json"
    subprocess.run([*env.kicad_cli(), "pcb", "drc", "--format", "json", "--schematic-parity", "-o", str(out),
                    str(pic / "pic_programmer.kicad_pcb")], check=True, capture_output=True)
    assert json.loads(out.read_text())["schematic_parity"] == []


NET = Path(__file__).parent / "data" / "ldo_r50.net"   # KiCad 10.0.8's netlist of the LDO example after
                                                       # adding R50 (VIN to LED_A) and setting C1 to 22u


def test_update_from_a_netlist_without_kicad(ldo, capsys):
    """The LDO example's footprints carry no symbol path (kicad-tools does not
    write one), so they are matched by reference, as KiCad does."""
    board = ldo / "ldo_breakout.kicad_pcb"
    old = board.read_text()
    assert main(["existing", str(ldo), "update", str(NET)]) == 0
    out = capsys.readouterr().out
    assert "R50: added Resistor_SMD:R_0805_2012Metric" in out and "C1: Value 10u -> 22u" in out
    new = board.read_text()
    added = [new[s:e] for s, e in update._footprints(new) if '(property "Reference" "R50"' in new[s:e]]
    assert len(added) == 1 and '(net "VIN")' in added[0] and '(net "LED_A")' in added[0]
    x = float(re.search(r"\n\t\t\(at ([-\d.]+) ", added[0]).group(1))
    assert x > update._outline(old)[2]                   # beside the board, not on it
    rest = new.replace(added[0], "", 1).split("\n")
    changed = [(a, b) for a, b in zip(old.split("\n"), rest) if a != b]
    assert len(rest) == len(old.split("\n")) and changed == [('\t\t(property "Value" "10u"', '\t\t(property "Value" "22u"')]
    assert main(["existing", str(ldo), "update", str(NET)]) == 0       # a second run changes nothing
    assert board.read_text() == new


@pytest.mark.parametrize("ref,footprint,says", [
    ("R1", "Resistor_SMD:R_1206_3216Metric", "swap it in KiCad"),      # on the board with another footprint
    ("R50", "Resistor_SMD:R_0402_1005Metric", "not found"),            # not in the project's library
])
def test_what_cannot_be_done_writes_nothing(ldo, tmp_path, capsys, ref, footprint, says):
    text = NET.read_text()
    i = text.index(f'(ref "{ref}")')
    text = text[:i] + text[i:].replace('"Resistor_SMD:R_0805_2012Metric"', f'"{footprint}"', 1)
    f = tmp_path / "n.net"
    f.write_text(text)
    board = ldo / "ldo_breakout.kicad_pcb"
    old = board.read_text()
    assert main(["existing", str(ldo), "update", str(f)]) == 1
    assert says in capsys.readouterr().out
    assert board.read_text() == old
