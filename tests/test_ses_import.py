"""Importing Freerouting's session (build.import_ses), against the output
recorded in tests/data/ses/.

Each case is a board as it stood when its DSN was exported (`<case>.kicad_pcb`),
the session Freerouting wrote for it (`<case>.ses`), and the board as
import_ses left it (`<case>.golden.kicad_pcb`, every `(uuid ...)` replaced by
"~"). Freerouting is not deterministic, so the sessions are fixtures, never
regenerated here. Every case but ldo_routed was made by `boardwright place` on
the example, then Freerouting run as build._route_once runs it; ldo_routed is
the routed LDO example saved by KiCad 10 and routed again, so its session
gives back every track and via the board already has. ldo_stubs is the LDO
session with copper added by hand: vias with a track on one side or none, a
track left hanging, a track two segments long ending in the open, one below
the minimum width, one given twice, and the same on a poured net.

The import must give the same tracks and vias (net, layer, ends, width, via
size and drill) and leave everything else in the file byte-identical.

To record the current output as the golden: `uv run python tests/test_ses_import.py`.
"""

import importlib.util
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

import pytest
from conftest import ROOT

from boardwright import build
from boardwright.copper import blocks

DATA = Path(__file__).parent / "data" / "ses"
# case -> the example whose board.py is the spec
CASES = {
    "ldo_breakout": "ldo_breakout",
    "ldo_routed": "ldo_breakout",
    "ldo_stubs": "ldo_breakout",
    "tps54202_buck": "tps54202_buck",
    "esp32c3_min": "esp32c3_min",
    "stm32f103_4l": "stm32f103_4l",
}


def spec(name: str):
    s = importlib.util.spec_from_file_location("board_def", ROOT / "examples" / "boards" / name / "board.py")
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def normalize(t: str) -> str:
    return re.sub(r'\(uuid "[^"]*"\)', '(uuid "~")', t)


def _f(v: str) -> float:
    return round(float(v), 6)       # KiCad keeps 1 nm


def copper(t: str) -> tuple[Counter, str]:
    """Every track and via as a comparable tuple, and the file without them."""
    names = dict(re.findall(r'\n\s*\(net (\d+) "([^"]*)"\)', t))
    items, rest, pos = [], [], 0
    for s0, e0 in blocks(t, ("segment", "via")):
        b = t[s0:e0]
        n = re.search(r'\(net (?:(\d+)|"([^"]*)")', b)
        net = n.group(2) if n.group(2) is not None else names[n.group(1)]
        if b.lstrip().startswith("(segment"):
            (x1, y1), (x2, y2) = re.findall(r"\((?:start|end) ([-\d.]+) ([-\d.]+)\)", b)
            w = re.search(r"\(width ([\d.]+)\)", b).group(1)
            layer = re.search(r'\(layer "([^"]+)"\)', b).group(1)
            items.append(("segment", net, layer, _f(x1), _f(y1), _f(x2), _f(y2), _f(w)))
        else:
            x, y = re.search(r"\(at ([-\d.]+) ([-\d.]+)\)", b).groups()
            size = re.search(r"\(size ([\d.]+)\)", b).group(1)
            drill = re.search(r"\(drill ([\d.]+)\)", b).group(1)
            layers = re.search(r"\(layers ([^)]*)\)", b).group(1).split()
            kind = re.match(r"\s*\(via( \w+)?", b).group(1) or ""
            items.append(("via" + kind, net, tuple(layers), _f(x), _f(y), _f(size), _f(drill)))
        rest.append(t[pos:s0])
        pos = e0
    rest = "".join(rest) + t[pos:]
    # where the routes went in: only the whitespace before the closing paren differs
    return Counter(items), re.sub(r"\s*\)\s*$", "\n)\n", normalize(rest))


def run(case: str, tmp: Path) -> str:
    pcb = tmp / f"{case}.kicad_pcb"
    shutil.copy(DATA / f"{case}.kicad_pcb", pcb)
    build.import_ses(pcb, DATA / f"{case}.ses", spec(CASES[case]))
    return pcb.read_text()


@pytest.mark.parametrize("case", sorted(CASES))
def test_ses_import_matches_its_golden(tmp_path, case):
    got_items, got_rest = copper(run(case, tmp_path))
    want_items, want_rest = copper((DATA / f"{case}.golden.kicad_pcb").read_text())
    assert got_rest == want_rest, "the board differs outside its tracks and vias"
    assert sorted(got_items - want_items) == [], "tracks or vias the golden does not have"
    assert sorted(want_items - got_items) == [], "tracks or vias missing against the golden"


def test_reroute_takes_only_the_named_nets_from_the_session(ldo_copy, monkeypatch):
    """`existing reroute` keeps only the named nets' copper from the session.
    ldo_routed's session is the LDO example's routing given back, so LED_A
    gets its own tracks back and the rest of the file is as it was."""
    from boardwright import env, existing

    copy = "import shutil, sys; shutil.copy(sys.argv[1], sys.argv[sys.argv.index('-do') + 1])"
    monkeypatch.setattr(env, "freerouting", lambda: [sys.executable, "-c", copy, str(DATA / "ldo_routed.ses")])
    pcb = existing.find(ldo_copy)
    want_items, want_rest = copper(pcb.read_text())
    assert existing.reroute(ldo_copy, ["LED_A"]) == 0
    got_items, got_rest = copper(pcb.read_text())
    assert got_rest == want_rest
    assert got_items == want_items


def test_session_units_and_quoted_names(tmp_path):
    """Coordinates are counts of 1/resolution of the declared unit, y as written;
    a quoted net name is the name without its quotes."""
    from boardwright import ses

    f = tmp_path / "x.ses"
    f.write_text('(session x (routes (resolution mil 10) (parser (string_quote ")) (library_out '
                 '(padstack V (shape (circle F.Cu 240 0 0)) (shape (circle B.Cu 240 0 0)))) '
                 '(network_out (net "/A B" (wire (path B.Cu 100 10000 20000 10000 30000)) (via V 10000 30000)))))')
    tracks, vias = ses.read(f, ["F.Cu", "B.Cu"])
    assert tracks == [("/A B", "B.Cu", 25.4, 50.8, 25.4, 76.2, 0.254)]
    assert vias == [("/A B", 25.4, 76.2, 0.6096, "F.Cu", "B.Cu")]


if __name__ == "__main__":
    import tempfile

    for case in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            (DATA / f"{case}.golden.kicad_pcb").write_text(normalize(run(case, Path(tmp))))
