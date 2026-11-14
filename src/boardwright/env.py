"""Where KiCad's libraries, its command line and Freerouting are on this machine.

Every location can be set explicitly; otherwise the usual install places are
searched. Settings:

    KICAD_SYMBOL_DIR, KICAD_FOOTPRINT_DIR   stock libraries (also KICAD10_*, KICAD9_*)
    NETSPEC_KICAD_CLI                       the KiCad command line (shared with netspec)
    BOARDWRIGHT_FREEROUTING                 the autorouter, e.g. "java -jar freerouting.jar"
"""

from __future__ import annotations

import glob
import os
import shlex
import shutil
import sys
from pathlib import Path

from .errors import EnvironmentFault

_FLATPAK_RT = "{root}/runtime/org.kicad.KiCad.Library.{kind}/x86_64/stable/active/files/{dir}"


def _library_candidates(dir_: str) -> list[Path]:
    kind = {"symbols": "Symbols", "footprints": "Footprints"}[dir_]
    roots = ["/var/lib/flatpak", str(Path.home() / ".local/share/flatpak")]
    pats = [
        f"/usr/share/kicad/{dir_}",
        f"/usr/local/share/kicad/{dir_}",
        *(_FLATPAK_RT.format(root=r, kind=kind, dir=dir_) for r in roots),
        f"/Applications/KiCad/KiCad.app/Contents/SharedSupport/{dir_}",
        f"C:/Program Files/KiCad/*/share/kicad/{dir_}",
    ]
    found: list[Path] = []
    for p in pats:
        found += [Path(g) for g in sorted(glob.glob(p), reverse=True)]
    return [p for p in found if p.is_dir()]


def _library(dir_: str) -> Path:
    name = {"symbols": "SYMBOL", "footprints": "FOOTPRINT"}[dir_]
    for var in (f"KICAD_{name}_DIR", f"KICAD10_{name}_DIR", f"KICAD9_{name}_DIR"):
        if os.environ.get(var):
            return Path(os.environ[var])
    cands = _library_candidates(dir_)
    if not cands:
        raise EnvironmentFault(
            f"KiCad's {dir_} library was not found. Install KiCad's libraries or set KICAD_{name}_DIR."
        )
    return cands[0]


def libraries() -> tuple[Path, Path]:
    """The stock symbol and footprint library directories."""
    return _library("symbols"), _library("footprints")


def use_libraries(sym: Path | None = None, fp: Path | None = None) -> None:
    """Point kicad-tools (which reads the KICAD_*_DIR variables) at a library set."""
    if sym is None or fp is None:
        sym, fp = libraries()
    for v in ("KICAD", "KICAD10", "KICAD9"):
        os.environ[f"{v}_SYMBOL_DIR"] = str(sym)
        os.environ[f"{v}_FOOTPRINT_DIR"] = str(fp)
    # kicad-tools keeps one symbol registry per process, with the search paths
    # it saw first; drop it so the next lookup uses these.
    from kicad_tools.schematic import registry

    registry._global_registry = None


def kicad_cli() -> list[str]:
    """The command prefix that runs kicad-cli (found the way netspec finds it)."""
    from kicad_netspec.oracle.discovery import KiCadNotFound, find_kicad_cli

    try:
        return list(find_kicad_cli().argv)
    except KiCadNotFound as e:
        raise EnvironmentFault(str(e)) from None


def freerouting() -> list[str]:
    cmd = shlex.split(os.environ.get("BOARDWRIGHT_FREEROUTING", "freerouting"))
    if not shutil.which(cmd[0]):
        raise EnvironmentFault(
            f"Freerouting not found ({cmd[0]!r}). Install it or set BOARDWRIGHT_FREEROUTING, "
            'e.g. "java -jar /path/to/freerouting.jar".'
        )
    return cmd


def kct() -> list[str]:
    """kicad-tools' command line, from the same environment as this package."""
    return [sys.executable, "-m", "kicad_tools.cli"]
