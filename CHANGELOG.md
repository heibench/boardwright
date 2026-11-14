# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (before 1.0, a minor version may change
the command line).

## [Unreleased]

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

[Unreleased]: https://github.com/heibench/boardwright/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/heibench/boardwright/releases/tag/v0.1.0
