"""Trace geometry for a target impedance, and differential pairs drawn from a centreline.

    boardwright impedance                    # table for the built-in stackups
    boardwright impedance jlc4_7628 50       # single-ended width
    boardwright impedance jlc4_7628 90 0.2   # pair gap for 90 ohm at 0.2 mm width

The formulas are the closed-form IPC-2141 microstrip ones: good to roughly
+-10 %, and only for an outer layer over an adjacent plane. Use them to pick
a starting geometry, then confirm with the fab's own calculator for the
stackup you order. The JLCPCB 4-layer stackups were checked against
jlcpcb.com/impedance on 2026-11-14 (prepreg thickness, dielectric constant,
copper weights), and the 6-layer ones (JLC06161H-3313, -7628, -1080, -2116:
first prepreg under the outer copper, its dielectric constant, 0.035 mm outer
copper) on 2026-11-21; that "06161H" names a 6-layer 1.6 mm board is read
from the name, the page states no thickness per stackup. OSH Park's 4-layer
stackup is from docs.oshpark.com/services/four-layer/, read 2026-11-21
(FR408HR 2113 prepreg, dk 3.61 at 1 GHz, 1.7 mil outer copper). The 2-layer
entry is a generic FR-4 figure (#49).
"""

from __future__ import annotations

import math

# h: outer copper to the adjacent plane (mm), er: that dielectric, t: outer copper thickness (mm)
STACKUPS = {
    "jlc4_7628": {"h": 0.2104, "er": 4.4, "t": 0.035, "note": "JLCPCB 4-layer 1.6 mm, 7628 prepreg"},
    "jlc4_3313": {"h": 0.0994, "er": 4.1, "t": 0.035, "note": "JLCPCB 4-layer 1.6 mm, 3313 prepreg"},
    "jlc6_3313": {"h": 0.0994, "er": 4.1, "t": 0.035, "note": "JLCPCB 6-layer JLC06161H-3313, 3313 prepreg"},
    "jlc6_7628": {"h": 0.2104, "er": 4.4, "t": 0.035, "note": "JLCPCB 6-layer JLC06161H-7628, 7628 prepreg"},
    "jlc6_1080": {"h": 0.0764, "er": 3.91, "t": 0.035, "note": "JLCPCB 6-layer JLC06161H-1080, 1080 prepreg"},
    "jlc6_2116": {"h": 0.127, "er": 4.16, "t": 0.035, "note": "JLCPCB 6-layer JLC06161H-2116, 2116 prepreg"},
    "oshpark4": {"h": 0.1999, "er": 3.61, "t": 0.0432, "note": "OSH Park 4-layer 1.6 mm, FR408HR 2113 prepreg"},
    "2layer_1.6": {"h": 1.5, "er": 4.5, "t": 0.035, "note": "2-layer 1.6 mm: plane is the far side"},
}


def z0(w: float, h: float, er: float, t: float = 0.035) -> float:
    """Single-ended surface microstrip, ohms."""
    return 87.0 / math.sqrt(er + 1.41) * math.log(5.98 * h / (0.8 * w + t))


def zdiff(w: float, s: float, h: float, er: float, t: float = 0.035) -> float:
    """Edge-coupled surface microstrip pair, ohms differential."""
    return 2 * z0(w, h, er, t) * (1 - 0.48 * math.exp(-0.96 * s / h))


def _solve(f, lo, hi, target):
    for _ in range(60):
        mid = (lo + hi) / 2
        if (f(mid) > target) == (f(lo) > target):
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def width_for(target: float, stack: dict) -> float:
    return round(_solve(lambda w: z0(w, stack["h"], stack["er"], stack["t"]), 0.05, 5.0, target), 3)


def gap_for(target: float, w: float, stack: dict) -> float | None:
    f = lambda s: zdiff(w, s, stack["h"], stack["er"], stack["t"])
    if not (f(0.05) <= target <= f(5.0)):
        return None
    return round(_solve(f, 0.05, 5.0, target), 3)


def pair(net_p: str, net_n: str, centre: list[tuple[float, float]], width: float, gap: float,
         layer: str = "F.Cu") -> tuple[list[tuple], dict]:
    """Two TRACKS entries offset either side of a centreline, mitred at corners.

    net_p runs on the left of the direction of travel (screen coordinates, y
    down). Returns (tracks, info); info has both lengths and their difference,
    which comes only from corners: each bend makes the outer track longer.
    """
    off = (width + gap) / 2
    def side(sign):
        pts = []
        for i, (x, y) in enumerate(centre):
            dirs = []
            if i > 0:
                dirs.append((x - centre[i - 1][0], y - centre[i - 1][1]))
            if i < len(centre) - 1:
                dirs.append((centre[i + 1][0] - x, centre[i + 1][1] - y))
            ns = []
            for dx, dy in dirs:
                L = math.hypot(dx, dy)
                ns.append((dy / L * sign, -dx / L * sign))        # left normal for sign=+1
            if len(ns) == 1:
                nx, ny = ns[0]
                pts.append((round(x + nx * off, 4), round(y + ny * off, 4)))
            else:
                bx, by = ns[0][0] + ns[1][0], ns[0][1] + ns[1][1]
                bl = math.hypot(bx, by)
                k = off / (bl / 2) / bl if bl > 1e-9 else 0       # mitre: off / cos(half angle)
                pts.append((round(x + bx * k, 4), round(y + by * k, 4)))
        return pts
    p, n = side(+1), side(-1)
    length = lambda pts: sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    info = {"p": round(length(p), 3), "n": round(length(n), 3), "skew": round(abs(length(p) - length(n)), 3),
            "p_ends": (p[0], p[-1]), "n_ends": (n[0], n[-1])}
    return [(net_p, p, width, layer), (net_n, n, width, layer)], info


def cli(argv: list[str]) -> int:
    argv = ["boardwright", *argv]
    a = argv[1:]
    if not a:
        for name, s in STACKUPS.items():
            w50 = width_for(50, s)
            print(f"{name:<12} {s['note']}\n    50 ohm single: w = {w50} mm")
            for w in (0.15, 0.2, 0.25):
                print(f"    pair at w = {w}: 90 ohm gap = {gap_for(90, w, s)}, 100 ohm gap = {gap_for(100, w, s)}")
    else:
        s = STACKUPS[a[0]]
        if len(a) == 2:
            print("width mm:", width_for(float(a[1]), s))
        else:
            print("gap mm:", gap_for(float(a[1]), float(a[2]), s))
    return 0
