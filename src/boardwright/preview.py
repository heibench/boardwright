"""Instant picture of a board without KiCad: pads, tracks, zone outlines, ratsnest.

    boardwright preview some/board.kicad_pcb [out.png]

Top copper red, bottom blue, inner layers green/orange; unrouted connections
as thin yellow lines (nets that have a pour are skipped). Good enough to see
placement and what is left to route, in well under a second.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

from .model import Board

COL = {"F.Cu": "#d33", "B.Cu": "#36c", "In1.Cu": "#3a3", "In2.Cu": "#d80", "In3.Cu": "#a3a", "In4.Cu": "#0aa"}


class Open(tuple):
    """((x1, y1), (x2, y2), net) of one unrouted connection, plus .a and .b: the pad names."""
    def __new__(cls, t, a, b):
        o = super().__new__(cls, t)
        o.a, o.b = a, b
        return o


def ratsnest(b: Board, skip: set[str]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    lines = []
    nets: dict[str, list] = {}
    for p in b.pads:
        if p.net and p.net not in skip and not p.net.startswith("unconnected-"):
            nets.setdefault(p.net, []).append(p)
    for net, pads in nets.items():
        if len(pads) < 2:
            continue
        parent = list(range(len(pads)))
        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        # copper graph: points joined by tracks and vias
        pts: dict = {}
        def node(x, y):
            return pts.setdefault((round(x, 2), round(y, 2)), len(pts))
        edges = [(node(*t.a), node(*t.b)) for t in b.tracks if t.net == net]
        cp = list(range(len(pts)))
        def cfind(i):
            while cp[i] != i:
                cp[i] = cp[cp[i]]
                i = cp[i]
            return i
        for u, v in edges:
            cp[cfind(u)] = cfind(v)
        comp_of_pad = {}
        for i, p in enumerate(pads):
            for (x, y), n in pts.items():
                if math.hypot(x - p.x, y - p.y) <= p.reach + 0.05:
                    comp_of_pad.setdefault(i, cfind(n))
                    break
        for i in range(len(pads)):
            for j in range(i):
                if i in comp_of_pad and j in comp_of_pad and comp_of_pad[i] == comp_of_pad[j]:
                    parent[find(i)] = find(j)
                elif (pads[i].ref, pads[i].num) == (pads[j].ref, pads[j].num):
                    pass
        pairs = sorted((math.hypot(pads[i].x - pads[j].x, pads[i].y - pads[j].y), i, j)
                       for i in range(len(pads)) for j in range(i))
        for _d, i, j in pairs:
            if find(i) != find(j):
                parent[find(i)] = find(j)
                lines.append(Open(((pads[i].x, pads[i].y), (pads[j].x, pads[j].y), net), f"{pads[i].ref}.{pads[i].num}", f"{pads[j].ref}.{pads[j].num}"))
    return lines


def svg(b: Board, scale: float = 20.0) -> tuple[str, int]:
    x0, y0, x1, y1 = b.bbox
    m = 2.0
    W, H = (x1 - x0 + 2 * m) * scale, (y1 - y0 + 2 * m) * scale
    X = lambda x: (x - x0 + m) * scale
    Y = lambda y: (y - y0 + m) * scale
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}">',
         '<rect width="100%" height="100%" fill="#111"/>',
         f'<rect x="{X(x0):.1f}" y="{Y(y0):.1f}" width="{(x1 - x0) * scale:.1f}" height="{(y1 - y0) * scale:.1f}" fill="#1b2a1b" stroke="#cc3" stroke-width="2"/>']
    poured = set()
    for z in b.zones:
        if not z.outline:
            continue
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in z.outline)
        if z.keepout:
            o.append(f'<polygon points="{pts}" fill="#f0f" fill-opacity="0.12" stroke="#f0f" stroke-dasharray="6 4"/>')
        else:
            poured.add(z.net)
            c = COL.get(z.layers[0] if z.layers else "", "#888")
            o.append(f'<polygon points="{pts}" fill="{c}" fill-opacity="0.07" stroke="{c}" stroke-opacity="0.5" stroke-dasharray="3 3"/>')
    order = {l: i for i, l in enumerate(reversed(b.layers))}
    for t in sorted(b.tracks, key=lambda t: order.get(t.layer, 0)):
        pts = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in t.pts)
        o.append(f'<polyline points="{pts}" fill="none" stroke="{COL.get(t.layer, "#888")}" stroke-opacity="0.85" '
                 f'stroke-width="{max(t.width * scale, 1.5):.1f}" stroke-linecap="round"/>')
    for p in b.pads:
        c = "#c9a227" if p.thru else COL.get(p.layer, "#888")
        op = 0.95 if p.layer == "F.Cu" or p.thru else 0.6
        o.append(f'<rect x="{X(p.x) - p.w * scale / 2:.1f}" y="{Y(p.y) - p.h * scale / 2:.1f}" width="{p.w * scale:.1f}" height="{p.h * scale:.1f}" '
                 f'fill="{c}" fill-opacity="{op}" transform="rotate({-p.angle:.0f} {X(p.x):.1f} {Y(p.y):.1f})"/>')
    for v in b.vias:
        o.append(f'<circle cx="{X(v.x):.1f}" cy="{Y(v.y):.1f}" r="{v.size * scale / 2:.1f}" fill="#ddd"/>'
                 f'<circle cx="{X(v.x):.1f}" cy="{Y(v.y):.1f}" r="{v.drill * scale / 2:.1f}" fill="#111"/>')
    rn = ratsnest(b, poured)
    for (ax, ay), (bx, by), _net in rn:
        o.append(f'<line x1="{X(ax):.1f}" y1="{Y(ay):.1f}" x2="{X(bx):.1f}" y2="{Y(by):.1f}" stroke="#ff3" stroke-width="1.2" stroke-opacity="0.8"/>')
    for fp in b.footprints:
        o.append(f'<text x="{X(fp.position[0]):.1f}" y="{Y(fp.position[1]):.1f}" fill="#fff" font-size="{0.9 * scale:.0f}" '
                 f'font-family="sans-serif" text-anchor="middle" dominant-baseline="middle" opacity="0.9">{fp.reference}</text>')
    o.append("</svg>")
    return "\n".join(o), len(rn)


def write(pcb: Path, out: Path) -> int:
    b = Board(pcb)
    s, n = svg(b)
    sv = out.with_suffix(".svg")
    sv.write_text(s)
    if shutil.which("rsvg-convert"):
        subprocess.run(["rsvg-convert", "-w", "1500", str(sv), "-o", str(out)], check=False)
    else:                                           # as `doctor` says: without rsvg-convert, previews stay SVG
        out = sv
    print(f"preview: {out}  ({len(b.pads)} pads, {len(b.tracks)} tracks, {n} unrouted connection(s) on unpoured nets)")
    return n


def cli(argv: list[str]) -> int:
    argv = ["boardwright", *argv]
    src = Path(argv[1])
    write(src, Path(argv[2]) if len(argv) > 2 else src.with_name(src.stem + "_preview.png"))
    return 0
