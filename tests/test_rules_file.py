"""Freerouting reads NAME.rules beside NAME.dsn without being given -dr, so a
rules file left by an earlier run (a plane layer switched off) steered later
runs that set no PLANES: 55 nets open in one directory, 0 in another (#224).
Each run now writes the rules it means, or removes a stale file."""

import types

import pytest
from conftest import BOARDS

from boardwright import build, dsn, existing

LDO = BOARDS / "ldo_breakout" / "ldo_breakout.kicad_pcb"
STALE = "(rules PCB x\n  (autoroute_settings\n    (layer_rule B.Cu\n      (active off)\n    )\n  )\n)\n"


class _Ran(Exception):
    pass


def _capture(monkeypatch, dsn_path):
    """Stop at the Freerouting call, recording its command and the rules file beside the DSN."""
    seen = {}
    def run(cmd, *a, **k):
        seen["cmd"] = list(cmd)
        rules = dsn_path.with_suffix(".rules")
        seen["rules"] = rules.read_text(encoding="utf-8") if rules.exists() else None
        raise _Ran
    monkeypatch.setattr(existing.subprocess, "run", run)
    monkeypatch.setattr(build.subprocess, "run", run)
    return seen


def test_rules_beside_writes_or_removes(tmp_path):
    d = tmp_path / "b.dsn"
    (tmp_path / "b.rules").write_text(STALE, encoding="utf-8")
    assert dsn.rules_beside(d, None) is None and not (tmp_path / "b.rules").exists()
    assert dsn.rules_beside(d, "(rules)") == tmp_path / "b.rules"
    assert (tmp_path / "b.rules").read_text(encoding="utf-8") == "(rules)"


@pytest.mark.parametrize("planes", [[], ["B.Cu"]])
def test_reroute_hands_freerouting_only_this_runs_rules(tmp_path, monkeypatch, planes):
    o = tmp_path / "boardwright_out"
    o.mkdir()
    m = types.SimpleNamespace(NAME="ldo_breakout")
    (o / "ldo_breakout.rules").write_text(STALE, encoding="utf-8")      # left by an earlier run
    seen = _capture(monkeypatch, o / "ldo_breakout.dsn")
    with pytest.raises(_Ran):
        existing._route_and_graft(LDO, m, o, ["VIN"], set(), LDO.read_text(encoding="utf-8"), planes)
    if planes:
        assert "-dr" in seen["cmd"] and "B.Cu" in seen["rules"] and seen["rules"] != STALE
    else:
        assert "-dr" not in seen["cmd"] and seen["rules"] is None


@pytest.mark.parametrize("planes", [{}, {"B.Cu": "GND"}])
def test_gen_hands_freerouting_only_this_runs_rules(tmp_path, monkeypatch, planes):
    d = tmp_path / "board"
    (d / "out").mkdir(parents=True)
    pcb = d / "ldo_breakout.kicad_pcb"
    pcb.write_text(LDO.read_text(encoding="utf-8"), encoding="utf-8")
    (d / "out" / "ldo_breakout.rules").write_text(STALE, encoding="utf-8")
    m = types.SimpleNamespace(NAME="ldo_breakout", PLANES=planes)
    seen = _capture(monkeypatch, d / "out" / "ldo_breakout.dsn")
    with pytest.raises(_Ran):
        build._route_once(d, m, pcb, "", None, "5")
    if planes:
        assert "-dr" in seen["cmd"] and "(active off)" in seen["rules"] and seen["rules"] != STALE
    else:
        assert "-dr" not in seen["cmd"] and seen["rules"] is None
