"""Where KiCad's libraries, its command line and Freerouting are on this machine.

Every location can be set explicitly; otherwise the usual install places are
searched. Settings:

    KICAD_SYMBOL_DIR, KICAD_FOOTPRINT_DIR   stock libraries (also KICAD10_*, KICAD9_*)
    KICAD_CONFIG_HOME                       KiCad's settings folder (its global library
                                            tables and path variables), as KiCad reads it
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


def _version_dirs(base: Path) -> list[Path]:
    """base itself if it holds the settings, else its version folders, newest first."""
    if (base / "kicad_common.json").exists() or (base / "sym-lib-table").exists():
        return [base]
    vers = [p for p in base.glob("*.*") if p.is_dir() and p.name.replace(".", "").isdigit()]
    return sorted(vers, key=lambda p: tuple(int(x) for x in p.name.split(".")), reverse=True)


def kicad_config() -> Path | None:
    """KiCad's settings folder for its newest version on this machine: the global
    library tables and the path variables set in Preferences. None if there is none."""
    home = Path.home()
    if os.environ.get("KICAD_CONFIG_HOME"):
        bases = [Path(os.environ["KICAD_CONFIG_HOME"])]
    else:
        bases = [Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "kicad",
                 home / ".var/app/org.kicad.KiCad/config/kicad",
                 home / "Library/Preferences/kicad"]
        if os.environ.get("APPDATA"):
            bases.append(Path(os.environ["APPDATA"]) / "kicad")
    found = [d for base in bases for d in _version_dirs(base)
             if (d / "sym-lib-table").exists() or (d / "kicad_common.json").exists()]
    if not found:
        return None

    def version(p: Path) -> tuple[int, ...]:
        return tuple(int(x) for x in p.name.split(".")) if p.name.replace(".", "").isdigit() else (0,)
    return max(found, key=version)              # several installs (native 9, Flatpak 10): the newest


def path_variables() -> dict[str, str]:
    """KiCad's path variables: those set in Preferences > Configure Paths, with the
    process environment taking precedence, as in KiCad."""
    import json

    out: dict[str, str] = {}
    cfg = kicad_config()
    if cfg is not None and (cfg / "kicad_common.json").exists():
        try:
            out.update((json.loads((cfg / "kicad_common.json").read_text()).get("environment") or {}).get("vars") or {})
        except (OSError, ValueError):
            pass
    out.update(os.environ)
    return out


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
