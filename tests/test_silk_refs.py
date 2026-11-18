"""Reference text placement on every example board, against kicad-tools 0.29's
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
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from boardwright import board, copper
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


def place_refs(pcb: Path) -> None:
    board.kct("place-silk-refs", str(pcb), "--allow-rotate", "-o", str(pcb), check=False)


def test_every_example_has_an_input():
    assert BOARDS == sorted(p.stem for p in DATA.glob("*.kicad_pcb"))
    assert len(BOARDS) == 7


@pytest.mark.parametrize("name", BOARDS)
def test_reference_text_matches_its_golden(tmp_path, name):
    pcb = tmp_path / f"{name}.kicad_pcb"
    shutil.copy(DATA / pcb.name, pcb)
    place_refs(pcb)
    assert refs(pcb.read_text()) == GOLDEN[name]
