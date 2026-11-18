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

The DSN must match byte for byte.

To record the current output as the golden: `uv run python tests/test_dsn_export.py`.
"""

import shutil
from pathlib import Path

import pytest

from boardwright import dsn

DATA = Path(__file__).parent / "data" / "dsn"
CASES = sorted(p.stem for p in DATA.glob("*.kicad_pcb"))


def run(case: str, tmp: Path) -> str:
    for ext in (".kicad_pcb", ".kicad_pro"):
        shutil.copy(DATA / f"{case}{ext}", tmp / f"{case}{ext}")
    out = tmp / "out" / f"{case}.dsn"
    out.parent.mkdir()
    dsn.export(tmp / f"{case}.kicad_pcb", out)
    return out.read_text()


def test_every_case_has_a_golden():
    assert len(CASES) == 10
    assert sorted(p.stem for p in DATA.glob("*.dsn")) == CASES


@pytest.mark.parametrize("case", CASES)
def test_dsn_matches_its_golden(tmp_path, case):
    assert run(case, tmp_path) == (DATA / f"{case}.dsn").read_text()


if __name__ == "__main__":
    import tempfile

    for case in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            (DATA / f"{case}.dsn").write_text(run(case, Path(tmp)))
