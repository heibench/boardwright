"""Points that are the same in the board file stay the same in the review keys.

Coordinates come out of the board model as differences from the board origin,
so a pad centre and the track end on it can differ by float noise: on
feastorg/Slice_AQEC, R2.2 at y 34.0625 and the track ends at
34.062500000000014. 34.0625 sits exactly on a half of the 0.001 mm grid the
keys used, so the two fell into different cells and the track end was not seen
as a stop at the pad. KiCad stores nanometres, so both are snapped to 1e-6 mm
first."""

from pathlib import Path
from types import SimpleNamespace

from boardwright import bends, jogs, segments, tidy
from boardwright.model import Pad, Track, Via

PAD = (34.25, 34.0625)
NOISY = (34.25000000000003, 34.062500000000014)        # the same point, as the model gives a track end


def _board(tracks, vias=(), pad=PAD):
    pad = Pad("R2", "2", "N", *pad, "F.Cu", 0.8, 0.95, 0, False, ["F.Cu"])
    return SimpleNamespace(tracks=[Track(list(t), 0.25, "F.Cu", "N") for t in tracks], pads=[pad], vias=list(vias),
                           zones=[], layers=["F.Cu", "B.Cu"], path=Path("/nonexistent/board.kicad_pcb"))


THROUGH = [((PAD[0] - 1, PAD[1]), NOISY), (NOISY, (PAD[0] + 1, PAD[1]))]      # straight on through the pad centre


def test_a_straight_run_stopping_at_its_pad_centre_is_no_split():
    assert [f for f in tidy.findings(_board(THROUGH), {"N"}) if f[0] == "split"] == []


def test_a_straight_run_stopping_at_its_pad_centre_counts_two_runs():
    assert segments.runs(_board(THROUGH), "N") == 2


def test_a_step_into_its_pad_centre_is_an_end_jog():
    """A run 0.1 mm below the pad's line, then a 0.1 mm step up onto its centre."""
    tracks = [((PAD[0] - 2, PAD[1] + 0.1), (NOISY[0] - 0.1, PAD[1] + 0.1)), ((NOISY[0] - 0.1, PAD[1] + 0.1), NOISY)]
    found = jogs.jogs(_board(tracks), {"N"}, 1.0)
    assert [f[0] for f in found] == ["end jog"]


def test_a_corner_whose_two_ends_differ_by_noise_is_one_bend():
    """Two segments meeting at a half-grid point clear of the pad, one end noisy."""
    corner, noisy = (40.0, PAD[1]), (40.000000000000014, NOISY[1])
    found = bends.bends(_board([((38.0, PAD[1]), corner), (noisy, (40.0, PAD[1] + 2))]), {"N"})
    assert [f[0] for f in found] == ["square"]


def test_a_step_onto_a_via_a_hair_from_its_end_is_an_end_jog():
    """A via 0.1 um from the step's end, either side of a 1 um cell edge
    (16.8825 is a half of the 0.001 mm grid): still the step's via."""
    via = Via(16.8825, 47.0838, 0.6, 0.3, ["F.Cu", "B.Cu"], "N")
    tracks = [((10.0, 47.0838 + 0.1), (16.8826 - 0.1, 47.0838 + 0.1)), ((16.8826 - 0.1, 47.0838 + 0.1), (16.8826, 47.0838))]
    found = jogs.jogs(_board(tracks, [via], pad=(0, 0)), {"N"}, 1.0)
    assert [f[0] for f in found] == ["end jog"]


def test_a_pad_the_model_rounds_to_a_tenth_micron_is_still_a_stop():
    """The model gives pad centres to 0.1 um (11.2755), the file has the track
    ends on them in nanometres (11.275535): 35 nm apart, and 11.2755 is a half of
    a 1 um cell. A stop is matched by distance, so the pad still holds the run."""
    end = (11.275535, 20.0)
    through = [((10.0, 20.0), end), (end, (12.5, 20.0))]
    board = _board(through, pad=(11.2755, 20.0))
    assert [f for f in tidy.findings(board, {"N"}) if f[0] == "split"] == []
    assert segments.runs(board, "N") == 2


def test_points_a_hair_apart_across_a_cell_edge_are_one_point():
    """34.063 is the edge between two 1 um cells; 0.2 um either side is one point."""
    key = tidy._Points([(1.0, 34.0628), (1.0, 34.0632)])
    assert key((1.0, 34.0628)) == key((1.0, 34.0632))


def test_a_row_of_close_points_does_not_chain_into_one():
    """Each 0.6 um from the next: the first gathers the second, not the third,
    which starts a point of its own and gathers the fourth, 0.4 um on."""
    a, b, c, d = (1.0, 2.0), (1.0006, 2.0), (1.0012, 2.0), (1.0016, 2.0)
    key = tidy._Points([a, b, c, d])
    assert key(a) == key(b) and key(c) != key(a) and key(d) == key(c)
