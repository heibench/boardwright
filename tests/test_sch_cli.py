import difflib
import re
import subprocess
import sys

import pytest

from boardwright import check, sch
from boardwright.cli import main


def changed_lines(before: str, after: str) -> list[str]:
    return [line for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
            if line[:1] in "+-" and not line.startswith(("+++", "---"))]


def test_set_value_changes_only_that_property(ldo_copy):
    f = ldo_copy / "ldo_breakout.kicad_sch"
    before = f.read_text()
    assert sch.set_fields(ldo_copy, "R1", ["Value=4k7"]) == 0
    diff = changed_lines(before, f.read_text())
    assert len(diff) == 2
    assert '"1k"' in diff[0] and '"4k7"' in diff[1]


def test_parts_with_fields_adds_the_matching_properties(ldo_copy, capsys):
    """For simulation schematics: the Sim.* fields, or any others, on the part's own line."""
    sch.parts(ldo_copy, "R1")
    plain = capsys.readouterr().out.rstrip("\n")
    sch.parts(ldo_copy, "R1", "Data*")
    assert capsys.readouterr().out.rstrip("\n") == plain + '  Datasheet="~"'
    sch.parts(ldo_copy, "R1", "Sim.*")
    assert capsys.readouterr().out.rstrip("\n") == plain


def test_parts_fields_show_a_value_as_the_file_holds_it(ldo_copy, capsys):
    sch.set_fields(ldo_copy, "R1", ['Value=a "b" c'])
    capsys.readouterr()
    sch.parts(ldo_copy, "R1", "Value")
    assert capsys.readouterr().out.rstrip("\n").endswith('  Value="a \\"b\\" c"')


def test_parts_fields_from_the_command_line(ldo_copy, capsys):
    assert main(["sch", str(ldo_copy), "parts", "R1", "--fields", "Data*"]) == 0
    assert capsys.readouterr().out.rstrip("\n").endswith('  Datasheet="~"')
    assert main(["sch", str(ldo_copy), "parts"]) == 0
    plain = capsys.readouterr().out.splitlines()
    assert main(["sch", str(ldo_copy), "parts", "--fields", "Data*"]) == 0     # no PATTERN: every part
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(plain) and all(line.startswith(p) for line, p in zip(lines, plain))
    assert sum('Datasheet="' in line for line in lines) >= 2                    # the fields are there
    assert main(["sch", str(ldo_copy), "parts", "--fields=Data*"]) == 0
    assert capsys.readouterr().out.splitlines() == lines


def test_parts_refuses_what_it_cannot_honour(ldo_copy, capsys):
    for args in (["R1", "--fields"], ["R1", "--fields", ""], ["R1", "D1"], ["R1", "--field", "Data*"], ["--verbose"],
                 ["-h"], ["R1", "--fields", "--fields=Data*"], ["--fields", "-x"]):
        assert main(["sch", str(ldo_copy), "parts", *args]) == 64, args


def test_parts_fields_match_names_with_case(ldo_copy, capsys):
    sch.parts(ldo_copy, "R1", "data*")
    assert "Datasheet" not in capsys.readouterr().out


def test_set_to_the_value_already_there_says_unchanged_and_writes_nothing(ldo_copy, capsys):
    """R1's Value is already 1k: a bulk-edit script must be able to tell this
    from an edit that landed, and the file is not written at all."""
    f = ldo_copy / "ldo_breakout.kicad_sch"
    before, mtime = f.read_text(), f.stat().st_mtime_ns
    assert sch.set_fields(ldo_copy, "R1", ["Value=1k", "dnp=no"]) == 0
    assert capsys.readouterr().out.splitlines() == ["R1: Value unchanged (already 1k)", "R1: dnp unchanged (already no)"]
    assert f.read_text() == before and f.stat().st_mtime_ns == mtime


def test_set_reports_each_pair_for_what_it_did(ldo_copy, capsys):
    f = ldo_copy / "ldo_breakout.kicad_sch"
    before = f.read_text()
    assert sch.set_fields(ldo_copy, "R1", ["Value=1k", "Value=4k7"]) == 0
    assert capsys.readouterr().out.splitlines() == ["R1: Value unchanged (already 1k)", "R1: Value -> 4k7"]
    assert len(changed_lines(before, f.read_text())) == 2


def test_set_flags_already_so_are_unchanged_and_a_flag_change_lands(ldo_copy, capsys):
    f = ldo_copy / "ldo_breakout.kicad_sch"
    before = f.read_text()
    assert main(["sch", str(ldo_copy), "set", "R1", "in_bom=yes", "on_board=yes"]) == 0
    assert capsys.readouterr().out.splitlines() == ["R1: in_bom unchanged (already yes)", "R1: on_board unchanged (already yes)"]
    assert f.read_text() == before
    assert main(["sch", str(ldo_copy), "set", "R1", "dnp=yes"]) == 0
    assert capsys.readouterr().out.splitlines() == ["R1: dnp -> yes"]
    assert len(changed_lines(before, f.read_text())) == 2


def test_pairs_that_cancel_out_say_nothing_was_written(ldo_copy, capsys):
    f = ldo_copy / "ldo_breakout.kicad_sch"
    before = f.read_text()
    assert sch.set_fields(ldo_copy, "R1", ["Value=4k7", "Value=1k"]) == 0
    assert capsys.readouterr().out.splitlines() == ["R1: nothing written: the pairs leave every field as it was"]
    assert f.read_text() == before


def test_a_refused_pair_reports_no_other_pair_as_done(ldo_copy, capsys):
    f = ldo_copy / "ldo_breakout.kicad_sch"
    before = f.read_text()
    with pytest.raises(SystemExit, match="no property"):
        sch.set_fields(ldo_copy, "R1", ["Value=4k7", "Colour=blue"])
    assert capsys.readouterr().out == "" and f.read_text() == before


def test_a_refused_write_reports_nothing_as_done(ldo_copy, capsys, monkeypatch):
    """The file changed on disk between read and write: the write refuses, and
    no line claims an edit."""
    f = ldo_copy / "ldo_breakout.kicad_sch"
    real = sch.Sheet.write

    def changed_meanwhile(self, new):
        f.write_text(f.read_text() + "\n")
        return real(self, new)
    monkeypatch.setattr(sch.Sheet, "write", changed_meanwhile)
    with pytest.raises(SystemExit, match="changed on disk"):
        sch.set_fields(ldo_copy, "R1", ["Value=4k7"])
    assert capsys.readouterr().out == ""


def test_unchanged_shows_a_value_as_typed_not_as_escaped(ldo_copy, capsys):
    sch.set_fields(ldo_copy, "R1", ['Value=a "b" c'])
    capsys.readouterr()
    sch.set_fields(ldo_copy, "R1", ['Value=a "b" c'])
    assert capsys.readouterr().out.splitlines() == ['R1: Value unchanged (already a "b" c)']


def test_a_pair_with_no_equals_is_refused_and_nothing_written(ldo_copy, capsys):
    f = ldo_copy / "ldo_breakout.kicad_sch"
    before = f.read_text()
    assert main(["sch", str(ldo_copy), "set", "R1", "Value=4k7", "Value"]) == 64
    assert "'Value' has no '=': write Value=VALUE, or Value= to empty it" in capsys.readouterr().err
    assert main(["sch", str(ldo_copy), "set", "R1", "dnp"]) == 64
    assert "'dnp' has no '=': write dnp=yes or dnp=no" in capsys.readouterr().err
    assert main(["sch", str(ldo_copy), "set", "R1", "Colour"]) == 64              # no such property: say so
    assert "R1 has no property 'Colour'" in capsys.readouterr().err
    assert f.read_text() == before


def test_an_explicit_empty_value_still_empties_the_field(ldo_copy, capsys):
    f = ldo_copy / "ldo_breakout.kicad_sch"
    assert sch.set_fields(ldo_copy, "R1", ["Value="]) == 0
    assert capsys.readouterr().out.splitlines() == ["R1: Value -> "]
    assert '(property "Value" ""' in f.read_text()


def test_a_reference_with_a_backslash_is_set_alike_in_both_places(ldo_copy):
    """The property and the instance's (reference ...) both hold R\\1."""
    f = ldo_copy / "ldo_breakout.kicad_sch"
    assert sch.set_fields(ldo_copy, "R1", ["Reference=R\\1"]) == 0
    text = f.read_text()
    assert '(property "Reference" "R\\\\1"' in text and '(reference "R\\\\1")' in text


def test_set_unknown_property_is_refused(ldo_copy):
    with pytest.raises(SystemExit, match="no property"):
        sch.set_fields(ldo_copy, "R1", ["Colour=blue"])


def test_remove_takes_out_one_symbol(ldo_copy):
    f = ldo_copy / "ldo_breakout.kicad_sch"
    sch.remove(ldo_copy, ["D1"])
    text = f.read_text()
    assert '"D1"' not in text and '"R1"' in text


def test_unknown_reference(ldo_copy):
    with pytest.raises(SystemExit):
        sch.set_fields(ldo_copy, "Q9", ["Value=x"])


def test_gate_steps_cover_drc_erc_and_fab_outputs(ldo_copy):
    full = [" ".join(s[:3]) for s in check.steps(ldo_copy)]
    quick = [" ".join(s[:3]) for s in check.steps(ldo_copy, quick=True)]
    assert any(s.startswith("pcb drc") for s in quick)
    assert not any(s.startswith("sch erc") for s in quick)
    for want in ("sch erc", "pcb export gerbers", "pcb export drill", "sch export netlist"):
        assert any(s.startswith(want) for s in full), want
    drc = next(s for s in check.steps(ldo_copy) if s[:2] == ["pcb", "drc"])
    assert {"--severity-all", "--schematic-parity", "--refill-zones"} <= set(drc)


def test_cli_version_and_help(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.startswith("boardwright ")
    assert main([]) == 0
    assert "boardwright gen DIR" in capsys.readouterr().out
    assert main(["no-such-command"]) == 64


def test_cli_review_exit_codes(tmp_path):
    from conftest import board

    ok = subprocess.run([sys.executable, "-m", "boardwright", "review", str(board("ldo_breakout"))],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    spec = tmp_path / "spec.py"
    spec.write_text('REVIEW = {"maxlen": {"LED_A": 0.1}}\n')
    bad = subprocess.run([sys.executable, "-m", "boardwright", "review", str(board("ldo_breakout")), str(spec)],
                         capture_output=True, text=True)
    assert bad.returncode == 1 and "LED_A" in bad.stdout


@pytest.fixture(params=["kicad present", "kicad absent"])
def machine(request, monkeypatch):
    """Run under this machine's KiCad, and again as if none were installed."""
    if request.param == "kicad absent":
        from boardwright import env

        for v in ("KICAD", "KICAD10", "KICAD9"):
            monkeypatch.delenv(f"{v}_SYMBOL_DIR", raising=False)
            monkeypatch.delenv(f"{v}_FOOTPRINT_DIR", raising=False)
        monkeypatch.setattr(env, "_library_candidates", lambda dir_: [])
        monkeypatch.setenv("BOARDWRIGHT_KICAD_CLI", "/nonexistent/kicad-cli")
        monkeypatch.setenv("BOARDWRIGHT_FREEROUTING", "/nonexistent/freerouting")
    return request.param


def test_exit_codes_follow_the_heibench_contract(ldo_copy, monkeypatch, capsys, machine):
    # 64 usage: bad arguments, or a spec naming something that is not there
    assert main(["gen"]) == 64
    assert main(["gen", str(ldo_copy / "nowhere")]) == 64
    assert main(["pins"]) == 64
    assert main(["no-such-command"]) == 64
    assert main(["sch", str(ldo_copy), "set", "R1", "Colour=blue"]) == 64
    assert main(["existing", str(ldo_copy), "no-such-step"]) == 64
    # 2 could not tell: verify with no KiCad reports is not a verdict
    assert main(["verify", str(ldo_copy)]) == 2
    assert "CANNOT TELL" in capsys.readouterr().out
    # 4 environment fault: no KiCad to run
    monkeypatch.setenv("BOARDWRIGHT_KICAD_CLI", "/nonexistent/kicad-cli")
    assert main(["check", str(ldo_copy)]) == 4
    # 1 violated: a finding about the design
    spec = ldo_copy / "spec.py"
    spec.write_text('REVIEW = {"maxlen": {"LED_A": 0.1}}\n')
    assert main(["review", str(ldo_copy / "ldo_breakout.kicad_pcb"), str(spec)]) == 1


def test_the_newest_kicad_settings_folder_wins(tmp_path, monkeypatch):
    from boardwright import env

    monkeypatch.delenv("KICAD_CONFIG_HOME")
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    old = tmp_path / ".config/kicad/9.0"
    new = tmp_path / ".var/app/org.kicad.KiCad/config/kicad/10.0"
    for d in (old, new):
        d.mkdir(parents=True)
        (d / "sym-lib-table").write_text("(sym_lib_table)\n")
    assert env.kicad_config() == new


STALE = '\n\t\t\t(project "Other"\n\t\t\t\t(path "/00000000-1111-2222-3333-444444444444" (reference "C9") (unit 1)\n\t\t\t\t)\n\t\t\t)'


def _stale_c1(ldo_copy):
    """C1 given a second instance entry, as a sheet copied from another project
    carries: another project, a path outside this hierarchy, reference C9."""
    f = ldo_copy / "ldo_breakout.kicad_sch"
    t = f.read_text(encoding="utf-8")
    i = t.index('(reference "C1") (unit 1)')
    k = t.index("\n\t\t\t)", i) + len("\n\t\t\t)")
    f.write_text(t[:k] + STALE + t[k:], encoding="utf-8")
    return f


def test_an_instance_entry_from_another_hierarchy_is_not_a_reference(ldo_copy, capsys):
    """#209: KiCad 10's netlist names C1, not C9: it keeps the entry on this
    hierarchy's path. parts listed C9 too, and set and remove found it."""
    _stale_c1(ldo_copy)
    sch.parts(ldo_copy, "C*")
    assert [ln.split()[0] for ln in capsys.readouterr().out.splitlines()] == ["C1", "C2"]
    with pytest.raises(SystemExit, match="0 symbols have the reference 'C9'"):
        sch.set_fields(ldo_copy, "C9", ["Value=1u"])
    assert sch.set_fields(ldo_copy, "C1", ["Value=22u"]) == 0
    assert "shares" not in capsys.readouterr().out                  # not taken for a second use


def test_two_entries_on_this_hierarchys_path_take_the_last():
    block = ('\t(symbol\n\t\t(property "Reference" "C1")\n\t\t(instances\n\t\t\t(project "a"\n'
             '\t\t\t\t(path "/r" (reference "C1") (unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t\t(project "b"\n'
             '\t\t\t\t(path "/r" (reference "C9") (unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)')
    assert sch.refs(block, frozenset({"/r"})) == ["C9"]
    assert sch.refs(block, frozenset({"/elsewhere"})) == ["C1", "C9"]  # no entry on this hierarchy: all, as before
    assert sch._instance_path(block, frozenset({"/r"})) == "/r"


def test_a_new_part_takes_this_hierarchys_path_not_a_stale_one(ldo_copy):
    """add copies its template part's instance path; with a stale entry first,
    the first path was the foreign one, and the new part sat outside the hierarchy."""
    block = ('\t(symbol\n\t\t(instances\n\t\t\t(project "Other"\n\t\t\t\t(path "/x" (reference "C9") (unit 1)\n'
             '\t\t\t\t)\n\t\t\t)\n\t\t\t(project "p"\n\t\t\t\t(path "/r" (reference "C1") (unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)')
    assert sch._instance_path(block, frozenset({"/r"})) == "/r"
    f = ldo_copy / "ldo_breakout.kicad_sch"
    t = f.read_text(encoding="utf-8")
    root = "/" + re.search(r'\n\t\(uuid "([^"]*)"\)', t).group(1)
    first = next(t[s:e] for s, e in sch.Sheet(f).instances() if sch.blocks(t[s:e], ("pin",)))   # add's template
    ins = first.index("\t\t\t(project ")
    f.write_text(t.replace(first, first[:ins] + STALE.lstrip("\n") + "\n" + first[ins:], 1), encoding="utf-8")
    spec = ldo_copy / "spec.py"
    spec.write_text('ADD = [("R70", "Device:R", "1k", "", {1: "VIN", 2: "GND"})]\n', encoding="utf-8")
    assert main(["sch", str(ldo_copy), "add", str(spec)]) == 0
    t = f.read_text(encoding="utf-8")
    r70 = next(t[s:e] for s, e in sch.Sheet(f).instances() if '(reference "R70")' in t[s:e])
    assert [p for p, _r in sch._entries(r70)] == [root], sch._entries(r70)
    assert '(project "Other"' not in r70                                # the stale project's entry is not copied
