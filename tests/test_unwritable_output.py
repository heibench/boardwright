"""A folder boardwright cannot write is an environment fault, exit 4 (#86)."""

import os
import shutil

import pytest
from conftest import ROOT

from boardwright.cli import main

BOARD = ROOT / "examples" / "boards" / "esp32c3_min"

pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="root writes through a read-only mode")


@pytest.fixture
def ro(tmp_path):
    d = tmp_path / "ro"
    d.mkdir()
    for f in ("esp32c3_min.kicad_pcb", "esp32c3_min.kicad_pro"):
        shutil.copy(BOARD / f, d)
    d.chmod(0o555)
    yield d
    d.chmod(0o755)


@pytest.mark.parametrize(
    "argv, path",
    [
        (lambda d: ["existing", str(d), "info"], lambda d: d / "boardwright_out"),
        (lambda d: ["preview", str(d / "esp32c3_min.kicad_pcb"), str(d / "p.png")], lambda d: d / "p.svg"),
    ],
    ids=["existing info", "preview"],
)
def test_an_unwritable_output_folder_exits_4_naming_it(ro, capsys, argv, path):
    """Both exited 2 with a traceback and "internal error", which reads as
    could not tell. The live apply snapshot reached the same handler."""
    assert main(argv(ro)) == 4
    err = capsys.readouterr().err
    assert err.strip().splitlines() == [f"boardwright: Permission denied: {path(ro)}"]
