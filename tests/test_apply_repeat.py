"""`existing apply` is repeatable, however the board was saved in between (#113)."""

import re

import pytest
from conftest import BOARDS

from boardwright import copper, existing
from boardwright.cli import main

# KiCad 10.0.8's form of what boardwright wrote for the spec below on the LDO
# example (origin 133.5, 95), after `kicad-cli pcb upgrade --force`.
KICAD_TEXT = ('\n\t(gr_text "REV A"\n\t\t(at 136.5 113 0)\n\t\t(layer "F.SilkS")\n\t\t(uuid "49c0df73-d07b-4807-8217-e4c5338d81a6")'
              '\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)')
KICAD_ZONE = ('\n\t(zone\n\t\t(net "GND")\n\t\t(layer "F.Cu")\n\t\t(uuid "a5714c1a-79c9-459e-8100-564738342adf")\n\t\t(hatch edge 0.5)'
              '\n\t\t(priority 1)\n\t\t(connect_pads yes\n\t\t\t(clearance 0.25)\n\t\t)\n\t\t(min_thickness 0.2)\n\t\t(fill yes'
              '\n\t\t\t(thermal_gap 0.3)\n\t\t\t(thermal_bridge_width 0.4)\n\t\t\t(island_removal_mode 0)\n\t\t)\n\t\t(polygon'
              '\n\t\t\t(pts\n\t\t\t\t(xy 134.5 96) (xy 139.5 96) (xy 139.5 99) (xy 134.5 99)\n\t\t\t)\n\t\t)\n\t)')
KICAD_KEEPOUT = ('\n\t(zone\n\t\t(layer "F.Cu")\n\t\t(uuid "a6ff95c2-e2f7-4771-a49f-d97f1f1461d0")\n\t\t(hatch edge 0.5)'
                 '\n\t\t(connect_pads\n\t\t\t(clearance 0)\n\t\t)\n\t\t(min_thickness 0.25)\n\t\t(keepout\n\t\t\t(tracks not_allowed)'
                 '\n\t\t\t(vias not_allowed)\n\t\t\t(pads allowed)\n\t\t\t(copperpour not_allowed)\n\t\t\t(footprints allowed)\n\t\t)'
                 '\n\t\t(placement\n\t\t\t(enabled no)\n\t\t\t(sheetname "")\n\t\t)\n\t\t(fill\n\t\t\t(thermal_gap 0.5)'
                 '\n\t\t\t(thermal_bridge_width 0.5)\n\t\t\t(island_removal_mode 0)\n\t\t)\n\t\t(polygon\n\t\t\t(pts'
                 '\n\t\t\t\t(xy 153.5 110) (xy 157.5 110) (xy 157.5 113) (xy 153.5 113)\n\t\t\t)\n\t\t)\n\t)')
OX, OY = 133.5, 95.0
SQUARE = [(1.0, 1.0), (6.0, 1.0), (6.0, 4.0), (1.0, 4.0)]
KEEP = [(20.0, 15.0), (24.0, 15.0), (24.0, 18.0), (20.0, 18.0)]


@pytest.mark.parametrize("ours, kicads", [
    (copper.text("REV A", 3.0, 18.0, OX, OY), KICAD_TEXT),
    (copper.zone('(net "GND")', "F.Cu", SQUARE, OX, OY), KICAD_ZONE),
    (copper.keepout(["F.Cu"], KEEP, OX, OY), KICAD_KEEPOUT),
], ids=["text", "zone", "keepout"])
def test_kicads_saved_form_is_the_same_item(ours, kicads):
    """KiCad writes 113 for 113.0, spreads an item over lines, drops a keepout's
    empty net and adds fields of its own: the key sees through all of it."""
    assert existing._item_key("\n" + ours.rstrip("\n")) == existing._item_key(kicads)


def test_a_different_item_is_not_dropped():
    moved = KICAD_ZONE.replace("(xy 134.5 96)", "(xy 134.5 96.5)")
    rules = KICAD_KEEPOUT.replace("(vias not_allowed)", "(vias allowed)")
    other = KICAD_TEXT.replace('"REV A"', '"REV B"')
    for a, b in [(KICAD_ZONE, moved), (KICAD_KEEPOUT, rules), (KICAD_TEXT, other)]:
        assert existing._item_key(a) != existing._item_key(b)


def test_zones_keepouts_and_text_are_not_added_twice(ldo_copy, capsys):
    """Every apply added another copy of each ZONES and KEEPOUTS entry: 2 zones,
    then 4, then 6, while it printed "so apply is repeatable"."""
    (ldo_copy / "boardwright.py").write_text(
        f'TRACKS = [("LED_A", [(5.0, 2.0), (8.0, 2.0)], 0.25, "F.Cu")]\nVIAS = [("LED_A", 8.0, 2.0)]\n'
        f'TEXT = [("REV A", 3.0, 18.0)]\nZONES = [("GND", "F.Cu", {SQUARE!r})]\nKEEPOUTS = [(["F.Cu"], {KEEP!r})]\n')
    board = ldo_copy / "ldo_breakout.kicad_pcb"
    assert main(["existing", str(ldo_copy), "apply"]) == 0
    once = board.read_text()
    assert main(["existing", str(ldo_copy), "apply"]) == 0
    assert "5 exact duplicate(s) dropped" in capsys.readouterr().out
    assert board.read_text() == once


def test_a_board_from_kicad_loses_nothing():
    """Top-level items only: a footprint's own zones are left alone."""
    for b in sorted(BOARDS.glob("*/*.kicad_pcb")):
        t = b.read_text()
        assert existing.dedupe(t) == (t, 0), b.name
    esp = (BOARDS / "esp32c3_min" / "esp32c3_min.kicad_pcb").read_text()
    assert re.search(r"\n\t\t\(zone\b", esp)            # the module's keep-out zone sits inside its footprint


def test_dedupe_never_reaches_inside_a_footprint():
    """Two footprints each holding the same zone (as two copies of a module
    with a keep-out do) are both left whole."""
    t = (BOARDS / "esp32c3_min" / "esp32c3_min.kicad_pcb").read_text()
    fp = next(t[s:e] for s, e in copper.blocks(t, ("footprint",)) if re.search(r"\n\t\t\(zone\b", t[s:e]))
    doubled = t.replace(fp, fp + fp, 1)
    assert existing.dedupe(doubled) == (doubled, 0)
