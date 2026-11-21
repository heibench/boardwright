"""`boardwright CMD --help` prints CMD's usage and exits 64, as bare CMD does,
before anything runs: no board is read and no KiCad is looked for (#146)."""

import pytest

from boardwright import cli
from boardwright.cli import main


@pytest.mark.parametrize("cmd", sorted(cli._MODULES) + ["doctor"])
@pytest.mark.parametrize("flag", ["--help", "-h"])
def test_help_prints_usage_without_running(cmd, flag, monkeypatch, capsys):
    monkeypatch.setenv("BOARDWRIGHT_KICAD_CLI", "/nonexistent/kicad-cli")
    assert main([cmd, flag]) == 64
    cap = capsys.readouterr()
    text = cap.out + cap.err
    assert text.strip() and "kicad-cli" not in text.split("\n")[0] and "No such file" not in text
