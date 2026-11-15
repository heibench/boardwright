import re
import subprocess
import xml.etree.ElementTree as ET

import pytest
from conftest import needs_kicad

from boardwright import sch
from boardwright.cli import main

SCH = "ldo_breakout.kicad_sch"


def _cached(text: str, lib_id: str, name: str) -> str:
    """A symbol from the schematic's cache, as a library symbol called `name`."""
    s, e = next((s, e) for s, e in sch.blocks(text, ("symbol",)) if text[s:s + 60].lstrip().startswith(f'(symbol "{lib_id}"'))
    body = text[s:e].replace(f'(symbol "{lib_id}"', f'(symbol "{name}"', 1)
    bare = lib_id.split(":", 1)[1]
    body = re.sub(r'\(symbol "%s_(\d+_\d+)"' % re.escape(bare), lambda m: f'(symbol "{name}_{m.group(1)}"', body)
    return "\n".join(ln[1:] if ln.startswith("\t") else ln for ln in body.split("\n"))


@pytest.fixture
def proj(ldo_copy):
    return with_mine(ldo_copy)


def with_mine(ldo_copy):
    """The LDO example with a local library 'Mine' the schematic does not use yet:
    a resistor, a two-unit part and a power symbol."""
    text = (ldo_copy / SCH).read_text()
    r = _cached(text, "Device:R", "R_new")
    dual = _cached(text, "Device:R", "Dual")
    i = dual.rfind("\n", 0, dual.index('(symbol "Dual_1_1"'))
    s, e = sch.blocks(dual[i:], ("symbol",))[0]
    unit = dual[i + s:i + e]
    dual = dual.replace(unit, unit + unit.replace('(symbol "Dual_1_1"', '(symbol "Dual_2_1"'), 1)
    pwr = _cached(text, "power:PWR_FLAG", "PWR_new")
    (ldo_copy / "libs" / "Mine.kicad_sym").write_text(
        '(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "test")' + r + dual + pwr + "\n)\n")
    table = ldo_copy / "sym-lib-table"
    t = table.read_text()
    table.write_text(t.replace("\n)", '\n  (lib (name "Mine")(type "KiCad")(uri "${KIPRJMOD}/libs/Mine.kicad_sym")(options "")(descr ""))\n)', 1))
    return ldo_copy


def _spec(tmp_path, rows) -> str:
    f = tmp_path / "add_spec.py"
    f.write_text(f"ADD = {rows!r}\n")
    return str(f)


R50 = ("R50", "Mine:R_new", "1k", "Resistor_SMD:R_0805_2012Metric", {1: "+3V3", 2: "GND"})


def test_a_library_part_is_added_and_nothing_else_changes(proj, tmp_path):
    f = proj / SCH
    before = f.read_text()
    assert main(["sch", str(proj), "add", _spec(tmp_path, [R50])]) == 0
    after = f.read_text()
    entry = next(after[s:e] for s, e in sch.blocks(after, ("symbol",)) if after[s:s + 60].lstrip().startswith('(symbol "Mine:R_new"'))
    assert after.count('(symbol "Mine:R_new"') == 1 and "\n\t\t(symbol \"Mine:R_new\"" in entry
    part = next(after[s:e] for s, e in sch.Sheet(f).instances() if '(lib_id "Mine:R_new")' in after[s:e])
    assert sch.prop(part, "Reference") == "R50" and sch.prop(part, "Value") == "1k"
    assert sorted(re.findall(r'\(pin "([^"]*)"', part)) == ["1", "2"]
    assert '(reference "R50")' in part and "ki_" not in part
    # everything that was there is still there, byte for byte, around the two insertions
    rest = after.replace(entry, "", 1)
    k = re.search(r"\n\t\((?:sheet_instances|embedded_fonts)\b", before).start()
    assert rest[:k] == before[:k] and rest.endswith(before[k:])
    # its pins land on the nets' own (global) labels
    assert rest.count('(global_label "+3V3"') == before.count('(global_label "+3V3"') + 1
    assert rest.count('(global_label "GND"') == before.count('(global_label "GND"') + 1


def test_a_second_part_reuses_the_cached_symbol(proj, tmp_path):
    assert main(["sch", str(proj), "add", _spec(tmp_path, [R50])]) == 0
    r51 = ("R51", "Mine:R_new", "2k", "Resistor_SMD:R_0805_2012Metric", {1: "VIN", 2: "GND"})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [r51])]) == 0
    assert (proj / SCH).read_text().count('(symbol "Mine:R_new"') == 1


@pytest.mark.parametrize("row,code,says", [
    (("U5", "Mine:Dual", "x", "", {1: "GND"}), 1, "2 units"),
    (("P5", "Mine:PWR_new", "x", "", {1: "GND"}), 64, "power symbol"),
    (("R5", "Mine:Nope", "x", "", {1: "GND"}), 64, "no symbol"),
    (("R5", "Nolib:R", "x", "", {1: "GND"}), 64, "no library"),
    (("R5", "Mine:R_new", "x", "", {3: "GND"}), 64, "no pin 3"),
    (("R1", "Mine:R_new", "x", "", {1: "GND"}), 64, "already exists"),
])
def test_refusals_write_nothing(proj, tmp_path, capsys, row, code, says):
    f = proj / SCH
    before = f.read_text()
    assert main(["sch", str(proj), "add", _spec(tmp_path, [row])]) == code
    assert says in capsys.readouterr().err
    assert f.read_text() == before


def _nets(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    return {n.get("name"): {(x.get("ref"), x.get("pin")) for x in n.iter("node")} for n in root.iter("net")}


@pytest.mark.kicad
@needs_kicad
def test_kicad_sees_the_new_part_on_its_nets_and_nothing_else(proj, tmp_path):
    from boardwright import env

    cli = env.kicad_cli()

    def run(name):
        net, erc = tmp_path / f"{name}.xml", tmp_path / f"{name}.json"
        subprocess.run([*cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(net), str(proj / SCH)],
                       check=True, capture_output=True)
        subprocess.run([*cli, "sch", "erc", "--format", "json", "--severity-all", "-o", str(erc), str(proj / SCH)],
                       check=True, capture_output=True)
        return _nets(net.read_text()), str(erc)

    before, erc_before = run("before")
    assert main(["sch", str(proj), "add", _spec(tmp_path, [R50])]) == 0
    after, erc_after = run("after")
    assert set(after) == set(before)
    changed = {n: after[n] - before[n] for n in after if after[n] != before[n]}
    assert changed == {"+3V3": {("R50", "1")}, "GND": {("R50", "2")}}
    assert sch.ercdiff(erc_before, erc_after) == 0


def test_a_copy_of_a_part_on_the_sheet_still_works(proj, tmp_path):
    f = proj / SCH
    before = f.read_text()
    row = ("R52", "R1", "4.7k", "Resistor_SMD:R_0805_2012Metric", {1: "VIN", 2: "NEW_NET"})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [row])]) == 0
    after = f.read_text()
    part = next(after[s:e] for s, e in sch.Sheet(f).instances() if '(reference "R52")' in after[s:e])
    assert '(lib_id "Device:R")' in part and sch.prop(part, "Value") == "4.7k"
    assert after.count('(global_label "NEW_NET"') == 1 and after.count('(symbol "Device:R"') == before.count('(symbol "Device:R"')


VCC = ('\n\t(symbol\n\t\t(lib_id "power:+3V3")\n\t\t(at 100 100 {r})\n\t\t(unit 1)\n'
       '\t\t(property "Value" "+3V3"\n\t\t\t(at 100 {vy} 0)\n\t\t)\n\t)')


@pytest.mark.parametrize("src_rot,value_y", [(0, 96.19), (180, 103.81)])
@pytest.mark.parametrize("away,rot,value_dy", [(90, 0, -3.81), (270, 180, 3.81), (0, 270, 0)])
def test_a_power_symbol_points_away_from_its_part(src_rot, value_y, away, rot, value_dy):
    """+3V3's body lies along its pin (angle 90, up). Placed on a stub pointing
    `away`, it turns to face that way, and its value text turns with it, whatever
    rotation the copied symbol had."""
    b = sch._place_power(VCC.format(r=src_rot, vy=value_y), 50, 60, away, (0.0, 0.0, 90.0))
    assert f"\n\t\t(at 50 60 {rot})" in b
    vx, vy = map(float, re.search(r'\(property "Value" "\+3V3"\s+\(at ([-\d.]+) ([-\d.]+)', b).groups())
    assert vy == pytest.approx(60 + value_dy) and vx == pytest.approx(50 + (3.81 if away == 0 else 0))


def _global_lib(own_kicad_settings, proj, tmp_path, nested=False):
    """Move 'Mine' out of the project into a folder named by a KiCad path variable,
    listed in the global table (or in a table nested in it)."""
    import json

    shelf = tmp_path / "shelf"
    shelf.mkdir()
    (proj / "libs" / "Mine.kicad_sym").rename(shelf / "Mine.kicad_sym")
    t = (proj / "sym-lib-table").read_text()
    (proj / "sym-lib-table").write_text(re.sub(r'\n  \(lib \(name "Mine"\)[^\n]*', "", t))
    (own_kicad_settings / "kicad_common.json").write_text(json.dumps({"environment": {"vars": {"MY_SHELF": str(shelf)}}}))
    row = '(lib (name "Mine")(type "KiCad")(uri "${MY_SHELF}/Mine.kicad_sym")(options "")(descr ""))'
    if nested:
        (shelf / "inner-table").write_text(f"(sym_lib_table\n  (version 7)\n  {row}\n)\n")
        row = '(lib (name "Shelf")(type "Table")(uri "${MY_SHELF}/inner-table")(options "")(descr ""))'
    (own_kicad_settings / "sym-lib-table").write_text(f"(sym_lib_table\n  (version 7)\n  {row}\n)\n")


@pytest.mark.parametrize("nested", [False, True])
def test_a_library_in_the_global_table_is_found(own_kicad_settings, proj, tmp_path, nested):
    _global_lib(own_kicad_settings, proj, tmp_path, nested)
    assert main(["sch", str(proj), "add", _spec(tmp_path, [R50])]) == 0
    assert '(lib_id "Mine:R_new")' in (proj / SCH).read_text()


def test_the_project_table_decides_before_the_global_one(own_kicad_settings, proj, tmp_path):
    """A nickname both tables name is the project's, even when its file is missing."""
    _global_lib(own_kicad_settings, proj, tmp_path)
    t = (proj / "sym-lib-table").read_text()
    (proj / "sym-lib-table").write_text(t.replace("\n)", '\n  (lib (name "Mine")(type "KiCad")(uri "${KIPRJMOD}/gone.kicad_sym")(options "")(descr ""))\n)', 1))
    assert main(["sch", str(proj), "add", _spec(tmp_path, [R50])]) == 64


def test_an_unknown_path_variable_is_a_usage_error(own_kicad_settings, proj, tmp_path):
    _global_lib(own_kicad_settings, proj, tmp_path)
    (own_kicad_settings / "kicad_common.json").write_text("{}")
    assert main(["sch", str(proj), "add", _spec(tmp_path, [R50])]) == 64

