"""Finding kicad-cli: BOARDWRIGHT_KICAD_CLI, then PATH, then Flatpak. Every command
here is a stub script in a temporary folder; this machine's KiCad is never run."""

import stat
import sys

import pytest

from boardwright import env
from boardwright.errors import EnvironmentFault


def _tool(folder, name, code=0, out="10.0.5"):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_text(f"#!/bin/sh\necho {out}\nexit {code}\n")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


@pytest.fixture(params=["home_a", "home_b"])
def host(request, tmp_path, monkeypatch):
    """No KiCad anywhere: PATH holds only a folder of stubs, HOME is empty, and
    the macOS and Windows install places are not looked at."""
    if sys.platform == "win32":
        pytest.skip("stub commands are shell scripts")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    monkeypatch.setenv("PATH", str(bin_))
    monkeypatch.setenv("HOME", str(tmp_path / request.param))
    monkeypatch.delenv("BOARDWRIGHT_KICAD_CLI", raising=False)
    monkeypatch.setattr(env, "_MACOS_KICAD_CLI", ())
    monkeypatch.setattr(env, "_WINDOWS_KICAD_CLI", ())
    return bin_


def test_path(host):
    cli = _tool(host, "kicad-cli")
    assert env.kicad_cli() == [str(cli)]


@pytest.mark.parametrize("value", [None, ""])
def test_flatpak_when_not_on_path(host, monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("BOARDWRIGHT_KICAD_CLI", value)     # empty counts as unset
    _tool(host, "flatpak")
    assert env.kicad_cli() == ["flatpak", "run", "--command=kicad-cli", "org.kicad.KiCad"]


def test_broken_path_cli_falls_through_to_flatpak(host):
    _tool(host, "kicad-cli", code=1)
    _tool(host, "flatpak")
    assert env.kicad_cli()[0] == "flatpak"


def test_variable_wins_over_path(host, tmp_path, monkeypatch):
    _tool(host, "kicad-cli")
    _tool(host, "flatpak")
    mine = _tool(tmp_path / "pinned", "kicad-cli")
    monkeypatch.setenv("BOARDWRIGHT_KICAD_CLI", str(mine))
    assert env.kicad_cli() == [str(mine)]


def test_variable_naming_a_path_with_spaces_is_one_command(host, tmp_path, monkeypatch):
    _tool(host, "kicad-cli")
    mine = _tool(tmp_path / "Program Files" / "KiCad", "kicad-cli")   # as on Windows
    monkeypatch.setenv("BOARDWRIGHT_KICAD_CLI", str(mine))
    assert env.kicad_cli() == [str(mine)]


def test_variable_with_arguments_is_split(host, tmp_path, monkeypatch):
    _tool(host, "kicad-cli")
    wrapper = _tool(tmp_path / "pinned", "wrapper")
    monkeypatch.setenv("BOARDWRIGHT_KICAD_CLI", f"{wrapper} run --command=kicad-cli")
    assert env.kicad_cli() == [str(wrapper), "run", "--command=kicad-cli"]


@pytest.mark.parametrize("value", ["/nowhere/kicad-cli", "broken"])
def test_variable_naming_a_broken_cli_does_not_fall_back(host, tmp_path, monkeypatch, value):
    _tool(host, "kicad-cli")
    if value == "broken":
        value = str(_tool(tmp_path / "pinned", "kicad-cli", code=3))
    monkeypatch.setenv("BOARDWRIGHT_KICAD_CLI", value)
    with pytest.raises(EnvironmentFault) as e:
        env.kicad_cli()
    assert e.value.exit == 4
    assert "BOARDWRIGHT_KICAD_CLI" in e.value.message


def test_not_found_is_an_environment_fault(host):
    with pytest.raises(EnvironmentFault) as e:
        env.kicad_cli()
    assert e.value.exit == 4
    assert "BOARDWRIGHT_KICAD_CLI" in e.value.message


def test_does_not_need_netspec(host, monkeypatch):
    cli = _tool(host, "kicad-cli")
    monkeypatch.setitem(sys.modules, "kicad_netspec", None)
    monkeypatch.setitem(sys.modules, "kicad_netspec.oracle", None)
    monkeypatch.setitem(sys.modules, "kicad_netspec.oracle.discovery", None)
    assert env.kicad_cli() == [str(cli)]
