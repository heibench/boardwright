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


def test_plane_layers_are_the_inner_zone_only_layers_unless_planes_says():
    """#106: reroute ran signals through stm32f103_4l's In1/In2 GND planes."""
    from types import SimpleNamespace

    from conftest import BOARDS

    from boardwright import existing
    from boardwright.model import Board

    four = Board(BOARDS / "stm32f103_4l" / "stm32f103_4l.kicad_pcb")
    two = Board(BOARDS / "ldo_breakout" / "ldo_breakout.kicad_pcb")      # GND pour on both outer layers
    none = SimpleNamespace()
    assert existing.plane_layers(four, none) == ["In1.Cu", "In2.Cu"]
    assert existing.plane_layers(two, none) == []
    assert existing.plane_layers(four, SimpleNamespace(PLANES=["In2.Cu"])) == ["In2.Cu"]
    assert existing.plane_layers(four, SimpleNamespace(PLANES={"In1.Cu": "GND"})) == ["In1.Cu"]
    assert existing.plane_layers(four, SimpleNamespace(PLANES=[])) == []
    with pytest.raises(Usage, match="In3.Cu"):
        existing.plane_layers(four, SimpleNamespace(PLANES=["In3.Cu"]))


def test_reroute_hands_freerouting_the_planes_switched_off(tmp_path, monkeypatch, capsys):
    import shutil

    from conftest import BOARDS

    d = tmp_path / "b"
    shutil.copytree(BOARDS / "stm32f103_4l", d, ignore=shutil.ignore_patterns("out", "boardwright_out", "board.py"))
    seen = tmp_path / "argv"
    monkeypatch.setattr(env, "freerouting",
                        lambda: [sys.executable, "-c", f"import sys; open({str(seen)!r}, 'w').write(repr(sys.argv))"])
    assert main(["existing", str(d), "reroute", "PA1"]) == 4                 # the stand-in writes no SES
    argv = eval(seen.read_text())
    rules = (d / "boardwright_out" / "stm32f103_4l.rules").read_text()
    assert argv[argv.index("-dr") + 1].endswith("stm32f103_4l.rules")
    assert "(layer_rule In1.Cu\n      (active off)" in rules and "(layer_rule In2.Cu\n      (active off)" in rules
    assert "(layer_rule F.Cu\n      (active on)" in rules and "(layer_rule B.Cu\n      (active on)" in rules
    assert "kept off the plane layer(s) In1.Cu, In2.Cu" in capsys.readouterr().out


def test_a_net_the_router_cannot_finish_refuses_the_whole_reroute(ldo_copy, board, monkeypatch, capsys):
    """Its old copper, put back, landed on the other named nets' new routes:
    two shorts with PA0 and PA1 on stm32f103_4l (#106). Now nothing changes."""
    from pathlib import Path

    ses = Path(__file__).parent / "data" / "ses" / "ldo_routed.ses"
    t = ses.read_text()
    i = t.index('      (net "LED_A"')
    j = t.index("\n      (net ", i + 1) if "\n      (net " in t[i + 1:] else t.rindex("\n    )")
    t = t[:i] + t[j + 1:]
    # the session was saved from a routed board, so +3V3's via is marked protect,
    # which reroute leaves out as the board's own; a real router gives a ripped
    # net's via back unprotected, and without it +3V3 is open too (#134)
    k = t.index('(via "Via[0-1]_Pad600_um" 1550681 1079552')
    t = t[:k] + t[k:].replace("\n          (type protect)", "", 1)
    partial = ldo_copy / "partial.ses"
    partial.write_text(t)
    copy = "import shutil, sys; shutil.copy(sys.argv[1], sys.argv[sys.argv.index('-do') + 1])"
    monkeypatch.setattr(env, "freerouting", lambda: [sys.executable, "-c", copy, str(partial)])
    before = _hash(board)
    assert main(["existing", str(ldo_copy), "reroute", "LED_A", "+3V3"]) == 1
    err = capsys.readouterr().err
    assert "refused: the router could not finish ['LED_A']; reroute ['+3V3'] without them" in err
    assert _hash(board) == before


def test_an_outer_pour_with_no_tracks_is_still_routed_on():
    """A two-layer board routed on top with GND poured on the bottom keeps both
    layers: only inner layers are planes by default."""
    from types import SimpleNamespace

    from boardwright import existing

    b = SimpleNamespace(layers=["F.Cu", "B.Cu"], zones=[SimpleNamespace(layers=["B.Cu"], keepout=False)],
                        tracks=[SimpleNamespace(layer="F.Cu")])
    assert existing.plane_layers(b, SimpleNamespace()) == []
