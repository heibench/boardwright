"""The KiCad gate for a generated board: ERC, netlist, DRC, fab outputs, plots.

    boardwright check <board dir>            every step
    boardwright check <board dir> --quick    DRC and copper plots only

Writes into <board dir>/out/. DRC runs at every severity with schematic parity,
refills the zones and saves the board, so the board file holds filled pours.
`boardwright verify` then reads what this wrote.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import env
from .errors import Usage

_SVG = ["pcb", "export", "svg", "--exclude-drawing-sheet", "--page-size-mode", "2", "--mode-single"]


def steps(d: Path, quick: bool = False) -> list[list[str]]:
    n = d.name
    pcb, sch, o = str(d / f"{n}.kicad_pcb"), str(d / f"{n}.kicad_sch"), d / "out"
    s = [
        ["pcb", "drc", "--format", "json", "--severity-all", "--schematic-parity",
         "--refill-zones", "--save-board", "-o", str(o / "drc.json"), pcb],
        [*_SVG, "--layers", "F.Cu,Edge.Cuts", "-o", str(o / "F_Cu.svg"), pcb],
        [*_SVG, "--layers", "B.Cu,Edge.Cuts", "-o", str(o / "B_Cu.svg"), pcb],
    ]
    if not quick:
        s += [
            ["sch", "erc", "--format", "json", "--severity-all", "-o", str(o / "erc.json"), sch],
            ["sch", "export", "netlist", "--format", "kicadxml", "-o", str(o / "netlist.xml"), sch],
            ["pcb", "export", "gerbers", "-o", f"{o / 'gerbers'}/", pcb],
            ["pcb", "export", "drill", "-o", f"{o / 'gerbers'}/", pcb],
            ["sch", "export", "bom", "-o", str(o / "bom.csv"), sch],
            ["pcb", "export", "pos", "--format", "csv", "--units", "mm", "-o", str(o / "cpl.csv"), pcb],
            ["sch", "export", "pdf", "-o", str(o / "schematic.pdf"), sch],
            ["pcb", "render", "--side", "top", "--width", "1600", "--height", "1250",
             "-o", str(o / "top.png"), pcb],
        ]
    return s


def check(d: Path, quick: bool = False) -> int:
    cli = env.kicad_cli()
    (d / "out" / "gerbers").mkdir(parents=True, exist_ok=True)
    for s in steps(d, quick):
        r = subprocess.run([*cli, *s], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"FAILED: {' '.join([*cli, *s])}\n{r.stdout[-2000:]}{r.stderr[-2000:]}")
            return 4
        print("ok  ", " ".join(s[:3]))
    return 0


def cli(argv: list[str]) -> int:
    if not argv:
        raise Usage(__doc__)
    return check(Path(argv[0]).resolve(), "--quick" in argv[1:])
