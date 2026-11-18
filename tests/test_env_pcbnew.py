"""Finding the PCB editor: BOARDWRIGHT_PCBNEW, then PATH, then Flatpak. Every command
here is a stub script in a temporary folder; nothing is started, only looked for."""

import stat
import sys
from pathlib import Path

import pytest

from boardwright import env
from boardwright.errors import EnvironmentFault

FLATPAK = ["flatpak", "run", "--command=pcbnew", "org.kicad.KiCad"]


def _tool(folder, name, code=0):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_text(f"#!/bin/sh\nexit {code}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


@pytest.fixture(params=["home_a", "home b"])
def host(request, tmp_path, monkeypatch):
    """No KiCad anywhere: PATH holds only a folder of stubs, HOME is empty, and
    the macOS and Windows install places are not looked at."""
    if sys.platform == "win32":
        pytest.skip("stub commands are shell scripts")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    monkeypatch.setenv("PATH", str(bin_))
    monkeypatch.setenv("HOME", str(tmp_path / request.param))
    monkeypatch.delenv("BOARDWRIGHT_PCBNEW", raising=False)
    monkeypatch.setattr(env, "_MACOS_PCBNEW", ())
    monkeypatch.setattr(env, "_WINDOWS_PCBNEW", ())
    return bin_


def test_path(host):
    ed = _tool(host, "pcbnew")
    _tool(host, "flatpak")
    assert env.pcbnew() == ([str(ed)], False)


@pytest.mark.parametrize("value", [None, ""])
def test_flatpak_when_not_on_path(host, monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("BOARDWRIGHT_PCBNEW", value)     # empty counts as unset
    _tool(host, "flatpak")
    assert env.pcbnew() == (FLATPAK, True)


def test_flatpak_without_kicad_installed_is_not_a_candidate(host):
    _tool(host, "flatpak", code=1)          # `flatpak info org.kicad.KiCad`: exit 1 when not installed
    with pytest.raises(EnvironmentFault) as e:
        env.pcbnew()
    assert e.value.exit == 4 and "not installed" in e.value.message


def test_variable_wins_over_path(host, tmp_path, monkeypatch):
    _tool(host, "pcbnew")
    _tool(host, "flatpak")
    mine = _tool(tmp_path / "pinned", "pcbnew")
    monkeypatch.setenv("BOARDWRIGHT_PCBNEW", str(mine))
    assert env.pcbnew() == ([str(mine)], False)


def test_variable_naming_a_path_with_spaces_is_one_command(host, tmp_path, monkeypatch):
    _tool(host, "pcbnew")
    mine = _tool(tmp_path / "Program Files" / "KiCad", "pcbnew")   # as on Windows
    monkeypatch.setenv("BOARDWRIGHT_PCBNEW", str(mine))
    assert env.pcbnew() == ([str(mine)], False)


def test_variable_naming_flatpak_is_the_flatpak_editor(host, monkeypatch):
    _tool(host, "flatpak")
    monkeypatch.setenv("BOARDWRIGHT_PCBNEW", "flatpak run --command=pcbnew org.kicad.KiCad")
    assert env.pcbnew() == (FLATPAK, True)


@pytest.mark.parametrize("value", ["/nowhere/pcbnew", "no-such-command --flag"])
def test_variable_naming_a_missing_command_does_not_fall_back(host, monkeypatch, value):
    _tool(host, "pcbnew")
    _tool(host, "flatpak")
    monkeypatch.setenv("BOARDWRIGHT_PCBNEW", value)
    with pytest.raises(EnvironmentFault) as e:
        env.pcbnew()
    assert e.value.exit == 4
    assert "BOARDWRIGHT_PCBNEW" in e.value.message


def test_not_found_is_an_environment_fault(host):
    with pytest.raises(EnvironmentFault) as e:
        env.pcbnew()
    assert e.value.exit == 4
    assert "BOARDWRIGHT_PCBNEW" in e.value.message


def test_windows_install_is_found(host, tmp_path, monkeypatch):
    base = tmp_path / "Program Files" / "KiCad"
    ed = _tool(base / "10.0" / "bin", "pcbnew.exe")
    monkeypatch.setattr(env, "_WINDOWS_PCBNEW", (str(base / "*" / "bin" / "pcbnew.exe"),))
    assert env.pcbnew() == ([str(ed)], False)


def test_windows_installs_newest_version_first(host, tmp_path, monkeypatch):
    base = tmp_path / "Program Files" / "KiCad"
    for folder in ("8.0", "9.0", "10.0", "nightly"):
        _tool(base / folder / "bin", "pcbnew.exe")
    monkeypatch.setattr(env, "_WINDOWS_PCBNEW", (str(base / "*" / "bin" / "pcbnew.exe"),))
    found = env._windows_installs(env._WINDOWS_PCBNEW)
    assert [Path(p).parent.parent.name for p in found] == ["10.0", "9.0", "8.0", "nightly"]
    assert env.pcbnew() == ([found[0]], False)


def test_variable_with_an_unbalanced_quote_is_an_environment_fault(host, monkeypatch):
    _tool(host, "pcbnew")
    monkeypatch.setenv("BOARDWRIGHT_PCBNEW", '"/opt/my kicad')
    with pytest.raises(EnvironmentFault) as e:
        env.pcbnew()
    assert e.value.exit == 4
    assert "BOARDWRIGHT_PCBNEW" in e.value.message and "unbalanced quote" in e.value.message
