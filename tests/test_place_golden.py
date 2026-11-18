"""`boardwright place` on every example board, against the output recorded in
tests/data/place_golden/: the board file must match outside its footprint blocks
byte for byte, and each footprint block must match too.

The golden board files have every `(uuid ...)` and the title block's date
replaced by "~": the hand-copper uuids are new on every run and the date is
today's. The schematic, which placement does not touch, is kept as a sha256.

To record the current output as the golden: `uv run python tests/test_place_golden.py`.
"""

import hashlib
import os
import re
import shutil
from pathlib import Path

import pytest
from conftest import ROOT, needs_libs

from boardwright.cli import main
from boardwright.copper import blocks

GOLDEN = Path(__file__).parent / "data" / "place_golden"
EXAMPLES = sorted(p.name for p in (ROOT / "examples" / "boards").iterdir() if (p / "board.py").exists())
# the module's keep-out zone turned, and on the back: what test_module_keepout_matches_its_library_copy places
VARIANTS = {
    "esp32c3_min_u1_r90": ("esp32c3_min", '(MX, MY, 90)'),
    "esp32c3_min_u1_r90_back": ("esp32c3_min", '(MX, MY, 90, "B")'),
}
CASES = EXAMPLES + sorted(VARIANTS)


def normalize(t: str) -> str:
    t = re.sub(r'\(uuid "[^"]*"\)', '(uuid "~")', t)
    return re.sub(r'(\n\t\t\(date )"[^"]*"\)', r'\1"~")', t, count=1)


def split(t: str) -> tuple[str, list[str]]:
    """The board without its top-level footprint blocks (each left as a marker), and those blocks."""
    fps = [(s, e) for s, e in blocks(t, ("footprint",)) if t[s:s + 13] == "\n\t(footprint "]
    rest, pos = [], 0
    for s, e in fps:
        rest.append(t[pos:s] + "\n\t(footprint ~)")
        pos = e
    return "".join(rest) + t[pos:], [t[s:e] for s, e in fps]


def place(case: str, tmp: Path) -> Path:
    name, spec = VARIANTS.get(case, (case, None))
    d = tmp / "boards" / name
    shutil.copytree(ROOT / "examples" / "boards" / name, d, ignore=shutil.ignore_patterns("out", "__pycache__"))
    shutil.copytree(ROOT / "examples" / "libs", tmp / "libs")        # customlib_test's LIBS = ["../../libs"]
    if spec:
        b = d / "board.py"
        t = b.read_text()
        assert '"U1": (MX, MY, 0),' in t
        b.write_text(t.replace('"U1": (MX, MY, 0),', f'"U1": {spec},'))
    saved = dict(os.environ)          # a LIBS board points KICAD_*_DIR at its merged view under tmp
    try:
        assert main(["place", str(d)]) == 0
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return d / name


@needs_libs
@pytest.mark.parametrize("case", CASES)
def test_place_matches_its_golden(tmp_path, case):
    out = place(case, tmp_path)
    got_rest, got_fps = split(normalize(out.with_suffix(".kicad_pcb").read_text()))
    want_rest, want_fps = split((GOLDEN / f"{case}.kicad_pcb").read_text())
    assert got_rest == want_rest, "the board differs outside its footprint blocks"
    assert len(got_fps) == len(want_fps)
    for got, want in zip(got_fps, want_fps):
        ref = re.search(r'\(property "Reference" "([^"]*)"', want).group(1)
        assert got == want, f"footprint {ref} differs from its golden"
    sch = hashlib.sha256(out.with_suffix(".kicad_sch").read_bytes()).hexdigest()
    assert sch == (GOLDEN / f"{case}.kicad_sch.sha256").read_text().strip()



@needs_libs
@pytest.mark.parametrize("case", ["esp32c3_min", *VARIANTS])
def test_module_zone_is_placed_in_board_coordinates(tmp_path, case):
    """The module's keep-out zone is its library outline, mirrored on the back,
    turned and moved with the footprint: board coordinates, where KiCad keeps it."""
    import math

    out = place(case, tmp_path)
    t = out.with_suffix(".kicad_pcb").read_text()
    fp = next(t[s:e] for s, e in blocks(t, ("footprint",)) if '"RF_Module:ESP32-C3-WROOM-02"' in t[s:s + 200])
    at = re.search(r"\n\t\t\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", fp)
    fx, fy, rot = float(at.group(1)), float(at.group(2)), float(at.group(3) or 0)
    back = '\n\t\t(layer "B.Cu")' in fp
    assert back == case.endswith("_back")
    c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    lib = (out.parent / "libs/RF_Module.pretty/ESP32-C3-WROOM-02.kicad_mod").read_text()
    want = []
    for x, y in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", lib[slice(*blocks(lib, ("zone",))[0])]):
        lx, ly = float(x), -float(y) if back else float(y)
        want += [fx + lx * c + ly * s, fy - lx * s + ly * c]
    got = [float(v) for xy in re.findall(r"\(xy ([-\d.]+) ([-\d.]+)\)", fp[slice(*blocks(fp, ("zone",))[0])]) for v in xy]
    assert got == pytest.approx(want)

if __name__ == "__main__":
    import tempfile

    GOLDEN.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["KICAD_CONFIG_HOME"] = str(Path(tmp) / "kicad_config")   # as conftest's own_kicad_settings
            out = place(case, Path(tmp))
            (GOLDEN / f"{case}.kicad_pcb").write_text(normalize(out.with_suffix(".kicad_pcb").read_text()))
            sch = hashlib.sha256(out.with_suffix(".kicad_sch").read_bytes()).hexdigest()
            (GOLDEN / f"{case}.kicad_sch.sha256").write_text(sch + "\n")
