"""What the preview draws (#136): a label that does not look printed for a
reference that does not print, and each pour as the fill KiCad left."""

import re

from conftest import BOARDS

from boardwright import copper
from boardwright.model import Board
from boardwright.preview import svg

STM = BOARDS / "stm32f103_min" / "stm32f103_min.kicad_pcb"
BUCK = BOARDS / "tps54202_buck" / "tps54202_buck.kicad_pcb"


def _svg(tmp_path, src, edit=None):
    pcb = tmp_path / src.name
    t = src.read_text()
    pcb.write_text(edit(t) if edit else t)
    b = Board(pcb)
    return b, svg(b)[0]


def _label(text, ref):
    return re.search(rf"<text [^>]*>{re.escape(ref)}</text>", text).group(0)


def test_a_printed_reference_has_a_plain_label(tmp_path):
    _b, t = _svg(tmp_path, STM)
    assert 'font-style="italic"' not in _label(t, "C2")


def test_a_hidden_reference_has_a_dimmed_label(tmp_path):
    hide = lambda t: t.replace('(property "Reference" "C2"\n\t\t\t(at 2.45 -1.73 0)\n\t\t\t(layer "F.SilkS")',  # noqa: E731
                               '(property "Reference" "C2"\n\t\t\t(at 2.45 -1.73 0)\n\t\t\t(layer "F.SilkS")\n\t\t\t(hide yes)', 1)
    _b, t = _svg(tmp_path, STM, hide)
    assert 'opacity="0.4" font-style="italic"' in _label(t, "C2")
    assert 'font-style="italic"' not in _label(t, "C3")


def test_pours_are_drawn_as_their_fills(tmp_path):
    b, t = _svg(tmp_path, BUCK)
    fills = sum(len(polys) for z in b.zones if not z.keepout for polys in z.fills.values())
    assert fills > 0 and t.count('fill-opacity="0.28"') == fills


def test_an_unfilled_pour_is_its_outline(tmp_path):
    def unfill(t):
        for s, e in reversed(copper.blocks(t, ("filled_polygon",))):
            t = t[:s] + t[e:]
        return t
    b, t = _svg(tmp_path, BUCK, unfill)
    assert not any(z.fills for z in b.zones)
    assert 'fill-opacity="0.28"' not in t and t.count('fill-opacity="0.07"') == sum(1 for z in b.zones if not z.keepout)
