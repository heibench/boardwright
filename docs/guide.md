# boardwright guide

Two ways in, one set of checks:

- **A new board** is described in `<dir>/board.py` and generated
  (`boardwright gen`). See "The loop".
- **A board that already exists** is worked on in place, nothing regenerated
  (`boardwright existing`, `boardwright sch`, `boardwright live`). See
  "First contact with a board you did not make".

Everything that reads a board (`pads`, preview, review) goes through
`boardwright/model.py`, which reads any KiCad board, hand-drawn or generated,
any layer count, curved tracks included. Boards saved by KiCad 6 to 10 are
read; KiCad 8, 9 and 10 files are tested. A board saved by a KiCad newer
than 10 is read as KiCad 10 would read it, with a note; one saved by KiCad 5
or older is not read yet (exit 4, #78): open it in a newer KiCad and save it
first.

Board-relative coordinates (what `pads` prints, and PLACE, TRACKS, VIAS,
ZONES and MOVE take) are measured from the top-left corner of the board
outline's bounding box: the board's own Edge.Cuts lines, rectangles, arcs
(to the furthest point they reach), circles, polygons and curves. A board
with no outline, or one with something else on Edge.Cuts, is measured from
the file's (0, 0); `existing DIR info` prints the origin it uses.

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
| `REVIEW` | see `boardwright/review.py`: `near`; before routing, `orient` (`(CAP, PIN)`: the cap's pad on PIN's net nearer PIN than its ground pad), `balance` (`(PART, PIN_A, PIN_B, mm)`: a crystal's two gaps differ by at most mm), `fronts` (`(IC, mm)`: each signal pin has a clear channel out, straight or at 45 degrees, past parts that do not connect to it), `via_site` (`(PAD, mm)`: room for a via of its net), `chain` (`(FROM, [series REF ...], TO[, mm])`: each shunt's node pad on the series path), `crossings` (`(NETS, limit)`: airwire crossings involving the named nets, each net's pads joined by a minimum spanning tree with copper ignored, poured and ground nets left out; the preview reports the board's total) (these and `near` also run in `place`, which exits 1 on a finding); `maxlen`, `maxpath`, `match` (routed pad-to-pad paths equal within mm), `ref` (mm a net may run with no ground on the adjacent layer), `via_gnd`, `via_near` (a pad has a via of its own net within mm), `apart` (`(QUIET, NOISY, mm)`, nets or lists of nets: the quiet copper keeps mm from the noisy copper, pours included, on the same and adjacent layers; two pads of one part left out), `clear_under` (`(REF, mm)`: no track or via of another net, ground aside, under REF's courtyard grown by mm, on any layer), `islands` (`[NETS]`: pour pieces of a net poured on two or more layers that no via or track joins to another layer and that reach the net through one pad at most; each is named with its bounds and a spot where a via fits, and over which layer's fill; a sliver too small for a via is only reported; KiCad's DRC can pass a board with islands), `tidy` (`[NETS]`, nets or patterns: track debris on those nets that DRC passes, each named with its place: a segment under 0.05 mm, two collinear segments where one would do, segments lying over each other, track ends under 0.05 mm apart that should be one point, an end on nothing (in its own pour, still named), an end more than 0.05 mm off its pad's centre, an end outside its pad joined only by the track's width, an end on another track's body, and a segment running over a pad of its net more than 0.05 mm from the pad's centre with both ends outside it (a straight run through the centre is not named); a short straight run out of a pad before the first bend is not judged, since the pin pitch can force it; arcs are not checked as segments; see `boardwright/tidy.py`), `bends` (`(NETS, FAIL)`: each bend where two straight segments of a net meet on a layer, outside a pad or via of the net, reported with its place and angle as `acute` (under 90°, an acid trap) or `square` (90°, a reviewer's convention, harmless electrically below the GHz range); and each segment of 0.05 mm or more running off the 0/45/90° grid, wherever it is, as `off-45`; only the kinds listed in FAIL fail, so `["acute"]` reports corners and fails acid traps; a board routed at any angle has every segment off-45; arcs are not checked; see `boardwright/bends.py`), `margin` (`(NETS, mm)`: each pair of nets, one of them named, whose copper comes within the clearance rule plus mm, measured edge to edge from tracks and vias to the other net's pads, tracks and vias on a shared layer along whole routes; the rule is the larger of the two nets' net-class clearances, as KiCad takes it; each pair is named once, at its smallest gap, with how long the track runs that close, and as a squeeze when the track crosses between two neighbouring pads of a part; pads are measured with their real rounded shape; pad to pad, pour fills, the board edge and `.kicad_dru` rules are not measured; Freerouting packs tracks at the rule, so a routed board needs `FR_MARGIN` to pass a margin; see `boardwright/margin.py`), `via_in_pad` (`[NETS]`: each via of the named nets whose centre lies in an SMD pad of its net, or whose copper overlaps such a pad's edge, with how far; an open via there wicks solder unless filled and capped; not named: a footprint's only pad, an exposed pad (the largest pad of a part with three or more, at least twice the next), a net tie's pads, and through-hole pads; see `boardwright/via_in_pad.py`), `jogs` (`(NETS, mm)`: each short sideways step in a route, with its place, its length and how far it moves the route: a jog, a segment shorter than mm between two runs of the net that are parallel and head the same way, and an end jog, a segment shorter than mm from the end of a run to a pad or via centre the run misses by under 0.2 mm; every one under mm fails, so set mm below steps the pin pitch forces; see `boardwright/jogs.py`), `segments` (`(NETS, excess)`: track segments beyond the fewest an octilinear route needs; a net through a series part is judged with its whole chain, pad to pad, so a dog-leg out to a column of parts shows; bends forced round obstacles count too, so compare layouts of the same nets with it; pads on one straight line share a segment, a net with an off-45° track is judged at one segment per connection, a poured net cannot be judged, and a route sharing a segment between connections, at a T-junction or over a pad, can come in under the minimum), `loop` (`(CAP, PIN, mm)`: each of the decoupler's ground pads, and its pad on PIN's net when that net has a pour, reaches a via of its own net within mm of copper, tracks or the pour fill it sits in; and, when PIN's net has a pour, PIN reaches CAP by tracks and vias with no plane via off that path nearer; TI SPRABV2 §2–3), `fab` (`"jlcpcb"`, `"oshpark"` or `"pcbway"`: tracks, vias, plated holes and the project's clearance and edge rules against that fab's published minimum, quoted with its page; below its standard-price limit is reported, not failed; `fab_copper_oz`, default 1, picks the limits for heavier copper; see `boardwright/fab.py`), `current` (a path carries amps: one pour piece that never narrows below the IPC-2221 width, or tracks that wide), `coverage`, `skew` |
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
multi-unit symbols, and placing and routing the parts a schematic change adds
(`existing update` puts them beside the board, on their nets).

## Existing boards

    boardwright existing <project dir> info | pads [REF..] | nets [PATTERN]
    boardwright existing <project dir> review | baseline | verify
    boardwright existing <project dir> apply [--force]
    boardwright existing <project dir> free REF [near REF.PAD | near X,Y]
    boardwright existing <project dir> reroute NET [NET ...] [--force]
    boardwright existing <project dir> update [NETLIST.net] [--body keep|library]

The project keeps its own schematic, libraries and rules. An optional
`boardwright.py` beside the board holds `REVIEW`, `TRACKS`, `VIAS`, `ZONES`,
`KEEPOUTS`, `TEXT`, plus `MOVE = {ref: (x, y, rot)}`, `RIPUP = [nets]` and
`REMOVE = [ref or LIB:NAME]`. A
`MOVE` entry may carry a fourth item placing the part's text, in the same
board-relative mm: `{"ref": (x, y[, angle]), "value": (x, y[, angle])}`; the
angle stays as it was unless given.
Outputs go to `<project dir>/boardwright_out/`. The board file is edited in
place: commit before `apply` or `reroute`.

- `info` and the preview work with no KiCad call, on any size of board
  (a 6-layer, 2000-track demo board reads in 2.5 s). The preview draws each
  pour as the fill KiCad last saved, with its outline dashed; it draws no
  silkscreen, but labels each part with its reference, dimmed and italic
  where the reference does not print (hidden, or on no silkscreen layer).
- The gate for an existing board is **"review passes and DRC shows nothing
  that is not in the baseline"**, not "DRC is zero". Run the DRC into
  `boardwright_out/drc.json`, `baseline` once, then `verify` after every
  change. A finding matches the baseline by its type and descriptions, less
  the track length KiCad writes into them, so a track that only got longer
  or shorter is not new. A clearance's `actual` figure is kept: a finding
  whose clearance changed is reported as new. Every new finding fails
  `verify`; it does not tell the nets the edit touched from the rest.
- `reroute` rips up only the named nets, gives Freerouting everything else as
  fixed copper (curved tracks included, as polylines), and
  afterwards keeps only the named nets' new copper: every other net is
  byte-identical to before. New tracks are held to the project's own minimum
  width. Inner layers that hold a zone and no track are planes, switched off
  for the router so the planes stay whole; `PLANES = [layers]` in
  `boardwright.py` (or `build`'s `{layer: net}`) replaces that list. When a
  named net cannot be finished, the reroute is refused (exit 1) and the board
  is left as it was read, since that net's old copper would land on the
  others' new routes: reroute the rest without it. When the route cannot run
  at all (no SES, a timeout past `FR_TIMEOUT`, an Edge.Cuts outline that does
  not close) the board is left as it was read, and the exit is 4 with the
  reason. A named net with a track wider than its net class (a power path,
  usually wide on purpose) is refused before anything runs (exit 1), naming
  each such track, since the router would put it back at the class width;
  `--force` reroutes it anyway. Zones are not refilled, so DRC checks new copper against the old
  fill until they are: refill in KiCad, or `kicad-cli pcb drc --refill-zones`.
- `apply` prints `STALE FILL` for each new track or via that lies in another
  net's saved zone fill: the fill in the file was computed without it and
  overlaps it until the zones are refilled and saved. A DRC run with
  `--refill-zones` checks a fresh fill and never sees it; a CI that checks the
  fill as committed can fail on it, and KiCad 10.0.8's own DRC of the saved
  file did not report it in testing.
- `apply` checks every `VIAS` entry is `(net, x, y[, size, drill])` before
  it changes anything (exit 64 otherwise).
- `apply` is repeatable: a track, via, text, zone or keepout it has already
  written is dropped, even after KiCad has saved the board in its own layout. A `REMOVE` entry is the
  exception: once its footprint is gone it names nothing, which is refused
  (exit 64), so take it out of the spec.
- `REMOVE` takes footprints off the board, each matched by reference or by
  `LIB:NAME`: logo art placed on the board alone is the usual case. Each
  footprint's block is cut whole (its own zones with it) and its uuid dropped
  from any group. A footprint with a pad on a net, or linked to a schematic
  symbol, is refused and nothing is written (exit 1); `--force` removes it
  anyway, and DRC shows what that leaves unconnected. It runs before `MOVE`.
- `apply` checks every part `MOVE` moves before it keeps the move: its pads
  against other nets' tracks, vias and pads (the net classes' clearance), and
  against the board edge (the project's copper-to-edge clearance), and its
  courtyard against the other courtyards on its side. A clash is listed and
  nothing is written (exit 1); `--force` applies it anyway.
- `free REF [near REF.PAD]` lists spots, nearest first, where that part (its
  own pads and courtyard, at 0, 90, 180 or 270 degrees) clears everything
  else, as `MOVE` entries. A part `update` put beside the board is placed with
  it. Pads are modelled with their real shapes (circle, oval, rounded
  rectangle); KiCad's DRC is still the judge.
- `update` does what KiCad's Update PCB from Schematic does, from KiCad's own
  netlist (`kicad-cli sch export netlist --format kicadsexpr`, made for you
  unless you pass one). Footprints are matched to symbols by their path, or by
  reference where a footprint has none (boards made by kicad-tools). Each
  matched footprint takes the symbol's reference and value, its datasheet,
  description and user fields (a missing one added hidden on F.Fab, as KiCad
  does; an empty one not added), its "Do not populate" and "Exclude from
  bill of materials" flags, and each pad its pin's net; a symbol with no footprint on the board gets one from the
  library (project, global, then stock `fp-lib-table`), beside the board
  outline, for you to place. A footprint changed in the schematic is swapped
  when the new library footprint has the board footprint's pads: the same
  numbers, and each the same type, shape, position, angle, size, drill and
  layers, read as KiCad places them (mirrored on the back). `--body keep`, the
  default, changes the link alone, so DRC may report
  `lib_footprint_mismatch` for the old drawing; `--body library` also replaces
  the drawings, texts, 3D models and zones with the library's. The footprint's
  place, pads, nets and fields stay either way, apart from the symbol's
  fields, which it takes as any matched footprint does. A swap to a footprint whose
  pads differ, a symbol with no footprint or a footprint not found stops the
  update with nothing written (exit 1), the first differences listed;
  footprints whose symbol is gone are listed and left (`REMOVE` takes them
  off).
  Tracks and zones are untouched: DRC shows what a changed net leaves
  unconnected. KiCad's DRC with `--schematic-parity` is the check. Boards
  saved by KiCad 10 only.

`examples/existing/` holds specs for three of the demo projects that ship
with KiCad; its README says where to copy them from.

### Existing schematics

    boardwright sch <project dir> parts [PATTERN] [--fields FIELDS]   # FIELDS: properties to show, e.g. 'Sim.*'
    boardwright sch <project dir> set REF Field=Value ...      # Value, Footprint, any property; dnp/in_bom/on_board
    boardwright sch <project dir> add SPEC.py                  # ADD = [(ref, like, value, footprint, {pin: net})]
    boardwright sch <project dir> remove REF ...
    boardwright sch <project dir> repoint OLD_LIB:OLD_NAME NEW_LIB:NEW_NAME [--body keep|library]
    boardwright sch ercdiff OLD.json NEW.json

Edits replace one block of the file and leave the rest byte-identical; the
file is written only if it is still what was read. A new part is put in an
empty area with a short wire from each pin to a label of the kind the net
already uses (local or global), or to a copy of the net's power symbol. `like`
is either a part already on the sheet, which is copied, or a library symbol
`LIB:NAME`, found like `repoint`'s and added to the sheet's symbol cache; its
fields come from the library. Single-unit symbols only, and not power symbols.

The check is KiCad's own connectivity: `netspec snap` before, `netspec diff`
after, and the difference must be the change you meant and nothing else.
`ercdiff` shows what an edit added to the ERC findings. After a schematic
change, `boardwright existing <project dir> update` carries it to the board;
DRC parity says whether anything is left.

`repoint` changes which library symbol parts link to, for every part using
`OLD_LIB:OLD_NAME` on every sheet: a library renamed or vendored under a new
nickname, or a `<project>-rescue` library left by an older KiCad. `--body keep`
(the default) renames the cached symbol, its units and each part's link and
keeps the drawing; `--body library` replaces the cached symbol with the one in
the new library (an `extends` symbol is merged with its parent, as KiCad does).
The new symbol is looked up in the project's `sym-lib-table`, then KiCad's global
one (with the path variables set in Preferences > Configure Paths, and any
table nested in it), then KiCad's stock libraries. Its pin numbers must be the
same set as the cached symbol's, or the edit is refused (exit 1) and nothing
is written. A part carrying a `lib_name` override is refused too.

On a sheet used more than once in a hierarchy, one symbol is a part in each
use: `parts` says which, `set` changes all of them and says so, `remove`
refuses, and so does `add`. `SHEET = "file.kicad_sch"` in the spec adds to a
sub-sheet used once: the new parts take its hierarchy path from a part already
on it, a sheet pin's net gets a hierarchical label, a power net a copy of its
power symbol from whichever sheet has one, and a net local to another sheet is
refused (exit 1), since only a sheet pin reaches it.

A net in a pin map is a label's name. The name KiCad's netlist and ERC give a
local label's net, with the sheet path in front (`/LED_A` on the root sheet,
`/io/LED_A` on sub-sheet io), joins that label too. Any other name with a `/`
in it is refused (exit 64) rather than written as a new label with the slash
in its text.

Limits: `add` places single-unit symbols on a sheet used once, and draws only
pin stubs. Nothing is moved or re-wired. A
schematic open in KiCad has to be closed and reopened to show the change.

## Live KiCad (the board that is open on screen)

    boardwright live status | snapshot | review [SPEC.py] | selection
    boardwright live select NET|REF ... | refill | revert
    boardwright live apply SPEC.py|EDITS.json [--dry-run] [--save]
    boardwright live --board FILE.kicad_pcb VERB ...
    boardwright live open BOARD.kicad_pcb
    boardwright edits SPEC.py BOARD.kicad_pcb OUT.json [PROJECT.kicad_pro]

Needs `pip install "boardwright[live]"` and KiCad 10 running with the PCB
editor open and Preferences > Plugins > Enable KiCad API switched on. It uses
KiCad's IPC API through kicad-python. `snapshot` writes the open board,
unsaved edits included, to `boardwright_out/live.kicad_pcb` without saving
anything in KiCad, so preview and review run on what is on screen.
`selection` reports what is selected in board-relative coordinates; `select`
selects items so you can see what a finding refers to. `apply` makes one
commit (one Ctrl+Z) from `MOVE`, `RIPUP`, `VIAS`, `TRACKS` and does not save
unless told to. `apply --save` refills the zones before saving when the edit
moved, removed or added anything, so a part moved into a pour is not saved
under stale fill. While KiCad is busy (a refill or a check running) it is
asked again every 0.5 s for up to 30 s, kicad-python 0.8.0's own refill
defaults; past that the command stops with exit 4.

`apply --save` saves the whole open board, so it first compares the board
in KiCad with its file and refuses (exit 1, nothing changed) when KiCad
holds edits the file does not, naming them (`footprint R1`). Save or undo
them in KiCad, or apply without `--save`. The comparison is item by item,
ignoring order, whitespace and the version stamp KiCad 10.0.8 adds inside
each footprint: KiCad writes an unchanged board differently from the file it
loaded. Measured on one board, KiCad 10.0.8 (#46).

`revert` takes back boardwright's own last `apply` that was not saved: it
reloads the board from its file (KiCad's RevertDocument), which drops every
unsaved change, so it does so only when the open board is exactly what that
apply left, the file is unchanged since, and nothing else was unsaved before
the apply. Otherwise it refuses (exit 1, nothing changed) and names what is in
the way; use Ctrl+Z in KiCad then. An `apply` without `--save` records itself
in `boardwright_out/live.applied.*`; `--save` and `revert` clear the record.
Measured on KiCad 10.0.8: the revert reloaded the file without anyone
touching the editor, and a footprint moved outside boardwright after the
apply made it refuse (#94).

The file edits (`existing apply`, `reroute`, `update`, and every `sch`
edit) warn when KiCad has the file open, which it shows by keeping
`~<name>.lck` beside it: KiCad's next save of that file overwrites the
edit. Close it in KiCad without saving, then reopen it.

With several KiCads running, give `--board FILE` (or `--board=FILE`) to any
verb. Without it, `live` uses kicad-python's default socket, `api.sock`, and
the first KiCad holds that one: a second instance gets `api-<pid>.sock`. If
the first is a project manager, `live` reaches a KiCad with no board.
`--board` asks every `api.sock` and `api-*.sock` in the Flatpak and native
socket folders (and `KICAD_API_SOCKET` first, if set) for its open board, and
uses the one whose path resolves to FILE. A socket that does not answer, or a
project manager, is skipped. No match is exit 4, listing each socket and what
it had open; two matches is exit 1. A KiCad that answers "not ready" while it
loads is asked again for up to the same 30 s.

`live open BOARD` gets a board in front of `live` on KiCad 10, whose API
cannot open a document (the project manager answers only a few common
requests). If a running KiCad already has BOARD open, it prints that socket
and starts nothing; two with it open is exit 1. Otherwise it starts the
standalone PCB editor on BOARD, detached, and asks every socket once a second
until one answers with BOARD open, for at most 60 s. That bound is chosen,
not measured: an editor's cold start loads the libraries, and it has not been
timed. Past it, or if the editor exits with an error first, it stops with
exit 4, naming the command it started and what the sockets had open. BOARD
must be an existing `.kicad_pcb` (otherwise exit 64). The editor is found as
kicad-cli is: `BOARDWRIGHT_PCBNEW`, then `pcbnew` on PATH, then the Flatpak
(`flatpak run --command=pcbnew org.kicad.KiCad`, if `flatpak info
org.kicad.KiCad` says it is installed), then the macOS bundle and a Windows
install; none is exit 4. With the Flatpak editor it refuses (exit 1) while
any `api-*.sock` is in the Flatpak socket folder: each Flatpak instance has
its own pid namespace, so a new one may take the same `api-<pid>.sock` name
as a running one. That collision is inferred, not seen. A project manager on
`api.sock` does not stop it.

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
run against KiCad. The refill before `apply --save` and the bounded busy wait
are tested against a fake KiCad only, and so is `live open`: it has not been run
against a real KiCad. `boardwright selection` was checked against two real
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
- `dsn.py` writes the board as Freerouting reads it; `ses.py` reads
  Freerouting's session; `build.import_ses` adds its tracks and vias.
  Freerouting routes. `env.py` finds `kicad-cli`, or takes it from
  `BOARDWRIGHT_KICAD_CLI`.
