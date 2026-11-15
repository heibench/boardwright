import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOARDS = ROOT / "examples" / "boards"


def board(name: str) -> Path:
    return BOARDS / name / f"{name}.kicad_pcb"


@pytest.fixture
def ldo_copy(tmp_path) -> Path:
    """A writable copy of the LDO example project."""
    dst = tmp_path / "ldo_breakout"
    # gate reports a local run left behind are not part of the example
    shutil.copytree(BOARDS / "ldo_breakout", dst, ignore=shutil.ignore_patterns("out", "boardwright_out", ".libmerge"))
    return dst


def _have_libraries() -> bool:
    from boardwright import env

    try:
        env.libraries()
        return True
    except SystemExit:
        return False


def _have_kicad_cli() -> bool:
    from boardwright import env

    try:
        env.kicad_cli()
        return True
    except SystemExit:
        return False


needs_libs = pytest.mark.skipif(not _have_libraries(), reason="KiCad's stock libraries not installed")
needs_kicad = pytest.mark.skipif(not _have_kicad_cli(), reason="kicad-cli not found")


def _have_freerouting() -> bool:
    from boardwright import env

    try:
        env.freerouting()
        return True
    except SystemExit:
        return False


needs_freerouting = pytest.mark.skipif(not _have_freerouting(), reason="Freerouting not found")
