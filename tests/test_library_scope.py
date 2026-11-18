"""A board's own libraries (LIBS) are used for that board's build only (#69)."""

import os
import shutil

from conftest import ROOT, needs_libs

from boardwright.cli import main

VARS = [f"{v}_{k}_DIR" for v in ("KICAD", "KICAD10", "KICAD9") for k in ("SYMBOL", "FOOTPRINT")]


@needs_libs
def test_a_board_with_libs_leaves_the_next_board_on_the_stock_libraries(tmp_path):
    """Placing customlib_test merges its libraries into <board>/.libmerge. The
    next board placed in the same process reads the stock libraries, even once
    that merged view is gone, and the library variables are as they were."""
    shutil.copytree(ROOT / "examples" / "libs", tmp_path / "libs")      # customlib_test's LIBS = ["../../libs"]
    for name in ("customlib_test", "esp32c3_min"):
        shutil.copytree(ROOT / "examples" / "boards" / name, tmp_path / "boards" / name,
                        ignore=shutil.ignore_patterns("out", "__pycache__", ".libmerge"))
    before = {v: os.environ.get(v) for v in VARS}
    custom = tmp_path / "boards" / "customlib_test"
    assert main(["place", str(custom)]) == 0
    assert {v: os.environ.get(v) for v in VARS} == before
    shutil.rmtree(custom / ".libmerge")
    assert main(["place", str(tmp_path / "boards" / "esp32c3_min")]) == 0
