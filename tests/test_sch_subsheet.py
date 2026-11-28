"""Adding parts on a sub-sheet, on KiCad's own pic_programmer demo: a root sheet
and one sub-sheet (pic_sockets) used once."""
import re
import subprocess
import xml.etree.ElementTree as ET

import pytest
from conftest import demo_copy, needs_demos, needs_kicad

from boardwright import sch
from boardwright.cli import main

pytestmark = needs_demos
ROOT, SUB = "pic_programmer.kicad_sch", "pic_sockets.kicad_sch"
ROWS = [("R90", "R1", "10k", "", {1: "VCC_PIC", 2: "GND"}),     # R1 is on the root sheet
        ("C90", "pic_programmer:C", "100n", "", {1: "VCC", 2: "SUB_NEW"})]


@pytest.fixture
def pic(tmp_path):
    return demo_copy(tmp_path, "pic_programmer")


def _spec(tmp_path, rows, sheet=SUB) -> str:
    f = tmp_path / "spec.py"
    f.write_text((f"SHEET = {sheet!r}\n" if sheet else "") + f"ADD = {rows!r}\n")
    return str(f)


def _part(text, ref):
    return next(text[s:e] for s, e in sch.blocks(text, ("symbol",)) if f'(reference "{ref}")' in text[s:e])


def test_parts_go_on_the_sub_sheet_with_its_path(pic, tmp_path):
    root_before = (pic / ROOT).read_text()
    sub_before = (pic / SUB).read_text()
    assert main(["sch", str(pic), "add", _spec(tmp_path, ROWS)]) == 0
    assert (pic / ROOT).read_text() == root_before
    sub = (pic / SUB).read_text()
    u6_path = sch._instance_path(_part(sub_before, "U6"))
    assert u6_path.count("/") == 2                        # root uuid / sheet uuid
    for ref in ("R90", "C90"):
        assert sch._instance_path(_part(sub, ref)) == u6_path
    # VCC has a power symbol on the root sheet only: the copy here takes this sheet's path
    vcc = [b for s, e in sch.Sheet(pic / SUB).instances() for b in [sub[s:e]]
           if (sch.prop(b, "Reference") or "").startswith("#PWR") and sch.prop(b, "Value") == "VCC"]
    assert len(vcc) == 1 and sch._instance_path(vcc[0]) == u6_path
    lid = re.search(r'\(lib_id "([^"]*)"', vcc[0]).group(1)
    assert sch._cached_entry(sub, lid) is not None       # its symbol came into this sheet's cache
    # VCC_PIC is a sheet pin here, so it gets a hierarchical label; the new net a local one
    assert sub.count('(hierarchical_label "VCC_PIC"') == sub_before.count('(hierarchical_label "VCC_PIC"') + 1
    assert sub.count('(label "SUB_NEW"') == 1


@pytest.mark.parametrize("rows,sheet,code,says", [
    ([("R91", "R1", "1k", "", {1: "PC-DATA-IN"})], SUB, 1, "local to another sheet"),
    ([("R1", "R1", "1k", "", {1: "GND"})], SUB, 64, "already exists"),        # R1 is taken on the root sheet
    ([("R91", "R1", "1k", "", {1: "GND"})], "nope.kicad_sch", 64, "no sheet"),
])
def test_refusals_write_nothing(pic, tmp_path, capsys, rows, sheet, code, says):
    before = {f: (pic / f).read_text() for f in (ROOT, SUB)}
    assert main(["sch", str(pic), "add", _spec(tmp_path, rows, sheet)]) == code
    assert says in capsys.readouterr().err
    assert {f: (pic / f).read_text() for f in (ROOT, SUB)} == before


def test_a_sheet_used_twice_is_refused(tmp_path, capsys):
    ch = demo_copy(tmp_path, "complex_hierarchy")
    before = (ch / "ampli_ht.kicad_sch").read_text()
    rows = [("R900", "R1", "1k", "", {1: "GND"})]
    assert main(["sch", str(ch), "add", _spec(tmp_path, rows, "ampli_ht.kicad_sch")]) == 1
    assert "used 2 times" in capsys.readouterr().err
    assert (ch / "ampli_ht.kicad_sch").read_text() == before


def _nets(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    return {n.get("name"): {(x.get("ref"), x.get("pin")) for x in n.iter("node")} for n in root.iter("net")}


@pytest.mark.kicad
@needs_kicad
def test_kicad_sees_the_new_parts_on_their_nets(pic, tmp_path):
    from boardwright import env

    cli = env.kicad_cli()

    def netlist(name):
        out = tmp_path / f"{name}.xml"
        subprocess.run([*cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(out), str(pic / ROOT)],
                       check=True, capture_output=True)
        return _nets(out.read_text())

    before = netlist("before")
    assert main(["sch", str(pic), "add", _spec(tmp_path, ROWS)]) == 0
    after = netlist("after")
    assert set(after) - set(before) == {"/pic_sockets/SUB_NEW"} and not set(before) - set(after)
    changed = {n: after[n] - before.get(n, set()) for n in after if after[n] != before.get(n)}
    assert changed == {"/pic_sockets/VCC_PIC": {("R90", "1")}, "GND": {("R90", "2")},
                       "VCC": {("C90", "1")}, "/pic_sockets/SUB_NEW": {("C90", "2")}}


@pytest.mark.parametrize("sheet", [ROOT, SUB])
def test_a_sheet_path_missing_its_slash_is_refused_through_add(pic, tmp_path, capsys, sheet):
    """pic_sockets/DATA-RB7 is the sub-sheet's label with its leading / dropped:
    written as a new net, KiCad put the pin alone on /pic_sockets/pic_sockets/DATA-RB7."""
    before = {f: (pic / f).read_text() for f in (ROOT, SUB)}
    rows = [("R91", "R1", "10k", "", {1: "pic_sockets/DATA-RB7", 2: "GND"})]
    assert main(["sch", str(pic), "add", _spec(tmp_path, rows, sheet)]) == 64
    assert "starts with the name of sheet 'pic_sockets'" in capsys.readouterr().err
    assert {f: (pic / f).read_text() for f in (ROOT, SUB)} == before


# complex_hierarchy places ampli_ht.kicad_sch twice; each of its parts has one
# reference per use (C201 in one, C301 in the other), on the hierarchy's two paths.

def test_parts_fields_show_each_uses_own_reference(tmp_path, capsys):
    """On a sheet used twice the shared Reference property holds one use's name."""
    ch = demo_copy(tmp_path, "complex_hierarchy")
    sch.parts(ch, "C[23]01", "Ref*")
    lines = capsys.readouterr().out.splitlines()
    assert sorted(line.split()[0] for line in lines) == ["C201", "C301"]
    for line in lines:
        assert line.endswith(f'Reference="{line.split()[0]}"')


def test_on_a_sheet_used_twice_a_use_keeps_its_own_name(tmp_path, capsys):
    ch = demo_copy(tmp_path, "complex_hierarchy")
    f = ch / "ampli_ht.kicad_sch"
    before = f.read_text(encoding="utf-8")
    assert sch.set_fields(ch, "C301", ["Reference=C301", "Value=15nF"]) == 0
    assert capsys.readouterr().out.splitlines() == ["C301: Reference unchanged (already C301)", "C301: Value unchanged (already 15nF)"]
    assert f.read_text(encoding="utf-8") == before
    assert sch.set_fields(ch, "C301", ["Value=22nF"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "note: C301 is one use of a symbol on a sheet that is used more than once; this also changes C201",
        "C301: Value -> 22nF"]


def test_one_use_of_a_shared_symbol_takes_a_backslash_reference(tmp_path):
    ch = demo_copy(tmp_path, "complex_hierarchy")
    assert sch.set_fields(ch, "C301", ["Reference=C\\7"]) == 0
    text = (ch / "ampli_ht.kicad_sch").read_text(encoding="utf-8")
    assert '(reference "C\\\\7")' in text and '(reference "C201")' in text
