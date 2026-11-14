# 07 existing board: StickHub

**What it is:** a KiCad demo project (7-port USB 2.0 hub, 2 layers, 94
footprints, 1293 tracks of which 179 are arcs), copied to
`dogfood/existing/stickhub/` with its own licence. Nobody here drew it. It
stands in for "a board that already exists".

**Stresses:** reading a hand-drawn board, reviewing it against a spec,
editing it in place, re-routing a few nets without disturbing the rest.

**What happened**
1. My parsers assumed the indentation this tool writes. Rebuilt on
   kicad-tools' parser (`model.py`); it reads this board in 0.3 s and a
   6-layer, 2084-track demo in 2.5 s.
2. Path lengths check out against a careful human layout: the three USB pairs
   measured are matched to 0.02, 0.04 and 0.12 mm.
3. The return-path check found downstream pairs running up to 12.4 mm over
   gaps in the opposite pour. A finding about the board, recorded in the spec.
4. **First re-route of two nets added about 300 tracks to other nets.**
   kicad-tools' DSN export omits arcs, so every net with a curved track looked
   open and the router routed it again.
5. Freerouting saw "147 violations" in a board KiCad calls clean, and could
   not route a 3.4 mm crystal net in ten passes.
6. The re-routed track came back at 0.112 mm on a board whose minimum is
   0.15 mm; the baseline gate caught it as two new DRC findings.
7. `apply` run twice added the silkscreen text twice.

**Tool changes**
- `boardwright/existing.py`: `info`, `pads`, `nets`, `review`, `baseline`,
  `verify`, `apply`, `reroute`.
- Arcs are added to the DSN as fixed polylines.
- After routing, only the named nets' new copper is grafted onto the
  pre-routing file; everything else is byte-identical. A net the router fails
  on gets its original routing back. New tracks respect the project's
  `min_track_width`.
- `apply` drops exact duplicates, text included.
- Gate for existing boards: review passes and DRC has nothing new since the
  baseline.

**Result:** silkscreen text applied, `/LED3` re-routed, `/XI` attempted and
restored. DRC 0 before and after, review OK.

**Left open**
- Freerouting on a dense existing board is close to useless. `reroute` is safe
  now, not capable. Real edits to an existing layout will be hand `TRACKS`.
- Existing schematics cannot be edited.
- Zones are not shown to the router as copper, so it cannot rely on a pour
  for a connection.
