"""A board against a fab's published limits (#49), on copies of the examples."""

import re
from types import SimpleNamespace

from conftest import BOARDS

from boardwright.fab import fab_review
from boardwright.model import Board
from boardwright.review import review

LDO = BOARDS / "ldo_breakout" / "ldo_breakout.kicad_pcb"
STM4 = BOARDS / "stm32f103_4l" / "stm32f103_4l.kicad_pcb"


def _board(tmp_path, src, edit=None):
    pcb = tmp_path / src.name
    text = src.read_text()
    pcb.write_text(edit(text) if edit else text)
    pcb.with_suffix(".kicad_pro").write_text(src.with_suffix(".kicad_pro").read_text())
    return pcb


def _widths(w):
    """Every track narrowed to w mm."""
    return lambda t: re.sub(r"(\(segment(?:(?!\n\t\().)*?\(width )[\d.]+", rf"\g<1>{w}", t, flags=re.S)


def _run(pcb, fab, oz=1):
    return fab_review(Board(pcb), pcb, fab, oz)


def test_the_ldo_example_passes_jlcpcb(tmp_path):
    lines, fails = _run(_board(tmp_path, LDO), "jlcpcb")
    assert fails == []
    assert lines[0] == "fab jlcpcb (2 layers, 1 oz; limits read 2026-11-21):"
    assert "  via_ring: 0.1 mm >= 0.075" in lines


def test_the_ldo_example_fails_oshpark_and_names_the_limit(tmp_path):
    fails = _run(_board(tmp_path, LDO), "oshpark")[1]
    assert ('thinnest via ring 0.1 mm is below oshpark\'s minimum 0.127 mm ("Minimum Annular Ring | 5mil (0.127mm)", '
            "https://docs.oshpark.com/services/two-layer/)") in fails
    assert any(f.startswith("smallest clearance the rules allow 0.15 mm is below oshpark's minimum 0.1524 mm") for f in fails)


def test_below_the_standard_price_is_reported_not_failed(tmp_path):
    lines, fails = _run(_board(tmp_path, STM4, _widths(0.08)), "jlcpcb")
    assert fails == []
    assert any(ln.startswith("  track: 0.08 mm, below the 0.09 mm standard") for ln in lines)


def test_below_the_minimum_fails(tmp_path):
    fails = _run(_board(tmp_path, STM4, _widths(0.07)), "jlcpcb")[1]
    assert any(f.startswith("narrowest track 0.07 mm is below jlcpcb's minimum 0.075 mm") for f in fails)


def test_an_unknown_fab_fails(tmp_path):
    assert _run(_board(tmp_path, LDO), "acme")[1] == ["fab 'acme' is not one of jlcpcb, oshpark, pcbway"]


def test_no_limits_for_the_board_cannot_judge(tmp_path):
    assert _run(_board(tmp_path, LDO), "oshpark", 2) == ([], ["fab oshpark: cannot judge, no limits for a 2-layer board at 2 oz"])


def test_review_runs_the_fab_check(tmp_path):
    fails = review(_board(tmp_path, LDO), SimpleNamespace(REVIEW={"fab": "oshpark"}))
    assert any("below oshpark's minimum" in f for f in fails)


def test_a_key_with_no_limit_at_this_copper_cannot_judge(tmp_path):
    """JLCPCB states track limits at 1, 2, 2.5 oz ... but none at 1.5: the track is not passed on nothing."""
    fails = _run(_board(tmp_path, LDO), "jlcpcb", 1.5)[1]
    assert "fab jlcpcb: cannot judge track, no limit for a 2-layer board at 1.5 oz" in fails


def test_the_limit_is_the_one_for_the_boards_layer_count(tmp_path):
    """OSH Park's four-layer ring is 4 mil, its two-layer one 5 mil: the 4-layer example gets the 4 mil one."""
    fails = _run(_board(tmp_path, STM4), "oshpark")[1]
    assert ("thinnest via ring 0.1 mm is below oshpark's minimum 0.1016 mm (\"Minimum Annular Ring | 4mil (0.1016mm)\", "
            "https://docs.oshpark.com/services/four-layer/)") in fails


def test_a_net_class_clearance_below_the_limit_fails(tmp_path):
    """The board rule allows 0.15 mm; a net class allowing 0.09 mm is what the fab must make."""
    import json

    pcb = _board(tmp_path, LDO)
    pro = pcb.with_suffix(".kicad_pro")
    j = json.loads(pro.read_text())
    j["net_settings"]["classes"][0]["clearance"] = 0.09
    pro.write_text(json.dumps(j))
    fails = _run(pcb, "pcbway")[1]
    assert any(f.startswith("smallest clearance the rules allow 0.09 mm is below pcbway's minimum 0.1 mm") for f in fails)
