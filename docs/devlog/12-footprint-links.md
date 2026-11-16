# 12 footprint links: re-pointing and removing footprints on existing boards

**Reference:** a fleet of existing boards brought up to date by hand
(boardwright 0.4.1, KiCad 10.0.8): parts whose symbols and footprints pointed
at libraries that no longer exist, and logo art from one of those libraries.
`sch repoint` moved 77 parts on 5 boards onto stock symbols with every netlist
identical. The board side had no tool.

**What broke**
1. A module's footprint link pointed at a dead library. `sch set` fixed the
   schematic's field, but `existing update` refused the swap, and nothing else
   could change the board's `(footprint "LIB:NAME"` line. It was edited by
   hand after checking that the 40 pads matched the stock footprint (#37).
2. Two boards carried a graphic-only art footprint (no pads, no symbol) from
   that dead library. Nothing in `existing` could take a footprint off the
   board; it was cut out with a script (#38).
3. Checking the fix on KiCad's coldfire demo, `existing update` could not find
   `Connector_PinHeader_2.54mm`: the project's own `fp-lib-table` names it as
   `${KICAD10_FOOTPRINT_DIR}/...`, and the lookup passed the table row's type
   where it meant "symbol or footprint", so the stock folder was never
   substituted.

**Tool changes**
- `existing update` swaps a footprint the schematic changed when the new
  library footprint's pads are the board's: number, type, shape, position,
  angle, size, drill, layers. `--body keep` changes the link alone;
  `--body library` also takes the drawings, texts, 3D models and zones from
  the library (#37).
- `REMOVE` in `existing apply`, by reference or `LIB:NAME`, refusing a
  footprint wired to a net or linked to a symbol unless `--force` (#38).
- The library lookup substitutes the stock folder for `${KICAD*_..._DIR}` in a
  project's own table.

**How placed footprints were read.** The pad check and `--body library` need a
footprint as KiCad places it. Measured on KiCad 10.0.8's demo boards against
its stock library: a pad keeps its library position in the footprint's own
frame and its angle is absolute; on the back, y and the layers are mirrored
and the angle turns the other way. 581 of 589 placed footprints match this way;
the other 8 differ in size, shape or layers. Rebuilding each of the 581
drawings from the library gave KiCad's own text for 472. In every one sampled,
the stock library has changed since the demo was saved (line sets became
rectangles). Arcs swap their ends on the back, text is mirrored and kept
upright, and 3D models are copied as they are.

**Judged by KiCad** (DRC with `--schematic-parity`):
- pic_programmer, U4 linked to a dead library with an old silkscreen line:
  `lib_footprint_issues` before; `--body keep` left `lib_footprint_mismatch`
  (the same result as the hand edit); `--body library` left nothing. Parity
  was clean throughout.
- coldfire, six parts re-pointed (front at 90 and 180 degrees, back at 90, 180
  and 270, a header at 270) with `--body library`: 0 violations, as on the
  untouched board. One back-side line left unmirrored by hand made KiCad
  report `lib_footprint_mismatch` on that part, so the clean result is a check.
- Found afterwards (#41): none of the parts above has a footprint zone. On
  KiCad's Pico, whose antenna keep-out is one, `--body library` still left
  `lib_footprint_mismatch`. Every coordinate was written with Python's `:g`,
  which keeps six significant digits: the keep-out's 149.119895 became
  149.12. A Pico added the way `update` adds parts mismatched as well, at
  0 degrees. With 1 nm kept, a Pico added, one turned 180 degrees by `MOVE`
  to y = 157.1375, and an old copy swapped with `--body library` at 180
  degrees came out at 0 violations.
- pic_programmer with a grouped logo footprint over U4: `REMOVE` took away the
  logo's three findings (library not found, missing courtyard, silkscreen
  over copper) and nothing else changed; the group lost only the logo's uuid.
