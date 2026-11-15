# 11 rehearsal: a 4-layer board as if someone else drew it

**Reference:** `examples/boards/stm32f103_4l` (06), copied without its
`board.py`, so the only way in was `boardwright existing` and `boardwright sch`,
as on a board drawn in KiCad. The change: I2C pull-ups, 4.7 kohm 0402, R10 on
PB6 and R11 on PB7, to +3V3, beside the right-hand header.

**Stresses:** the whole existing-board loop on four layers, start to finish:
schematic edit, carry it to the board, place, route, text, DRC, verify.
KiCad 10.0.8 judged each step (`kicad-cli` through the session's wrapper).

**What broke**
1. Placing by eye. `MOVE` put R10 and R11 beside J3 on top of PB7 and PB8
   tracks and inside SW2's courtyard; `apply` said nothing; DRC found 16
   violations, three of them shorts (#24).
2. Two `ROUTES` from R11.1 each dropped a +3V3 via at the same point,
   0.01 mm apart: `hole_to_hole`. It came back with a clean placement too (#23).
3. With copper clean, R10's reference sat over J3's silkscreen, and nothing in
   the tool could move a footprint's text: `verify` NOT DONE on 4 silkscreen
   findings (#25).
4. Generated boards carry no footprint-to-symbol link; renaming R1 to R12 in
   the schematic made `update` add a new R12 and orphan the routed R1 (#26).
5. `MOVE` saved through kicad-tools and rewrote the file: a four-part move,
   +198 / -5507 lines, nothing lost (#32).
6. The connectivity check the guide names, `netspec snap` / `netspec diff`,
   could not reach KiCad from the session; the netlists were compared from
   KiCad's own export instead. That is the machine's limit, not this tool's.

**Tool changes**
- `existing apply` checks every moved part (pads against other nets' copper
  and the edge, courtyard against courtyards, real pad shapes) and writes
  nothing on a clash; `existing free REF [near PAD]` lists clear spots.
- Routes change layer on their own net's via or through-hole pad instead of
  adding one.
- A `MOVE` entry can place the part's reference and value text.
- `gen` links footprints to symbols; `existing update` links what it matches
  by reference.
- `MOVE` edits only the moved footprints' blocks.
- On the way: previews crashed without `rsvg-convert` (now SVG), and
  `update` wrote a sub-sheet part's `sheetname` wrongly.

**Result:** schematic netlist changed by exactly R10.1/R11.1 on +3V3, R10.2 on
PB6, R11.2 on PB7; ERC 0. After `update`, `free`, `MOVE`, four `ROUTES` (7 vias,
one shared) and the text move: DRC at every severity 0 violations,
0 unconnected, 0 parity issues; `existing verify` PASS against the baseline.

**Left open**
- Text placement is by hand: `free` finds room for copper and courtyards, not
  for silkscreen. The first spot tried for R10's reference overlapped SW2.
- `live apply --save` saves without refilling: a part moved into a pour
  keeps stale fill over its pads until `live refill`.
