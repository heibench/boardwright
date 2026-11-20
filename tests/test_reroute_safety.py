"""`existing reroute` and `existing apply` change nothing when they cannot finish
(#104, #105, #107). The router here is a stand-in: these failures happen before
or instead of a route, so they need no Freerouting."""

import hashlib
import sys

import pytest

from boardwright import copper, dsn, env
from boardwright.cli import main
from boardwright.errors import EnvironmentFault, Usage


def _hash(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture
def board(ldo_copy):
    return ldo_copy / "ldo_breakout.kicad_pcb"


@pytest.mark.parametrize("router, spec, says", [
    ("pass", "", "freerouting produced no SES"),
    ("import time; time.sleep(30)", "FR_TIMEOUT = 0.5\n", "freerouting did not finish in FR_TIMEOUT = 0.5 s"),
], ids=["no SES", "timeout"])
def test_a_failed_reroute_leaves_the_board_as_it_was(ldo_copy, board, monkeypatch, capsys, router, spec, says):
    """It wrote the ripped-up board and left it there: LED_A's track was gone,
    and a timeout said "nothing was checked or written" (#104)."""
    monkeypatch.setattr(env, "freerouting", lambda: [sys.executable, "-c", router])
    if spec:
        (ldo_copy / "boardwright.py").write_text(spec)
    before = _hash(board)
    assert main(["existing", str(ldo_copy), "reroute", "LED_A"]) == 4
    err = capsys.readouterr().err
    assert says in err and "restored as it was read; nothing changed" in err
    assert _hash(board) == before


def test_an_open_outline_stops_the_export_naming_its_ends(ldo_copy, board, monkeypatch, capsys):
    """A 5 um gap gave a DSN with no boundary, on which Freerouting 2.5.0 throws
    a NullPointerException (#105). Now the export refuses, and reroute leaves the
    board as it was."""
    t = board.read_text()
    a = "(gr_line\n\t\t(start 133.5 95)\n\t\t(end 163.5 95)"
    assert t.count(a) == 1
    board.write_text(t.replace(a, "(gr_line\n\t\t(start 133.5 95)\n\t\t(end 163.495 95)"))
    with pytest.raises(EnvironmentFault, match=r"open ends at \(163\.495, 95\), \(163\.5, 95\)"):
        dsn.export(board, ldo_copy / "x.dsn")
    monkeypatch.setattr(env, "freerouting", lambda: pytest.fail("no route without an outline"))
    before = _hash(board)
    assert main(["existing", str(ldo_copy), "reroute", "LED_A"]) == 4
    assert "does not close within 1 um" in capsys.readouterr().err
    assert _hash(board) == before


@pytest.mark.parametrize("entry", [("LED_A", (10.0, 10.0)), ("LED_A", 10.0), ("LED_A", 1.0, 2.0, 0.6),
                                   (None, 1.0, 2.0), ("LED_A", "1", 2.0), "LED_A"])
def test_a_via_in_another_form_is_a_usage_error(entry):
    with pytest.raises(Usage, match=r"is not \(net, x, y\[, size, drill\]\)"):
        copper.check_vias(type("M", (), {"VIAS": [entry]}))


@pytest.mark.parametrize("entry", [("LED_A", 1.0, 2.0), ("LED_A", 1, 2, 0.6, 0.3), ["LED_A", 1.0, 2.0]])
def test_the_documented_via_forms_pass(entry):
    copper.check_vias(type("M", (), {"VIAS": [entry]}))


def test_apply_refuses_a_bad_via_before_ripping_anything_up(ldo_copy, board, capsys):
    """It ripped up and moved first, then crashed with an IndexError, exit 2 (#107)."""
    (ldo_copy / "boardwright.py").write_text('RIPUP = ["LED_A"]\nVIAS = [("LED_A", (10.0, 10.0))]\n')
    before = _hash(board)
    assert main(["existing", str(ldo_copy), "apply"]) == 64
    assert "VIAS entry ('LED_A', (10.0, 10.0)) is not (net, x, y[, size, drill])" in capsys.readouterr().err
    assert _hash(board) == before
