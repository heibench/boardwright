# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (before 1.0, a minor version may change
the command line).

## [Unreleased]

### Added

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

- Generated boards now link each footprint to its symbol (`path`,
  `sheetname`, `sheetfile`), as KiCad does; kicad-tools wrote no link, so
  renaming a part in the schematic orphaned its placed footprint (#26). The
  example boards are linked. `existing update` adds the link when it matches
  a footprint by reference, like KiCad's re-link.
- `existing update` wrote a new footprint's `sheetname` as the sheet's name
  (`pic_sockets`); KiCad writes the sheet path (`/pic_sockets/`).
- `sch add` found a cached symbol only if `(symbol "LIB:NAME"` fit in the
  first 40 characters of its entry, so a long name such as
  `My_Connector_Library:1217861-1_Tab` was refused as not cached.
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

[Unreleased]: https://github.com/heibench/boardwright/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/heibench/boardwright/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/heibench/boardwright/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/heibench/boardwright/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/heibench/boardwright/releases/tag/v0.1.0
