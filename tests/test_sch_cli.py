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


def test_exit_codes_follow_the_heibench_contract(ldo_copy, monkeypatch, capsys):
    # 64 usage: bad arguments, or a spec naming something that is not there
    assert main(["gen"]) == 64
    assert main(["sch", str(ldo_copy), "set", "R1", "Colour=blue"]) == 64
    assert main(["existing", str(ldo_copy), "no-such-step"]) == 64
    # 2 could not tell: verify with no KiCad reports is not a verdict
    assert main(["verify", str(ldo_copy)]) == 2
    assert "CANNOT TELL" in capsys.readouterr().out
    # 4 environment fault: no KiCad to run
    monkeypatch.setenv("NETSPEC_KICAD_CLI", "/nonexistent/kicad-cli")
    assert main(["check", str(ldo_copy)]) == 4
    # 1 violated: a finding about the design
    spec = ldo_copy / "spec.py"
    spec.write_text('REVIEW = {"maxlen": {"LED_A": 0.1}}\n')
    assert main(["review", str(ldo_copy / "ldo_breakout.kicad_pcb"), str(spec)]) == 1
