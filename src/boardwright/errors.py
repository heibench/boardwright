"""Exit codes, shared with the other heibench tools.

    0   done: the board passed, or the edit was made and checked
    1   refused or violated: a finding about the design, or an edit not made
    2   could not tell: a check that could not be decided (a report is missing)
    4   environment fault: KiCad, a library or Freerouting missing or failing,
        or an input that cannot be read; never a verdict on the design
    64  usage: bad arguments, or a spec naming parts, nets or layers that are not there
"""

from __future__ import annotations


class Outcome(SystemExit):
    """A SystemExit carrying a message and one of the codes above."""

    exit = 1

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CannotTell(Outcome):
    exit = 2


class EnvironmentFault(Outcome):
    exit = 4


class Usage(Outcome):
    exit = 64
