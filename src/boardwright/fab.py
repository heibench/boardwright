"""A board against a fab's published limits (#49): REVIEW = {"fab": "jlcpcb"}.

Each limit is a fab's own published value, read on READ from the page named
with it, and quoted. Two levels:

    min   the fab's stated minimum: a board below it is refused (a failure)
    std   the limit at the standard price, or the fab's recommendation: below
          it the review says so and what it costs, but does not fail

The fab's limit depends on what it depends on there: layer count and copper
weight (1 oz unless REVIEW gives "fab_copper_oz"). OSH Park's and PCBWay's
values are those of their 1 oz service. A measured value the fab has limits
for, but none at this board's layers and copper, fails as "cannot judge"
rather than going unchecked. What is checked: the
board's own tracks, vias and plated holes, and the project's clearance and
copper-to-edge rules, which KiCad's DRC already holds the board to.

Eurocircuits is not here: its limits are published as an image, which this
data was not read from. PCBWay states no via-hole or edge limit in its
standard table, so none is checked for it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

READ = "2026-11-21"


@dataclass(frozen=True)
class Limit:
    key: str              # track, space, drill, via_hole, via_diameter, via_ring, pth_ring, edge
    value: float          # mm
    level: str            # "min" or "std"
    page: str
    quote: str
    layers: tuple[int, int] = (1, 99)
    oz: tuple[float, float] = (0, 99)


JLC = "https://jlcpcb.com/capabilities/pcb-capabilities"
JLC_EXTRA = "https://jlcpcb.com/help/article/in-what-cases-will-there-be-charged-extra"
OSH2 = "https://docs.oshpark.com/services/two-layer/"
OSH4 = "https://docs.oshpark.com/services/four-layer/"
PCBWAY = "https://www.pcbway.com/capabilities.html"

FABS: dict[str, list[Limit]] = {
    "jlcpcb": [
        Limit("track", 0.10, "min", JLC, "1- and 2-layer: 0.10 / 0.10 mm (4 / 4 mil)", (1, 2), (0, 1)),
        Limit("space", 0.10, "min", JLC, "1- and 2-layer: 0.10 / 0.10 mm (4 / 4 mil)", (1, 2), (0, 1)),
        Limit("track", 0.075, "min", JLC_EXTRA, "If the trace width or spacing of multi-layer boards is 3.0-3.5mil, "
              "extra cost will be charged", (4, 99), (0, 1)),
        Limit("space", 0.075, "min", JLC_EXTRA, "If the trace width or spacing of multi-layer boards is 3.0-3.5mil, "
              "extra cost will be charged", (4, 99), (0, 1)),
        Limit("track", 0.09, "std", JLC, "Multilayer: 0.09 / 0.09 mm (3.5 / 3.5 mil)", (4, 99), (0, 1)),
        Limit("space", 0.09, "std", JLC, "Multilayer: 0.09 / 0.09 mm (3.5 / 3.5 mil)", (4, 99), (0, 1)),
        Limit("track", 0.16, "min", JLC, "2-layer: 0.16 / 0.16 mm (6.5 / 6.5 mil)", (1, 2), (2, 2)),
        Limit("space", 0.16, "min", JLC, "2-layer: 0.16 / 0.16 mm (6.5 / 6.5 mil)", (1, 2), (2, 2)),
        Limit("track", 0.15, "min", JLC, "Multilayer: 0.15 / 0.15 mm (6 / 6 mil)", (4, 99), (2, 2)),
        Limit("space", 0.15, "min", JLC, "Multilayer: 0.15 / 0.15 mm (6 / 6 mil)", (4, 99), (2, 2)),
        Limit("drill", 0.3, "min", JLC, "1-layer: 0.3 – 6.3 mm", (1, 1)),
        Limit("drill", 0.1, "min", JLC, "Min. drill diameter for 2- or more-layer PCBs is 0.1 mm (more costly!)", (2, 99)),
        Limit("drill", 0.15, "std", JLC, "2-layer: 0.15 – 6.3 mm", (2, 99)),
        Limit("via_hole", 0.15, "min", JLC, "Min. Via hole size/diameter: 0.15/0.25mm", (2, 99)),
        Limit("via_hole", 0.2, "std", JLC, "Preferred Min. Via hole size: 0.2mm; 0.1mm or 0.15mm hole size with any "
              "size via diameter will cost more", (2, 99)),
        Limit("via_diameter", 0.25, "min", JLC, "Min. Via hole size/diameter: 0.15/0.25mm", (2, 99)),
        Limit("via_ring", 0.05, "min", JLC, "Via diameter should be 0.1mm(0.15mm preferred) larger than Via hole size"),
        Limit("via_ring", 0.075, "std", JLC, "Via diameter should be 0.1mm(0.15mm preferred) larger than Via hole size"),
        Limit("pth_ring", 0.18, "min", JLC, "1 oz: Recommended 0.25 mm or above; absolute minimum 0.18 mm", (1, 2), (0, 1)),
        Limit("pth_ring", 0.25, "std", JLC, "1 oz: Recommended 0.25 mm or above; absolute minimum 0.18 mm", (1, 2), (0, 1)),
        Limit("pth_ring", 0.15, "min", JLC, "1 oz: Recommended 0.20 mm or above; absolute minimum 0.15 mm", (4, 99), (0, 1)),
        Limit("pth_ring", 0.20, "std", JLC, "1 oz: Recommended 0.20 mm or above; absolute minimum 0.15 mm", (4, 99), (0, 1)),
        Limit("edge", 0.2, "min", JLC, "Copper clearance from routed board edges: ≧0.2 mm"),
    ],
    "oshpark": [
        Limit("track", 0.1524, "min", OSH2, "Trace Width | 6mil (0.1524mm)", (2, 2), (0, 1)),
        Limit("space", 0.1524, "min", OSH2, "Trace Spacing | 6mil (0.1524mm)", (2, 2), (0, 1)),
        Limit("drill", 0.254, "min", OSH2, "Minimum Drill Size | 10mil (0.254mm)", (2, 2), (0, 1)),
        Limit("via_ring", 0.127, "min", OSH2, "Minimum Annular Ring | 5mil (0.127mm)", (2, 2), (0, 1)),
        Limit("pth_ring", 0.127, "min", OSH2, "Minimum Annular Ring | 5mil (0.127mm)", (2, 2), (0, 1)),
        Limit("edge", 0.381, "min", OSH2, "Board Edge Keepout | 15mil (0.381) from nominal board edge", (2, 2), (0, 1)),
        Limit("track", 0.127, "min", OSH4, "Trace Width | 5mil (0.127mm)", (4, 4), (0, 1)),
        Limit("space", 0.127, "min", OSH4, "Trace Spacing | 5mil (0.127mm)", (4, 4), (0, 1)),
        Limit("drill", 0.254, "min", OSH4, "Minimum Drill Size | 10mil (0.254mm)", (4, 4), (0, 1)),
        Limit("via_ring", 0.1016, "min", OSH4, "Minimum Annular Ring | 4mil (0.1016mm)", (4, 4), (0, 1)),
        Limit("pth_ring", 0.1016, "min", OSH4, "Minimum Annular Ring | 4mil (0.1016mm)", (4, 4), (0, 1)),
        Limit("edge", 0.381, "min", OSH4, "Board Edge Keepout | 15mil (0.381) from nominal board edge", (4, 4), (0, 1)),
    ],
    "pcbway": [
        Limit("track", 0.1, "min", PCBWAY, "Min Trace 0.1mm/4mil", (1, 14), (0, 1)),
        Limit("space", 0.1, "min", PCBWAY, "Min manufacturable spacing is 4mil(0.1mm)", (1, 14), (0, 1)),
        Limit("drill", 0.15, "min", PCBWAY, "Min drill size is 0.15mm", (1, 14), (0, 1)),
        Limit("drill", 0.2, "std", PCBWAY, "Any holes greater than 6mm or smaller than 0.2mm will be subject to extra "
              "charges", (1, 14), (0, 1)),
        Limit("via_ring", 0.15, "min", PCBWAY, "For pads with vias in the middle, Min width for Annular Ring is "
              "0.15mm(6mil)", (1, 14), (0, 1)),
        Limit("pth_ring", 0.15, "min", PCBWAY, "Min Width of Annular Ring 0.15mm(6mil)", (1, 14), (0, 1)),
    ],
}

WHAT = {"track": "narrowest track", "space": "smallest clearance the rules allow", "drill": "smallest plated hole",
        "via_hole": "smallest via hole", "via_diameter": "smallest via", "via_ring": "thinnest via ring",
        "pth_ring": "thinnest plated-hole ring", "edge": "copper-to-edge clearance the rules allow"}


def _rules(pcb: Path) -> tuple[dict, list[float]]:
    """The project's board rules, and every net class clearance."""
    pro = pcb.with_suffix(".kicad_pro")
    if not pro.exists():
        return {}, []
    j = json.loads(pro.read_text())
    rules = j.get("board", {}).get("design_settings", {}).get("rules", {})
    return rules, [c["clearance"] for c in j.get("net_settings", {}).get("classes", []) if "clearance" in c]


def measure(b, pcb: Path) -> dict[str, float]:
    """The board's smallest value for each key it has anything for."""
    out = {}
    if b.tracks:
        out["track"] = min(t.width for t in b.tracks)
    rules, clearances = _rules(pcb)
    space = [v for v in [rules.get("min_clearance")] + clearances if v]
    if space:
        out["space"] = min(space)
    if rules.get("min_copper_edge_clearance"):
        out["edge"] = rules["min_copper_edge_clearance"]
    holes = [v.drill for v in b.vias] + [p.drill for f in b.footprints for p in f.pads if p.drill and p.type == "thru_hole"]
    if holes:
        out["drill"] = min(holes)
    if b.vias:
        out["via_hole"] = min(v.drill for v in b.vias)
        out["via_diameter"] = min(v.size for v in b.vias)
        out["via_ring"] = min((v.size - v.drill) / 2 for v in b.vias)
    rings = [(min(p.size) - p.drill) / 2 for f in b.footprints for p in f.pads if p.drill and p.type == "thru_hole"]
    if rings:
        out["pth_ring"] = min(rings)
    return out


def fab_review(b, pcb: Path, fab: str, copper_oz: float = 1) -> tuple[list[str], list[str]]:
    """(report lines, failures) for the board against `fab`'s limits."""
    if fab not in FABS:
        return [], [f"fab {fab!r} is not one of {', '.join(sorted(FABS))}"]
    layers = len(b.layers)
    limits = [lim for lim in FABS[fab] if lim.layers[0] <= layers <= lim.layers[1] and lim.oz[0] <= copper_oz <= lim.oz[1]]
    if not limits:
        return [], [f"fab {fab}: cannot judge, no limits for a {layers}-layer board at {copper_oz:g} oz"]
    have = measure(b, pcb)
    lines, fails = [f"fab {fab} ({layers} layers, {copper_oz:g} oz; limits read {READ}):"], []
    for key in WHAT:
        mins = [lim for lim in limits if lim.key == key and lim.level == "min"]
        stds = [lim for lim in limits if lim.key == key and lim.level == "std"]
        if key not in have:
            continue
        if not (mins or stds):
            if any(lim.key == key for lim in FABS[fab]):
                fails.append(f"fab {fab}: cannot judge {key}, no limit for a {layers}-layer board at {copper_oz:g} oz")
                lines.append(f"  {key}: no {fab} limit at {copper_oz:g} oz")
            continue
        v = have[key]
        low = max(mins, key=lambda lim: lim.value) if mins else None
        std = max(stds, key=lambda lim: lim.value) if stds else None
        if low and v < low.value - 1e-9:
            fails.append(f"{WHAT[key]} {v:g} mm is below {fab}'s minimum {low.value:g} mm (\"{low.quote}\", {low.page})")
            lines.append(f"  {key}: {v:g} mm < {low.value:g} minimum")
        elif std and v < std.value - 1e-9:
            lines.append(f"  {key}: {v:g} mm, below the {std.value:g} mm standard: \"{std.quote}\" ({std.page})")
        else:
            lines.append(f"  {key}: {v:g} mm >= {(std or low).value:g}")
    return lines, fails
