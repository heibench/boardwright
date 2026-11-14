import pytest

from boardwright.si import STACKUPS, gap_for, width_for, z0, zdiff


@pytest.mark.parametrize("name", sorted(STACKUPS))
def test_width_for_inverts_z0(name):
    s = STACKUPS[name]
    w = width_for(50, s)
    assert z0(w, s["h"], s["er"]) == pytest.approx(50, abs=1.5)


def test_impedance_falls_as_track_widens():
    s = next(iter(STACKUPS.values()))
    assert z0(0.15, s["h"], s["er"]) > z0(0.3, s["h"], s["er"])


def test_pair_gap_for_90_ohm():
    s = STACKUPS["jlc4_7628"]
    g = gap_for(90, 0.2, s)
    assert g is not None and g > 0
    assert zdiff(0.2, g, s["h"], s["er"]) == pytest.approx(90, abs=3)
