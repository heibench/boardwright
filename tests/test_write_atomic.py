"""Design files are read and written as UTF-8, and an in-place write leaves the
old file whole if it fails (#218). Under a non-UTF-8 locale, write_text
truncated the schematic, then failed to encode µ, and left it empty."""

import os
import shutil
import subprocess
import sys

import pytest
from conftest import BOARDS

from boardwright import env

LDO = BOARDS / "ldo_breakout"


def test_sch_add_under_a_c_locale_edits_the_schematic(tmp_path):
    proj = tmp_path / "ldo"
    shutil.copytree(LDO, proj, ignore=shutil.ignore_patterns("out", "boardwright_out", ".libmerge", "__pycache__"))
    spec = tmp_path / "spec.py"
    spec.write_text('ADD = [("C70", "C1", "10µF", "", {1: "VIN", 2: "GND"})]\n', encoding="utf-8")
    run = subprocess.run([sys.executable, "-c", "import sys; from boardwright.cli import main; sys.exit(main(sys.argv[1:]))",
                          "sch", str(proj), "add", str(spec)],
                         env={**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONIOENCODING": "utf-8"},
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    after = (proj / "ldo_breakout.kicad_sch").read_text(encoding="utf-8")
    assert '"10µF"' in after and '"C70"' in after


def test_a_failed_encode_leaves_the_file_whole(tmp_path):
    f = tmp_path / "board.kicad_pcb"
    f.write_bytes(b"(kicad_pcb)\n")
    with pytest.raises(UnicodeEncodeError):
        env.write_atomic(f, "(kicad_pcb \ud800)\n")                       # a lone surrogate cannot be UTF-8
    assert f.read_bytes() == b"(kicad_pcb)\n"
    assert [p.name for p in tmp_path.iterdir()] == ["board.kicad_pcb"]


def test_a_failed_move_leaves_the_file_whole_and_no_temp_file(tmp_path, monkeypatch):
    f = tmp_path / "board.kicad_pcb"
    f.write_bytes(b"(kicad_pcb)\n")
    def boom(*a):
        raise OSError("disk full")
    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        env.write_atomic(f, "(kicad_pcb (new))\n")
    assert f.read_bytes() == b"(kicad_pcb)\n"
    assert [p.name for p in tmp_path.iterdir()] == ["board.kicad_pcb"]


def test_the_write_keeps_the_mode_and_follows_a_symlink(tmp_path):
    real = tmp_path / "real.kicad_sch"
    real.write_text("old\n", encoding="utf-8")
    real.chmod(0o640)
    link = tmp_path / "link.kicad_sch"
    link.symlink_to(real)
    env.write_atomic(link, "nëw\n")
    assert link.is_symlink() and real.read_bytes() == "nëw\n".encode()
    assert real.stat().st_mode & 0o777 == 0o640


def test_no_text_read_or_write_in_the_package_relies_on_the_locale():
    """Every read_text/write_text in boardwright names its encoding."""
    import ast
    from pathlib import Path
    src = Path(env.__file__).parent
    bare = []
    for f in sorted(src.glob("*.py")):
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("read_text", "write_text")
                    and not any(k.arg == "encoding" for k in n.keywords)):
                bare.append(f"{f.name}:{n.lineno}")
    assert bare == []


def test_a_read_only_file_is_refused_and_left_as_it_is(tmp_path):
    f = tmp_path / "board.kicad_pcb"
    f.write_bytes(b"(kicad_pcb)\n")
    f.chmod(0o444)
    with pytest.raises(PermissionError):
        env.write_atomic(f, "(kicad_pcb (new))\n")
    assert f.read_bytes() == b"(kicad_pcb)\n"


def test_a_read_only_directory_still_takes_the_edit(tmp_path):
    d = tmp_path / "shared"
    d.mkdir()
    f = d / "board.kicad_pcb"
    f.write_bytes(b"(kicad_pcb)\n")
    d.chmod(0o555)
    try:
        env.write_atomic(f, "(kicad_pcb (new))\n")
        assert f.read_text(encoding="utf-8") == "(kicad_pcb (new))\n"
    finally:
        d.chmod(0o755)


def test_a_write_leaves_no_temporary_file(tmp_path):
    f = tmp_path / "x.kicad_sch"
    for i in range(3):
        env.write_atomic(f, f"({i})\n")
    assert [p.name for p in tmp_path.iterdir()] == ["x.kicad_sch"]


def forbid_plain_writes(monkeypatch, suffixes=(".kicad_sch", ".kicad_pcb")):
    """A design file written with Path.write_text or write_bytes, rather than
    env.write_atomic (whose temporary file has another suffix), fails the test."""
    from pathlib import Path
    for name in ("write_text", "write_bytes"):
        real = getattr(Path, name)
        def guarded(self, *a, _real=real, _name=name, **k):
            if self.suffix in suffixes:
                raise AssertionError(f"{self.name} written with {_name}, not write_atomic")
            return _real(self, *a, **k)
        monkeypatch.setattr(Path, name, guarded)


@pytest.fixture
def design_write_text_forbidden(monkeypatch):
    forbid_plain_writes(monkeypatch)


def test_sch_edits_write_the_schematic_atomically(ldo_copy, tmp_path, design_write_text_forbidden):
    from boardwright.cli import main
    spec = tmp_path / "spec.py"
    spec.write_bytes(b'ADD = [("R70", "R1", "1k", "", {1: "VIN", 2: "GND"})]\n')
    assert main(["sch", str(ldo_copy), "add", str(spec)]) == 0
    assert main(["sch", str(ldo_copy), "set", "R70", "Value=2k"]) == 0
    assert main(["sch", str(ldo_copy), "move", "R70.1", "NEWNET"]) == 0


def test_a_read_only_directory_warns_that_the_write_is_not_atomic(tmp_path, capsys):
    d = tmp_path / "shared"
    d.mkdir()
    f = d / "board.kicad_pcb"
    f.write_bytes(b"(kicad_pcb)\n")
    d.chmod(0o555)
    try:
        env.write_atomic(f, "(kicad_pcb (new))\n")
    finally:
        d.chmod(0o755)
    assert "not atomically" in capsys.readouterr().err


def test_a_new_file_takes_the_umask_not_0600(tmp_path):
    old = os.umask(0o022)
    try:
        env.write_atomic(tmp_path / "new.kicad_sch", "(kicad_sch)\n")
    finally:
        os.umask(old)
    assert (tmp_path / "new.kicad_sch").stat().st_mode & 0o777 == 0o644


@pytest.mark.parametrize("module,receivers", [
    ("existing.py", {"pcb"}),
    ("copper.py", {"pcb"}),
    ("sch.py", {"self.path"}),
])
def test_no_in_place_design_write_bypasses_write_atomic(module, receivers):
    """Each in-place write of the user's board or schematic in these modules goes
    through env.write_atomic; a write_text or write_bytes on that path, at any
    site, fails here. Some sites (reroute, clash rollback) need Freerouting or a
    clash to reach at run time, so the check reads the code."""
    import ast
    from pathlib import Path
    tree = ast.parse((Path(env.__file__).parent / module).read_text(encoding="utf-8"))
    bad = [n.lineno for n in ast.walk(tree)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("write_text", "write_bytes")
           and ast.unparse(n.func.value) in receivers]
    assert bad == [], f"{module}: lines {bad}"
