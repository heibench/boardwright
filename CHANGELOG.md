# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (before 1.0, a minor version may change
the command line).

## [Unreleased]

### Changed
- `existing update`, when it cannot export the netlist (no working kicad-cli,
  or the export fails), says how to pass one exported elsewhere:
  `existing DIR update NETLIST.net` (#144).

## [0.11.0] - 2026-11-21

### Added
- `REVIEW` `apart` (`(QUIET, NOISY, mm)`, a net or a list of nets each): the
  quiet nets' pads, tracks and vias keep mm from the noisy nets' copper,
  pours included, edge to edge on the same and adjacent layers (TI SNVA021:
  feedback away from the switch node). Two pads of one part are left out.
- `REVIEW` `clear_under` (`(REF, mm)`): no track or via of a net other than
  the part's own and ground crosses its courtyard grown by mm, on any layer
  (no traces under a crystal). Pours do not count.
- Either fails as "cannot judge" on a side with no copper or a part with no
  courtyard (#125).

### Changed
- The preview draws each pour as the fill KiCad last saved, under its dashed
  outline, and dims and italicises the label of a part whose reference does
  not print, so a reviewer does not take it for silkscreen (#136).
- `existing reroute` refuses a named net with a track wider than its net class
  (exit 1, nothing changed), naming each one: the router would put it back at
  the class width. `--force` reroutes it anyway (#137).

### Fixed
- The preview's ratsnest (and the unrouted count in `existing info`, `gen` and
  `reroute`) judges connectivity as KiCad does: copper on a shared layer that
  touches, a track's end or body. A track ending off a pad's centre is no
  longer an open, and tracks on different layers meeting without a via no
  longer count as joined (#134).
- `existing apply` checks MOVE for clashes on the board as it will be written,
  after RIPUP from the same file, so a part moved into copper being ripped up
  no longer needs `--force` (#135).

## [0.10.0] - 2026-11-21

### Added
- `REVIEW = {"fab": "jlcpcb"}` (or `"oshpark"`, `"pcbway"`): `verify` checks
  the board's tracks, vias, plated holes and the project's clearance and
  copper-to-edge rules against that fab's published minimum for the board's
  layer count and copper weight (`fab_copper_oz`, default 1). Each limit is
  quoted from the fab's own page with its URL, read 2026-11-21. Below the
  minimum fails; below the standard-price limit is reported and does not
  fail; a value the fab has limits for, but none at this board's layers and
  copper, fails as "cannot judge" (#49).
- `REVIEW` `loop` (`(CAP, PIN, mm)`): after routing, each of a decoupler's
  ground pads, and its pad on PIN's net when that net has a pour, must reach
  a via of its own net within mm of copper, along its tracks or across the
  pour fill it sits in. Where PIN's net has a pour, PIN must reach the
  capacitor by tracks and vias before any plane via off that path: a pin fed
  through the plane first fails. A via shared with a cap on the back is on
  the way. A cap with no ground pad fails as "cannot judge" (#122).
- `boardwright impedance` knows JLCPCB's 6-layer stackups JLC06161H-3313,
  -7628, -1080 and -2116, and OSH Park's 4-layer one (#49).

### Fixed
- Routed path lengths (`REVIEW` `maxpath` and `match`) raised TypeError on a
  net with a through-hole pad (#129).

## [0.9.0] - 2026-11-21

### Added

- Placement checks as `REVIEW` keys, run by `place` (which now exits 1 on a
  finding) and by `verify`: `orient` (a decoupler's ground pad not facing its
  pin), `balance` (a crystal's two gaps), `fronts` (a clear channel out of
  each signal pin, past parts that do not connect to it), `via_site` (room for
  a via near a pad) and `chain` (an RF shunt's node pad on the series path).
  A check with nothing to judge fails and says so rather than passing (#47).
- An agent skill, `skills/boardwright/SKILL.md`: when boardwright applies, the
  new-board loop to `verify` PASS, first contact with a board someone else
  made, live editing, and placement guidance adapted from kistack's
  layout-placement skill (MIT, with its notice). It ships in the package;
  `boardwright --docs` prints the directory that holds it (#48).
- `live revert` takes back boardwright's own last unsaved `live apply`, and
  nothing else. It refuses (exit 1, nothing changed) unless the open board is
  exactly what that apply left, the file is unchanged, and nothing was unsaved
  before the apply, since KiCad's revert drops every unsaved change (#94).

## [0.8.6] - 2026-11-21

### Fixed

- `existing apply` is repeatable for `TEXT`, `ZONES` and `KEEPOUTS` too. A
  second run added every zone and keepout again (2 zones, then 4, then 6),
  and a text again once KiCad had saved the board, which writes `113` for
  `113.0`. Items are now compared by what they are: string, position and
  layer for text; net, layers, outline and keepout rules for a zone (#113).

## [0.8.5] - 2026-11-20

### Fixed

- `existing reroute` keeps signals off inner plane layers, those holding a
  zone and no track, by switching them off for Freerouting as `build` does for
  `PLANES`; `PLANES` in `boardwright.py` replaces the list. It routed through
  them and cut the planes (#106).

### Changed

- `existing reroute` refuses (exit 1) and leaves the board as it was read when
  the router cannot finish a named net. It put that net's old copper back on
  top of the other named nets' new routes, which shorted on stm32f103_4l
  (#106).

## [0.8.4] - 2026-11-20

### Fixed

- `existing reroute` leaves the board as it was read when the route cannot
  run, and exits 4 with the reason. It wrote the named nets' rip-up first and
  left it there when Freerouting gave no SES; on a timeout it also said
  "nothing was checked or written as a result" (#104).
- The DSN export refuses a board whose Edge.Cuts outline does not close
  within 1 um, naming the open ends. It wrote a DSN with no boundary, which
  Freerouting 2.5.0 fails on with a NullPointerException (#105).
- `existing apply` refuses a `VIAS` entry that is not
  `(net, x, y[, size, drill])` with exit 64 before changing anything. A nested
  `("NET", (x, y))` crashed with an IndexError, exit 2, after the rip-up and
  moves were written (#107).
- `sch add` takes a net named the way KiCad's netlist names a local label,
  with the sheet path in front (`/LED_A`), as that label. It wrote a new
  label `/LED_A`, which KiCad kept on a net of its own. Any other name with a
  `/` in it is refused (exit 64), naming the sheet's local labels (#102).

## [0.8.3] - 2026-11-20

### Fixed

- `existing update` sets or clears each footprint's `dnp` and
  `exclude_from_bom` attributes from its symbol, as KiCad's Update PCB does,
  leaving its other attributes as they are. They were never read, so KiCad's
  schematic parity check reported "'Do not populate' settings differ" and
  "'Exclude from bill of materials' settings differ" (#98).
- `sch add` with a library symbol no longer stops with a traceback (exit 2)
  when the sheet's first placed part has no pins: it takes its pin format
  from a part that has one. A sheet with none refuses the library part with a
  message (exit 1); copying an existing part still works there (#99).

## [0.8.2] - 2026-11-20

### Fixed

- `existing update` copies each symbol's datasheet, description and user
  fields onto its footprint, added, swapped or matched, as KiCad's Update PCB
  does. Added footprints had only what their library footprint had, so KiCad's
  schematic parity check reported `footprint_symbol_field_mismatch` on each
  one with a field set (#95).
- `live apply --save` refuses (exit 1) when the board open in KiCad has edits
  that are not in its file, naming them, instead of saving them along with
  its own. Nothing is changed. The board and file are compared item by item:
  KiCad 10.0.8 writes an unchanged board differently from the file it
  loaded, so a byte comparison would refuse every board (#46).
- `existing apply`, `reroute`, `update` and the `sch` edits warn when KiCad
  has the file open (its `~<name>.lck` beside it), since KiCad's next save
  of it overwrites the edit (#46).
- A file or folder boardwright cannot read or write, such as a read-only
  `boardwright_out` next to the board, now exits 4 with one line naming it.
  It exited 2 with a traceback and "internal error". Seen on `live apply`'s
  snapshot; `existing DIR info` and `preview` reached the same handler (#86).

## [0.8.1] - 2026-11-19

### Fixed

- `existing reroute` and `gen` no longer stop with `via padstack '…' is not
  in the session's library_out`. Freerouting gives the board's own vias
  back as protected copper under the DSN's padstack names, which the
  session's `library_out` need not list; those vias are now left out when
  the session is read, as both commands already left them out of the board
  (#77).

## [0.8.0] - 2026-11-18

### Changed

- `place` and `gen` place footprints by editing each footprint's own block
  instead of loading and re-saving the whole board through kicad-tools' `PCB`.
  Moving a footprint, turning it over onto the back and putting a no-connect
  pad on its net each replace only that footprint's block; a net the board
  does not list yet is added to its net list. A back-side footprint now keeps
  its place in the file instead of moving to the end, and angles are written
  in (-180, 180] (`-90`, not `270`), as `existing apply` writes them (#55).
- `gen` and `existing reroute` read Freerouting's session themselves instead
  of running kicad-tools' `pcb import-ses`, and add only its tracks and vias
  to the board. `gen` leaves out what it used to remove afterwards (the
  protected copper the session gives back, dangling vias and stubs) and
  widens tracks below the minimum width as it adds them; copper already on
  the board is no longer touched by that clean-up (#56).
- `place` and `gen` create the board themselves instead of running
  kicad-tools' `create-pcb`: the same outline, layers, 4-layer stackup,
  footprints and nets. Each footprint is taken from the project's library as
  `existing update` adds one, with fresh uuids (kicad-tools gave every copy
  of a footprint the library's), and waits at the sheet origin until it is
  placed. The nets come from the circuit, so the board no longer depends on
  whether kicad-tools found a working kicad-cli, and a no-connect pad no
  longer leaves an unused `Net-(REF-PIN)` entry in the net list (#57).
- `place`, `gen` and `pins` read symbols from the libraries themselves, and
  `place` and `gen` write the schematic themselves instead of through
  kicad-tools' `Schematic`. Everything outside the symbol cache is the
  same as before, byte for byte, uuids included. The cache now holds each
  symbol as its library writes it, as `sch add` does, rather than in
  kicad-tools' layout, and a symbol that extends another keeps its parent's
  order and one `embedded_fonts` (kicad-tools wrote it twice) (#59).
- `gen` places reference text itself instead of running kicad-tools'
  `place-silk-refs --allow-rotate`, which saved the whole board through
  kicad-tools (2,388 changed lines on rp2040_min, formatting only). The
  placement is the same, ported from kicad-tools: on every example the
  references land where the command put them. Only the `(at ...)` of
  each moved reference changes now; the rest of the file stays as it was
  (#54).
- `gen` and `existing reroute` write the DSN for Freerouting themselves
  instead of running kicad-tools' `pcb export-dsn`. For the example boards
  it is the same file but for its `host_version`, and curved tracks go in
  with the rest of the fixed copper instead of being added afterwards.
  Every signal, power and mixed copper layer goes in, front to back, where
  kicad-tools left out the layers past In6.Cu; KiCad 10's jumper layers
  stay out. An Edge.Cuts arc or circle is still cut into chords within
  0.1 um of it, at different points (#60).
- Boards are read by boardwright's own reader instead of kicad-tools'
  parser. On every committed board and 17 of KiCad 10's demos it reads the
  same footprints, pads, tracks, vias, zones, outline and board origin as
  before. Boards saved by KiCad 6 to 10 are read, and KiCad 8, 9 and 10
  files are tested. A board saved by a newer KiCad is read as KiCad 10
  would read it, with a note on stderr; one saved by KiCad 5 or older,
  which kicad-tools read, is not read yet and exits 4 (#78). The board origin, which
  every board-relative coordinate is measured from, is unchanged and now
  written down in the guide. Copper layers of KiCad's `mixed` type count
  as copper, as `dsn.py` already counted them (#58).

### Removed

- The kicad-tools dependency. Nothing in boardwright uses it any more:
  the board reader, footprint placement, the board skeleton, the
  schematic writer, the SES import, the DSN export and reference text
  placement are all boardwright's own. Installing boardwright no longer
  brings in kicad-tools, pydantic, rich or rtree, and `doctor` has no
  kicad-tools row (#58, #60, #61).
- `PREROUTE(pcb)`, which handed a board's spec the kicad-tools board object
  before routing. No example used it; hand copper goes in `TRACKS` and
  `VIAS` (#55).

### Fixed

- A board with a copper arc whose three points lie on a line, or a file
  that is not a board, no longer stops a command with an internal error
  (exit 2): the arc is read as a straight track, and the file is refused
  as unreadable (exit 4) (#58).
- `existing reroute` no longer leaves a `<board>.dsn-revision.json` in the
  project folder; kicad-tools' export wrote it beside the board (#60).
- Footprint zones (an RF module's antenna keep-out) are placed in board
  coordinates as each footprint is placed. kicad-tools' create-pcb leaves them
  in the library's coordinates; `board.place_footprint_zones`, which patched
  them after placement, is gone (#55, #36).
- A board with `LIBS` no longer leaves `KICAD_SYMBOL_DIR` and
  `KICAD_FOOTPRINT_DIR` pointing at its merged library view after the
  command: the next board placed in the same Python process used that
  board's libraries, or failed once its `.libmerge` was gone (#69).

## [0.7.0] - 2026-11-17

### Added

- `live open BOARD` starts the PCB editor on BOARD, detached, and waits up to
  60 s (chosen, not measured) until a running KiCad answers with it open; a
  board already open starts nothing. KiCad 10's API cannot open a document.
  The editor is found as kicad-cli is, or set in `BOARDWRIGHT_PCBNEW`. The
  Flatpak editor is not started while another `api-*.sock` exists, since its
  namespaced pid may repeat (#62).

### Fixed

- On Windows, kicad-cli, pcbnew and KiCad's libraries are taken from the newest KiCad version folder first; `9.0` was tried before `10.0`.
- `BOARDWRIGHT_KICAD_CLI` with an unbalanced quote stopped with a Python
  traceback; it is now exit 4 naming the variable.

## [0.6.0] - 2026-11-17

### Added

- `live --board FILE` picks the running KiCad that has FILE open. A second
  KiCad gets `api-<pid>.sock`, and kicad-python's default socket reached a
  board-less project manager instead of the editor. Every socket in KiCad's
  Flatpak and native socket folders is asked; none with the board is exit 4,
  more than one is exit 1. Connecting retries KiCad's "not ready" reply for up
  to 30 s (#62).

### Changed

- boardwright no longer depends on kicad-netspec; it finds kicad-cli itself,
  on PATH, in Flatpak or in KiCad's install places, or as set in
  `BOARDWRIGHT_KICAD_CLI`.

### Fixed

- `existing verify` reported a baseline DRC finding as new when only a
  track's length had changed: KiCad writes `length X mm` into the item's
  description, and findings were matched on the full text. The length is now
  left out of the match (#44).
- `live apply --save` saved the board without refilling zones, so a part
  moved into a pour kept stale fill over its pads until `live refill`. It now
  refills before saving when the edit moved, removed or added copper (#45).
- `live refill`, `live review` and `live snapshot --refill` could hang
  forever on a KiCad that stayed busy: kicad-python 0.8.0's
  `Board.refill_zones` never counts its polls. boardwright now polls itself,
  every 0.5 s for at most 30 s, and then stops with exit 4 (#45).

## [0.5.1] - 2026-11-15

### Fixed

- Coordinates boardwright wrote were rounded to six significant digits, so
  any figure of 100 mm or more lost its fourth decimal and beyond: a
  footprint zone point at 149.119895 became 149.12. KiCad then reported
  `lib_footprint_mismatch` on a footprint `existing update` had added or
  swapped with `--body library` (KiCad's Raspberry Pi Pico, with its antenna
  keep-out, was one). `MOVE` wrote a position such as 157.1375 as 157.138.
  Board and schematic coordinates now keep KiCad's 1 nm (#41).

## [0.5.0] - 2026-11-15

### Added

- `existing update` swaps a footprint the schematic changed, when the new
  library footprint's pads are the same as the board's (number, type, shape,
  position, angle, size, drill, layers). `--body keep` (the default) changes
  the library link alone; `--body library` also takes the drawing from the
  library. A swap to a footprint whose pads differ is still refused, now with
  the differences listed (#37).
- `REMOVE = ["G***", "LIB:NAME"]` in `existing apply` takes footprints off the
  board, by reference or library name. One with a pad on a net or a schematic
  symbol is refused unless `--force` (#38).

### Fixed

- A library a project's own table names through `${KICAD10_FOOTPRINT_DIR}` or
  `${KICAD10_SYMBOL_DIR}` (as KiCad's demo projects do) was reported as not
  found by `existing update`, `sch add` and `sch repoint` unless the variable
  was set in the environment. It now means the stock folder that was found.

## [0.4.1] - 2026-11-15

### Fixed

- `existing apply` saved a `MOVE` through kicad-tools, which rewrote the whole
  board file (a four-part move: +198 / -5507 lines, nothing lost). A move now
  edits only the moved footprints' blocks: position, the absolute angles of
  their pads and texts, and their own zones (#32).

## [0.4.0] - 2026-11-15

### Added

- A `MOVE` entry can place the part's reference and value text:
  `{"R10": (25, 25, 270, {"ref": (25.2, 27.4, 0)})}` (#25).
- `existing apply` checks each part `MOVE` moves (pads against other nets'
  copper and the board edge, courtyard against courtyards) and writes
  nothing on a clash unless given `--force`; `existing free REF [near PAD]`
  lists clear spots for a part (#24).
- `existing update`: carry schematic changes to the board, as KiCad's
  Update PCB from Schematic does, from KiCad's own netlist (the last part of
  #3). New parts land beside the board on their nets; references, values
  and pad nets follow the schematic; a footprint swap, a missing footprint
  or a symbol without one stops it with nothing written. Checked by KiCad's
  DRC schematic parity.
- `sch add` adds on a sub-sheet used once: `SHEET = "file.kicad_sch"` in
  the spec (part of #3). Parts take the sheet's hierarchy path; sheet-pin nets
  get hierarchical labels; power symbols are copied from whichever sheet has
  one; a net local to another sheet is refused. References are checked across
  every sheet, not only the root.
- `sch add` and `sch repoint` find a library in KiCad's global
  `sym-lib-table` too, after the project's: its path variables (Preferences >
  Configure Paths, or the environment) are filled in and tables nested in it
  are followed. `KICAD_CONFIG_HOME` names KiCad's settings folder; otherwise
  the newest one in the usual places is used.
- `sch add` takes a library symbol `LIB:NAME` as `like`, so a part can be
  added whose symbol the schematic does not use yet (part of #3). Its pins
  are labelled with the kind of label each net already uses, so `add` now
  also works on sheets connected by global labels, such as generated ones.

### Changed

- `sch add` sizes the free area from each part's pins and labels instead of
  a fixed 12.7 mm per part, keeps 20 mm from the sheet edge, and turns each
  power symbol to point away from the part it connects (a +3V3 on a pin that
  faces down used to be drawn over the part).

### Fixed

- Pad-to-pad routes that share a pad no longer stack a via each at it, 0 to
  0.3 mm apart (KiCad's `hole_to_hole`): a route changes layer on its own
  net's existing via or through-hole pad without adding one (#23).
- A preview (`place`, `existing apply`, `existing info`) crashed with exit 2
  after the board was written when `rsvg-convert` was not installed; it now
  stays SVG, as `doctor` says.
- Generated boards now link each footprint to its symbol (`path`,
  `sheetname`, `sheetfile`), as KiCad does; kicad-tools wrote no link, so
  renaming a part in the schematic orphaned its placed footprint (#26). The
  example boards are linked. `existing update` adds the link when it matches
  a footprint by reference, like KiCad's re-link.
- `sch add` found a cached symbol only if `(symbol "LIB:NAME"` fit in the
  first 40 characters of its entry, so a long name such as
  `My_Connector_Library:1217861-1_Tab` was refused as not cached.
- The STM32F103 examples (`stm32f103_min`, `stm32f103_4l`) take 100 nF on
  VDDA, as ST AN2586 Rev 8 section 2.2 asks; they had 10 nF, written from
  memory (#6). Every example's reference document has now been read.
- `live status` names the open board by its full path, and `live apply`
  prints that path before it edits, so two copies of a board with the
  same file name can be told apart (#17).

## [0.3.1] - 2026-11-15

### Fixed

- `sch repoint --body keep` onto a symbol the schematic already caches now
  also compares the cached copy's pin numbers with the library's, and refuses
  when they differ; it used to move parts onto a stale cached copy silently.

## [0.3.0] - 2026-11-15

### Added

- `boardwright sch DIR repoint OLD_LIB:OLD_NAME NEW_LIB:NEW_NAME [--body keep|library]`
  points every part that uses one library symbol at another, across all
  sheets, and refuses when the pin numbers differ (#8).

### Changed

- The `current` review measures how narrow a pour gets between the two pads
  and fails a pour that necks below the IPC-2221 width, instead of accepting
  any single piece. Parallel channels are not added together, so a pad fed
  through thermal spokes measures as one spoke (#5).

### Fixed

- A footprint's own zones (an RF module's antenna keep-out) were left in the
  library's coordinates when kicad-tools created the board, so they sat beside
  the part and KiCad reported the footprint as differing from its library.
  They are now placed with the footprint; KiCad accepts the result at 0, 90
  and 180 degrees on top and 0 and 90 on the bottom. The ESP32-C3 example no
  longer ignores that check (#6; upstream rjwalters/kicad-tools#8958).
- The LDO example's output capacitor is a 22 uF tantalum, as the AMS1117
  datasheet asks for stability; it was a ceramic (#6).

## [0.2.0] - 2026-11-14

### Changed

- Exit codes follow the heibench contract: `2` when a check cannot be
  decided (`verify` with KiCad's reports missing or stale, which used to exit
  `1`), `4` for an environment fault (KiCad, its libraries or Freerouting
  missing or failing, which used to exit `1`), and `64` for usage errors
  (which used to exit `1`, or `2` for an unknown command). An unexpected
  error exits `2` instead of `1`.

### Added

- A documentation site at https://heibench.com/boardwright/.

## [0.1.0] - 2026-11-14

First public release.

### Added

- `boardwright place | gen | check | verify | pads` for boards described in a
  `board.py`: schematic generation, placement (fixed or by pad intent with
  `pad_at`), hand copper (`TRACKS`, `VIAS`, `ZONES`, `KEEPOUTS`, `TEXT`),
  Freerouting with a bottom-layer cost and plane layers closed to it, a
  pad-to-pad completion pass, pours, and a KiCad gate (ERC, DRC at every
  severity with schematic parity, netlist, gerbers, drill, BOM, placement,
  PDF, plots).
- An engineering review beyond DRC (`REVIEW`): pad distances, net and path
  lengths, pair matching with vias counted, reference-plane runs, ground vias
  beside signal vias, pour coverage and continuity, current capacity per
  IPC-2221.
- `boardwright existing` for boards the tool did not make: inspection and
  preview of any size of board, review, DRC compared with a baseline, in-place
  edits (move, rip-up, routes by intent, hand copper), and re-routing of named
  nets that leaves every other net byte-identical.
- `boardwright sch` for schematics: list parts, set fields, remove parts, add
  a part by copying one with the same symbol, across hierarchical sheets;
  `ercdiff` for ERC reports.
- `boardwright live` for the board open in KiCad 10 through its IPC API
  (optional `[live]` extra), and `boardwright edits` / `selection` for plain
  edit lists and KiCad's selection text.
- `boardwright impedance` (IPC-2141 closed form) and `doctor`.
- Seven example boards and specs for KiCad's own demo projects.

[Unreleased]: https://github.com/heibench/boardwright/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/heibench/boardwright/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/heibench/boardwright/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/heibench/boardwright/compare/v0.8.6...v0.9.0
[0.8.6]: https://github.com/heibench/boardwright/compare/v0.8.5...v0.8.6
[0.8.5]: https://github.com/heibench/boardwright/compare/v0.8.4...v0.8.5
[0.8.4]: https://github.com/heibench/boardwright/compare/v0.8.3...v0.8.4
[0.8.3]: https://github.com/heibench/boardwright/compare/v0.8.2...v0.8.3
[0.8.2]: https://github.com/heibench/boardwright/compare/v0.8.1...v0.8.2
[0.8.1]: https://github.com/heibench/boardwright/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/heibench/boardwright/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/heibench/boardwright/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/heibench/boardwright/compare/v0.5.1...v0.6.0
[0.5.1]: https://github.com/heibench/boardwright/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/heibench/boardwright/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/heibench/boardwright/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/heibench/boardwright/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/heibench/boardwright/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/heibench/boardwright/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/heibench/boardwright/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/heibench/boardwright/releases/tag/v0.1.0
