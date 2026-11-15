# boardwright guide

Two ways in, one set of checks:

- **A new board** is described in `<dir>/board.py` and generated
  (`boardwright gen`). See "The loop".
- **A board that already exists** is worked on in place, nothing regenerated
  (`boardwright existing`, `boardwright sch`, `boardwright live`). See
  "First contact with a board you did not make".

Everything that reads a board (`pads`, preview, review) goes through
`boardwright/model.py`, which uses kicad-tools' parser and so reads any KiCad
board, hand-drawn or generated, any layer count, curved tracks included.

`boardwright doctor` says what this machine has for each step.

## The loop

1. **Read the vendor reference.** Datasheet typical application and layout
   section, or the vendor's hardware design guide. Note which values came from
   the document and which you chose.
2. **Look up pins and pads** rather than guessing:
   `boardwright pins Lib:Symbol [Lib:Footprint]`.
3. **Write `<dir>/board.py`** (options below). The examples in
   `examples/boards/` cover two- and four-layer boards, a buck converter, USB
   pairs, an RF module keep-out and a custom library.
4. **Place, look, repeat:** `boardwright place <dir>` stops before the
   autorouter: schematic, PCB, placement, hand copper, and `out/preview.png`
   (pads, hand tracks, ratsnest) in about five seconds and no KiCad call.
   Iterate here until placement and hand routes are right.
   `boardwright pads <dir>` prints every pad's position, net and layer.
5. **Generate:** `boardwright gen <dir>` does the same and then routes the
   rest with Freerouting and pours. Minutes on a dense board.
6. **The KiCad gate.** `boardwright check <dir>` runs ERC, netlist, DRC with
   schematic parity, fab outputs and plots through `kicad-cli`. `--quick` is
   DRC and copper plots only, enough while iterating. Run the whole gate
   before calling a board done.
7. **Verify:** `boardwright verify <dir>`. PASS needs ERC 0, DRC 0 at every
   severity (unconnected and parity included), KiCad's netlist equal to the
   declared circuit, the review clean, fab files present.
8. **Look at it.** `out/F_Cu.png` and `out/B_Cu.png` (copper, the only view
   that shows pours and polygons), `out/top.png`, `out/schematic.pdf`.

A board is not done until step 7 says PASS. PASS is not "works": it means
KiCad and the review found nothing, not that the board has been built.

## board.py

| Name | Meaning |
|------|---------|
| `NAME`, `W`, `H` | project name, board size in mm |
| `CIRCUIT` | `Circuit(title)`; `c.add(ref, "Lib:Symbol", value, "Lib:Footprint", {pin: net or None}, bom=True)`; `c.groups` lays the schematic out in blocks |
| `PLACE` | `ref -> (x, y, rot)` or `(x, y, rot, "B")`; or `pad_at(pad, target, dx, dy, rot or toward, side)` to put a named pad at a pin of a fixed part or at a point |
| `LIBS` | directories with your own `*.kicad_sym` / `*.pretty`, relative to the board dir |
| `LAYERS`, `PLANES` | `4` and `{"In1.Cu": "GND", "In2.Cu": "GND"}`; plane layers are closed to the autorouter |
| `CLASSES` | `{"Default": (clearance, track, via, drill), "Power": (..., [nets])}` |
| `RULES` | overrides for board minimums (`min_track_width`, ...) |
| `TRACKS` | hand routes, fixed before the autorouter: `(net, [(x, y), ...], width, layer)` |
| `VIAS` | `(net, x, y[, size, drill])`, fixed before the autorouter |
| `ZONES` | local copper polygons: `(net, layer, [(x, y), ...])`, solid, above the pour |
| `KEEPOUTS` | `(layers, [(x, y), ...])` no tracks, vias or pour |
| `POURS` | default `[("GND", ("F.Cu", "B.Cu"))]`; a third `True` makes pad connections solid |
| `TEXT` | silkscreen: `(string, x, y[, size, layer, rot])` |
| `REVIEW` | see `boardwright/review.py`: `near`, `maxlen`, `maxpath`, `match` (routed pad-to-pad paths equal within mm), `ref` (mm a net may run with no ground on the adjacent layer), `via_gnd`, `via_near` (a pad has a via of its own net within mm), `current` (a path carries amps: one pour piece that never narrows below the IPC-2221 width, or tracks that wide), `coverage`, `skew` |
| `FR_BOTTOM_COST` | makes the bottom layer expensive for the autorouter; 20 is the measured sweet spot (6 does nothing, 60 abandons nets) |
| `SEVERITIES` | per-board KiCad DRC severity override, with a written reason |
| `FR_PASSES`, `FR_TIMEOUT`, `FR_MARGIN`, `FR_ATTEMPTS`, `POUR_FIRST` | router knobs |

All coordinates are board-relative mm, origin top-left, y down.

## First contact with a board you did not make

Do these in order before changing anything. `P` is the project directory.

1. **Commit.** The board and schematic are edited in place; git is the undo.
   Work on a branch.
2. **Read what the repository says** about the board: its README, notes, any
   stated rules or constraints. Find out what the task is and what must not
   change.
3. **Inspect.** `boardwright existing P info` (layers, counts, pours,
   preview), `boardwright existing P nets PATTERN`, `boardwright sch P parts`.
   Look at `P/boardwright_out/preview.png`.
4. **Take the baselines** with KiCad, before any edit, into
   `P/boardwright_out/`: DRC with schematic parity to `drc.json`, then
   `boardwright existing P baseline`; ERC to `erc_before.json`; the
   connectivity with `netspec snap`. An existing design is rarely clean: from
   here on the question is what an edit added, not whether the count is zero.
5. **Write `P/boardwright.py`** with a `REVIEW` for what matters on this board
   (matched pairs, return paths, decoupling, current paths, pour coverage) and
   run `boardwright existing P review`. Report the findings as findings: do
   not fix what you were not asked to fix.
6. **Then work**, one change at a time: plan it as a spec, apply it (in place,
   or to the board open in KiCad as one undo step), read the result back, run
   the DRC, `verify`. For a schematic change, `netspec diff` must show the
   intended change and nothing else.
7. **Write down** what was asked, what was done, what the checks said, what
   was left.

What this tool does badly, so say so rather than try: re-routing in dense
areas, anything that needs existing tracks moved aside, length-tuned pairs,
adding a symbol the sheet does not already use, and carrying a schematic
change through to the board (that step is done in KiCad).

## Existing boards

    boardwright existing <project dir> info | pads [REF..] | nets [PATTERN]
    boardwright existing <project dir> review | baseline | verify
    boardwright existing <project dir> apply
    boardwright existing <project dir> reroute NET [NET ...]

The project keeps its own schematic, libraries and rules. An optional
`boardwright.py` beside the board holds `REVIEW`, `TRACKS`, `VIAS`, `ZONES`,
`KEEPOUTS`, `TEXT`, plus `MOVE = {ref: (x, y, rot)}` and `RIPUP = [nets]`.
Outputs go to `<project dir>/boardwright_out/`. The board file is edited in
place: commit before `apply` or `reroute`.

- `info` and the preview work with no KiCad call, on any size of board
  (a 6-layer, 2000-track demo board reads in 2.5 s).
- The gate for an existing board is **"review passes and DRC shows nothing
  that is not in the baseline"**, not "DRC is zero". Run the DRC into
  `boardwright_out/drc.json`, `baseline` once, then `verify` after every
  change.
- `reroute` rips up only the named nets, gives Freerouting everything else as
  fixed copper (curved tracks included, which kicad-tools' export omits), and
  afterwards keeps only the named nets' new copper: every other net is
  byte-identical to before. A net the router cannot finish gets its original
  routing back. New tracks are held to the project's own minimum width.
- `apply` is repeatable: exact duplicates are dropped.

`examples/existing/` holds specs for three of the demo projects that ship
with KiCad; its README says where to copy them from.

### Existing schematics

    boardwright sch <project dir> parts [PATTERN]
    boardwright sch <project dir> set REF Field=Value ...      # Value, Footprint, any property; dnp/in_bom/on_board
    boardwright sch <project dir> add SPEC.py                  # ADD = [(ref, like, value, footprint, {pin: net})]
    boardwright sch <project dir> remove REF ...
    boardwright sch <project dir> repoint OLD_LIB:OLD_NAME NEW_LIB:NEW_NAME [--body keep|library]
    boardwright sch ercdiff OLD.json NEW.json

Edits replace one block of the file and leave the rest byte-identical; the
file is written only if it is still what was read. A new part is a copy of a
part already on the sheet with the same symbol, put in an empty area with a
short wire from each pin to a label, or to a copy of the net's power symbol.

The check is KiCad's own connectivity: `netspec snap` before, `netspec diff`
after, and the difference must be the change you meant and nothing else.
`ercdiff` shows what an edit added to the ERC findings. After a schematic
change the board has to be updated from it in KiCad (parity will say so until
it is).

`repoint` changes which library symbol parts link to, for every part using
`OLD_LIB:OLD_NAME` on every sheet: a library renamed or vendored under a new
nickname, or a `<project>-rescue` library left by an older KiCad. `--body keep`
(the default) renames the cached symbol, its units and each part's link and
keeps the drawing; `--body library` replaces the cached symbol with the one in
the new library (an `extends` symbol is merged with its parent, as KiCad does).
The new symbol is looked up in the project's `sym-lib-table`, then KiCad's stock
libraries. Its pin numbers must be the same set as the cached symbol's, or the
edit is refused (exit 1) and nothing is written. A part carrying a `lib_name`
override is refused too.

On a sheet used more than once in a hierarchy, one symbol is a part in each
use: `parts` says which, `set` changes all of them and says so, `remove`
refuses.

Limits: `add` needs a part with the same symbol already present, works on
the root sheet, and draws only pin stubs. Nothing is moved or re-wired. A
schematic open in KiCad has to be closed and reopened to show the change.

## Live KiCad (the board that is open on screen)

    boardwright live status | snapshot | review [SPEC.py] | selection
    boardwright live select NET|REF ... | refill
    boardwright live apply SPEC.py|EDITS.json [--dry-run] [--save]
    boardwright edits SPEC.py BOARD.kicad_pcb OUT.json [PROJECT.kicad_pro]

Needs `pip install "boardwright[live]"` and KiCad 10 running with the PCB
editor open and Preferences > Plugins > Enable KiCad API switched on. It uses
KiCad's IPC API through kicad-python. `snapshot` writes the open board,
unsaved edits included, to `boardwright_out/live.kicad_pcb` without saving
anything in KiCad, so preview and review run on what is on screen.
`selection` reports what is selected in board-relative coordinates; `select`
selects items so you can see what a finding refers to. `apply` makes one
commit (one Ctrl+Z) from `MOVE`, `RIPUP`, `VIAS`, `TRACKS` and does not save
unless told to.

`boardwright selection SELECTION_FILE BOARD.kicad_pcb` describes KiCad's text
for a set of selected or copied items (footprints, loose pads, tracks, vias)
in board-relative coordinates, naming each part and pad.

An edit is carried as a plain **edit list** (`boardwright/edits.py`): ordered
operations `move_footprint`, `remove_routing`, `add_via`, `add_track` in the
board file's absolute mm. `boardwright edits` builds one from a spec, checking
every reference, net and layer against the board and refusing crossed hand
tracks; `boardwright live apply` executes one. Anything else that can reach
KiCad can execute the same file.

**Status (KiCad 10.0.8):** `status`, `snapshot`, `review`, `select` and an
earlier form of `apply` (one via, one track) ran against a board open in
KiCad and did what they say. An edit list holding all four operations,
executed by a separate client, was applied and read back correctly. `live
apply` has since been rewritten to execute edit lists and has not been run
against KiCad in that form; `live selection` and `refill` have never been
run against KiCad. `boardwright selection` was checked against two real
selections copied from KiCad 10.0.8. Limits found: the PCB editor must be open (the project manager
alone answers nothing); with the schematic editor open as well, KiCad refuses
a grouped commit from kicad-python 0.8.0, so the edit lands as separate undo
steps; the API gives no access to the interactive router.

To check an edited board that is open in KiCad: snapshot it,
`boardwright existing <project dir> stage SNAPSHOT`, run the DRC in the
staged folder, then `verify --staged` compares against the project's baseline.

## Routing a connection by intent

`ROUTES = [("U1.22", "Y1.1"), ("U1.5", "R9.2", {"layers": ["B.Cu"], "width": 0.15})]`
in a spec routes each pair pad to pad round the existing copper
(`boardwright/route.py`: a grid search with 45-degree moves, vias where a
through via clears every layer). Each route takes width, clearance and via
size from the net class the project assigns to its net, by explicit
assignment or by pattern; rules kept in a `.kicad_dru` file are not read.
Each result is an obstacle for the next; hand `TRACKS` and `VIAS` in the same
spec are obstacles too; nets in `RIPUP` are treated as already gone. It works
in `boardwright existing apply`, in `boardwright edits` and so in a live
edit. A connection it cannot make stops the whole edit.

It finds a legal path for one connection. It does not push other tracks
aside, tune length, or route a pair as a pair, and its pad shapes are plain
rectangles (rounded pads are treated as slightly larger than they are).

## Mid-speed signals

- `boardwright impedance` prints trace width and pair gap for a target
  impedance on a stackup (IPC-2141 closed form, about +-10 %). Confirm with
  the fab's calculator.
- `boardwright.si.pair(net_p, net_n, centreline, width, gap, layer)` returns
  the two `TRACKS` of a pair and its corner-induced skew.
- In `REVIEW`, `match` compares real routed path lengths pad to pad, vias
  counted; `ref` measures how far a net runs with no ground copper on the
  adjacent layer; `via_gnd` wants a ground via near each of its vias.

## What the example boards taught (details in `devlog/`)

- **DRC 0 is not a good board.** The autorouter will run a signal through a
  power polygon and leave the halves joined by a thin trace; KiCad accepts it.
  `verify` reviews for that. Declare `REVIEW` limits for what matters:
  decoupler-to-pin distance, crystal and feedback trace length, pair skew.
- **The bottom layer is a ground plane only if you defend it.** Left alone,
  the autorouter cut the STM32 board's bottom pour to 36% coverage in nine
  pieces. Set `FR_BOTTOM_COST` and a `REVIEW` coverage limit; `verify` prints
  the coverage of every whole-board pour.
- **Power is routed by hand.** Join every pad of a high-current loop with
  `TRACKS`, lay `ZONES` over them, stitch GND beside each return with `VIAS`,
  and leave only small signals to Freerouting. Do not hand polygons to the
  router as planes: it stops routing those nets and still crosses them.
- **KiCad is the only judge of connectivity.** Freerouting's "N unrouted" line
  is wrong once protected hand tracks exist.
- **The autorouter's result is not trusted to be complete.** After it runs,
  open connections are found from the copper and finished by the pad-to-pad
  router; if some are boxed in by the autorouter's own tracks, the build
  starts again with a slightly different bottom-layer cost (`FR_ATTEMPTS`,
  default 3) and keeps the first attempt with nothing open.
- **Read the vendor document; do not recall it.** `devlog/references.md`
  records which boards were checked. Reading changed one board in three.
- **Fine pitch needs fine rules.** 0.4 mm QFN or 0.5 mm LQFP on two layers:
  `CLASSES = {"Default": (0.15, 0.2, 0.6, 0.3), "Power": (0.15, 0.3, 0.6, 0.3, [nets])}`.
- **Decouplers go on the bottom, under the chip,** beside the pin pair they
  serve, when the top is full.
- **Route GND as traces, pour afterwards** (the default). Whole-board pours
  given to Freerouting as planes fragment into islands.
- Freerouting necks traces below the fab minimum; the driver widens them back
  and DRC checks the result.
- No-connect pads carry KiCad's `unconnected-(REF-PIN-PadN)` net name or
  parity fails; mechanical parts need `bom=False`.

## Pieces

- `circuit.py` schematic generation; `project.py` library vendoring and
  `.kicad_pro`; `board.py` placement and pours; `copper.py` hand copper and
  pad dump; `review.py` engineering review; `verify.py` netlist == intent;
  `build.py` driver (`gen`, `place`, `pads`, `verify`); `check.py` the KiCad
  gate; `pins.py` symbol/footprint lookup; `env.py` where KiCad, its
  libraries and Freerouting are.
- `model.py` board reader (pads, tracks incl. arcs, vias, zones, routed path
  lengths); `placement.py` `pad_at` solver; `preview.py` instant picture and
  ratsnest; `route.py` pad-to-pad router; `edits.py` edit lists; `live.py`
  KiCad's IPC API; `selection.py` selection text; `si.py` impedance and
  pairs; `existing.py` in-place work on an existing board; `sch.py` in-place
  edits to an existing schematic.
- kicad-tools (pinned) does PCB file plumbing, DSN export and SES import.
  Freerouting routes. netspec finds `kicad-cli`.
