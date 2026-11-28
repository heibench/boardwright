"""`existing reroute` takes a net as the board stores it (/ESTOP{slash}D2) or as
KiCad shows it in its DRC report and XML netlist (/ESTOP/D2) (#223)."""

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


def test_the_stored_name_wins_with_a_note(capsys):
    """/ESTOP/D2 stored so is sheet ESTOP's label D2; the root's label ESTOP/D2,
    stored /ESTOP{slash}D2, shows the same way. The stored name is that net."""
    known = {"/ESTOP{slash}D2", "/ESTOP/D2"}
    assert existing._board_net("/ESTOP/D2", known) == "/ESTOP/D2"
    assert "shows the same way" in capsys.readouterr().err
    assert existing._board_net("/ESTOP{slash}D2", known) == "/ESTOP{slash}D2"


def test_a_shown_name_two_stored_nets_share_is_refused():
    """A label B/C on sheet A is /A/B{slash}C; a root label A/B/C is
    /A{slash}B{slash}C. KiCad 10.0.8's DRC shows both as /A/B/C."""
    with pytest.raises(Usage, match=r"could be '/A/B\{slash\}C' or '/A\{slash\}B\{slash\}C'"):
        existing._board_net("/A/B/C", {"/A/B{slash}C", "/A{slash}B{slash}C"})


def test_a_net_is_printed_so_that_it_types_back_in_as_itself():
    known = {"V{slash}IN", "GND"}
    assert existing._named("V{slash}IN", known) == "V/IN"
    known = {"/V{slash}IN", "/V/IN"}                                    # /V/IN shows as itself and as the other
    assert existing._named("/V{slash}IN", known) == "/V{slash}IN"
    assert existing._named("/V/IN", known) == "/V/IN"
    for net in known | {"V{slash}IN"}:
        assert existing._board_net(existing._named(net, known | {"V{slash}IN"}), known | {"V{slash}IN"}) == net
    known = {"/A/B{slash}C", "/A{slash}B{slash}C"}                       # both show as /A/B/C, neither is stored so
    for net in known:
        assert existing._named(net, known) == net and existing._board_net(existing._named(net, known), known) == net


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


def test_reroute_reports_nets_as_kicad_shows_them(ldo_copy, monkeypatch, capsys):
    """A WIDE refusal names V/IN, as DRC does."""
    pcb = ldo_copy / "ldo_breakout.kicad_pcb"
    t = pcb.read_text(encoding="utf-8")
    pcb.write_text(t.replace('"VIN"', '"V{slash}IN"'), encoding="utf-8")
    from boardwright import route
    monkeypatch.setattr(route, "net_classes", lambda b: (lambda n: {"width": 0.01}))   # every track counts as wide
    assert main(["existing", str(ldo_copy), "reroute", "V/IN", "V{slash}IN"]) == 1        # named twice, judged once
    out = capsys.readouterr()
    assert "WIDE V/IN " in out.out and "{slash}" not in out.out
    assert "on ['V/IN']" in out.err


def test_a_net_named_twice_is_routed_once(ldo_copy, monkeypatch):
    """V/IN and V{slash}IN are one net: the router is handed it once."""
    pcb = ldo_copy / "ldo_breakout.kicad_pcb"
    pcb.write_text(pcb.read_text(encoding="utf-8").replace('"VIN"', '"V{slash}IN"'), encoding="utf-8")
    seen = {}
    def stop(pcb_, m, o, nets_, *a):
        seen["nets"] = list(nets_)
        raise RuntimeError("stop")
    monkeypatch.setattr(existing, "_route_and_graft", stop)
    with pytest.raises(RuntimeError, match="stop"):
        existing.reroute(ldo_copy, ["V/IN", "V{slash}IN"])
    assert seen["nets"] == ["V{slash}IN"]
