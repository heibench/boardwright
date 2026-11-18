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


def _summary(path: Path) -> dict:
    return reader_dump.summary(reader_dump.dump(path))


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
