"""The board as Freerouting reads it: a Specctra DSN."""

from __future__ import annotations

from pathlib import Path


def export(pcb: Path, dsn: Path) -> int:
    """Write the DSN Freerouting routes `pcb` from; return how many curved
    tracks went in as fixed polylines."""
    from . import board as B
    from .existing import add_arcs_to_dsn
    from .model import Board
    B.kct("pcb", "export-dsn", str(pcb), "-o", str(dsn))
    return add_arcs_to_dsn(dsn, Board(pcb))
