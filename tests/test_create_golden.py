"""board.create on every example board, against the board recorded in
tests/data/create_golden/: the board as it stands before placement.

Each golden is kicad-tools 0.29's `create-pcb` output, made by
`boardwright place` up to that step, with the title block's date replaced by
"~" (it is today's). Two runs gave byte-identical files: kicad-tools derives
its uuids from the content. They were recorded where kicad-tools found no
working kicad-cli, so it read the schematic itself; with kicad-cli's netlist
the footprints and nets come in KiCad's order instead, and no-connect pads get
KiCad's own net names.

To record the current output as the golden: `uv run python tests/test_create_golden.py`.
"""

import os
import re
import shutil
from pathlib import Path
from unittest import mock

import pytest
from conftest import ROOT, needs_libs

from boardwright import board, build

GOLDEN = Path(__file__).parent / "data" / "create_golden"
EXAMPLES = sorted(p.name for p in (ROOT / "examples" / "boards").iterdir() if (p / "board.py").exists())


def normalize(t: str) -> str:
    return re.sub(r'(\n\t\t\(date )"[^"]*"\)', r'\1"~")', t, count=1)


class _Created(Exception):
    pass


def create(name: str, tmp: Path) -> str:
    """The example's board as `place` creates it, before anything is placed."""
    d = tmp / "boards" / name
    shutil.copytree(ROOT / "examples" / "boards" / name, d, ignore=shutil.ignore_patterns("out", "__pycache__"))
    shutil.copytree(ROOT / "examples" / "libs", tmp / "libs")        # customlib_test's LIBS = ["../../libs"]
    real = board.create

    def create_then_stop(*args, **kwargs):
        real(*args, **kwargs)
        raise _Created
    saved = dict(os.environ)          # a LIBS board points KICAD_*_DIR at its merged view under tmp
    try:
        with mock.patch.object(board, "create", create_then_stop), pytest.raises(_Created):
            build.stage_place(d, build.load(d))
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return (d / f"{name}.kicad_pcb").read_text()


@needs_libs
@pytest.mark.parametrize("name", EXAMPLES)
def test_create_matches_its_golden(tmp_path, name):
    assert normalize(create(name, tmp_path)) == (GOLDEN / f"{name}.kicad_pcb").read_text()


if __name__ == "__main__":
    import tempfile

    GOLDEN.mkdir(parents=True, exist_ok=True)
    # one folder for every case: a LIBS board leaves kicad-tools' symbol registry on its merged view
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["KICAD_CONFIG_HOME"] = str(Path(tmp) / "kicad_config")   # as conftest's own_kicad_settings
        for name in EXAMPLES:
            (GOLDEN / f"{name}.kicad_pcb").write_text(normalize(create(name, Path(tmp) / name)))
