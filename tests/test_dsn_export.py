"""The DSN Freerouting is given (dsn.export), against the output recorded in
tests/data/dsn/.

Each case is a board and its project (`<case>.kicad_pcb`, `<case>.kicad_pro`)
and the DSN written for it (`<case>.dsn`). The boards are what `gen` and
`existing reroute` export:

- customlib_test, esp32c3_min, ldo_breakout, rp2040_min, stm32f103_4l,
  stm32f103_min, tps54202_buck: `boardwright place` on the example, the board
  `gen` hands to Freerouting
- esp32c3_min_back: the same with the module turned 90 degrees and on the back
  (test_place_golden's esp32c3_min_u1_r90_back)
- ldo_arcs: the routed LDO example with LED_A ripped up, as `existing reroute`
  leaves it, and two +3V3 tracks made arcs (same ends, mid point 0.3 mm off
  the chord)
- tps54202_routed: the routed buck example with FB ripped up: its pours and
  ZONES, and protected tracks and vias on every other net

The goldens are kicad-tools 0.29's `pcb export-dsn` followed by
add_arcs_to_dsn, as recorded before the export moved in-house. The DSN must
match them line for line, with two differences normalized:

- the header's `(host_version ...)` says "boardwright", not "kicad-tools"
- an arc's polyline points may differ by 0.1 um, the last digit written: they
  are worked out in the file's coordinates, where add_arcs_to_dsn worked them
  out from the board origin and added it back, so a point that falls on a
  half of the last digit can round either way (one point of ldo_arcs does)

To record the current output as the golden: `uv run python tests/test_dsn_export.py`.
"""

import re
import shutil
from pathlib import Path

import pytest

from boardwright import dsn

DATA = Path(__file__).parent / "data" / "dsn"
CASES = sorted(p.stem for p in DATA.glob("*.kicad_pcb"))


def _copy(case: str, tmp: Path) -> Path:
    for ext in (".kicad_pcb", ".kicad_pro"):
        shutil.copy(DATA / f"{case}{ext}", tmp / f"{case}{ext}")
    return tmp / f"{case}.kicad_pcb"


def run(case: str, tmp: Path) -> str:
    out = tmp / "out" / f"{case}.dsn"
    dsn.export(_copy(case, tmp), out)
    return out.read_text()


def test_every_case_has_a_golden():
    assert len(CASES) == 10
    assert sorted(p.stem for p in DATA.glob("*.dsn")) == CASES


def same(got: str, want: str) -> bool:
    if got == want:
        return True
    a, b = got.split(), want.split()
    return (len(a) == len(b) and a[:3] == b[:3] and a[0] == "(path"
            and all(abs(float(x.rstrip(")")) - float(y.rstrip(")"))) <= 0.1 + 1e-9 for x, y in zip(a[3:], b[3:]))
            and all(re.sub(r"[\d.-]", "", x) == re.sub(r"[\d.-]", "", y) for x, y in zip(a, b)))


@pytest.mark.parametrize("case", CASES)
def test_dsn_matches_its_golden(tmp_path, case):
    got = run(case, tmp_path).split("\n")
    want = (DATA / f"{case}.dsn").read_text().replace('(host_version "kicad-tools")', '(host_version "boardwright")')
    want = want.split("\n")
    assert len(got) == len(want)
    assert [i for i, (g, w) in enumerate(zip(got, want)) if not same(g, w)] == []


def test_every_routable_copper_layer_goes_in_front_to_back(tmp_path):
    """kicad-tools knew In1-In6 only and kept the file's order. A layer of
    KiCad 10's jumper type is not routed on."""
    pcb = _copy("stm32f103_4l", tmp_path)
    t = pcb.read_text()
    old = '\t\t(0 "F.Cu" signal)\n\t\t(1 "In1.Cu" signal)\n\t\t(2 "In2.Cu" signal)\n\t\t(31 "B.Cu" signal)\n'
    assert t.count(old) == 1
    inner = "".join(f'\t\t({2 + 2 * i} "In{i}.Cu" {"jumper" if i == 4 else "power" if i == 7 else "signal"})\n'
                    for i in range(1, 9))
    pcb.write_text(t.replace(old, '\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n' + inner))
    out = tmp_path / "out.dsn"
    dsn.export(pcb, out)
    got = out.read_text()
    assert re.findall(r"\n    \(layer (\S+)", got) == ["F.Cu", "In1.Cu", "In2.Cu", "In3.Cu", "In5.Cu", "In6.Cu",
                                                         "In7.Cu", "In8.Cu", "B.Cu"]
    assert "(padstack Via[0-8]_Pad600_um" in got


def test_unconditional_kicad_dru_rules_raise_every_class(tmp_path):
    """An unconditional clearance, track_width or via_diameter minimum in the
    .kicad_dru raises every class; a conditional or layer rule does not, and a
    file KiCad would ignore whole is ignored."""
    pcb = _copy("ldo_breakout", tmp_path)
    out = tmp_path / "out.dsn"
    rules = """(version 1)
(rule "floor" (constraint clearance (min 0.3mm)))
(rule "tracks" (condition "A.Type == 'track'") (constraint track_width (min 0.4mm)))
(rule "gnd" (condition "A.NetName == 'GND'") (constraint track_width (min 1mm)))
(rule "top" (layer "F.Cu") (constraint via_diameter (min 2mm)))
"""
    pcb.with_suffix(".kicad_dru").write_text(rules)
    dsn.export(pcb, out)
    got = out.read_text()
    assert "        (width 400.0)\n        (clearance 300.0)" in got
    assert "Via[0-1]_Pad2000_um" not in got
    pcb.with_suffix(".kicad_dru").write_text(rules + '(rule "x" (constraint solder_mask_margin (min 1mm)))\n')
    dsn.export(pcb, out)
    assert "        (width 250.0)\n        (clearance 200.0)" in out.read_text()


def test_nothing_is_written_beside_the_board(tmp_path):
    """kicad-tools wrote <board>.dsn-revision.json beside the board, into the
    user's project on `existing reroute`."""
    pcb = _copy("ldo_breakout", tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    assert dsn.export(pcb, tmp_path / "out" / "x.dsn") == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(before + ["out"])


if __name__ == "__main__":
    import tempfile

    for case in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            (DATA / f"{case}.dsn").write_text(run(case, Path(tmp)))
