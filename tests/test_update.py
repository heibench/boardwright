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
    assert comps["/aaaa/u1"]["sheetname"] == "/sub/"          # the sheet path, as KiCad writes it on the board
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


def _unlink(ldo):
    """The LDO example as boardwright generated it before footprints were linked to symbols."""
    pcb = ldo / "ldo_breakout.kicad_pcb"
    pcb.write_text(re.sub(r"\n\t\t\((?:path|sheetname|sheetfile) [^\n]*\)", "", pcb.read_text()))


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
def test_a_swap_to_other_pads_is_refused_and_nothing_written(ldo, capsys):
    """R1 pointed at the project's LED 0805, whose pads sit 0.025 mm further out."""
    assert main(["sch", str(ldo), "set", "R1", "Footprint=LED_SMD:LED_0805_2012Metric"]) == 0
    board = ldo / "ldo_breakout.kicad_pcb"
    old = board.read_text()
    assert main(["existing", str(ldo), "update"]) == 1
    assert "pad 1 x: -0.9125 on the board, -0.9375 in the library" in capsys.readouterr().out
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
    _unlink(ldo)
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
    # each footprint matched by reference is linked to its symbol, as KiCad's re-link does
    assert out.count("linked to its symbol") == 7
    assert new.replace(added[0], "", 1).count("\n\t\t(path ") == 7
    rest = [ln for ln in new.replace(added[0], "", 1).split("\n")
            if not ln.startswith(("\t\t(path ", "\t\t(sheetname ", "\t\t(sheetfile "))]
    changed = [(a, b) for a, b in zip(old.split("\n"), rest) if a != b]
    assert len(rest) == len(old.split("\n")) and changed == [('\t\t(property "Value" "10u"', '\t\t(property "Value" "22u"')]
    assert main(["existing", str(ldo), "update", str(NET)]) == 0       # a second run changes nothing
    assert board.read_text() == new


@pytest.mark.parametrize("ref,footprint,says", [
    ("R1", "Resistor_SMD:R_1206_3216Metric", "which is not found"),    # a swap to a footprint not in the library
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


def test_a_linked_footprint_follows_a_renamed_symbol(ldo, tmp_path, capsys):
    """Linked to its symbol (as gen now does), R1 renamed R12 in the schematic is
    renamed on the board, not orphaned beside a new R12."""
    _unlink(ldo)
    from boardwright import board

    assert board.link_symbols(ldo / "ldo_breakout.kicad_pcb", ldo / "ldo_breakout.kicad_sch") == 7
    text = NET.read_text()
    text = text.replace('(ref "R1")', '(ref "R12")')            # the component and its two pins
    f = tmp_path / "renamed.net"
    f.write_text(text)
    assert main(["existing", str(ldo), "update", str(f)]) == 0
    out = capsys.readouterr().out
    assert "R12: Reference R1 -> R12" in out
    assert "R12: added" not in out and "left on the board" not in out


def test_link_symbols_links_a_generated_board_once(ldo):
    _unlink(ldo)
    from boardwright import board, sch

    pcb, sch_file = ldo / "ldo_breakout.kicad_pcb", ldo / "ldo_breakout.kicad_sch"
    assert board.link_symbols(pcb, sch_file) == 7
    linked = pcb.read_text()
    s = sch.Sheet(sch_file)
    r1 = next(s.text[a:b] for a, b in s.instances() if sch.prop(s.text[a:b], "Reference") == "R1")
    uid = re.search(r'\n\t\t\(uuid "([^"]*)"\)', r1).group(1)
    fp = next(linked[a:b] for a, b in update._footprints(linked) if update._prop(linked[a:b], "Reference") == "R1")
    assert f'(path "/{uid}")\n\t\t(sheetname "/")\n\t\t(sheetfile "ldo_breakout.kicad_sch")' in fp
    assert board.link_symbols(pcb, sch_file) == 0 and pcb.read_text() == linked


def _own_copy(ldo, name="R_0805", size=None):
    """The project's 0805 resistor footprint again, as Mine:<name>: the pads are
    the same unless `size` changes pad 1's."""
    lib = ldo / "libs" / "Mine.pretty"
    lib.mkdir()
    mod = (ldo / "libs" / "Resistor_SMD.pretty" / "R_0805_2012Metric.kicad_mod").read_text()
    if size:
        i = mod.index('(pad "1"')
        mod = mod[:i] + re.sub(r"\(size [^)]*\)", f"(size {size})", mod[i:], count=1)
    (lib / f"{name}.kicad_mod").write_text(mod)
    table = ldo / "fp-lib-table"
    table.write_text(table.read_text().rstrip()[:-1] +
                     '  (lib (name "Mine")(type "KiCad")(uri "${KIPRJMOD}/libs/Mine.pretty")(options "")(descr ""))\n)\n')


def _netlist_with(tmp_path, ref, footprint):
    text = NET.read_text()
    i = text.index(f'(ref "{ref}")')
    text = text[:i] + re.sub(r'\(footprint "[^"]*"\)', f'(footprint "{footprint}")', text[i:], count=1)
    f = tmp_path / "swap.net"
    f.write_text(text)
    return f


def test_a_footprint_with_the_same_pads_is_swapped_and_its_drawing_kept(ldo, tmp_path, capsys):
    """#37: the schematic points R1 at another footprint with the same pads. The
    board's footprint is re-pointed, and nothing else in its block changes."""
    _unlink(ldo)
    _own_copy(ldo)
    board = ldo / "ldo_breakout.kicad_pcb"
    old = board.read_text()
    assert main(["existing", str(ldo), "update", str(_netlist_with(tmp_path, "R1", "Mine:R_0805"))]) == 0
    out = capsys.readouterr().out
    assert "R1: footprint Resistor_SMD:R_0805_2012Metric -> Mine:R_0805 (pads match; drawing kept)" in out
    assert "C1: Value 10u -> 22u" in out
    new = board.read_text()
    fps = {update._prop(new[s:e], "Reference"): new[s:e] for s, e in update._footprints(new)}
    assert fps["R1"].startswith('\n\t(footprint "Mine:R_0805"\n')
    # beside R50, which the netlist adds, the board differs from before in R1's
    # link, C1's value and the symbol links alone
    rest = [ln for ln in new.replace(fps["R50"], "", 1).split("\n") if not ln.startswith(("\t\t(path ", "\t\t(sheetname ", "\t\t(sheetfile "))]
    changed = [(a, b) for a, b in zip(old.split("\n"), rest) if a != b]
    assert len(rest) == len(old.split("\n")) and changed == [
        ('\t(footprint "Resistor_SMD:R_0805_2012Metric"', '\t(footprint "Mine:R_0805"'),
        ('\t\t(property "Value" "10u"', '\t\t(property "Value" "22u"')]


def test_the_library_drawing_replaces_the_boards(ldo, tmp_path, capsys):
    """--body library: the drawing comes from the new library footprint; the pads,
    their nets, the fields and the footprint's place stay."""
    _unlink(ldo)
    _own_copy(ldo)
    lib = ldo / "libs" / "Mine.pretty" / "R_0805.kicad_mod"
    lib.write_text(lib.read_text().replace('(layer "F.CrtYd")', '(layer "F.CrtYd")\n\t\t(uuid "aaaaaaaa-0000-0000-0000-000000000000")'))
    lib.write_text(lib.read_text().replace("(start -0.227064 -0.735)", "(start -1.7 -0.95)", 1))
    board = ldo / "ldo_breakout.kicad_pcb"
    old = board.read_text()
    r1 = lambda t: next(t[s:e] for s, e in update._footprints(t) if update._prop(t[s:e], "Reference") == "R1")
    before = r1(old)
    assert main(["existing", str(ldo), "update", str(_netlist_with(tmp_path, "R1", "Mine:R_0805")), "--body", "library"]) == 0
    assert "(pads match; drawing from the library)" in capsys.readouterr().out
    after = r1(board.read_text())
    assert "(start -1.7 -0.95)" in after and "(start -1.7 -0.95)" not in before     # the library's drawing
    assert "aaaaaaaa-0000" not in after                                             # with uuids of its own
    pads = lambda fp: [fp[s:e] for s, e, _n, _net in update._pads(fp)]
    assert pads(after) == pads(before)                                              # pads, nets and uuids as they were
    for line in ("\n\t\t(at ", '\n\t\t(property "Reference"', '\n\t\t(property "Value"', "\n\t\t(uuid "):
        assert re.search(re.escape(line) + "[^\n]*", after).group(0) == re.search(re.escape(line) + "[^\n]*", before).group(0)
    assert update.pad_differences(after, lib.read_text()) == []
    assert after.count("(") == after.count(")")


def test_a_footprint_whose_pads_differ_is_refused(ldo, tmp_path, capsys):
    _unlink(ldo)
    _own_copy(ldo, size="1.2 1.4")
    board = ldo / "ldo_breakout.kicad_pcb"
    old = board.read_text()
    assert main(["existing", str(ldo), "update", str(_netlist_with(tmp_path, "R1", "Mine:R_0805"))]) == 1
    out = capsys.readouterr().out
    assert "and their pads differ (pad 1 size: 1.025 1.4 on the board, 1.2 1.4 in the library)" in out
    assert "nothing written" in out and board.read_text() == old


def test_an_unknown_body_is_a_usage_error(ldo):
    assert main(["existing", str(ldo), "update", "--body", "art"]) == 64


@needs_demos
def test_the_pad_check_reads_a_turned_part_on_the_back_as_kicad_placed_it():
    """C112 on KiCad's coldfire demo: on the back, turned 180 degrees. KiCad
    mirrors its pads' y and layers and turns their angles the other way."""
    from conftest import DEMOS

    from boardwright import sch

    t = (DEMOS / "kit-dev-coldfire-xilinx_5213" / "kit-dev-coldfire-xilinx_5213.kicad_pcb").read_text()
    fps = [t[s:e] for s, e in update._footprints(t) if '\n\t\t(layer "B.Cu")' in t[s:e]]
    fp = next(f for f in fps if update._prop(f, "Reference") == "C112")
    assert "\n\t\t(at 129.921 91.44 180)" in fp
    lib = sch.fp_dir(Path("."), "Capacitor_SMD")
    if lib is None:
        pytest.skip("KiCad's stock footprints not installed")
    mod = (lib / "C_0805_2012Metric.kicad_mod").read_text()
    assert update.pad_differences(fp, mod) == []
    moved = re.sub(r'(\(pad "2" smd roundrect\s*\(at [-\d.]+) ([-\d.]+)', r"\1 0.1", fp, count=1)
    assert update.pad_differences(moved, mod) == ["pad 2 y: -0.1 on the board, 0 in the library"]


def test_coordinates_keep_kicads_precision():
    """#41: Python's :g keeps six significant digits, so a footprint zone point
    at 149.119895 was written as 149.12 and KiCad reported the footprint as not
    matching its library. Lengths keep KiCad's 1 nm."""
    from boardwright.copper import num

    assert [num(v) for v in (149.119895, 157.1375, 2.0, -0.0, -1e-9, 1234.5678)] == \
        ["149.119895", "157.1375", "2", "0", "0", "1234.5678"]
    sym = {"ref": "U7", "value": "THING", "sheetname": "sub", "sheetfile": "sub.kicad_sch"}
    fp = update.new_footprint(MOD, "Lib:Thing", sym, "/aaaa/u1", 130.69, 157.1375, {})
    assert "\n\t\t(at 130.69 157.1375)" in fp
    assert "(xy 127.69 154.1375) (xy 133.69 154.1375) (xy 133.69 160.1375)" in fp
    # turned half way round and rebuilt from the library: the zone lands to the nanometre
    turned = fp.replace("\n\t\t(at 130.69 157.1375)", "\n\t\t(at 130.69 157.1375 180)")
    rebuilt = update.swap(turned, "Lib:Thing", MOD, "library")
    assert "(xy 133.69 160.1375) (xy 127.69 160.1375) (xy 127.69 154.1375)" in rebuilt


def _with_fields(text: str, ref: str, fields: dict[str, str]) -> str:
    """NET with `ref`'s Datasheet and Description set, and any user field added,
    in the form KiCad 10.0.8 writes them."""
    i = text.index(f'(ref "{ref}")')
    j = text.index("(fields", i)
    k = text.index("\n\t\t\t)", j)                                  # the end of that (fields ...)
    block = text[j:k]
    for name, val in fields.items():
        val = val.replace('"', '\\"')
        empty = f'(field\n\t\t\t\t\t(name "{name}")\n\t\t\t\t)'
        if empty in block:
            block = block.replace(empty, f'(field\n\t\t\t\t\t(name "{name}") "{val}")')
        else:
            block += f'\n\t\t\t\t(field\n\t\t\t\t\t(name "{name}") "{val}")'
    return text[:j] + block + text[k:]


def test_update_carries_the_symbols_fields_onto_its_footprints(ldo, tmp_path, capsys):
    """KiCad's Update PCB copies Datasheet, Description and user fields onto the
    footprint, and its parity check flags any that differ (#95). R50 is added,
    R1 matched and C1 matched; a second run changes nothing."""
    _unlink(ldo)
    text = _with_fields(NET.read_text(), "R50", {"Datasheet": "https://example.com/r50.pdf"})
    text = _with_fields(text, "R1", {"Description": 'Resistor, "thick film"', "Height": "0.5 mm"})
    f = tmp_path / "fields.net"
    f.write_text(text)
    board = ldo / "ldo_breakout.kicad_pcb"
    assert main(["existing", str(ldo), "update", str(f)]) == 0
    out = capsys.readouterr().out
    assert "R1: Description, Height from the symbol" in out
    new = board.read_text()
    fp = {update._prop(new[s:e], "Reference"): new[s:e] for s, e in update._footprints(new)}
    assert update._prop(fp["R50"], "Datasheet") == "https://example.com/r50.pdf"
    assert update._prop(fp["R1"], "Description") == 'Resistor, \\"thick film\\"'
    height = fp["R1"][fp["R1"].index('(property "Height"'):]
    assert height.startswith('(property "Height" "0.5 mm"\n\t\t\t(at 0 0 ') and '(layer "F.Fab")\n\t\t\t(hide yes)' in height
    assert fp["R1"].index('(property "Height"') < fp["R1"].index("(path ")   # with the properties, before the link
    assert out.count("from the symbol") == 1                                   # empty fields add nothing
    assert main(["existing", str(ldo), "update", str(f)]) == 0
    assert board.read_text() == new
    assert "from the symbol" not in capsys.readouterr().out


def test_tilde_and_empty_are_the_same_empty_datasheet():
    fp = '\n\t(footprint "X"\n\t\t(at 1 2)\n\t\t(property "Datasheet" "~"\n\t\t)\n\t)'
    assert update.with_fields(fp, {"Datasheet": ""}) == (fp, [])
    assert update.with_fields(fp, {"Datasheet": "a.pdf"})[1] == ["Datasheet"]


@pytest.mark.kicad
@needs_kicad
def test_kicad_finds_no_field_mismatch_after_an_update(ldo, tmp_path):
    """#95: R1, with a datasheet and a user field, taken off the board and added
    back by the update, and C1's datasheet changed in place. KiCad's parity
    check flags both before and neither after."""
    sch = ldo / "ldo_breakout.kicad_sch"
    s = sch.read_text()
    j = s.index('\t\t(property "Datasheet" "~"', s.index('(property "Reference" "R1"'))
    sch.write_text(s[:j] + '\t\t(property "Height" "0.5 mm"\n\t\t\t(at 213.36 22.86 0)\n\t\t\t(effects\n\t\t\t\t(font\n'
                   '\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n\t\t)\n' + s[j:])
    assert main(["sch", str(ldo), "set", "R1", "Datasheet=https://example.com/r1.pdf"]) == 0
    assert main(["sch", str(ldo), "set", "C1", "Datasheet=https://example.com/c1.pdf"]) == 0
    (ldo / "boardwright.py").write_text('REMOVE = ["R1"]\n')
    assert main(["existing", str(ldo), "apply", "--force"]) == 0
    before = {v["type"] for v in _gate(ldo, tmp_path, "before")["schematic_parity"]}
    assert before == {"footprint_symbol_field_mismatch", "missing_footprint"}
    assert main(["existing", str(ldo), "update"]) == 0
    assert _gate(ldo, tmp_path, "after")["schematic_parity"] == []


def _with_flag(text: str, ref: str, flag: str) -> str:
    """NET with `ref` carrying the component property `flag` (dnp,
    exclude_from_bom), in the form KiCad 10.0.8 writes it."""
    i = text.index(f'(ref "{ref}")')
    j = text.index('\t\t\t(property\n\t\t\t\t(name "Sheetname")', i)
    return text[:j] + f'\t\t\t(property\n\t\t\t\t(name "{flag}")\n\t\t\t)\n' + text[j:]


def test_update_carries_dnp_and_exclude_from_bom_onto_the_footprint(ldo, tmp_path, capsys):
    """KiCad's parity check flags a footprint whose "Do not populate" or
    "Exclude from bill of materials" differs from its symbol's (#98). Set,
    then a second run changes nothing, then cleared in the schematic."""
    _unlink(ldo)
    text = _with_flag(_with_flag(NET.read_text(), "C1", "dnp"), "R1", "exclude_from_bom")
    f = tmp_path / "flags.net"
    f.write_text(text)
    board = ldo / "ldo_breakout.kicad_pcb"
    assert main(["existing", str(ldo), "update", str(f)]) == 0
    out = capsys.readouterr().out
    assert "C1: dnp set" in out and "R1: exclude_from_bom set" in out
    new = board.read_text()
    fp = {update._prop(new[s:e], "Reference"): new[s:e] for s, e in update._footprints(new)}
    assert "\n\t\t(attr smd dnp)\n" in fp["C1"] and "\n\t\t(attr smd exclude_from_bom)\n" in fp["R1"]
    assert "\n\t\t(attr smd)\n" in fp["D1"]
    assert main(["existing", str(ldo), "update", str(f)]) == 0
    assert board.read_text() == new
    assert main(["existing", str(ldo), "update", str(NET)]) == 0
    out = capsys.readouterr().out
    assert "C1: dnp cleared" in out and "R1: exclude_from_bom cleared" in out
    assert "(attr smd dnp)" not in board.read_text() and "exclude_from_bom)" not in board.read_text()


@pytest.mark.parametrize("attr, sym, want", [
    ("(attr through_hole)", {"dnp": True, "exclude_from_bom": True}, "(attr through_hole exclude_from_bom dnp)"),
    ("(attr exclude_from_pos_files exclude_from_bom)", {"dnp": False, "exclude_from_bom": False},
     "(attr exclude_from_pos_files)"),
    ("(attr smd allow_missing_courtyard)", {"dnp": True, "exclude_from_bom": False}, "(attr smd allow_missing_courtyard dnp)"),
])
def test_flags_keep_the_other_attributes_in_kicads_order(attr, sym, want):
    fp = f'\n\t(footprint "X"\n\t\t(at 1 2)\n\t\t{attr}\n\t)'
    assert update.with_flags(fp, sym)[0] == f'\n\t(footprint "X"\n\t\t(at 1 2)\n\t\t{want}\n\t)'


def test_a_footprint_without_attr_gets_one_after_its_link():
    fp = '\n\t(footprint "X"\n\t\t(at 1 2)\n\t\t(property "Reference" "X1"\n\t\t)\n\t\t(path "/a")\n\t\t(sheetfile "x.kicad_sch")\n\t)'
    new, changed = update.with_flags(fp, {"dnp": True, "exclude_from_bom": False})
    assert changed == ["dnp set"] and '(sheetfile "x.kicad_sch")\n\t\t(attr dnp)\n\t)' in new


@pytest.mark.kicad
@needs_kicad
def test_kicad_finds_no_flag_mismatch_after_an_update(ldo, tmp_path):
    """#98: D1 set do-not-populate and R1 left out of the BOM in the schematic.
    KiCad's parity check flags both before the update and neither after."""
    assert main(["sch", str(ldo), "set", "D1", "dnp=yes"]) == 0
    assert main(["sch", str(ldo), "set", "R1", "in_bom=no"]) == 0
    before = [v["description"] for v in _gate(ldo, tmp_path, "before")["schematic_parity"]]
    assert len(before) == 2 and all("settings differ" in d for d in before)
    assert main(["existing", str(ldo), "update"]) == 0
    assert _gate(ldo, tmp_path, "after")["schematic_parity"] == []
