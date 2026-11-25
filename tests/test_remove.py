"""`existing apply`'s REMOVE (#38): a board-only art footprint taken off the LDO
example, and the refusals for a part that is wired or linked to a symbol."""
import re
import shutil

import pytest
from conftest import BOARDS

from boardwright import update
from boardwright.cli import main

NAME = "ldo_breakout"
ART = """
\t(footprint "OldLogos:Mark"
\t\t(layer "F.Cu")
\t\t(uuid "0a0a0a0a-0000-4000-8000-000000000001")
\t\t(at 150 100)
\t\t(property "Reference" "G***"
\t\t\t(at 0 0 0)
\t\t\t(layer "F.SilkS")
\t\t\t(hide yes)
\t\t\t(uuid "0a0a0a0a-0000-4000-8000-000000000002")
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1 1)
\t\t\t\t\t(thickness 0.15)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(attr board_only exclude_from_pos_files exclude_from_bom)
\t\t(fp_poly
\t\t\t(pts
\t\t\t\t(xy -1 -1) (xy 1 -1) (xy 1 1) (xy -1 1)
\t\t\t)
\t\t\t(stroke
\t\t\t\t(width 0)
\t\t\t\t(type solid)
\t\t\t)
\t\t\t(fill yes)
\t\t\t(layer "F.SilkS")
\t\t\t(uuid "0a0a0a0a-0000-4000-8000-000000000003")
\t\t)
\t\t(embedded_fonts no)
\t)"""
GROUP = """
\t(group ""
\t\t(uuid "0a0a0a0a-0000-4000-8000-0000000000ff")
\t\t(members "0a0a0a0a-0000-4000-8000-000000000001" "%s")
\t)"""


@pytest.fixture
def ldo(tmp_path):
    """The LDO example with a logo footprint on the board alone, grouped with R1."""
    d = tmp_path / NAME
    shutil.copytree(BOARDS / NAME, d, ignore=shutil.ignore_patterns("out", "boardwright_out", "board.py", "__pycache__"))
    pcb = d / f"{NAME}.kicad_pcb"
    t = pcb.read_text()
    r1 = next(t[s:e] for s, e in update._footprints(t) if update._prop(t[s:e], "Reference") == "R1")
    uid = re.search(r'\n\t\t\(uuid "([^"]*)"\)', r1).group(1)
    k = update._footprints(t)[-1][1]
    pcb.write_text(t[:k] + ART + GROUP % uid + t[k:])
    return d


def _spec(d, text):
    (d / "boardwright.py").write_text(text)


def test_a_board_only_footprint_is_removed_and_nothing_else(ldo, capsys):
    pcb = ldo / f"{NAME}.kicad_pcb"
    before = pcb.read_text()
    _spec(ldo, 'REMOVE = ["G***"]\n')
    assert main(["existing", str(ldo), "apply"]) == 0
    assert "removed G*** (OldLogos:Mark)" in capsys.readouterr().out
    after = pcb.read_text()
    assert "OldLogos:Mark" not in after
    # the block is gone and the group no longer names it; every other byte is as it was
    assert after == before.replace(ART, "", 1).replace('(members "0a0a0a0a-0000-4000-8000-000000000001" ', "(members ", 1)
    assert after.count("(") == after.count(")")


def test_a_footprint_is_matched_by_its_library_name(ldo, capsys):
    _spec(ldo, 'REMOVE = ["OldLogos:Mark"]\n')
    assert main(["existing", str(ldo), "apply"]) == 0
    assert "removed G*** (OldLogos:Mark)" in capsys.readouterr().out


def test_a_wired_part_is_refused_without_force(ldo, capsys):
    pcb = ldo / f"{NAME}.kicad_pcb"
    before = pcb.read_text()
    _spec(ldo, 'REMOVE = ["G***", "R1"]\n')
    assert main(["existing", str(ldo), "apply"]) == 1
    out = capsys.readouterr().out
    assert "REFUSED R1 (Resistor_SMD:R_0805_2012Metric): pads on +3V3, LED_A, linked to a schematic symbol" in out
    assert "nothing written" in out and pcb.read_text() == before       # not even the logo
    assert main(["existing", str(ldo), "apply", "--force"]) == 0
    out = capsys.readouterr().out
    assert "removed R1 (Resistor_SMD:R_0805_2012Metric), pads on +3V3, LED_A, linked to a schematic symbol" in out
    t = pcb.read_text()
    assert [update._prop(t[s:e], "Reference") for s, e in update._footprints(t)].count("R1") == 0


def test_a_part_linked_to_its_symbol_is_refused(ldo, capsys):
    pcb = ldo / f"{NAME}.kicad_pcb"
    t = pcb.read_text()
    # J1's pads taken off their nets: its link to its symbol alone still refuses it
    j1 = next(t[s:e] for s, e in update._footprints(t) if update._prop(t[s:e], "Reference") == "J1")
    pcb.write_text(t.replace(j1, re.sub(r'\n\t\t\t\(net "[^"]*"\)', "", j1), 1))
    _spec(ldo, 'REMOVE = ["J1"]\n')
    assert main(["existing", str(ldo), "apply"]) == 1
    assert "REFUSED J1 (Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical): linked to a schematic symbol" \
        in capsys.readouterr().out


def test_a_name_on_no_footprint_is_a_usage_error(ldo, capsys):
    pcb = ldo / f"{NAME}.kicad_pcb"
    before = pcb.read_text()
    _spec(ldo, 'REMOVE = ["G***", "G2"]\n')
    assert main(["existing", str(ldo), "apply"]) == 64
    assert "REMOVE 'G2': no footprint" in capsys.readouterr().err
    assert pcb.read_text() == before


def test_the_removal_writes_through_the_board_writers_check(ldo, monkeypatch, capsys):
    """With the bracket check saying no, nothing is written (#190)."""
    from boardwright import board
    pcb = ldo / f"{NAME}.kicad_pcb"
    before = pcb.read_text()
    _spec(ldo, 'REMOVE = ["G***"]\n')
    monkeypatch.setattr(board, "balanced", lambda t: False)
    assert main(["existing", str(ldo), "apply"]) == 1
    assert "unbalance" in capsys.readouterr().err
    assert pcb.read_text() == before
