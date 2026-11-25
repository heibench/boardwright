"""REVIEW "tidy": track debris DRC passes (#138), on copies of rp2040_min whose
GPIO25 leaves U1.37 eastward in one straight segment."""

from types import SimpleNamespace

from conftest import BOARDS
from test_segments import SEG, A, B, _seg

from boardwright import tidy
from boardwright.model import Board
from boardwright.review import review
from boardwright.tidy import tidy_check

RP = BOARDS / "rp2040_min" / "rp2040_min.kicad_pcb"
OX, OY = 118.5, 82.0            # the board's origin: findings are reported relative to it


def _edit(*segs):
    """GPIO25's first segment replaced by these (start, end) segments."""
    def edit(t):
        assert t.count(SEG) == 1
        return t.replace(SEG, "".join(_seg(a, b, i) for i, (a, b) in enumerate(segs)))
    return edit


def _check(tmp_path, edit=None, nets=("GPIO25",)):
    pcb = tmp_path / RP.name
    t = RP.read_text()
    pcb.write_text(edit(t) if edit else t)
    return tidy_check(Board(pcb), {"tidy": list(nets)})


def _at(x, y):
    return f"({x - OX:.2f}, {y - OY:.2f})"


def test_a_clean_route_passes(tmp_path):
    assert _check(tmp_path, nets=("GPIO25", "LED_25")) == (["tidy 2 net(s): clean"], [])


def test_a_segment_shorter_than_micro_is_named(tmp_path, monkeypatch):
    lines, fails = _check(tmp_path, _edit((A, (155, 105.4)), ((155, 105.4), (155.02, 105.42)), ((155.02, 105.42), B)))
    assert f"micro on GPIO25 F.Cu at {_at(155, 105.4)}: a 0.028 mm segment" in fails
    assert not any(f.startswith("near-miss") for f in fails)      # its own two ends are not a miss
    monkeypatch.setattr(tidy, "MICRO", 0.01)
    assert not any(f.startswith("micro") for f in _check(tmp_path, _edit(
        (A, (155, 105.4)), ((155, 105.4), (155.02, 105.42)), ((155.02, 105.42), B)))[1])


def test_a_straight_run_split_in_two_is_named(tmp_path):
    lines, fails = _check(tmp_path, _edit((A, (155, 105.4)), ((155, 105.4), B)))
    assert lines == ["tidy 1 net(s): split 1"]
    assert fails == [f"split on GPIO25 F.Cu at {_at(155, 105.4)}: two collinear segments where one would do"]


def test_a_split_at_a_via_is_not_named(tmp_path):
    via = ('\t(via\n\t\t(at 155 105.4)\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n'
           '\t\t(net "GPIO25")\n\t\t(uuid "00000000-0000-0000-0000-000000000200")\n\t)\n')

    def edit(t):
        t = _edit((A, (155, 105.4)), ((155, 105.4), B))(t)
        end = t.rstrip().rfind(")")
        return t[:end] + via + t[end:]
    assert _check(tmp_path, edit) == (["tidy 1 net(s): clean"], [])


def test_track_ends_at_a_via_are_not_dangling(tmp_path):
    """Two segments stopping 0.15 mm apart, both inside a 0.6 mm via of their net."""
    via = ('\t(via\n\t\t(at 155 105.4)\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n'
           '\t\t(net "GPIO25")\n\t\t(uuid "00000000-0000-0000-0000-000000000200")\n\t)\n')

    def edit(t):
        t = _edit((A, (155, 105.4)), ((155.15, 105.4), B))(t)
        end = t.rstrip().rfind(")")
        return t[:end] + via + t[end:]
    assert _check(tmp_path, edit) == (["tidy 1 net(s): clean"], [])


def test_two_ends_that_miss_each_other_are_named(tmp_path):
    fails = _check(tmp_path, _edit((A, (155, 105.4)), ((155.01, 105.4), B)))[1]
    assert f"near-miss on GPIO25 F.Cu at {_at(155, 105.4)}: two track ends 0.010 mm apart" in fails


def test_a_segment_lying_over_another_is_named(tmp_path):
    fails = _check(tmp_path, _edit((A, B), ((153, 105.4), (156, 105.4))))[1]
    assert f"overlap on GPIO25 F.Cu at {_at(153, 105.4)}: two segments lie over each other for 3.000 mm" in fails


def test_a_spur_ending_on_nothing_is_named(tmp_path):
    fails = _check(tmp_path, _edit((A, (155, 105.4)), ((155, 105.4), B), ((155, 105.4), (155, 104))))[1]
    assert fails == [f"dangling on GPIO25 F.Cu at {_at(155, 104)}: ends on nothing"]


def test_a_track_ending_off_its_pad_centre_is_named(tmp_path):
    fails = _check(tmp_path, _edit(((152.0375, 105.4), B)))[1]
    assert fails == [f"off-centre on GPIO25 F.Cu at {_at(152.0375, 105.4)}: ends 0.100 mm from the centre of U1.37"]


def test_a_track_stopping_outside_its_pad_is_named(tmp_path):
    """U1.37's east edge is at x 152.375; the track stops 0.075 mm beyond it,
    within its own half-width of 0.1 mm, so only its width touches the pad."""
    fails = _check(tmp_path, _edit(((152.45, 105.4), B)))[1]
    assert fails == [f"short-of-pad on GPIO25 F.Cu at {_at(152.45, 105.4)}: ends outside U1.37, "
                     "joined to it only by the track's width"]


def test_a_track_ending_on_another_tracks_body_is_named(tmp_path):
    fails = _check(tmp_path, _edit((A, B), ((155, 105.4), (155, 104)), ((155, 104), (157, 104))))[1]
    assert f"on-track on GPIO25 F.Cu at {_at(155, 105.4)}: ends on the body of another track, not at its end" in fails


def test_an_unknown_net_fails(tmp_path):
    assert _check(tmp_path, nets=("NOPE",))[1] == ["tidy NOPE: no such net"]


def test_review_runs_the_tidy_check(tmp_path):
    pcb = tmp_path / RP.name
    pcb.write_text(_edit((A, (155, 105.4)), ((155, 105.4), B))(RP.read_text()))
    fails = review(pcb, SimpleNamespace(REVIEW={"tidy": ["GPIO25"]}))
    assert any(f.startswith("split on GPIO25") for f in fails)
