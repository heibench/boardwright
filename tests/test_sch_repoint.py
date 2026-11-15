import re
import subprocess
import xml.etree.ElementTree as ET

import pytest
from conftest import needs_kicad

from boardwright import sch
from boardwright.cli import main

SCH = "ldo_breakout.kicad_sch"


def _cached_r(text: str) -> str:
    """The schematic's cached Device:R, as a library symbol named R_copy."""
    s, e = next((s, e) for s, e in sch.blocks(text, ("symbol",)) if text[s:s + 40].lstrip().startswith('(symbol "Device:R"'))
    body = text[s:e]
    body = body.replace('(symbol "Device:R"', '(symbol "R_copy"', 1)
    body = re.sub(r'\(symbol "R_(\d+_\d+)"', r'(symbol "R_copy_\1"', body)
    return "\n".join(ln[1:] if ln.startswith("\t") else ln for ln in body.split("\n"))


@pytest.fixture
def proj(ldo_copy):
    """The LDO example with a local library 'Mine' holding variants of its resistor."""
    text = (ldo_copy / SCH).read_text()
    r_copy = _cached_r(text)
    r3 = r_copy.replace('(symbol "R_copy"', '(symbol "R3"', 1)
    r3 = re.sub(r'\(symbol "R_copy_(\d+_\d+)"', r'(symbol "R3_\1"', r3)
    pin2 = next(r3[s:e] for s, e in sch.blocks(r3, ("pin",)) if '(number "2"' in r3[s:e])
    r3 = r3.replace(pin2, pin2 + pin2.replace('(number "2"', '(number "3"'), 1)
    child = ('\n\t(symbol "R_child"\n\t\t(extends "R_copy")\n'
             '\t\t(property "Reference" "R"\n\t\t\t(at 0 0 0)\n\t\t)\n'
             '\t\t(property "Value" "R_child"\n\t\t\t(at 0 0 0)\n\t\t)\n\t)')
    (ldo_copy / "libs" / "Mine.kicad_sym").write_text(
        '(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "test")' + r_copy + r3 + child + "\n)\n")
    table = ldo_copy / "sym-lib-table"
    t = table.read_text()
    table.write_text(t.replace("\n)", '\n  (lib (name "Mine")(type "KiCad")(uri "${KIPRJMOD}/libs/Mine.kicad_sym")(options "")(descr ""))\n)', 1))
    return ldo_copy


def test_repoint_and_back_is_byte_identical(proj):
    f = proj / SCH
    before = f.read_text()
    assert sch.repoint(proj, "Device:R", "Mine:R_copy") == 0
    mid = f.read_text()
    assert '(lib_id "Device:R")' not in mid and mid.count('(lib_id "Mine:R_copy")') == before.count('(lib_id "Device:R")')
    assert '(symbol "Mine:R_copy"' in mid and '(symbol "R_copy_0_1"' in mid and '(symbol "R_0_1"' not in mid
    assert sch.repoint(proj, "Mine:R_copy", "Device:R") == 0
    assert f.read_text() == before


def test_different_pin_numbers_are_refused_and_nothing_written(proj, capsys):
    f = proj / SCH
    before = f.read_text()
    assert main(["sch", str(proj), "repoint", "Device:R", "Mine:R3"]) == 1
    assert "extra ['3']" in capsys.readouterr().err
    assert f.read_text() == before


def test_unknown_names_are_usage_errors(proj):
    f = proj / SCH
    before = f.read_text()
    assert main(["sch", str(proj), "repoint", "Device:R", "Mine:Nope"]) == 64
    assert main(["sch", str(proj), "repoint", "Device:R", "Nolib:R"]) == 64
    assert main(["sch", str(proj), "repoint", "Device:Q", "Mine:R_copy"]) == 64
    assert main(["sch", str(proj), "repoint", "Device:R", "Mine:R_copy", "--body", "maybe"]) == 64
    assert f.read_text() == before


def test_library_body_flattens_an_extends_symbol(proj):
    assert main(["sch", str(proj), "repoint", "Device:R", "Mine:R_child", "--body", "library"]) == 0
    text = (proj / SCH).read_text()
    entry = next(text[s:e] for s, e in sch.blocks(text, ("symbol",)) if text[s:s + 40].lstrip().startswith('(symbol "Mine:R_child"'))
    assert "(extends" not in entry
    assert '(property "Value" "R_child"' in entry
    assert '(symbol "R_child_1_1"' in entry and '(symbol "R_copy_' not in entry
    assert sch._pin_numbers(entry) == ["1", "2"]


def _nets(xml_text: str) -> set:
    root = ET.fromstring(xml_text)
    return {(n.get("name"), frozenset((x.get("ref"), x.get("pin")) for x in n.iter("node"))) for n in root.iter("net")}


@pytest.mark.kicad
@needs_kicad
@pytest.mark.parametrize("body", ["keep", "library"])
def test_kicad_sees_the_same_nets(proj, body, tmp_path):
    from boardwright import env

    cli = env.kicad_cli()

    def netlist(name):
        out = tmp_path / f"{name}.xml"
        subprocess.run([*cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(out), str(proj / SCH)],
                       check=True, capture_output=True)
        return out.read_text()

    before = _nets(netlist("before"))
    assert main(["sch", str(proj), "repoint", "Device:R", "Mine:R_copy", "--body", body]) == 0
    after = _nets(netlist("after"))
    assert before == after and len(before) >= 4


def test_two_symbols_onto_one_target_share_its_cache_entry(proj):
    """Two different symbols re-pointed to the same target: the second finds the
    target cached already and drops its own entry."""
    f = proj / SCH
    assert sch.repoint(proj, "Device:R", "Mine:R_copy") == 0
    assert sch.repoint(proj, "Mine:R_copy", "Mine:R_child", "library") == 0
    text = f.read_text()
    assert text.count('(symbol "Mine:R_child"') == 1 and '(symbol "Mine:R_copy"' not in text


def test_a_stale_cached_target_is_refused(proj):
    """The old symbol and the library's target agree on pins, but the schematic
    already caches the target with an extra pin: moving parts onto that copy with
    --body keep would silently use it, so the edit is refused."""
    f = proj / SCH
    text = f.read_text()
    e = next(text[s:e] for s, e in sch.blocks(text, ("symbol",)) if text[s:s + 40].lstrip().startswith('(symbol "Device:R"'))
    stale = e.replace('(symbol "Device:R"', '(symbol "Mine:R_copy"', 1).replace('(symbol "R_', '(symbol "R_copy_')
    pin2 = next(stale[s:e2] for s, e2 in sch.blocks(stale, ("pin",)) if '(number "2"' in stale[s:e2])
    stale = stale.replace(pin2, pin2 + pin2.replace('(number "2"', '(number "3"'), 1)
    f.write_text(text.replace(e, e + stale, 1))
    before = f.read_text()
    assert main(["sch", str(proj), "repoint", "Device:R", "Mine:R_copy"]) == 1
    assert f.read_text() == before
