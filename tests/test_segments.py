"""REVIEW "segments": track segments against the fewest the route needs (#148),
on copies of rp2040_min, whose LED_25 chain runs U1.37 -> R9 -> D2.2."""

from types import SimpleNamespace

from conftest import BOARDS
from test_loop import _no_tracks

from boardwright.model import Board
from boardwright.review import review
from boardwright.segments import segments_check

RP = BOARDS / "rp2040_min" / "rp2040_min.kicad_pcb"
# GPIO25's first segment, U1.37 eastward, in file coordinates
SEG = '''	(segment
		(start 151.9375 105.4)
		(end 159.7149 105.4)
		(width 0.2)
		(layer "F.Cu")
		(net "GPIO25")
		(uuid "04dddb40-cb66-4053-ade9-b0ed9f6c109b")
	)
'''


def _seg(a, b, n):
    return (f'\t(segment\n\t\t(start {a[0]} {a[1]})\n\t\t(end {b[0]} {b[1]})\n\t\t(width 0.2)\n\t\t(layer "F.Cu")\n'
            f'\t\t(net "GPIO25")\n\t\t(uuid "00000000-0000-0000-0000-00000000010{n}")\n\t)\n')


def _path(*pts):
    """GPIO25's first segment replaced by a path through pts."""
    def edit(t):
        assert t.count(SEG) == 1
        return t.replace(SEG, "".join(_seg(a, b, i) for i, (a, b) in enumerate(zip(pts, pts[1:]))))
    return edit


def _check(tmp_path, spec, edit=None):
    pcb = tmp_path / RP.name
    t = RP.read_text()
    pcb.write_text(edit(t) if edit else t)
    return segments_check(Board(pcb), {"segments": spec})


A, B = (151.9375, 105.4), (159.7149, 105.4)


def test_a_chain_through_a_series_part_is_judged_whole(tmp_path):
    lines, fails = _check(tmp_path, [("GPIO25", 7)])
    assert lines == ["segments U1.37 -> D2.2 through R9 (GPIO25, LED_25): 10, minimum 3 (excess <= 7)"]
    assert fails == []


def test_naming_either_net_of_the_chain_judges_it_once(tmp_path):
    assert len(_check(tmp_path, [(["LED_25", "GPIO25"], 7)])[0]) == 1


def test_a_dog_leg_is_excess(tmp_path):
    """One straight segment replaced by three: two more than the route needs."""
    lines, fails = _check(tmp_path, [("GPIO25", 7)], _path(A, (155, 105.4), (155.5, 105.9), B))
    assert lines == ["segments U1.37 -> D2.2 through R9 (GPIO25, LED_25): 12, minimum 3 (excess <= 7)"]
    assert fails == ["U1.37 -> D2.2 through R9 (GPIO25, LED_25) takes 12 segments where 3 would do, excess 9, limit 7"]


def test_a_straight_run_split_in_two_is_one_run(tmp_path):
    lines = _check(tmp_path, [("GPIO25", 7)], _path(A, (155, 105.4), B))[0]
    assert lines == ["segments U1.37 -> D2.2 through R9 (GPIO25, LED_25): 10, minimum 3 (excess <= 7)"]


def test_a_via_starts_a_new_run_and_allows_one_more_segment(tmp_path):
    """The straight run split in two with a via of its net at the split: the two
    halves are not joined across the via, and the minimum rises by one."""
    via = ('\t(via\n\t\t(at 155 105.4)\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n'
           '\t\t(net "GPIO25")\n\t\t(uuid "00000000-0000-0000-0000-000000000200")\n\t)\n')
    def edit(t):
        t = _path(A, (155, 105.4), B)(t)
        end = t.rstrip().rfind(")")
        return t[:end] + via + t[end:]
    lines = _check(tmp_path, [("GPIO25", 7)], edit)[0]
    assert lines == ["segments U1.37 -> D2.2 through R9 (GPIO25, LED_25): 11, minimum 4 (excess <= 7)"]


def test_octilinear_pads_need_one_segment_and_others_two():
    from boardwright.segments import _octilinear, _tree_minimum
    assert [_octilinear((0, 0), q) for q in [(3, 0), (0, 3), (2, 2), (2, -2), (1, 2), (3, 1)]] == [1, 1, 1, 1, 2, 2]
    # a square's spanning tree is three sides, each one segment; a skewed point adds two
    assert _tree_minimum([(0, 0), (2, 0), (2, 2), (0, 2)]) == 3
    assert _tree_minimum([(0, 0), (2, 0), (5, 1)]) == 3


def test_a_net_outside_any_chain_uses_its_pads(tmp_path):
    lines = _check(tmp_path, [("RUN", 99)])[0]
    assert len(lines) == 1 and lines[0].startswith("segments RUN: ") and "minimum" in lines[0]


def test_a_net_with_no_track_cannot_judge(tmp_path):
    def strip(t):
        return _no_tracks("LED_25")(_no_tracks("GPIO25")(t))
    assert _check(tmp_path, [("GPIO25", 7)], strip)[1] == ["segments GPIO25: cannot judge, it has no track"]


def test_an_unknown_net_fails(tmp_path):
    assert _check(tmp_path, [("NOPE", 0)])[1] == ["segments NOPE: no such net"]


def test_review_runs_the_segments_check(tmp_path):
    pcb = tmp_path / RP.name
    pcb.write_text(RP.read_text())
    fails = review(pcb, SimpleNamespace(REVIEW={"segments": [("GPIO25", 0)]}))
    assert any(f.startswith("U1.37 -> D2.2 through R9") for f in fails)
