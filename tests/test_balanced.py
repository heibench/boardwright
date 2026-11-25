"""A write is refused when its edit would leave the file's brackets unbalanced
(#190). Brackets inside a quoted string are text, not structure, and do not
count: a value like `a(b` or `10k (1%)` is valid."""

import pytest

from boardwright import board, sch
from boardwright.model import _tree, balanced


def test_brackets_in_strings_do_not_count():
    assert balanced('(property "Value" "a(b")')
    assert balanced('(property "Value" "10k (1%)")')
    assert balanced('(property "Note" "he said \\"(\\" twice")')        # an escaped quote stays inside


def test_unbalanced_structure_is_caught():
    assert not balanced('(a (b "x")')
    assert not balanced('(a) )(')
    assert not balanced('(a "x(")) ')


def test_a_value_with_an_unmatched_bracket_is_set(ldo_copy, capsys):
    f = ldo_copy / "ldo_breakout.kicad_sch"
    assert sch.set_fields(ldo_copy, "R1", ["Value=a(b"]) == 0
    assert capsys.readouterr().out.splitlines() == ["R1: Value -> a(b"]
    text = f.read_text()
    assert '(property "Value" "a(b"' in text
    _tree(text)                                                  # and it still reads


def test_the_board_writer_takes_a_quoted_bracket_and_refuses_a_real_imbalance(tmp_path):
    pcb = tmp_path / "b.kicad_pcb"
    t0 = '(kicad_pcb (gr_text "x" (at 0 0)))\n'
    pcb.write_text(t0)
    board._write(pcb, t0, '(kicad_pcb (gr_text "a(b" (at 0 0)))\n')
    assert '"a(b"' in pcb.read_text()
    t1 = pcb.read_text()
    with pytest.raises(SystemExit, match="unbalance"):
        board._write(pcb, t1, '(kicad_pcb (gr_text "x" (at 0 0))\n')
    assert pcb.read_text() == t1
