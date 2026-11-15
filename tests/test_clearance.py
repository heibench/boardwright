"""The clearance check behind `existing apply`'s MOVE and `existing free`, on the
four-layer STM32 example: R9 (an 0402 by the LEDs) moved onto SW2, and to a spot
`free` finds."""
import json
import shutil
import subprocess

import pytest
from conftest import BOARDS, needs_kicad

from boardwright.cli import main
from boardwright.model import Board
from boardwright.placement import Clearance

NAME = "stm32f103_4l"


@pytest.fixture
def stm(tmp_path):
    dst = tmp_path / NAME
    shutil.copytree(BOARDS / NAME, dst, ignore=shutil.ignore_patterns("out", "boardwright_out", "board.py", "__pycache__"))
    return dst


def _spec(d, text):
    (d / "boardwright.py").write_text(text)


def test_the_board_as_it_is_has_no_clash(stm):
    c = Clearance(Board(stm / f"{NAME}.kicad_pcb"))
    assert all(c.clashes(ref) == [] for ref in c.fps)


def test_a_part_moved_onto_a_switch_clashes(stm):
    c = Clearance(Board(stm / f"{NAME}.kicad_pcb"))
    sw = c.fps["SW2"][1]
    found = c.clashes("R9", (sw[0], sw[1], 0))
    assert "R9 courtyard overlaps SW2's" in found
    assert any("from" in f for f in found)                    # and its pads touch other copper


def test_apply_refuses_a_clashing_move_and_writes_nothing(stm, capsys):
    pcb = stm / f"{NAME}.kicad_pcb"
    sw = Clearance(Board(pcb)).fps["SW2"][1]
    _spec(stm, f"MOVE = {{'R9': ({sw[0]}, {sw[1]}, 0)}}\n")
    before = pcb.read_text()
    assert main(["existing", str(stm), "apply"]) == 1
    out = capsys.readouterr().out
    assert "CLASH R9 courtyard overlaps SW2's" in out and "nothing written" in out
    assert pcb.read_text() == before
    assert main(["existing", str(stm), "apply", "--force"]) == 0
    assert pcb.read_text() != before


def test_free_finds_spots_that_do_not_clash(stm, capsys):
    pcb = stm / f"{NAME}.kicad_pcb"
    assert main(["existing", str(stm), "free", "R9", "near", "J3.7"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines and all(ln.startswith('"R9": (') for ln in lines)
    spot = eval(lines[0].split(": ", 1)[1].rstrip(","))
    c = Clearance(Board(pcb))
    assert c.clashes("R9", spot) == []
    _spec(stm, f"MOVE = {{'R9': {spot}}}\n")
    assert main(["existing", str(stm), "apply"]) == 0


@pytest.mark.kicad
@needs_kicad
def test_kicad_finds_no_clash_where_free_put_a_part(stm, tmp_path, capsys):
    from boardwright import env

    assert main(["existing", str(stm), "free", "R9", "near", "J3.7"]) == 0
    spot = capsys.readouterr().out.strip().splitlines()[0].split(": ", 1)[1].rstrip(",")
    _spec(stm, f"MOVE = {{'R9': {spot}}}\n")
    assert main(["existing", str(stm), "apply"]) == 0
    out = tmp_path / "drc.json"
    subprocess.run([*env.kicad_cli(), "pcb", "drc", "--format", "json", "--refill-zones", "-o", str(out),
                    str(stm / f"{NAME}.kicad_pcb")], check=True, capture_output=True)
    bad = [v for v in json.loads(out.read_text())["violations"]
           if v["type"] in ("clearance", "shorting_items", "courtyards_overlap", "copper_edge_clearance")
           and any("R9" in i["description"] for i in v["items"])]
    assert bad == []


# R7 and R5 on the top at 90 and -90 degrees, C7 and C3 on the bottom at 90 and 180:
# each one's reference text moved onto the centre of a pad elsewhere on the board.
FIELD_MOVES = {
    "R7": (15.25, 41.2, 90, {"ref": (28.0, 26.24)}),        # onto J3.7
    "R5": (20.525, 30.87, -90, {"ref": (2.6, 21.16)}),      # onto J2.5
    "C7": (13.197, 35.0, 90, {"ref": (17.003, 31.02)}),     # onto C4.1
    "C3": (17.0, 36.503, 180, {"ref": (28.0, 13.54)}),      # onto J3.2
}
FIELD_TARGETS = {"R7": ("J3", "7"), "R5": ("J2", "5"), "C7": ("C4", "1"), "C3": ("J3", "2")}


def test_reference_text_lands_where_asked(stm):
    """Read back with the footprint frame KiCad uses (and boardwright uses for
    footprint zones), each moved reference sits at the point asked for."""
    import math
    import re

    from boardwright import update

    _spec(stm, f"MOVE = {FIELD_MOVES!r}\n")
    assert main(["existing", str(stm), "apply", "--force"]) == 0
    t = (stm / f"{NAME}.kicad_pcb").read_text()
    ox, oy = Board(stm / f"{NAME}.kicad_pcb").origin
    for ref, mv in FIELD_MOVES.items():
        fp = next(t[s:e] for s, e in update._footprints(t) if update._prop(t[s:e], "Reference") == ref)
        fx, fy, rot = map(float, re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)", fp).groups())
        lx, ly = map(float, re.search(r'\(property "Reference" "%s"\s*\(at ([-\d.]+) ([-\d.]+)' % ref, fp).groups())
        r = math.radians(rot)
        ax, ay = fx + lx * math.cos(r) + ly * math.sin(r), fy - lx * math.sin(r) + ly * math.cos(r)
        assert (round(ax - ox, 3), round(ay - oy, 3)) == pytest.approx(mv[3]["ref"], abs=1e-3)


def test_an_unknown_text_field_is_refused(stm):
    _spec(stm, "MOVE = {'R7': (15.25, 41.2, 90, {'footprint': (1, 1)})}\n")
    assert main(["existing", str(stm), "apply"]) == 64


@pytest.mark.kicad
@needs_kicad
def test_kicad_draws_each_moved_reference_over_the_pad_aimed_at(stm, tmp_path):
    from boardwright import env

    _spec(stm, f"MOVE = {FIELD_MOVES!r}\n")
    assert main(["existing", str(stm), "apply", "--force"]) == 0
    out = tmp_path / "drc.json"
    subprocess.run([*env.kicad_cli(), "pcb", "drc", "--format", "json", "--severity-all", "-o", str(out),
                    str(stm / f"{NAME}.kicad_pcb")], check=True, capture_output=True)
    hits = {(i["description"].split()[3], j["description"]) for v in json.loads(out.read_text())["violations"]
            if v["type"] == "silk_over_copper" for i in v["items"] if i["description"].startswith("Reference field of")
            for j in v["items"] if j is not i}
    for ref, (tref, num) in FIELD_TARGETS.items():
        assert any(r == ref and f"pad {num} " in d.lower() and f" of {tref}" in d for r, d in hits), (ref, hits)
