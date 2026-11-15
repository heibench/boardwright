# Tool gaps (most painful first)

## Open

- **Live KiCad saves without refilling.** `live apply --save` writes the
  board as it is; a part moved into a pour keeps stale fill over its pads
  until `live refill`. The API gives no access to the interactive router.
- **Text is placed by hand.** `existing free` finds room for a part's copper
  and courtyard, not for its silkscreen; a `MOVE` can place the reference and
  value, but where is your call (11).
- **Freerouting is the weak link.** Not repeatable on dense boards; ignores
  polygons; necks tracks; its log names nets as unrouted that are routed; on
  an existing dense board it could not route a 3.4 mm net. Worth trying:
  its job/API mode and the Topola router.
- **Schematic editing is narrow.** `boardwright.sch` changes fields, removes
  parts and adds a part, copied from one on the sheet or taken from a library
  (single-unit only), on the root or a sheet used once, connected by label or
  power symbol (09). It does not wire point to point or add sheet pins.
  `existing update` carries a change to the board but does not swap
  footprints or remove footprints whose symbol is gone; what it adds lands
  beside the board for `free` and `MOVE`.
- **The pad-to-pad router is new and narrow.** It routed two nets on the
  StickHub demo (one that Freerouting could not), applied live and DRC-clean
  against the baseline, and five of six layer-changing nets on a 6-layer demo
  by its own clearance measure (10), and the four connections of the 4-layer
  rehearsal with vias, judged clean by KiCad (11). Rules in a `.kicad_dru`
  file are not read. No push-aside, no pairs, no length tuning; multi-pad
  nets are routed as the pairs you list.
- **Alternatives to Freerouting were not tried.** Its job mode and the
  Topola router both need installing or configuring, which is a decision
  about the machine, not this tool.
- **`si.pair` and the impedance numbers have not been used on a real board.**
  Stackup figures are from memory of the fabs' tables.
- **02's bottom pour stays in five pieces (78 %).** Tried `FR_BOTTOM_COST = 20`
  on it in a throwaway copy: three attempts left 19, 8 and 1 connections
  open; the completion pass finished two of them. A 0.4 mm QFN-56 on two
  layers needs the bottom layer for its escape. The honest fix is four layers.
- **The completion pass is slow.** It is capped at 12 open connections and 90
  seconds; before the cap it ground for seven minutes on a board with 19 open.
- One flat schematic sheet, label-per-pin, for generated boards.
- No current or thermal sizing of copper.
- No part sourcing. Konnect's approach: the JLC parts feed in local SQLite
  and rule-based footprint-to-package matching.
- Boards 01-05 pass with the current tool's checks but were last generated
  before the staging refactor. 03 was regenerated in a throwaway copy
  afterwards and came out DRC-clean and equivalent.

## Closed

- Live apply, selection, refill, move, rip-up and save not run against KiCad -> all run on KiCad 10.0.8 (#4).
- Parts moved onto other copper without a word -> `apply`'s clash check, `existing free` (11, #24).
- Stacked vias from routes sharing a pad -> routes reuse their net's through copper (11, #23).
- No way to move a footprint's text -> `MOVE` text placement (11, #25).
- Generated boards unlinked from their symbols -> `gen` and `update` link them (11, #26).
- `MOVE` rewrote the board file -> moved blocks edited in place (11, #32).
- Schematic adds only by copying, root sheet only, no way to the board -> library symbols, global tables, sub-sheets, `existing update` (#3).
- ESP32 footprint warning: the module's keep-out zone was left beside the part -> `board.place_footprint_zones` (05, #6).
- Pour necks not measured by the current check -> `review.neck` (#5).
- Pours invisible in renders -> copper plots (03).
- Legal-but-split power polygons -> review (03).
- Hand routing, vias, polygons, keep-outs, silkscreen text -> `copper.py` (03, 05).
- Length figures doubled by duplicate segments -> de-duplication (04).
- Crossed hand tracks -> `check_tracks` (05).
- Autorouter stubs and dangling vias -> removed after routing (04).
- Starved thermal reliefs that moved every run -> one spoke suffices (04).
- Bottom pours shredded by the autorouter -> coverage review, `FR_BOTTOM_COST` (04, 05).
- Skew as total copper -> `match` on routed pad-to-pad paths (06).
- Stock libraries only -> `LIBS` (08).
- Two layers only -> `LAYERS`, `PLANES` (06).
- No return-path check -> `ref`, `via_gnd` (06).
- Orientation found after the fact -> `pad_at` (06).
- Minutes per look -> `place` + preview, 5 s (06).
- Generated boards only -> `boardwright.existing` (07).
- Hand routes as typed coordinates -> `ROUTES`, pad to pad (07).
- Autorouter leaving random nets open -> completion pass and retry (06).
- Decouplers with no via of their own -> `via_near`, hand ground vias (06).
- No current sizing -> `current`, per path, IPC-2221 (03).
- Values from memory -> every board and the stackups read from the documents (`references.md`).
- No check of an edited live board -> `stage` and `verify --staged` (07).
