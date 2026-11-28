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
    # a new file each time: a same-size rewrite within a second could rerun the old spec (#213)
    f = tmp_path / f"add_spec_{len(list(tmp_path.glob('add_spec_*.py')))}.py"
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


@pytest.mark.kicad
@needs_kicad
def test_kicad_sees_a_two_style_part_on_its_nets(proj, tmp_path):
    """The body-style case judged by KiCad: R60's pins are on the nets add named."""
    from boardwright import env

    _two_styles(proj)
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("R60", "Mine:DS", "1k", "", {1: "NETA", 2: "NETB"})])]) == 0
    net = tmp_path / "after.xml"
    subprocess.run([*env.kicad_cli(), "sch", "export", "netlist", "--format", "kicadxml", "-o", str(net), str(proj / SCH)],
                   check=True, capture_output=True)
    nets = _nets(net.read_text())
    assert ("R60", "1") in nets.get("NETA", set()) and ("R60", "2") in nets.get("NETB", set()), \
        {n: v for n, v in nets.items() if any(r == "R60" for r, _p in v)}


def test_a_copy_of_a_part_on_the_sheet_still_works(proj, tmp_path):
    f = proj / SCH
    before = f.read_text()
    row = ("R52", "R1", "4.7k", "Resistor_SMD:R_0805_2012Metric", {1: "VIN", 2: "NEW_NET"})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [row])]) == 0
    after = f.read_text()
    part = next(after[s:e] for s, e in sch.Sheet(f).instances() if '(reference "R52")' in after[s:e])
    assert '(lib_id "Device:R")' in part and sch.prop(part, "Value") == "4.7k"
    assert after.count('(global_label "NEW_NET"') == 1 and after.count('(symbol "Device:R"') == before.count('(symbol "Device:R"')


def test_a_net_or_reference_with_a_quote_is_written_escaped(proj, tmp_path):
    """A net named A"B( and a reference R5"3: written as KiCad escapes them, so the
    sheet still reads and the label names the net (#191)."""
    from boardwright.model import _tree, balanced
    f = proj / SCH
    row = ('R5"3', "R1", "4.7k", "Resistor_SMD:R_0805_2012Metric", {1: "VIN", 2: 'A"B('})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [row])]) == 0
    after = f.read_text()
    assert '(global_label "A\\"B("' in after and '(reference "R5\\"3")' in after
    assert balanced(after)
    _tree(after)


def test_a_net_or_reference_with_a_backslash_is_written_escaped(proj, tmp_path):
    """A backslash survives too: a regex replacement template would have eaten it."""
    from boardwright.model import _tree
    f = proj / SCH
    row = ("R5\\9", "R1", "4.7k", "Resistor_SMD:R_0805_2012Metric", {1: "VIN", 2: "N\\1"})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [row])]) == 0
    after = f.read_text()
    assert '(global_label "N\\\\1"' in after and '(reference "R5\\\\9")' in after
    _tree(after)


def _alias(f, lib_id, name):
    """Give lib_id's cache entry and placed symbols the name KiCad gives an entry
    that differs from the library (GND_1 for power:GND): (symbol "NAME" ...) in
    the cache, (lib_name "NAME") on each placed symbol."""
    t = f.read_text()
    bare = lib_id.split(":", 1)[1]
    assert t.count(f'(symbol "{lib_id}"') == 1
    t = t.replace(f'(symbol "{lib_id}"', f'(symbol "{name}"', 1)
    t = re.sub(r'\(symbol "%s_(\d+_\d+)"' % re.escape(bare), lambda m: f'(symbol "{name}_{m.group(1)}"', t)
    t = t.replace(f'\t\t(lib_id "{lib_id}")', f'\t\t(lib_name "{name}")\n\t\t(lib_id "{lib_id}")')
    f.write_text(t)


def test_a_power_symbol_with_a_lib_name_is_copied_with_it(proj, tmp_path):
    """The sheet's PWR_FLAG goes by lib_name PWR_FLAG_1: a pin on its net gets a
    copy under the same name, and the cache keeps the one entry."""
    from boardwright.model import _tree
    f = proj / SCH
    _alias(f, "power:PWR_FLAG", "PWR_FLAG_1")
    row = ("R9", "R1", "1k", "", {1: "PWR_FLAG", 2: "X"})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [row])]) == 0
    after = f.read_text()
    assert after.count('(lib_name "PWR_FLAG_1")') == 3 and after.count('(symbol "PWR_FLAG_1"') == 1
    _tree(after)


def test_a_part_with_a_lib_name_is_copied(proj, tmp_path, capsys):
    from boardwright.model import _tree
    f = proj / SCH
    _alias(f, "Device:R", "R_1")
    row = ("R9", "R1", "1k", "", {1: "X", 2: "Y"})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [row])]) == 0
    assert "added R9 (Device:R, copied from R1)" in capsys.readouterr().out     # the symbol, not its alias
    after = f.read_text()
    part = next(after[s:e] for s, e in sch.Sheet(f).instances() if '(reference "R9")' in after[s:e])
    assert '(lib_name "R_1")' in part and after.count('(symbol "R_1"') == 1
    _tree(after)


def test_a_missing_pin_names_the_symbol_not_its_alias(proj, tmp_path, capsys):
    _alias(proj / SCH, "Device:R", "R_1")
    row = ("R9", "R1", "1k", "", {7: "X"})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [row])]) == 64
    assert "Device:R has no pin 7" in capsys.readouterr().err


def test_a_cached_entry_of_the_same_name_but_other_pins_is_refused():
    """A lib_name is local to a sheet: another sheet's R_1 can be a different
    symbol. Copying in a body whose pins differ from the one cached is refused."""
    pin = '\n\t\t\t(pin passive line (at 0 0 0) (length 1) (number "{}"))'
    def entry(*nums):
        return '\n\t\t(symbol "R_1"' + "".join(pin.format(n) for n in nums) + '\n\t\t)'
    t = '(kicad_sch\n\t(lib_symbols' + entry("1", "2") + '\n\t)\n)\n'
    assert sch._with_cached(t, "R_1", entry("1", "2")) == t
    with pytest.raises(SystemExit, match="already caches a different R_1"):
        sch._with_cached(t, "R_1", entry("1", "2", "3"))


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


def test_a_long_library_name_is_found_in_the_cache(proj, tmp_path):
    """LIB:NAME longer than the 40 characters the cache lookup once looked at."""
    long_nick = "A_Library_Nickname_Of_Some_Length"
    t = (proj / "sym-lib-table").read_text()
    (proj / "sym-lib-table").write_text(t.replace('(name "Mine")', f'(name "{long_nick}")'))
    row = ("R50", f"{long_nick}:R_new", "1k", "Resistor_SMD:R_0805_2012Metric", {1: "+3V3", 2: "GND"})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [row])]) == 0


@pytest.mark.parametrize("kind,table,var,lib", [
    ("SYMBOL", "sym-lib-table", "KICAD10_SYMBOL_DIR", "Device.kicad_sym"),
    ("FOOTPRINT", "fp-lib-table", "KICAD10_FOOTPRINT_DIR", "Resistor_SMD.pretty"),
])
def test_a_project_row_naming_the_stock_folder_is_found(tmp_path, monkeypatch, kind, table, var, lib):
    """KiCad's demo projects list stock libraries in their own tables as
    ${KICAD10_FOOTPRINT_DIR}/X.pretty. The variable is KiCad's built-in, not set
    in its settings, so it means the stock folder that was found."""
    from boardwright import env

    stock = tmp_path / "stock"
    (stock / lib).mkdir(parents=True)
    for v in ("KICAD_SYMBOL_DIR", "KICAD_FOOTPRINT_DIR", "KICAD10_SYMBOL_DIR", "KICAD10_FOOTPRINT_DIR",
              "KICAD9_SYMBOL_DIR", "KICAD9_FOOTPRINT_DIR"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(env, "_library_candidates", lambda dir_: [])   # only the folder named below exists
    monkeypatch.setenv(f"KICAD_{kind}_DIR", str(stock))
    d = tmp_path / "proj"
    d.mkdir()
    nick = lib.split(".")[0]
    (d / table).write_text(f'({table.replace("-", "_")}\n  (version 7)\n'
                           f'  (lib (name "{nick}")(type "KiCad")(uri "${{{var}}}/{lib}")(options "")(descr ""))\n)\n')
    assert sch._in_table(d / table, nick, d, kind=kind) == (True, stock / lib)


def _strip_pins(f, refs):
    """The sheet with the placed parts `refs` written without (pin ...) lines,
    as a part with no pins (a mounting hole, a logo) is."""
    t = f.read_text()
    for s, e in reversed(sch.Sheet(f).instances()):
        if sch.prop(t[s:e], "Reference") in refs:
            t = t[:s] + re.sub(r'\n\t\t\(pin "[^"]*" \(uuid "[^"]*"\)\n\t\t\)', "", t[s:e]) + t[e:]
    f.write_text(t)


def _two_styles(proj):
    """Mine:DS, a resistor with a second body style that draws pin 1 elsewhere:
    at (5.08, 0) pointing left, where style 1 has it at (0, 3.81) pointing down.
    Style 2 also draws a pin 3, which style 1 has not."""
    lib = proj / "libs" / "Mine.kicad_sym"
    t = lib.read_text()
    s, e = next((s, e) for s, e in sch.blocks(t, ("symbol",)) if t[s:s + 40].lstrip().startswith('(symbol "R_new"'))
    ds = t[s:e].replace('(symbol "R_new', '(symbol "DS')
    alt = ('\n\t\t(symbol "DS_1_2"\n\t\t\t(pin passive line (at 5.08 0 180) (length 1.27)'
           '\n\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))\n\t\t\t\t(number "1" (effects (font (size 1.27 1.27))))\n\t\t\t)'
           '\n\t\t\t(pin passive line (at 0 -3.81 90) (length 1.27)'
           '\n\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))\n\t\t\t\t(number "2" (effects (font (size 1.27 1.27))))\n\t\t\t)'
           '\n\t\t\t(pin passive line (at -5.08 0 0) (length 1.27)'
           '\n\t\t\t\t(name "~" (effects (font (size 1.27 1.27))))\n\t\t\t\t(number "3" (effects (font (size 1.27 1.27))))\n\t\t\t)\n\t\t)')
    ds = ds[:ds.rstrip().rfind(")")] + alt + "\n\t)"
    lib.write_text(t[:e] + "\n\t" + ds.lstrip() + t[e:])


def _stubs_start_on_pins(f, ref, wired=("1", "2")) -> tuple[int, int]:
    """Assert each pin of placed `ref` in `wired` has a wire starting on it,
    where KiCad draws the pin for the part's unit and body style; return that
    (unit, style)."""
    t = f.read_text()
    part = next(t[s:e] for s, e in sch.Sheet(f).instances() if f'(reference "{ref}")' in t[s:e])
    starts = {(round(float(a), 2), round(float(b), 2))
              for a, b, _c, _d in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)\s*\(xy ([-\d.]+) ([-\d.]+)\)", t)}
    pins = sch._placed_pins(t, part)
    assert set(wired) <= set(pins), sorted(pins)
    for num in wired:
        x, y, _a = pins[num]
        assert (round(x, 2), round(y, 2)) in starts, (ref, num, pins[num])
    return sch._unit_style(part)


@pytest.mark.parametrize("template_style", [None, 2])
def test_each_stub_starts_on_its_pin_as_the_placed_body_style_draws_it(proj, tmp_path, template_style):
    """A symbol with two body styles defines pin 1 twice. add placed body style 1
    but drew pin 1's stub from style 2's pin, so the label dangled and ERC
    reported pin 1 unconnected, while add printed the pin as joined. A part
    from the library is placed in style 1 even when the sheet's template part,
    whose head it copies, is drawn in style 2."""
    _two_styles(proj)
    f = proj / SCH
    if template_style:
        t = f.read_text()
        tpl = next(t[s:e] for s, e in sch.Sheet(f).instances() if sch.blocks(t[s:e], ("pin",)))
        assert tpl.count("\n\t\t(unit 1)") == 1
        f.write_text(t.replace(tpl, tpl.replace("\n\t\t(unit 1)", f"\n\t\t(unit 1)\n\t\t(body_style {template_style})"), 1))
    row = ("R60", "Mine:DS", "1k", "", {1: "NETA", 2: "NETB"})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [row])]) == 0
    assert _stubs_start_on_pins(f, "R60") == (1, 1)


def test_a_copy_keeps_its_body_style_and_draws_from_it(proj, tmp_path):
    """A part drawn in body style 2, copied, is placed in style 2 with its stubs
    on style 2's pins."""
    _two_styles(proj)
    f = proj / SCH
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("R60", "Mine:DS", "1k", "", {1: "A", 2: "B"})])]) == 0
    t = f.read_text()
    r60 = next(t[s:e] for s, e in sch.Sheet(f).instances() if '(reference "R60")' in t[s:e])
    f.write_text(t.replace(r60, re.sub(r"\n\t\t\(unit 1\)(\n\t\t\(body_style \d+\))?", "\n\t\t(unit 1)\n\t\t(body_style 2)", r60, count=1), 1))
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("R61", "R60", "1k", "", {1: "C", 2: "D", 3: "E"})])]) == 0
    assert _stubs_start_on_pins(f, "R61", ("1", "2", "3")) == (1, 2)       # pin 3 exists only in style 2


def _unit_two(proj, tmp_path):
    """U9, unit 2 of Mine:Dual2, whose unit 1 draws pins 1 and 2 and unit 2
    pins 3 and 4: an R from the library, turned into that part by hand, as add
    places no multi-unit part itself."""
    f = proj / SCH
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("U9", "Mine:R_new", "x", "", {})])]) == 0
    t = f.read_text()
    s, e = next((s, e) for s, e in sch.blocks(t, ("symbol",)) if t[s:s + 40].lstrip().startswith('(symbol "Mine:R_new"'))
    entry = t[s:e].replace('(symbol "Mine:R_new"', '(symbol "Mine:Dual2"').replace('(symbol "R_new_', '(symbol "Dual2_')
    inner = entry[1:]
    a, b = next((a, b) for a, b in sch.blocks(inner, ("symbol",)) if '"Dual2_1_1"' in inner[a:b])
    unit2 = inner[a:b].replace('"Dual2_1_1"', '"Dual2_2_1"').replace('(number "1"', '(number "3"').replace('(number "2"', '(number "4"')
    entry = entry[:1 + b] + "\n\t\t\t" + unit2.lstrip() + entry[1 + b:]
    t = t[:e] + "\n\t\t" + entry.lstrip() + t[e:]
    part = next(t[s:e] for s, e in sch.blocks(t, ("symbol",)) if t[s:s + 12].startswith("\n\t(symbol") and '(reference "U9")' in t[s:e])
    new = part.replace('(lib_id "Mine:R_new")', '(lib_id "Mine:Dual2")').replace("\n\t\t(unit 1)", "\n\t\t(unit 2)")
    new = new.replace('(pin "1"', '(pin "3"').replace('(pin "2"', '(pin "4"')
    f.write_text(t.replace(part, new, 1))


def test_a_pin_on_another_unit_names_the_unit(proj, tmp_path, capsys):
    """Copying unit 2 with a pin map naming unit 1's pin wired it to unit 2's
    geometry in 0.17.1, a wrong net in KiCad; now it is refused, naming the unit."""
    _unit_two(proj, tmp_path)
    f = proj / SCH
    before = f.read_text()
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("U10", "U9", "x", "", {1: "NX"})])]) == 64
    assert "Mine:Dual2 has pin 1 on unit 1, not on unit 2, which U9 is" in capsys.readouterr().err
    assert f.read_text() == before
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("U11", "U9", "x", "", {3: "NY", 4: "NZ"})])]) == 0
    assert _stubs_start_on_pins(f, "U11", ("3", "4")) == (2, 1)


def test_a_library_part_is_added_when_the_first_part_has_no_pins(proj, tmp_path):
    """#99: add took its pin lines from the sheet's first placed part, J1 here,
    and crashed (StopIteration, exit 2) when it had none."""
    _strip_pins(proj / SCH, {"J1"})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [R50])]) == 0
    after = (proj / SCH).read_text()
    part = next(after[s:e] for s, e in sch.Sheet(proj / SCH).instances() if '(lib_id "Mine:R_new")' in after[s:e])
    assert sorted(re.findall(r'\(pin "([^"]*)"', part)) == ["1", "2"]


def test_a_sheet_with_no_pinned_part_refuses_a_library_part_with_a_message(proj, tmp_path, capsys):
    f = proj / SCH
    _strip_pins(f, {sch.prop(f.read_text()[s:e], "Reference") for s, e in sch.Sheet(f).instances()})
    before = f.read_text()
    assert main(["sch", str(proj), "add", _spec(tmp_path, [R50])]) == 1
    assert "no placed part on the sheet has a pin" in capsys.readouterr().err
    assert f.read_text() == before


def test_a_sheet_with_no_pinned_part_still_copies_an_existing_part(proj, tmp_path):
    f = proj / SCH
    _strip_pins(f, {sch.prop(f.read_text()[s:e], "Reference") for s, e in sch.Sheet(f).instances()})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("R51", "R1", "2k", "Resistor_SMD:R_0805_2012Metric",
                                                              {1: "+3V3", 2: "GND"})])]) == 0
    assert '(reference "R51")' in f.read_text()


def _led_a_local(f):
    """LED_A's two global labels turned into local labels at the same places,
    so KiCad's netlist names the net /LED_A."""
    t = f.read_text()
    t, n = re.subn(r'\t\(global_label "LED_A" \(shape bidirectional\) \(at ([-\d.]+ [-\d.]+ [-\d.]+)\) \(fields_autoplaced yes\)\n'
                   r'\t\t\(effects\n\t\t\t\(font\n\t\t\t\t\(size 1\.27 1\.27\)\n\t\t\t\)\n\t\t\t\(justify left\)\n\t\t\)\n'
                   r'\t\t\(uuid "([^"]+)"\)\n\t\)',
                   lambda m: f'\t(label "LED_A"\n\t\t(at {m.group(1)})\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n'
                             f'\t\t\t)\n\t\t\t(justify left bottom)\n\t\t)\n\t\t(uuid "{m.group(2)}")\n\t)', t)
    assert n == 2
    f.write_text(t)


@pytest.mark.parametrize("net", ["/LED_A", "LED_A"])
def test_a_netlist_name_joins_the_local_label(proj, tmp_path, capsys, net):
    """#102: KiCad's netlist calls the root sheet's local label LED_A "/LED_A".
    That name, like the bare one, joins the label; it wrote (label "/LED_A"),
    a net of its own."""
    f = proj / SCH
    _led_a_local(f)
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("R50", "R1", "1k", "Resistor_SMD:R_0805_2012Metric",
                                                              {1: net, 2: "GND"})])]) == 0
    assert "R50.1 -> LED_A  [label]" in capsys.readouterr().out
    after = f.read_text()
    assert '(label "/LED_A"' not in after and after.count('(label "LED_A"') == 3


@pytest.mark.parametrize("net", ["SDA/A4", "SDA{slash}A4"])
def test_a_slash_in_a_name_joins_the_label_kicad_stores_with_slash(proj, tmp_path, capsys, net):
    """#210: KiCad shows SDA{slash}A4 as SDA/A4, and move accepts that form;
    add refused it as a sheet path. Both forms join the one label, and the pin
    is printed as KiCad shows it."""
    f = proj / SCH
    first = ("R70", "R1", "1k", "", {1: "SDA{slash}A4", 2: "GND"})
    assert main(["sch", str(proj), "add", _spec(tmp_path, [first])]) == 0
    capsys.readouterr()
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("R71", "R1", "1k", "", {1: net, 2: "GND"})])]) == 0
    assert "R71.1 -> SDA/A4  [global label]" in capsys.readouterr().out
    after = f.read_text()
    assert after.count('"SDA{slash}A4"') == 2 and '"SDA/A4"' not in after


def test_a_new_net_with_a_slash_is_written_as_kicad_stores_it(proj, tmp_path, capsys):
    f = proj / SCH
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("R70", "R1", "1k", "", {1: "I2C_CLK/A5", 2: "GND"})])]) == 0
    assert "R70.1 -> I2C_CLK/A5  [global label (new net)]" in capsys.readouterr().out
    after = f.read_text()
    assert '"I2C_CLK{slash}A5"' in after and '"I2C_CLK/A5"' not in after


def test_a_netlist_name_joins_a_local_label_with_a_slash(proj, tmp_path, capsys):
    """KiCad's XML netlist names the root's local label LED{slash}A /LED/A (its
    s-expression netlist, /LED{slash}A)."""
    f = proj / SCH
    _led_a_local(f)
    f.write_text(f.read_text().replace('(label "LED_A"', '(label "LED{slash}A"'))
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("R50", "R1", "1k", "", {1: "/LED/A", 2: "GND"})])]) == 0
    assert "R50.1 -> LED/A  [label]" in capsys.readouterr().out
    assert f.read_text().count('(label "LED{slash}A"') == 3


@pytest.mark.parametrize("net", ["/NOPE", "/sub/LED_A", "/LED_A/x"])
def test_a_slashed_name_that_is_no_label_here_is_refused(proj, tmp_path, capsys, net):
    f = proj / SCH
    _led_a_local(f)
    before = f.read_text()
    assert main(["sch", str(proj), "add", _spec(tmp_path, [("R50", "R1", "1k", "Resistor_SMD:R_0805_2012Metric",
                                                              {1: net, 2: "GND"})])]) == 64
    assert "is not a label on ldo_breakout.kicad_sch" in capsys.readouterr().err
    assert f.read_text() == before


def test_a_sub_sheet_path_is_its_sheet_names(tmp_path):
    def sheet(name, *subs):
        body = "".join(f'\t(sheet\n\t\t(property "Sheetname" "{n}"\n\t\t)\n\t\t(property "Sheetfile" "{f}"\n\t\t)\n\t)\n'
                       for n, f in subs)
        (tmp_path / name).write_text(f"(kicad_sch\n{body})\n")
        return sch.Sheet(tmp_path / name)
    top, io, adc = sheet("top.kicad_sch", ("io", "io.kicad_sch")), sheet("io.kicad_sch", ("adc", "adc.kicad_sch")), sheet("adc.kicad_sch")
    all_ = [top, io, adc]
    assert [sch._sheet_path(s, all_, top.path) for s in all_] == ["/", "/io/", "/io/adc/"]


def test_a_known_name_with_a_slash_is_matched_as_written():
    """A power symbol's Value such as VCC/2 is matched as its Value reads; turned
    into VCC{slash}2 it would become a label of its own, not the power net."""
    assert sch._local_name("VCC/2", "/", set(), {"VCC/2"}, "x.kicad_sch") == "VCC/2"
    assert sch._local_name("SDA/A4", "/", set(), set(), "x.kicad_sch") == "SDA{slash}A4"


def test_a_sheet_path_without_its_leading_slash_is_refused():
    """io/LED_A names sub-sheet io's label LED_A with its leading / dropped. Written
    as a new net it would be io{slash}LED_A, on its own; KiCad's netlist put such
    a pin alone on /io/io/LED_A."""
    with pytest.raises(sch.Usage, match=r"starts with the sheet name 'io'.*\(/io/LED_A\)"):
        sch._local_name("io/LED_A", "/", set(), set(), "x.kicad_sch", frozenset({"io"}))
    assert sch._local_name("ion/LED_A", "/", set(), set(), "x.kicad_sch", frozenset({"io"})) == "ion{slash}LED_A"
