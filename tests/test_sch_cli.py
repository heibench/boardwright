import difflib
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


def test_parts_fields_show_each_uses_own_reference(ldo_copy, capsys):
    """On a sheet used twice the shared Reference property holds one use's name."""
    f = ldo_copy / "ldo_breakout.kicad_sch"
    t = f.read_text()
    a = '(reference "R1") (unit 1)\n\t\t\t\t)'
    assert t.count(a) == 1
    f.write_text(t.replace(a, a + '\n\t\t\t\t(path "/aaaa" (reference "R9") (unit 1)\n\t\t\t\t)'))
    sch.parts(ldo_copy, "R[19]", "Ref*")
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines] == ["R1", "R9"]
    assert lines[0].endswith('Reference="R1"') and lines[1].endswith('Reference="R9"')
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


def _two_uses(ldo_copy):
    """R1's symbol given a second use, R5, as on a sheet placed twice."""
    f = ldo_copy / "ldo_breakout.kicad_sch"
    t = f.read_text()
    a = '(reference "R1") (unit 1)\n\t\t\t\t)'
    assert t.count(a) == 1
    f.write_text(t.replace(a, a + '\n\t\t\t\t(path "/aaaa" (reference "R5") (unit 1)\n\t\t\t\t)'))
    return f


def test_on_a_sheet_used_twice_a_use_keeps_its_own_name(ldo_copy, capsys):
    f = _two_uses(ldo_copy)
    before = f.read_text()
    assert sch.set_fields(ldo_copy, "R5", ["Reference=R5", "Value=1k"]) == 0
    assert capsys.readouterr().out.splitlines() == ["R5: Reference unchanged (already R5)", "R5: Value unchanged (already 1k)"]
    assert f.read_text() == before
    assert sch.set_fields(ldo_copy, "R5", ["Value=2k"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "note: R5 is one use of a symbol on a sheet that is used more than once; this also changes R1",
        "R5: Value -> 2k"]


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


def test_one_use_of_a_shared_symbol_takes_a_backslash_reference(ldo_copy):
    f = _two_uses(ldo_copy)
    assert sch.set_fields(ldo_copy, "R5", ["Reference=R\\7"]) == 0
    text = f.read_text()
    assert '(reference "R\\\\7")' in text and '(reference "R1")' in text


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
