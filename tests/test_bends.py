"""REVIEW "bends": the angle at each bend of a route (#138), on copies of
rp2040_min whose GPIO25 leaves U1.37 eastward in one straight segment A -> B.
Each path below ends eastward into B, so the bend already at B is unchanged."""

from types import SimpleNamespace

from conftest import BOARDS
from test_segments import A, B
from test_tidy import OX, OY, _edit

from boardwright.bends import bends_check
from boardwright.model import Board
from boardwright.review import review

RP = BOARDS / "rp2040_min" / "rp2040_min.kicad_pcb"
END = ((158.2149, 104.4), (159.2149, 105.4), B)       # back down at 45 degrees, then east into B
VIA = ('\t(via\n\t\t(at 155 105.4)\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n'
       '\t\t(net "GPIO25")\n\t\t(uuid "00000000-0000-0000-0000-000000000200")\n\t)\n')


def _path(*pts, via=False):
    edit = _edit(*zip(pts, pts[1:]))
    if not via:
        return edit

    def with_via(t):
        t = edit(t)
        end = t.rstrip().rfind(")")
        return t[:end] + VIA + t[end:]
    return with_via


def _check(tmp_path, edit=None, fail=("acute",), nets="GPIO25"):
    pcb = tmp_path / RP.name
    t = RP.read_text()
    pcb.write_text(edit(t) if edit else t)
    return bends_check(Board(pcb), {"bends": [(nets, list(fail))]})


def _at(x, y):
    return f"({x - OX:.2f}, {y - OY:.2f})"


SQUARE = (A, (155, 105.4), (155, 104.4), *END)       # up at 90 degrees, along, back down


def test_a_straight_route_has_no_bends(tmp_path):
    assert _check(tmp_path) == (["bends 1 net(s): acute 0, square 0, off-45 0 (failing: acute)"], [])
    split = _check(tmp_path, _path(A, (155, 105.4), B), fail=("off-45",))     # a straight joint is no bend
    assert split == (["bends 1 net(s): acute 0, square 0, off-45 0 (failing: off-45)"], [])


def test_an_acute_bend_fails(tmp_path):
    lines, fails = _check(tmp_path, _path(A, (155, 105.4), (154, 104.4), *END))
    assert lines[0] == "bends 1 net(s): acute 2, square 0, off-45 0 (failing: acute)"
    assert fails == [f"acute bend on GPIO25 F.Cu at {_at(154, 104.4)}, 45.0 degrees",
                     f"acute bend on GPIO25 F.Cu at {_at(155, 105.4)}, 45.0 degrees"]


def test_a_square_bend_is_reported_and_fails_only_when_asked(tmp_path):
    lines, fails = _check(tmp_path, _path(*SQUARE))
    assert fails == []
    assert lines == ["bends 1 net(s): acute 0, square 2, off-45 0 (failing: acute)",
                     f"square bend on GPIO25 F.Cu at {_at(155, 104.4)}, 90.0 degrees",
                     f"square bend on GPIO25 F.Cu at {_at(155, 105.4)}, 90.0 degrees"]
    assert len(_check(tmp_path, _path(*SQUARE), fail=("square",))[1]) == 2


OFF = (A, (155, 105.4), (156, 104.9), (157, 104.9), (157.5, 105.4), B)   # one segment at 153.4 degrees


def test_a_segment_off_the_45_degree_grid_is_off_45(tmp_path):
    lines, fails = _check(tmp_path, _path(*OFF), fail=("off-45",))
    assert lines == ["bends 1 net(s): acute 0, square 0, off-45 1 (failing: off-45)"]
    assert fails == [f"off-45 segment on GPIO25 F.Cu from {_at(155, 105.4)}, running at 153.4 degrees"]


def test_an_off_45_segment_at_a_via_is_still_named(tmp_path):
    """The via covers the corner but not the segment's direction."""
    assert _check(tmp_path, _path(*OFF, via=True), fail=("off-45",))[1] == [
        f"off-45 segment on GPIO25 F.Cu from {_at(155, 105.4)}, running at 153.4 degrees"]


def test_a_segment_shorter_than_micro_has_no_direction(tmp_path):
    """A 0.03 mm piece at 26.6 degrees is left to tidy."""
    path = (A, (155, 105.4), (155.0268, 105.3866), (155.0268 + 0.0134, 105.4), B)
    assert _check(tmp_path, _path(*path), fail=("off-45",))[1] == []


def test_a_bend_at_a_via_is_not_judged(tmp_path):
    lines = _check(tmp_path, _path(*SQUARE, via=True))[0]
    assert lines[0] == "bends 1 net(s): acute 0, square 1, off-45 0 (failing: acute)"
    assert not any(_at(155, 105.4) in ln for ln in lines)


def test_a_bend_inside_a_pad_is_not_judged(tmp_path):
    """A square bend at x 152.2, inside U1.37 (which reaches x 152.375): the
    pad's copper covers the inside corner. The rest of the path turns at 45."""
    lines = _check(tmp_path, _path(A, (152.2, 105.4), (152.2, 105.9), (152.7, 106.4), (157, 106.4), (158, 105.4), B))[0]
    assert lines == ["bends 1 net(s): acute 0, square 0, off-45 0 (failing: acute)"]


def test_an_unknown_kind_or_net_fails(tmp_path):
    assert _check(tmp_path, fail=("sharp",))[1] == ["bends: unknown kind sharp; the kinds are acute, square, off-45"]
    assert _check(tmp_path, nets="NOPE")[1] == ["bends NOPE: no such net"]


def test_review_runs_the_bends_check(tmp_path):
    pcb = tmp_path / RP.name
    pcb.write_text(_path(A, (155, 105.4), (154, 104.4), *END)(RP.read_text()))
    fails = review(pcb, SimpleNamespace(REVIEW={"bends": [("GPIO25", ["acute"])]}))
    assert any(f.startswith("acute bend on GPIO25") for f in fails)
