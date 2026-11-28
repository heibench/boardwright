"""A spec or board file is run as its source reads now. Loaded through
importlib, an edit of the same size within the same second reused the
first load's cached bytecode, and the old spec ran without a word."""

import os

import pytest

from boardwright import build, edits, existing, live, review, sch
from boardwright.env import load_source


def _same_stamp_rewrite(f, old, new):
    """Rewrite f from old to new text of the same size, with the same mtime."""
    assert len(old) == len(new)
    st = f.stat()
    f.write_text(new)
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))


def test_a_same_size_edit_in_the_same_second_is_seen(tmp_path):
    f = tmp_path / "spec.py"
    f.write_text("X = 1\n")
    assert load_source(f, "spec").X == 1
    _same_stamp_rewrite(f, "X = 1\n", "X = 2\n")
    assert load_source(f, "spec").X == 2


def test_the_module_knows_its_file_and_a_missing_file_raises(tmp_path):
    f = tmp_path / "spec.py"
    f.write_text("import os\nHERE = os.path.basename(__file__)\n")
    assert load_source(f, "spec").HERE == "spec.py"
    with pytest.raises(FileNotFoundError):
        load_source(tmp_path / "nope.py", "spec")


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
    _same_stamp_rewrite(f, 'NAME = "aa"\n', 'NAME = "bb"\n')
    assert loader(f).NAME == "bb"


def test_sch_add_and_review_read_the_source():
    import inspect
    for fn in (sch.add, review.cli):
        src = inspect.getsource(fn)
        assert "load_source(" in src and "spec_from_file_location" not in src, fn.__name__
