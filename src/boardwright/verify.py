"""Compare KiCad's own netlist against the declared circuit. Exact, no tolerance."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .circuit import Circuit


def kicad_nets(netlist_xml: Path) -> tuple[dict[str, frozenset], dict[str, str]]:
    root = ET.parse(netlist_xml).getroot()
    nets = {}
    for n in root.iter("net"):
        nodes = frozenset((nd.get("ref"), nd.get("pin")) for nd in n.iter("node")
                          if not nd.get("ref", "").startswith("#"))
        if nodes:
            nets[n.get("name").lstrip("/")] = nodes
    fps = {c.get("ref"): (c.findtext("footprint") or "") for c in root.iter("comp")}
    return nets, fps


def compare(c: Circuit, netlist_xml: Path) -> list[str]:
    got, fps = kicad_nets(netlist_xml)
    want = {n: frozenset(m) for n, m in c.nets().items()}
    problems = []
    # Single-node nets in KiCad are unconnected pins; drop those the intent also has as single.
    got_by_members = {m: n for n, m in got.items() if len(m) > 1}
    for name, members in want.items():
        if len(members) == 1:
            continue
        if members not in got_by_members:
            close = [n for n, m in got.items() if m & members]
            problems.append(f"net {name} {sorted(members)} not in KiCad netlist; overlaps {close}")
    want_sets = {m for m in want.values() if len(m) > 1}
    for m, n in got_by_members.items():
        if m not in want_sets:
            problems.append(f"KiCad net {n} {sorted(m)} was not declared")
    for p in c.parts:
        if fps.get(p.ref) != p.footprint:
            problems.append(f"{p.ref} footprint {fps.get(p.ref)!r} != {p.footprint!r}")
    return problems
