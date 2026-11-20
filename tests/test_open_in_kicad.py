"""A file edit warns when KiCad has the file open (#46, item 3)."""

import pytest

from boardwright import env
from boardwright.cli import main


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(env, "_warned_open", set())


def test_sch_set_warns_once_when_kicad_holds_the_lock_and_still_writes(ldo_copy, capsys):
    """KiCad 10.0.8 keeps ~<name>.lck beside an open document; its next save
    would overwrite this edit. The edit goes ahead, with one warning."""
    f = ldo_copy / "ldo_breakout.kicad_sch"
    (ldo_copy / "~ldo_breakout.kicad_sch.lck").write_text("")
    assert main(["sch", str(ldo_copy), "set", "R1", "Value=4k7"]) == 0
    assert main(["sch", str(ldo_copy), "set", "R1", "Value=10k"]) == 0
    err = capsys.readouterr().err
    assert err.count("warning: KiCad has ldo_breakout.kicad_sch open (~ldo_breakout.kicad_sch.lck is beside it)") == 1
    assert '"10k"' in f.read_text()


def test_no_lock_no_warning(ldo_copy, capsys):
    assert main(["sch", str(ldo_copy), "set", "R1", "Value=4k7"]) == 0
    assert "warning" not in capsys.readouterr().err


def test_a_lock_for_another_file_does_not_warn(ldo_copy, capsys):
    (ldo_copy / "~ldo_breakout.kicad_pcb.lck").write_text("")
    assert main(["sch", str(ldo_copy), "set", "R1", "Value=4k7"]) == 0
    assert "warning" not in capsys.readouterr().err


def test_the_board_lock_name(tmp_path, capsys):
    pcb = tmp_path / "x.kicad_pcb"
    env.warn_if_open_in_kicad(pcb)
    assert capsys.readouterr().err == ""
    (tmp_path / "~x.kicad_pcb.lck").write_text("")
    env.warn_if_open_in_kicad(pcb)
    assert "KiCad has x.kicad_pcb open (~x.kicad_pcb.lck is beside it)" in capsys.readouterr().err
