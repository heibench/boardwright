"""model.Board against kicad-tools 0.29's reading of the same boards.

Every field boardwright reads from a board (tests/reader_dump.py lists them)
was recorded from kicad-tools 0.29's parser, when model.py was built on it:

- data/reader/golden.json: every board committed under examples/boards and
  tests/data, keyed by its path in the repo. The examples are KiCad 10 files
  (version 20260206); the boards under tests/data are as boardwright writes
  them (20241229, KiCad 9's format) or as KiCad 10 saved them.
  data/reader/cheapino_kicad8.kicad_pcb is a KiCad 8 file (20240108), cut
  down from tompi/cheapino (CC BY 4.0, see cheapino_kicad8.NOTICE).
- data/reader/demos.json: KiCad's demo boards, keyed by their path under
  share/kicad/demos, with the sha256 of the file each was recorded from. They
  are not copied here (they ship under their own licences); a demo that is
  missing, or whose file is not the one recorded, is skipped.

The golden keeps the small fields (origin, copper layers, bbox, area, via
tenting) as they are and every list as its length and the sha256 of its
JSON. Two recordings, each in its own process, gave identical dumps for
every board.

model.py reads each of them as kicad-tools did but for one field, which
_as_kicad_tools_read_it puts back: the reference angle silk.py takes from a
footprint. silk.py found it in the footprint's own s-expression node, which
kicad-tools linked to the footprint by uuid; on a board where footprints
share a uuid (kicad-tools' create-pcb gave every copy of a library
footprint the library's), every footprint of such a group but the last has
no node, and the dump recorded None. model.py reads the angle from the
footprint's reference text, so it has one for every footprint.
"""

import hashlib
import json
from pathlib import Path

import pytest
import reader_dump
from conftest import DEMOS, ROOT

DATA = Path(__file__).parent / "data" / "reader"
GOLDEN = json.loads((DATA / "golden.json").read_text())
DEMO_GOLDEN = json.loads((DATA / "demos.json").read_text())


def _as_kicad_tools_read_it(d: dict) -> dict:
    last = {fp[1]: i for i, fp in enumerate(d["footprints"])}
    d["footprints"] = [fp[:5] + [None] + fp[6:] if fp[1] and last[fp[1]] != i else fp
                       for i, fp in enumerate(d["footprints"])]
    return d


def _summary(path: Path) -> dict:
    return reader_dump.summary(_as_kicad_tools_read_it(reader_dump.dump(path)))


def test_every_committed_board_has_a_golden():
    boards = [*ROOT.glob("examples/boards/*/*.kicad_pcb"), *(ROOT / "tests" / "data").glob("*/*.kicad_pcb")]
    assert sorted(str(p.relative_to(ROOT)) for p in boards) == sorted(GOLDEN)


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_a_board_reads_as_kicad_tools_read_it(name):
    assert _summary(ROOT / name) == GOLDEN[name]


@pytest.mark.parametrize("name", sorted(DEMO_GOLDEN))
def test_a_kicad_demo_reads_as_kicad_tools_read_it(name):
    path = DEMOS / name if DEMOS else None
    if path is None or not path.exists():
        pytest.skip("KiCad's demo projects not installed")
    want = dict(DEMO_GOLDEN[name])
    if hashlib.sha256(path.read_bytes()).hexdigest() != want.pop("board_sha256"):
        pytest.skip(f"{name} is not the file recorded (another KiCad version)")
    assert _summary(path) == want


def _board(tmp_path, body: str, version="20260206"):
    p = tmp_path / "b.kicad_pcb"
    head = f"(version {version})" if version else ""
    p.write_text(f'(kicad_pcb {head} (generator "pcbnew")\n\t(layers (0 "F.Cu" signal) (1 "In1.Cu" mixed) '
                 f'(2 "In2.Cu" jumper) (31 "B.Cu" signal) (44 "Edge.Cuts" user))\n{body})\n')
    return p


EDGE = '\t(gr_rect (start 100 50) (end 130 70) (stroke (width 0.05) (type default)) (fill no) (layer "Edge.Cuts"))\n'


def test_a_kicad_8_board_is_read():
    """Its outline is gr_lines and gr_arcs; 40 of its 100 tracks are arcs."""
    from boardwright.model import Board

    b = Board(DATA / "cheapino_kicad8.kicad_pcb")
    assert b.version == 20240108 and b.layers == ["F.Cu", "B.Cu"] and b.origin == (60.096401, 45.766378)
    assert [fp.reference for fp in b.footprints] == ["REF**", "U1", "K1", "D1", "JP1", "ENC1", "J_2_RIGHT1"]
    assert (len(b.tracks), sum(len(t.pts) > 2 for t in b.tracks), len(b.vias), len(b.zones)) == (100, 40, 28, 4)
    assert len(b.outline) == 77 and b.bbox[:2] == (0.0, 0.0)


def test_a_mixed_copper_layer_is_copper(tmp_path):
    """kicad-tools 0.29 counted signal and power layers only; KiCad routes on
    mixed layers too (dsn.py writes them). A jumper layer is not routed."""
    from boardwright.model import Board

    assert Board(_board(tmp_path, EDGE)).layers == ["F.Cu", "In1.Cu", "B.Cu"]


def test_text_escapes_read_as_kicad_writes_them(tmp_path):
    from boardwright.model import Board

    b = Board(_board(tmp_path, EDGE + '\t(gr_text "a\\nb \\"c\\" d\\\\e" (at 110 60) (layer "F.SilkS"))\n'))
    assert [t.text for t in b.texts] == ['a\nb "c" d\\e']


def test_the_origin_is_the_outline_corner(tmp_path):
    from boardwright.model import Board

    b = Board(_board(tmp_path, EDGE + '\t(via (at 101 52) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 0))\n'))
    assert b.origin == (100.0, 50.0) and (b.vias[0].x, b.vias[0].y) == (1.0, 2.0)
    assert b.outline == [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0), (0.0, 0.0)]


def _line(a, b) -> str:
    return f'\t(gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (stroke (width 0.05) (type default)) (layer "Edge.Cuts"))\n'


def test_the_outline_is_the_largest_contour_closed_across_small_gaps(tmp_path):
    """Lines out of file order that miss by 4 um still close (kicad-tools'
    0.01 mm), with the last point put on the first; a cutout drawn first is
    not the outline."""
    from boardwright.model import Board

    cutout = '\t(gr_rect (start 110 55) (end 115 60) (stroke (width 0.05) (type default)) (fill no) (layer "Edge.Cuts"))\n'
    lines = [((100, 50), (130, 50)), ((130, 70), (100, 70)), ((130, 50), (130, 70)), ((100, 70), (100, 50.004))]
    b = Board(_board(tmp_path, cutout + "".join(_line(*ln) for ln in lines)))
    assert b.origin == (100.0, 50.0)
    assert b.outline == [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0), (0.0, 0.0)]


def test_a_polygon_outline_closes(tmp_path):
    from boardwright.model import Board

    poly = '\t(gr_poly (pts (xy 100 50) (xy 130 50) (xy 130 70) (xy 100 70)) (stroke (width 0.05) (type solid)) ' \
           '(fill solid) (layer "Edge.Cuts"))\n'
    b = Board(_board(tmp_path, poly))
    assert b.outline == [(0.0, 0.0), (30.0, 0.0), (30.0, 20.0), (0.0, 20.0), (0.0, 0.0)]
    assert [g.is_filled for g in b.graphics] == [True]      # KiCad 7 and older write (fill solid)


def test_a_vias_own_tenting_is_read_front_then_back(tmp_path):
    from boardwright.model import Board

    via = '\t(via (at 101 52) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (tenting (front yes) (back no)) (net 0))\n'
    b = Board(_board(tmp_path, EDGE + via + "\t(setup (tenting (front no) (back yes)))\n"))
    assert b.vias[0].tenting == ("yes", "no") and b.tenting == (False, True)


def test_a_copper_arc_on_a_line_is_a_straight_track(tmp_path):
    """kicad-tools refused to load the board (ValueError), which ended any
    command in an internal error."""
    from boardwright.model import Board

    b = Board(_board(tmp_path, EDGE + '\t(net 1 "A")\n\t(arc (start 101 51) (mid 102 51) (end 103 51) (width 0.2) '
                                       '(layer "F.Cu") (net 1))\n'))
    assert [(t.pts, t.net) for t in b.tracks] == [([(1.0, 1.0), (3.0, 1.0)], "A")]


def test_a_kicad_5_board_is_refused(tmp_path):
    from boardwright.errors import EnvironmentFault
    from boardwright.model import Board

    with pytest.raises(EnvironmentFault, match="KiCad 5 or older") as e:
        Board(_board(tmp_path, EDGE, version="20171130"))
    assert e.value.exit == 4


def test_a_file_that_is_not_a_board_is_refused(tmp_path):
    from boardwright.errors import EnvironmentFault
    from boardwright.model import Board

    p = tmp_path / "x.kicad_pcb"
    p.write_text("(kicad_sch (version 20250114))\n")
    with pytest.raises(EnvironmentFault, match="not a KiCad board"):
        Board(p)
    p.write_text("(kicad_pcb (version 20250114)\n")
    with pytest.raises(EnvironmentFault, match="not a readable KiCad board"):
        Board(p)


def test_a_newer_board_is_read_with_one_note(tmp_path, capsys):
    from boardwright.model import Board

    p = _board(tmp_path, EDGE, version="20990101")
    assert Board(p).origin == (100.0, 50.0) and Board(p).layers == ["F.Cu", "In1.Cu", "B.Cu"]
    err = capsys.readouterr().err
    assert err.count("saved by a KiCad newer than 10 (version 20990101)") == 1


def test_a_board_with_no_version_is_read(tmp_path):
    """KiCad's selection text (what `selection` reads) is a kicad_pcb document
    that may not say which version wrote it."""
    from boardwright.model import Board

    assert Board(_board(tmp_path, EDGE, version=None)).origin == (100.0, 50.0)
