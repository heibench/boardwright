"""A spec or board file is run as its source reads now. Loaded through
importlib, an edit of the same size within the same second reused the
first load's cached bytecode, and the old spec ran without a word (#213)."""

import os
import shutil
import sys

import pytest
from conftest import BOARDS

from boardwright import build, edits, existing, live, review
from boardwright.cli import main
from boardwright.env import load_source

LDO = BOARDS / "ldo_breakout"


@pytest.fixture(autouse=True)
def _bytecode_on(monkeypatch):
    """The stale reuse needs a cached .pyc: write one, whatever the environment says."""
    monkeypatch.setattr(sys, "dont_write_bytecode", False)


def _same_stamp_rewrite(f, new):
    """Rewrite f to new text of the same size, with the same mtime."""
    st = f.stat()
    assert len(new.encode()) == st.st_size
    f.write_text(new)
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))


def test_a_same_size_edit_in_the_same_second_is_seen(tmp_path):
    f = tmp_path / "spec.py"
    f.write_text("X = 1\n")
    assert load_source(f, "spec").X == 1
    _same_stamp_rewrite(f, "X = 2\n")
    assert load_source(f, "spec").X == 2


def test_the_module_knows_its_file_and_a_missing_file_raises(tmp_path, monkeypatch):
    f = tmp_path / "spec.py"
    f.write_text("HERE = __file__\n")
    monkeypatch.chdir(tmp_path)
    assert load_source("spec.py", "spec").HERE == str(f)                   # absolute, as importlib gave it
    with pytest.raises(FileNotFoundError):
        load_source(tmp_path / "nope.py", "spec")


def test_a_spec_is_compiled_as_written_not_with_boardwrights_future_flags(tmp_path):
    """env.py has `from __future__ import annotations`; inherited, it made every
    annotation a string, and a dataclass in a spec raised AttributeError."""
    f = tmp_path / "spec.py"
    f.write_text("from dataclasses import dataclass\n\n@dataclass\nclass Zone:\n    net: str\n    w: float\n\nZ = Zone('GND', 0.5)\n")
    m = load_source(f, "spec")
    assert m.Z.net == "GND" and m.Zone.__annotations__ == {"net": str, "w": float}


@pytest.mark.parametrize("raw", [
    "﻿V = '10µF'\n".encode(),                                         # UTF-8 with a BOM
    "# -*- coding: latin-1 -*-\nV = '25°C'\n".encode("latin-1"),           # a PEP 263 coding line
])
def test_a_spec_decodes_as_python_decodes_it(tmp_path, raw):
    f = tmp_path / "spec.py"
    f.write_bytes(raw)
    assert load_source(f, "spec").V in ("10µF", "25°C")


@pytest.mark.parametrize("name,loader", [
    ("edit_spec.py", lambda f: edits.load_spec(str(f))),
    ("live_spec.py", lambda f: live._load(str(f))),
    ("board.py", lambda f: build.load(f.parent)),
    ("boardwright.py", lambda f: existing.spec(f.parent)),
])
def test_every_loader_reads_the_source(tmp_path, name, loader):
    f = tmp_path / name
    f.write_text('NAME = "aa"\n')
    assert loader(f).NAME == "aa"
    _same_stamp_rewrite(f, 'NAME = "bb"\n')
    assert loader(f).NAME == "bb"


def test_sch_add_runs_the_rewritten_spec(tmp_path):
    proj = tmp_path / "ldo"
    shutil.copytree(LDO, proj, ignore=shutil.ignore_patterns("out", "boardwright_out", ".libmerge", "__pycache__"))
    f = tmp_path / "add_spec.py"
    row = 'ADD = [("R7%d", "R1", "1k", "Resistor_SMD:R_0805_2012Metric", {1: "+3V3", 2: "GND"})]\n'
    f.write_text(row % 0)
    assert main(["sch", str(proj), "add", str(f)]) == 0
    _same_stamp_rewrite(f, row % 1)
    assert main(["sch", str(proj), "add", str(f)]) == 0                    # was 64, "R70 already exists"
    assert '"R71"' in (proj / "ldo_breakout.kicad_sch").read_text()


def test_review_runs_the_rewritten_spec(tmp_path):
    f = tmp_path / "review_spec.py"
    f.write_text("X = 1 // 1\n")
    review.cli([str(LDO / "ldo_breakout.kicad_pcb"), str(f)])
    _same_stamp_rewrite(f, "X = 1 // 0\n")
    with pytest.raises(ZeroDivisionError):
        review.cli([str(LDO / "ldo_breakout.kicad_pcb"), str(f)])
