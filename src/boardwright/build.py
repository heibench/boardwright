"""Build driver.

    boardwright gen <board dir>       # sch + pcb + place + pour + route
    boardwright check <board dir>     # the KiCad gate (ERC, DRC, exports)
    boardwright verify <board dir>    # parse the reports, gate

A board dir holds board.py defining: NAME, CIRCUIT, W, H, PLACE, and optionally
ROUTE_SKIP (nets left to pours), POURS (list of (net, layers)).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from . import board as B
from . import copper, env
from .circuit import write_schematic
from .errors import EnvironmentFault, Usage
from .project import vendor_libs, write_project
from .review import review
from .verify import compare

SCH_OUT = ("erc.json", "netlist.xml", "bom.csv", "schematic.pdf")
KEEP = {"board.py", ".libmerge", "libs", "sym-lib-table", "fp-lib-table", "notes.md"}


def load(board_dir: Path):
    m = env.load_source(board_dir / "board.py", "board_def")
    if getattr(m, "LIBS", None):
        from .project import merge_libs
        merge_libs([(board_dir / p).resolve() for p in m.LIBS], board_dir)
    return m


def clean(d: Path) -> None:
    for p in d.iterdir():
        if p.name in KEEP:
            continue
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()


def stage_place(d: Path, m) -> Path:
    """Everything up to a placed, unrouted board: seconds, no autorouter."""
    # Schematic-side gate outputs survive a regeneration that leaves the
    # schematic byte-identical (the usual case: only the layout changed).
    old_sch = d / f"{m.NAME}.kicad_sch"
    old_text = old_sch.read_text() if old_sch.exists() else None
    keep = {n: (d / "out" / n).read_bytes() for n in SCH_OUT if (d / "out" / n).exists()}
    clean(d)
    out = d / "out"
    out.mkdir()
    vendor_libs(m.CIRCUIT, d)
    write_project(d, m.NAME, getattr(m, "RULES", None), getattr(m, "CLASSES", None), getattr(m, "SEVERITIES", None))
    sch, pcb = d / f"{m.NAME}.kicad_sch", d / f"{m.NAME}.kicad_pcb"
    print("schematic:", write_schematic(m.CIRCUIT, sch))
    if old_text is not None and sch.read_text() == old_text and len(keep) == len(SCH_OUT):
        for n, data in keep.items():
            (out / n).write_bytes(data)
        print("schematic unchanged: kept", ", ".join(SCH_OUT))
    check_parts(m.CIRCUIT, d)
    B.create(sch, pcb, m.W, m.H, getattr(m, "LAYERS", 2), m.CIRCUIT)
    from .placement import resolve
    place = resolve(pcb, m.PLACE, m.CIRCUIT, d)
    (out / "placement.json").write_text(json.dumps(place, indent=1))
    B.place(pcb, place)
    B.set_pad_nets(pcb, m.CIRCUIT.nc_nets)   # KiCad's own name for a no-connect pad
    copper.apply(pcb, m, "pre")      # VIAS, TRACKS, KEEPOUTS: fixed before routing
    return pcb


def place_only(d: Path) -> int:
    """`place` step: placed board + hand copper + instant preview, no routing,
    and the REVIEW keys that read only placement (#47): exit 1 on a finding."""
    m = load(d)
    pcb = stage_place(d, m)
    from .preview import write
    write(pcb, d / "out" / "preview.png")
    from .model import Board
    from .placement_review import KEYS, placement_review
    spec = getattr(m, "REVIEW", {})
    if not any(spec.get(k) for k in KEYS):
        return 0
    lines, fails = placement_review(Board(pcb), spec)
    print("placement:", *("    " + ln for ln in lines), sep="\n")
    print(f"{'OK  ' if not fails else 'FAIL'} placement", *fails, sep="\n    ")
    return 1 if fails else 0


def gen(d: Path) -> None:
    m = load(d)
    pcb = stage_place(d, m)
    pours = getattr(m, "POURS", [("GND", ("F.Cu", "B.Cu"))])
    if getattr(m, "POUR_FIRST", False):  # let Freerouting treat pours as planes
        for net, layers, *solid in pours:
            B.gnd_pour(pcb, net, layers, solid=bool(solid and solid[0]))
    route(d, m, pcb)
    copper.apply(pcb, m, "post")     # ZONES (local power polygons), TEXT
    if not getattr(m, "POUR_FIRST", False):  # route every net as traces, then pour
        for net, layers, *solid in pours:
            B.gnd_pour(pcb, net, layers, solid=bool(solid and solid[0]))
    for layer, net in getattr(m, "PLANES", {}).items():      # inner planes, after routing: see AGENTS.md
        B.gnd_pour(pcb, net, (layer,), solid=False)
    write_project(d, m.NAME, getattr(m, "RULES", None), getattr(m, "CLASSES", None), getattr(m, "SEVERITIES", None))
    from .model import Board
    from .review import crossings
    for c in crossings(Board(pcb), m):
        print("REVIEW:", c)
    print("generated", pcb)


def route(d: Path, m, pcb: Path) -> None:
    """Freerouting, clean up, then finish what it left open.

    Freerouting abandons a net or two on some runs of a dense board, and which
    ones changes with any small change to the input. So: route, let the
    pad-to-pad router complete the open connections, and if some are boxed in
    by the autorouter's own tracks, start again from the unrouted board with a
    slightly different bottom-layer cost. The first attempt with nothing open
    is kept; otherwise the best one, with a warning."""
    from .model import Board
    from .preview import ratsnest
    poured = ({p[0] for p in getattr(m, "POURS", [("GND",)])} | {z[0] for z in getattr(m, "ZONES", [])}
              | set(getattr(m, "PLANES", {}).values()))
    base = getattr(m, "FR_BOTTOM_COST", None)
    costs = [base] if not base else [base, round(base * 0.8, 1), round(base * 1.25, 1), round(base * 0.6, 1)]
    costs = costs[:getattr(m, "FR_ATTEMPTS", 3)] if base else [None, None][:1]
    unrouted = pcb.read_text()
    best = None
    for n, cost in enumerate(costs):
        if n:
            pcb.write_text(unrouted)
            print(f"attempt {n + 1}: bottom cost {cost}")
        _route_once(d, m, pcb, "", cost, str(getattr(m, "FR_PASSES", 100)))
        left = sorted({x for *_p, x in ratsnest(Board(pcb), poured)})
        print("after the autorouter, nets still open (poured nets not checked):", left or "none")
        if left:
            left = complete(pcb, m, poured)
        if best is None or len(left) < len(best[0]):
            best = (left, pcb.read_text())
        if not left:
            break
    if best[1] != pcb.read_text():
        pcb.write_text(best[1])
    if best[0]:
        print("WARNING: still open after every attempt, hand-route these:", best[0])
    from .silk import place_refs
    moved = place_refs(pcb)
    print(f"reference text moved clear: {len(moved)}")


def complete(pcb: Path, m, poured: set) -> list[str]:
    """Route what the autorouter left open, one connection at a time, with the
    pad-to-pad router. Freerouting abandons a net or two on some runs of a
    dense board; this makes the outcome independent of that."""
    from .model import Board
    from .preview import ratsnest
    from .route import route
    classes = getattr(m, "CLASSES", {})
    default = classes.get("Default", (0.2, 0.25, 0.6, 0.3))
    by_net = {n: spec for name, spec in classes.items() if name != "Default" for n in spec[4]}
    planes = set(getattr(m, "PLANES", {}))
    import time
    deadline = time.time() + getattr(m, "COMPLETE_SECONDS", 90)
    for _round in range(3):
        b = Board(pcb)
        todo = ratsnest(b, poured)
        if not todo:
            return []
        if len(todo) > 12:              # this is not a board with a stray net or two: do not grind through it
            print(f"{len(todo)} connections open: too many for the completion pass")
            break
        chunks, extra = [], []
        ox, oy = b.origin
        t = pcb.read_text()
        for o in todo:
            net = o[2]
            clr, width, via_d, via_drill = (by_net.get(net) or default)[:4]
            if time.time() > deadline:
                break
            r = route(b, o.a, o.b, width=width, clearance=clr, via=(via_d, via_drill),
                      layers=[l for l in b.layers if l not in planes], extra=extra,
                      max_nodes=200_000, grow=1)
            if not r:
                continue
            for tr in r.tracks:
                chunks.append(copper.track(copper._net(t, net), tr[1], ox, oy, tr[2], tr[3]))
                extra.append(("t", net, tr[1], tr[2], tr[3]))
            for v in r.vias:
                chunks.append(copper.via(copper._net(t, net), v[1], v[2], ox, oy, v[3], v[4]))
                extra.append(("v", net, v[1], v[2], v[3]))
            print(f"completed {o.a} -> {o.b} ({net}): {r.length:.1f} mm, {len(r.vias)} via(s)")
        if not chunks:
            break
        copper.append(pcb, chunks)
    return sorted({n for *_p, n in ratsnest(Board(pcb), poured)})


def _route_once(d: Path, m, pcb: Path, tag: str, bcost, passes: str) -> None:
    dsn, ses = d / "out" / f"{m.NAME}{tag}.dsn", d / "out" / f"{m.NAME}{tag}.ses"
    from .dsn import export
    export(pcb, dsn)
    # FR_MARGIN (mm) routes wider than the DRC clearance. Costs routability on
    # fine-pitch parts, so it is off unless a board asks for it.
    margin = getattr(m, "FR_MARGIN", 0) * 1000
    if margin:
        dsn.write_text(re.sub(r"\(clearance ([\d.]+)", lambda mm: f"(clearance {float(mm.group(1)) + margin}", dsn.read_text()))
    cmd = [*env.freerouting(), "-de", str(dsn), "-do", str(ses), "-mp", passes]
    planes = getattr(m, "PLANES", {})
    if bcost or planes:
        # A Freerouting rules file. Only the layer rules act in 2.5 (fanout, via
        # and rip-up lines are ignored). Measured on stm32f103_min: no file =
        # 798 mm of bottom track, bottom cost 20 = 195 mm with everything
        # routed, cost 60 = 7 nets abandoned. The top layer's against-direction
        # cost must stay 2.5; at 1.0 nets were abandoned on every run.
        # Plane layers are switched off for routing so the planes stay whole.
        from .model import Board
        rules = d / "out" / f"{m.NAME}.rules"
        body = ""
        for i, layer in enumerate(Board(pcb).layers):
            if layer in planes:
                body += f"    (layer_rule {layer}\n      (active off)\n    )\n"
                continue
            cost = (bcost or 1.0) if layer == "B.Cu" else 1.0
            against = cost if layer == "B.Cu" and bcost else 2.5
            body += (f"    (layer_rule {layer}\n      (active on)\n"
                     f"      (preferred_direction {'horizontal' if i % 2 == 0 else 'vertical'})\n"
                     f"      (preferred_direction_trace_costs {cost})\n"
                     f"      (against_preferred_direction_trace_costs {against})\n    )\n")
        rules.write_text(f"(rules PCB {m.NAME}\n  (autoroute_settings\n{body}  )\n)\n")
        cmd += ["-dr", str(rules)]
    r = subprocess.run(cmd,
                       capture_output=True, text=True, timeout=getattr(m, "FR_TIMEOUT", 900))
    (d / "out" / f"freerouting{tag}.log").write_text(r.stdout + r.stderr)
    if not ses.exists():
        raise EnvironmentFault("freerouting produced no SES; see out/freerouting.log")
    import_ses(pcb, ses, m)


def import_ses(pcb: Path, ses: Path, m) -> None:
    """Add Freerouting's tracks and vias to the board, leaving the rest of the
    file as it was, without what the session gets wrong: the protected copper
    it gives back a second time, tracks necked below the minimum width, and
    vias and stubs left from abandoned attempts.

    Vias and tracks on poured nets are kept (a pour connects them), and so are
    vias at hand-placed VIAS. The board's own copper is never removed.
    """
    import math
    from collections import Counter

    from . import ses as S
    text = pcb.read_text()
    layers = S.copper_layers(text)
    tracks, vias = S.read(ses, layers)
    unknown = {i[0] for i in tracks + vias} - S.nets(text)
    if unknown:
        raise ValueError(f"{ses.name} routes nets {sorted(unknown)}, which the board does not have")
    have_t, have_v = [], []     # the board's own: (layer, x1, y1, x2, y2) and (x, y)
    for s0, e0 in copper.blocks(text, ("segment", "via")):
        b = text[s0:e0]
        if b.lstrip().startswith("(via"):
            have_v.append(tuple(map(float, re.search(r"\(at ([-\d.]+) ([-\d.]+)", b).groups())))
        else:
            ends = re.findall(r"\((?:start|end) ([-\d.]+) ([-\d.]+)\)", b)
            have_t.append((re.search(r'\(layer "([^"]+)"', b).group(1), *map(float, ends[0] + ends[1])))
    # The vias and tracks placed before routing come back as protected copper: keep the board's own.
    seen = {(round(x, 3), round(y, 3)) for x, y in have_v}
    new_v = []
    for v in vias:
        if (round(v[1], 3), round(v[2], 3)) not in seen:
            seen.add((round(v[1], 3), round(v[2], 3)))
            new_v.append(v)
    def key(layer, x1, y1, x2, y2):
        return frozenset([(round(x1, 3), round(y1, 3)), (round(x2, 3), round(y2, 3))]), layer
    seen = {key(*t) for t in have_t}
    # Freerouting necks traces down to squeeze between pads; never below the fab minimum.
    minw = (getattr(m, "RULES", None) or {}).get("min_track_width", 0.15)
    new_t = []
    for t in tracks:
        if key(*t[1:6]) not in seen:
            seen.add(key(*t[1:6]))
            new_t.append((*t[:6], max(t[6], minw)))
    # A via from an abandoned attempt has a track on one side or none.
    poured = {p[0] for p in getattr(m, "POURS", [("GND",)])} | {z[0] for z in getattr(m, "ZONES", [])}
    ox, oy = copper.origin(pcb)
    def r2(x, y):
        return round(x, 2), round(y, 2)
    on: dict[tuple[float, float], set[str]] = {}
    for layer, x1, y1, x2, y2 in have_t + [t[1:6] for t in new_t]:
        for pt in (r2(x1, y1), r2(x2, y2)):
            on.setdefault(pt, set()).add(layer)
    placed = {r2(v[1] + ox, v[2] + oy) for v in getattr(m, "VIAS", [])}
    new_v = [v for v in new_v if r2(v[1], v[2]) in placed or v[0] in poured or len(on.get(r2(v[1], v[2]), ())) >= 2]
    # A stub: a track end touching no pad, via or other track on its layer. Dropping one can leave another.
    pads = [(p[3] + ox, p[4] + oy, p.reach + 0.05) for p in copper.pads(pcb)]
    at_via = {r2(x, y) for x, y in have_v} | {r2(v[1], v[2]) for v in new_v}
    removed = 0
    while True:
        count = Counter((pt, layer) for layer, x1, y1, x2, y2 in have_t + [t[1:6] for t in new_t]
                        for pt in (r2(x1, y1), r2(x2, y2)))
        def held(pt, layer):
            return (count[(pt, layer)] > 1 or pt in at_via
                    or any(math.hypot(pt[0] - px, pt[1] - py) <= r for px, py, r in pads))
        keep = [t for t in new_t if t[0] in poured or (held(r2(*t[2:4]), t[1]) and held(r2(*t[4:6]), t[1]))]
        if len(keep) == len(new_t):
            break
        removed += len(new_t) - len(keep)
        new_t = keep
    if removed:
        print(f"removed {removed} dangling autorouter stub segment(s)")
    copper.append(pcb, [S.track_block(text, t) for t in new_t] + [S.via_block(text, v, layers) for v in new_v])


def _violations(report: Path) -> list[dict]:
    d = json.loads(report.read_text())
    if "sheets" in d:
        return [v for s in d["sheets"] for v in s["violations"]]
    return d.get("violations", []) + d.get("unconnected_items", []) + d.get("schematic_parity", [])


def verify(d: Path) -> int:
    m = load(d)
    out = d / "out"
    ok, missing = True, False
    for name in ("erc.json", "drc.json"):
        f = out / name
        if not f.exists():
            print(f"MISSING {name} -- run the KiCad gate (boardwright check)"); missing = True; continue
        vs = [v for v in _violations(f) if v.get("severity") != "exclusion"]
        print(f"{'OK  ' if not vs else 'FAIL'} {name}: {len(vs)} violations")
        for v in vs[:40]:
            print("    ", v.get("severity"), v.get("type"), v.get("description"),
                  [i.get("description") for i in v.get("items", [])][:2])
        ok &= not vs
    nl = out / "netlist.xml"
    if nl.exists():
        probs = compare(m.CIRCUIT, nl)
        print(f"{'OK  ' if not probs else 'FAIL'} netlist == intent", *probs, sep="\n    ")
        ok &= not probs
    else:
        print("MISSING netlist.xml -- run the KiCad gate (boardwright check)"); missing = True
    pcb = d / f"{m.NAME}.kicad_pcb"
    if (out / "drc.json").exists() and (out / "drc.json").stat().st_mtime < pcb.stat().st_mtime - 2:
        print("STALE drc.json is older than the board -- rerun the gate"); missing = True
    print("review:")
    rf = review(pcb, m)
    print(f"{'OK  ' if not rf else 'FAIL'} review", *rf, sep="\n    ")
    ok &= not rf
    gerbers = list((out / "gerbers").glob("*")) if (out / "gerbers").exists() else []
    print(f"{'OK  ' if gerbers else 'MISSING'} gerbers+drill: {len(gerbers)} files")
    missing |= not gerbers
    for svg in out.glob("*_Cu.svg") if shutil.which("rsvg-convert") else []:   # copper plots, as PNG where it can
        subprocess.run(["rsvg-convert", "-w", "1500", "-b", "white", str(svg), "-o", str(svg.with_suffix(".png"))], check=False)
    if not ok:
        print("NOT DONE")
        return 1
    if missing:
        print("CANNOT TELL: reports are missing or stale")
        return 2
    print("PASS")
    return 0


def check_parts(c, d: Path) -> None:
    """Every pin a part uses must exist as a pad on its footprint (catches a wrong
    footprint or a custom symbol/footprint pair that disagree)."""
    problems = []
    for p in c.parts:
        if not p.footprint or not p.pins:
            continue
        nick, name = p.footprint.split(":")
        mod = (d / "libs" / f"{nick}.pretty" / f"{name}.kicad_mod").read_text()
        padnames = set(re.findall(r'\(pad "([^"]*)"', mod))
        missing = sorted(set(p.pins) - padnames)
        if missing:
            problems.append(f"{p.ref}: {p.lib_id} pins {missing} have no pad on {p.footprint}")
        unused = sorted(padnames - set(p.pins) - {""})
        if unused:
            print(f"note: {p.ref} footprint pads {unused} have no symbol pin")
    if problems:
        raise ValueError("symbol/footprint mismatch:\n  " + "\n  ".join(problems))


def pads(d: Path) -> int:
    m = load(d)
    for ref, num, net, x, y, layer in sorted(copper.pads(d / f"{m.NAME}.kicad_pcb")):
        print(f"{ref:<6}{num:<5}{net:<28}{x:>8.3f}{y:>8.3f}  {layer}")
    return 0


def cli(argv: list[str]) -> int:
    argv = ["boardwright", *argv]
    d, step = Path(argv[1]).resolve(), argv[2]
    if not (d / "board.py").exists():
        raise Usage(f"{d} has no board.py")
    return ({"gen": lambda: gen(d) or 0, "verify": lambda: verify(d), "pads": lambda: pads(d),
              "place": lambda: place_only(d)}[step]())
