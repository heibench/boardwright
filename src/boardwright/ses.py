"""Freerouting's session file (Specctra SES): its tracks and vias, in board
coordinates, and as board text.

What is read is `(routes ...)`: its `(resolution UNIT N)`, the via padstacks in
`(library_out ...)` and each `(net NAME (wire (path LAYER WIDTH x y ...)) (via
PADSTACK x y))` in `(network_out ...)`. The `(placement ...)` section is not
read: Freerouting is run without placement, so it repeats the DSN's positions.

Coordinates are in the board's own frame: the DSN is exported in KiCad's
coordinates, y down, and Freerouting writes them back unchanged.
"""

from __future__ import annotations

import re
from pathlib import Path

from .copper import _net, _u, blocks, num

# mm per declared unit (the Specctra DSN specification's resolution units)
_MM = {"um": 0.001, "mil": 0.0254, "mm": 1.0, "cm": 10.0, "inch": 25.4}
# Specctra carries no drill. 0.4 mm is what kicad-tools 0.29's import-ses wrote
# for every via (SESToKiCadImporter.merge_into's default_via_drill).
DRILL = 0.4


def _tree(text: str) -> list:
    # (string_quote ") declares the quote character; its lone quote opens no string
    text = re.sub(r'\(\s*string_quote\s+"\s*\)', "", text)
    stack: list[list] = [[]]
    for tok in re.findall(r'"[^"]*"|[()]|[^\s()"]+', text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            node = stack.pop()
            stack[-1].append(node)
        else:
            stack[-1].append(tok[1:-1] if tok.startswith('"') else tok)
    return stack[0][0]


def _kids(node: list, head: str) -> list[list]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == head]


def copper_layers(text: str) -> list[str]:
    """The board's copper layers, front to back."""
    s0, e0 = blocks(text, ("layers",))[0]
    found = re.findall(r'\(\d+ "([^"]*\.Cu)"', text[s0:e0])
    return sorted(found, key=lambda l: (0, 0) if l == "F.Cu" else (2, 0) if l == "B.Cu" else (1, int(l[2:-3])))


def read(ses: Path, layers: list[str]) -> tuple[list[tuple], list[tuple]]:
    """Tracks (net, layer, x1, y1, x2, y2, width) and vias (net, x, y, size,
    top, bottom), in mm, in the order the session lists them. `layers` is the
    board's copper, front to back, which a via's padstack is read against."""
    routes = _kids(_tree(ses.read_text()), "routes")[0]
    unit, count = _kids(routes, "resolution")[0][1:3]
    scale = _MM[unit.lower()] / float(count)

    def mm(v) -> float:
        return round(float(v) * scale, 6)      # KiCad keeps 1 nm

    pads = {}
    for p in _kids(routes, "library_out")[0][1:] if _kids(routes, "library_out") else []:
        if not (isinstance(p, list) and p[0] == "padstack"):
            continue
        on = [g[1] for s in _kids(p, "shape") for g in s[1:] if isinstance(g, list)]
        dia = [float(g[2]) for s in _kids(p, "shape") for g in s[1:] if isinstance(g, list) and g[0] == "circle"]
        if not dia or any(l not in layers for l in on) or len(set(on)) < 2:
            raise ValueError(f"via padstack {p[1]!r}: no circle, or not two or more of the board's copper layers")
        span = sorted(set(on), key=layers.index)
        pads[p[1]] = (mm(max(dia)), span[0], span[-1])
    tracks, vias = [], []
    for net in (n for o in _kids(routes, "network_out") for n in _kids(o, "net")):
        name = net[1]
        for w in _kids(net, "wire"):
            path = _kids(w, "path")
            if not path or path[0][1] not in layers:
                raise ValueError(f"a wire on net {name!r} is not a path on the board's copper")
            v = [mm(a) for a in path[0][2:]]
            pts = list(zip(v[1::2], v[2::2]))
            tracks += [(name, path[0][1], *a, *b, v[0]) for a, b in zip(pts, pts[1:])]
        for via in _kids(net, "via"):
            if via[1] not in pads:
                raise ValueError(f"via padstack {via[1]!r} is not in the session's library_out")
            vias.append((name, mm(via[2]), mm(via[3]), *pads[via[1]]))
    return tracks, vias


def nets(text: str) -> set[str]:
    return set(re.findall(r'\(net (?:\d+ )?"([^"]*)"\)', text))


def track_block(text: str, t: tuple) -> str:
    net, layer, x1, y1, x2, y2, w = t
    return (f'\t(segment (start {num(x1)} {num(y1)}) (end {num(x2)} {num(y2)}) (width {num(w)}) '
            f'(layer "{layer}") {_net(text, net)} (uuid "{_u()}"))\n')


def via_block(text: str, v: tuple, layers: list[str]) -> str:
    net, x, y, size, top, bottom = v
    kind = "" if (top, bottom) == (layers[0], layers[-1]) else \
        " blind" if layers[0] in (top, bottom) or layers[-1] in (top, bottom) else " buried"
    return (f'\t(via{kind} (at {num(x)} {num(y)}) (size {num(size)}) (drill {DRILL}) '
            f'(layers "{top}" "{bottom}") {_net(text, net)} (uuid "{_u()}"))\n')
