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
from boardwright.model import Pad, Track

PAD = (34.25, 34.0625)
NOISY = (34.25000000000003, 34.062500000000014)        # the same point, as the model gives a track end


def _board(tracks):
    pad = Pad("R2", "2", "N", *PAD, "F.Cu", 0.8, 0.95, 0, False, ["F.Cu"])
    return SimpleNamespace(tracks=[Track(list(t), 0.25, "F.Cu", "N") for t in tracks], pads=[pad], vias=[],
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
