"""`existing reroute` takes a net as the board stores it (/ESTOP{slash}D2) or as
KiCad shows it in its GUI, DRC report and XML netlist (/ESTOP/D2) (#223)."""

import sys

import pytest

from boardwright import env, existing
from boardwright.cli import main
from boardwright.errors import Usage


def test_a_shown_name_maps_to_the_stored_one():
    known = {"/ESTOP{slash}D2", "GND", "VIN"}
    assert existing._board_net("/ESTOP/D2", known) == "/ESTOP{slash}D2"
    assert existing._board_net("/ESTOP{slash}D2", known) == "/ESTOP{slash}D2"
    assert existing._board_net("GND", known) == "GND"
    with pytest.raises(Usage, match="no net '/NOPE'"):
        existing._board_net("/NOPE", known)


def test_a_name_two_stored_nets_show_as_is_refused():
    """/ESTOP/D2 is both the root's label ESTOP/D2 and sheet ESTOP's label D2."""
    known = {"/ESTOP{slash}D2", "/ESTOP/D2"}
    with pytest.raises(Usage, match="could be '/ESTOP/D2' or '/ESTOP{slash}D2'"):
        existing._board_net("/ESTOP/D2", known)
    assert existing._board_net("/ESTOP{slash}D2", known) == "/ESTOP{slash}D2"   # the stored form is never ambiguous


def test_reroute_runs_on_a_shown_name(ldo_copy, monkeypatch, capsys):
    """VIN renamed V{slash}IN on the board: reroute V/IN reaches the router (a
    stand-in that writes no SES), where 0.17.3 stopped with "no net"."""
    pcb = ldo_copy / "ldo_breakout.kicad_pcb"
    t = pcb.read_text(encoding="utf-8")
    assert '"VIN"' in t
    pcb.write_text(t.replace('"VIN"', '"V{slash}IN"'), encoding="utf-8")
    monkeypatch.setattr(env, "freerouting", lambda: [sys.executable, "-c", "pass"])
    assert main(["existing", str(ldo_copy), "reroute", "V/IN"]) == 4
    err = capsys.readouterr().err
    assert "no net" not in err and "freerouting produced no SES" in err
