"""silk.place_refs on every example board, against kicad-tools 0.29's
`place-silk-refs --allow-rotate` output for it, recorded in
tests/data/silk_refs/golden.json when `gen` still ran that command.

The inputs, tests/data/silk_refs/<board>.kicad_pcb, are each example as `gen`
left it just before that step (b47943e): placed and routed, before TEXT and
the pours. They are committed rather than regenerated because Freerouting does
not route a dense board the same way twice, and the step's output depends on
the copper.

place-silk-refs saved the whole board through kicad-tools, rewriting 2,388
lines of rp2040_min's layout, so the goldens hold only what the step decides:
each footprint's Reference text, its (at x y [angle]), layer and justify.
kicad-tools gave byte-identical files on two runs of each board. The goldens
are kicad-tools' output and are not re-recorded from boardwright's.

place_refs edits only the (at ...) of each reference it moves, so
test_only_the_reference_positions_change holds the rest of the file to the
input, byte for byte.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from boardwright import copper, silk
from boardwright.update import _footprints, _prop

DATA = Path(__file__).parent / "data" / "silk_refs"
GOLDEN = json.loads((DATA / "golden.json").read_text())
BOARDS = sorted(GOLDEN)


def refs(t: str) -> dict:
    """ref -> {"at": [x, y, angle or None], "layer": ..., "justify": ... or None}"""
    out = {}
    for s, e in _footprints(t):
        fp = t[s:e]
        ref = _prop(fp, "Reference")
        p = next(fp[a:b] for a, b in copper.blocks(fp, ("property",)) if fp[a:b].lstrip().startswith('(property "Reference"'))
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", p)
        j = re.search(r"\(justify ([^()]*)\)", p)
        out[ref] = {"at": [float(at.group(1)), float(at.group(2)), float(at.group(3)) if at.group(3) else None],
                    "layer": re.search(r'\(layer "([^"]*)"\)', p).group(1),
                    "justify": j.group(1) if j else None}
    return out


def test_every_example_has_an_input():
    assert BOARDS == sorted(p.stem for p in DATA.glob("*.kicad_pcb"))
    assert len(BOARDS) == 7


@pytest.mark.parametrize("name", BOARDS)
def test_reference_text_matches_its_golden(tmp_path, name):
    pcb = tmp_path / f"{name}.kicad_pcb"
    shutil.copy(DATA / pcb.name, pcb)
    silk.place_refs(pcb)
    assert refs(pcb.read_text()) == GOLDEN[name]


def _without_reference_positions(t: str) -> str:
    return re.sub(r'(\n\t\t\(property "Reference" "[^"\n]*"\n\t\t\t)\(at [^()]*\)', r"\1(at)", t)


@pytest.mark.parametrize("name", BOARDS)
def test_only_the_reference_positions_change(tmp_path, name):
    pcb = tmp_path / f"{name}.kicad_pcb"
    shutil.copy(DATA / pcb.name, pcb)
    moved = silk.place_refs(pcb)
    before, after = (DATA / pcb.name).read_text(), pcb.read_text()
    assert moved and after != before
    assert _without_reference_positions(after) == _without_reference_positions(before)
    assert _without_reference_positions(before).count("\t(at)") == len(refs(before))      # one per footprint, no more


def test_references_keep_clear_of_the_board_edge(tmp_path):
    """No example's reference is decided by the edge rule, so one is made: J1 on
    ldo_breakout moved to 0.95 mm from the left edge, where its reference, left
    above it, would come within 0.2 mm (silk.EDGE) of the edge."""
    from boardwright.model import Board

    pcb = tmp_path / "ldo_breakout.kicad_pcb"
    t = (DATA / pcb.name).read_text()
    assert t.count("\n\t\t(at 136.5 103.7)\n") == 1
    pcb.write_text(t.replace("\n\t\t(at 136.5 103.7)\n", "\n\t\t(at 134.45 103.7)\n"))
    assert "J1" in silk.place_refs(pcb)
    b = Board(pcb).pcb
    material, outline = silk._material(b)
    for fp in b.footprints:
        r = next(x for x in fp.texts if x.text_type == "reference")
        g = silk._text_box(r.text, r.font_size, r.font_thickness, silk._transform(fp)(r.position), silk._angle(fp))
        assert material.covers(g) and g.distance(outline) >= silk.EDGE - silk.EPS, fp.reference
