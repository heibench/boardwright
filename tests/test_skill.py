"""The agent skill (#48): every command it names exists, its new-board loop is
the one CI's KiCad job runs to verify PASS, and installs carry it."""

import re
import shutil
import subprocess
import zipfile

import pytest
from conftest import ROOT

from boardwright import cli, existing, live
from boardwright.cli import main

SKILL = ROOT / "skills" / "boardwright" / "SKILL.md"
TEXT = SKILL.read_text()


def _commands():
    """Every `boardwright ...` the skill tells an agent to run, as word lists."""
    return [c.split()[1:] for c in re.findall(r"`(boardwright [^`]+)`", TEXT)]


def test_every_command_the_skill_names_exists():
    top = cli._BUILD | set(cli._MODULES) | {"doctor", "--docs", "--help", "--version"}
    steps = set(re.search(r"if step not in \(([^)]*)\)", (ROOT / "src/boardwright/existing.py").read_text()).group(1)
                .replace('"', "").replace(" ", "").split(","))
    verbs = set(re.findall(r"boardwright live (\w+)", live.__doc__))
    sch = {"parts", "set", "remove", "add", "repoint", "move"}
    named = _commands()
    assert len(named) >= 15                                     # the parse found the skill's commands
    for words in named:
        cmd = words[0]
        assert cmd in top, words
        if cmd == "existing" and len(words) > 2:
            assert words[2] in steps, words
        if cmd == "live" and len(words) > 1:
            assert words[1] in verbs, words
        if cmd == "sch" and len(words) > 2:
            assert words[2] in sch, words
    short = re.findall(r"`live (\w+)", TEXT)                    # verbs named without the program
    assert short and set(short) <= verbs, set(short) - verbs
    assert existing.reroute and "revert" in verbs                # what the skill relies on is there


def test_the_new_board_loop_is_the_one_ci_runs_to_pass():
    """Without a KiCad here, the acceptance is that the skill's loop is the loop
    the KiCad pipeline job proves on the LDO example: gen, check, verify."""
    loop = [w[0] for w in _commands() if len(w) > 1 and w[1] == "DIR" and w[0] in ("gen", "check", "verify")]
    assert loop[:3] == ["gen", "check", "verify"]
    pipeline = (ROOT / "tests" / "test_pipeline.py").read_text()
    assert re.search(r'main\(\["gen", str\(ldo_copy\)\]\) == 0\s+assert main\(\["check", str\(ldo_copy\)\]\) == 0'
                     r'\s+assert main\(\["verify", str\(ldo_copy\)\]\) == 0', pipeline)
    check_yml = (ROOT / ".github" / "workflows" / "check.yml").read_text()
    assert "tests/test_pipeline.py" in check_yml and "Assert nothing skipped" in check_yml


def test_docs_points_at_the_skill(capsys):
    assert main(["--docs"]) == 0
    root = capsys.readouterr().out.strip()
    assert (ROOT.__class__(root) / "skills" / "boardwright" / "SKILL.md").read_text() == TEXT


def test_the_skill_says_when_it_applies():
    head = TEXT.split("---")[1]
    assert re.search(r"^name: boardwright$", head, re.M) and "Use when" in head and "Not for" in head


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv builds the wheel")
def test_the_wheel_carries_exactly_the_tracked_skill(tmp_path):
    """force-include copies what is on disk: an untracked file would ship too."""
    subprocess.run(["uv", "build", "--wheel", "-q", "-o", str(tmp_path)], cwd=ROOT, check=True, capture_output=True)
    wheel = next(tmp_path.glob("*.whl"))
    shipped = sorted(n.split("_bundled/", 1)[1] for n in zipfile.ZipFile(wheel).namelist() if "/_bundled/" in n)
    tracked = sorted(subprocess.run(["git", "ls-files", "skills"], cwd=ROOT, check=True, capture_output=True,
                                    text=True).stdout.split())
    assert shipped == tracked
