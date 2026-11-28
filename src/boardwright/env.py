"""Where KiCad's libraries, its command line and Freerouting are on this machine.

Every location can be set explicitly; otherwise the usual install places are
searched. Settings:

    KICAD_SYMBOL_DIR, KICAD_FOOTPRINT_DIR   stock libraries (also KICAD10_*, KICAD9_*)
    KICAD_CONFIG_HOME                       KiCad's settings folder (its global library
                                            tables and path variables), as KiCad reads it
    BOARDWRIGHT_KICAD_CLI                   the KiCad command line, e.g. "flatpak run --command=kicad-cli org.kicad.KiCad"
    BOARDWRIGHT_PCBNEW                      the PCB editor, e.g. "flatpak run --command=pcbnew org.kicad.KiCad"
    BOARDWRIGHT_FREEROUTING                 the autorouter, e.g. "java -jar freerouting.jar"
    KICAD_API_SOCKET                        a running KiCad's API socket, asked first by `live --board`
"""

from __future__ import annotations

import glob
import os
import shlex
import shutil
import subprocess
import sys
from contextlib import contextmanager
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
        found += _newest_first(p)
    return [p for p in found if p.is_dir()]


def _newest_first(pattern: str) -> list[Path]:
    """The matches of a glob pattern with at most one `*` standing for a version
    folder, newest version first (see _version_key)."""
    if "*" not in pattern:                      # a fixed path: nothing to order
        return [Path(g) for g in glob.glob(pattern)]
    base = Path(pattern.partition("*")[0])
    return sorted((Path(g) for g in glob.glob(pattern)), key=_version_key(base), reverse=True)


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
            out.update((json.loads((cfg / "kicad_common.json").read_text(encoding="utf-8")).get("environment") or {}).get("vars") or {})
        except (OSError, ValueError):
            pass
    out.update(os.environ)
    return out


def libraries() -> tuple[Path, Path]:
    """The stock symbol and footprint library directories."""
    return _library("symbols"), _library("footprints")


def use_libraries(sym: Path | None = None, fp: Path | None = None) -> None:
    """Point libraries() at a library set, through the KICAD_*_DIR variables,
    until library_scope ends."""
    if sym is None or fp is None:
        sym, fp = libraries()
    for v in ("KICAD", "KICAD10", "KICAD9"):
        os.environ[f"{v}_SYMBOL_DIR"] = str(sym)
        os.environ[f"{v}_FOOTPRINT_DIR"] = str(fp)


_LIBRARY_VARS = [f"{v}_{k}_DIR" for v in ("KICAD", "KICAD10", "KICAD9") for k in ("SYMBOL", "FOOTPRINT")]


@contextmanager
def library_scope():
    """The KICAD_*_DIR variables as they are now, restored on leaving: a board's
    LIBS point them at its merged view (project.merge_libs) for its own build only."""
    saved = {v: os.environ.get(v) for v in _LIBRARY_VARS}
    try:
        yield
    finally:
        for v, value in saved.items():
            if value is None:
                os.environ.pop(v, None)
            else:
                os.environ[v] = value


# kicad-cli discovery, ported from netspec 0.9.0 (heibench/netspec, Apache-2.0),
# its oracle/discovery.py, keeping its search order and its rule that a
# command named by the variable is used or refused, never fallen back from.
_KICAD_CLI_VAR = "BOARDWRIGHT_KICAD_CLI"
_MACOS_KICAD_CLI = (
    "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    "/Applications/KiCad/kicad-cli",
)
_WINDOWS_KICAD_CLI = (
    r"C:\Program Files\KiCad\*\bin\kicad-cli.exe",
    r"C:\Program Files (x86)\KiCad\*\bin\kicad-cli.exe",
)


def _command(var: str, value: str) -> list[str]:
    """A command set in `var`: a file named whole ("C:\\Program Files\\KiCad\\...") is one
    command; anything else is split as a shell would."""
    if Path(value).is_file():
        return [value]
    try:
        return shlex.split(value)
    except ValueError as e:
        raise EnvironmentFault(f"{var} has an unbalanced quote ({e}): {value}") from e


def _kicad_cli_candidates() -> list[tuple[list[str], str]]:
    out: list[tuple[list[str], str]] = []
    value = os.environ.get(_KICAD_CLI_VAR)
    if value:
        out.append((_command(_KICAD_CLI_VAR, value), "env"))
    on_path = shutil.which("kicad-cli")
    if on_path:
        out.append(([on_path], "path"))
    if shutil.which("flatpak"):
        out.append((["flatpak", "run", "--command=kicad-cli", "org.kicad.KiCad"], "flatpak"))
    out.extend(([c], "macos") for c in _MACOS_KICAD_CLI if Path(c).exists())
    out.extend(([m], "windows") for m in _windows_installs(_WINDOWS_KICAD_CLI))
    return out


def _windows_installs(patterns) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        root, _, tail = pattern.partition("*")
        base = Path(root)
        if base.is_dir():
            found += [str(m) for m in sorted(base.glob("*" + tail.replace("\\", "/")), key=_version_key(base), reverse=True)]
    return found


def _version_key(base: Path):
    """Order matches under base by the version folder they are in, compared by number
    (10.0 after 9.0); a folder whose name is not a version comes after every version."""
    def key(m: Path) -> tuple[bool, tuple[int, ...]]:
        parts = m.relative_to(base).parts[0].split(".")
        return (True, tuple(map(int, parts))) if all(p.isdigit() for p in parts) else (False, ())
    return key


def _kicad_cli_works(argv: list[str]) -> bool:
    try:
        done = subprocess.run([*argv, "--version"], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and bool(done.stdout.strip())


def kicad_cli() -> list[str]:
    """The command prefix that runs kicad-cli, first working one of: BOARDWRIGHT_KICAD_CLI,
    PATH, Flatpak, the macOS bundle, a Windows install. A command named by the variable
    is not fallen back from: it was set to choose that engine."""
    tried: list[str] = []
    for argv, origin in _kicad_cli_candidates():
        if _kicad_cli_works(argv):
            return argv
        if origin == "env":
            raise EnvironmentFault(
                f"{_KICAD_CLI_VAR} names a kicad-cli that does not work: {' '.join(argv)}\n"
                "It was set to choose a specific engine, so boardwright will not fall back "
                "to another one. Correct it, or unset it to let discovery choose."
            )
        tried.append(f"{origin}: {' '.join(argv)}")
    raise EnvironmentFault(
        f"no working kicad-cli found. Set {_KICAD_CLI_VAR}=/path/to/kicad-cli, or install KiCad. Tried:\n  "
        + "\n  ".join(tried)
    )


# The PCB editor, found in the same order as kicad-cli, for `live open`.
# pcbnew is a GUI: it has no --version to probe without opening a window, so
# it is never run to check it. A file that exists (on PATH or in an install
# place) is the test, and for Flatpak `flatpak info org.kicad.KiCad`, which
# exits 0 when the app is installed and 1 when it is not.
_PCBNEW_VAR = "BOARDWRIGHT_PCBNEW"
_FLATPAK_PCBNEW = ["flatpak", "run", "--command=pcbnew", "org.kicad.KiCad"]
# KiCad 10.0.8's macOS build moves pcbnew.app into the main bundle's
# Contents/Applications (CMakeLists.txt OSX_BUNDLE_APP_DIR, kicad/CMakeLists.txt
# move_to_main_bundle), under the same /Applications/KiCad as kicad-cli above.
# Read from the build files; not run on a Mac.
_MACOS_PCBNEW = ("/Applications/KiCad/KiCad.app/Contents/Applications/pcbnew.app/Contents/MacOS/pcbnew",)
_WINDOWS_PCBNEW = (
    r"C:\Program Files\KiCad\*\bin\pcbnew.exe",
    r"C:\Program Files (x86)\KiCad\*\bin\pcbnew.exe",
)


def _flatpak_has_kicad() -> bool:
    try:
        done = subprocess.run(["flatpak", "info", "org.kicad.KiCad"], capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def pcbnew() -> tuple[list[str], bool]:
    """(the command prefix that starts the PCB editor, whether it is the Flatpak one):
    the first of BOARDWRIGHT_PCBNEW, PATH, Flatpak, the macOS bundle, a Windows
    install. A command named by the variable is not fallen back from."""
    value = os.environ.get(_PCBNEW_VAR)
    if value:
        argv = _command(_PCBNEW_VAR, value)
        if not argv or not (Path(argv[0]).is_file() or shutil.which(argv[0])):
            raise EnvironmentFault(
                f"{_PCBNEW_VAR} names a PCB editor that is not there: {value}\n"
                "It was set to choose a specific editor, so boardwright will not fall back "
                "to another one. Correct it, or unset it to let discovery choose."
            )
        return argv, Path(argv[0]).name == "flatpak"
    on_path = shutil.which("pcbnew")
    if on_path:
        return [on_path], False
    tried = ["PATH: no pcbnew"]
    if not shutil.which("flatpak"):
        tried.append("flatpak: not on PATH")
    elif _flatpak_has_kicad():
        return list(_FLATPAK_PCBNEW), True
    else:
        tried.append("flatpak: org.kicad.KiCad is not installed")
    installed = [c for c in _MACOS_PCBNEW if Path(c).is_file()] + _windows_installs(_WINDOWS_PCBNEW)
    if installed:
        return [installed[0]], False
    tried.append("macOS and Windows install places: none")
    raise EnvironmentFault(
        f"no PCB editor (pcbnew) found. Set {_PCBNEW_VAR}=/path/to/pcbnew, or install KiCad. Looked:\n  "
        + "\n  ".join(tried)
    )


# KiCad's API socket folders, as kicad-python 0.8.0 looks for api.sock
# (kipy/kicad.py, _default_socket_path). A second KiCad instance names its
# socket api-<pid>.sock; inside Flatpak the pid is namespaced, so the name
# says nothing about which instance it is.
def _native_socket_dir() -> Path:
    if sys.platform == "win32":
        import tempfile
        return Path(tempfile.gettempdir()) / "kicad"
    return Path("/tmp/kicad")


def flatpak_socket_dir() -> Path:
    return Path.home() / ".var/app/org.kicad.KiCad/cache/tmp/kicad"


def kicad_api_sockets() -> list[Path]:
    """Every KiCad API socket that may answer: KICAD_API_SOCKET if set, then
    api.sock and api-*.sock in the Flatpak and the native socket folders."""
    out: list[Path] = []
    value = os.environ.get("KICAD_API_SOCKET")
    if value:
        out.append(Path(value.removeprefix("ipc://")))
    for d in (flatpak_socket_dir(), _native_socket_dir()):
        if d.is_dir():
            out += [d / "api.sock"] if (d / "api.sock").exists() else []
            out += sorted(d.glob("api-*.sock"))
    seen: set[Path] = set()
    unique = []
    for p in out:
        if p.resolve() not in seen:
            seen.add(p.resolve())
            unique.append(p)
    return unique


def freerouting() -> list[str]:
    cmd = shlex.split(os.environ.get("BOARDWRIGHT_FREEROUTING", "freerouting"))
    if not shutil.which(cmd[0]):
        raise EnvironmentFault(
            f"Freerouting not found ({cmd[0]!r}). Install it or set BOARDWRIGHT_FREEROUTING, "
            'e.g. "java -jar /path/to/freerouting.jar".'
        )
    return cmd


_warned_open: set[Path] = set()


def warn_if_open_in_kicad(path: Path) -> None:
    """Warn, once per file, when KiCad has `path` open: KiCad keeps
    `~<name>.lck` beside an open document (10.0.8, #46), and its next save
    of that document overwrites what a file edit wrote. A lock left by a
    crash warns too; the edit still goes ahead."""
    lock = path.with_name(f"~{path.name}.lck")
    if lock.exists() and path not in _warned_open:
        _warned_open.add(path)
        print(f"warning: KiCad has {path.name} open ({lock.name} is beside it); its next save there "
              "overwrites this edit, so close it in KiCad without saving, then reopen it", file=sys.stderr)


def load_source(path: Path | str, name: str):
    """Run a spec or board file as a module, from its source as it reads now.
    importlib's loader trusts a cached .pyc whose source has the same size and
    mtime, so an edit of the same size within a second ran the old spec.
    The source is compiled from its bytes, so a BOM or a coding line decodes as
    importlib decodes it, and without this module's __future__ flags, so a
    spec's annotations stay as the spec wrote them."""
    import types
    path = Path(path).absolute()
    m = types.ModuleType(name)
    m.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec", dont_inherit=True), m.__dict__)
    return m


def write_atomic(path: Path | str, text: str) -> None:
    """Write a design file in place, as UTF-8 (KiCad's encoding), so that a
    failure leaves the old file whole: the text is encoded first, written to a
    temporary file beside it, flushed, then moved over it, keeping its mode.
    write_text truncated the file before encoding, and an encode error left it
    empty (#218). A file its owner made read-only is refused, as write_text
    refused it. In a directory that takes no new file, the encoded bytes are
    written in place, as before, with a warning: that route is not atomic. The
    move gives the file a new inode: a hard link to it keeps the old text, and
    the file takes the writer's ownership."""
    import tempfile
    path = Path(path).resolve()                         # a symlink's target, not the link
    data = text.encode("utf-8")
    if path.exists() and not os.access(path, os.W_OK):
        raise PermissionError(f"{path} is read-only; nothing written")
    try:
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    except PermissionError:                            # a read-only directory: no atomic route
        print(f"warning: {path.parent} takes no new file, so {path.name} is written in place, not "
              "atomically: a failure part way leaves it cut short", file=sys.stderr)
        path.write_bytes(data)
        return
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            shutil.copymode(path, tmp)
        else:                                           # mkstemp's 0600; a new file takes the umask
            mask = os.umask(0)
            os.umask(mask)
            os.chmod(tmp, 0o666 & ~mask)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
