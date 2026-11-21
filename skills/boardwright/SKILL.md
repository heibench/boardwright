---
name: boardwright
description: Generate a KiCad board from a short Python description, or edit an existing KiCad board and schematic in place, until KiCad's own ERC, DRC with schematic parity and netlist agree. Use when asked to make a new PCB, place or route parts, change a board or schematic someone else made, or edit the board open in KiCad. Not for schematic capture from scratch, not for footprint or symbol library design, and not a substitute for building and testing the board.
---

# boardwright

boardwright writes KiCad files; KiCad judges them. A board is done when
`boardwright verify` says PASS, and PASS means KiCad and the review found
nothing wrong. It does not mean the board works: nobody has built it.

`boardwright --help` lists every command, and `boardwright doctor` says what
this machine has for each step (KiCad's command line, its libraries,
Freerouting, the live client). Read doctor's answer before blaming a board.

Exit codes are the same on every command:

| Code | Meaning |
|---|---|
| 0 | done: the board passed, or the edit was made and checked |
| 1 | refused or violated: a finding about the design, or an edit not made |
| 2 | could not tell: a check that could not be decided (a KiCad report missing) |
| 4 | environment fault: KiCad, a library or Freerouting missing or failing, or a file it cannot read or write. Never a verdict on the board |
| 64 | usage: bad arguments, or a spec naming parts, nets or layers that are not there |

Coordinates in every spec are board-relative mm, origin at the top-left
corner of the board outline, y down: what `pads` prints.

## A new board

`DIR` holds `board.py`. Work in this order, and do not skip to `gen`.

1. **Read the vendor's reference** for every IC: the datasheet's typical
   application and layout section, or the hardware design guide. Write down
   which values came from it and which you chose.
2. **Look up pins and footprints** instead of guessing:
   `boardwright pins LIB:SYMBOL [LIB:FOOTPRINT]`.
3. **Write `DIR/board.py`.** `NAME`, `W`, `H`; `CIRCUIT` with
   `c.add(ref, "Lib:Symbol", value, "Lib:Footprint", {pin: net})`; `PLACE` as
   `ref -> (x, y, rot)`, or `pad_at(...)` to put a named pad at a pin;
   `LAYERS = 4` with `PLANES = {"In1.Cu": "GND", ...}` for four layers;
   `REVIEW` for what this board must hold (decoupling `near`, matched pairs,
   current paths). The boards in `examples/boards/` of the boardwright
   repository show each of these.
4. **Place, look, repeat.** `boardwright place DIR` writes the schematic and
   placed board with `out/preview.png` (pads, ratsnest) in seconds, without
   KiCad. `boardwright pads DIR` prints every pad. Get placement right here,
   following "Placement" below: routing cannot fix a part in the wrong place.
5. **Generate:** `boardwright gen DIR` routes with Freerouting and pours.
   Minutes on a dense board.
6. **Gate:** `boardwright check DIR` runs ERC, the netlist, DRC with schematic
   parity, fab outputs and plots through KiCad. `--quick` is DRC and copper
   plots only, for iterating.
7. **Verify:** `boardwright verify DIR`. PASS needs ERC 0, DRC 0 at every
   severity (unconnected and parity included), KiCad's netlist equal to the
   declared circuit, the review clean and the fab files present.
8. **Look** at `out/F_Cu.png`, `out/B_Cu.png` (the only views that show
   pours), `out/top.png` and `out/schematic.pdf`.

When `verify` fails, it names what failed. Fix the cause in `board.py` and go
back to step 4 or 5. Do not relax a check to get a PASS: `SEVERITIES` in
`board.py` exists for a decision you can write a reason for, not for a
finding you would rather not see.

## A board you did not make

Do these in order, before changing anything. `P` is the project directory.

1. **Commit, on a branch.** Files are edited in place; git is the undo.
2. **Read what the repository says** about the board: README, notes, rules.
   Find out what the task is and what must not change.
3. **Inspect:** `boardwright existing P info` (layers, counts, pours,
   preview), `boardwright existing P nets PATTERN`, `boardwright sch P parts`.
4. **Take baselines** before any edit: KiCad's DRC with schematic parity to
   `P/boardwright_out/drc.json`, then `boardwright existing P baseline`, and
   ERC to `P/boardwright_out/erc_before.json`. An existing design is rarely
   clean. From here on the question is what your edit added, not whether the
   count is zero.
5. **Write `P/boardwright.py`** with a `REVIEW` for what matters on this
   board and run `boardwright existing P review`. Report findings as
   findings; do not fix what you were not asked to fix.
6. **Then one change at a time.** Plan it as a spec, apply it
   (`boardwright existing P apply`, `reroute NET ...`, `update`, or a `sch`
   edit), read the result back, run the DRC, and compare with the baseline.
7. **Write down** what was asked, what was done, what the checks said, and
   what was left.

Things to know before editing:

- `existing apply`, `reroute`, `update` and every `sch` edit warn when KiCad
  has the file open: KiCad's next save of it overwrites the edit. Close it in
  KiCad without saving first.
- `reroute NET ...` leaves the board exactly as it was when the router cannot
  finish a net or cannot run, and keeps signals off inner plane layers.
  Zones are not refilled: refill before judging DRC.
- `existing apply` is repeatable; running it twice adds nothing.

What boardwright does badly, so say so instead of trying: re-routing in dense
areas, anything that needs existing tracks pushed aside, length-tuned pairs,
multi-unit symbols, and placing the parts a schematic change adds
(`existing update` puts them beside the board for you to place).

## The board open in KiCad

`boardwright live` edits the board open in KiCad's PCB editor through KiCad's
IPC API (needs the `live` extra and "Enable KiCad API" in KiCad).
`live apply SPEC.py` makes one undo step and does not save. Look at it, then:

- `live apply SPEC.py --save` refuses (exit 1, nothing changed) when KiCad
  holds edits its file does not, since the save would keep them too.
- `live revert` takes back boardwright's own last unsaved apply, and refuses
  when anything else is unsaved. Otherwise the person undoes it with Ctrl+Z.
- `live snapshot` and `live review` work on what is on screen, unsaved edits
  included.

Never save over a person's unsaved work, and never ask them to close KiCad so
you can edit the files.

## Placement

Placement decides most of what routing can achieve. Work from the reasons;
the rules follow from them, and where they disagree on a board, follow the
reason and the vendor's reference.

**The reasons.**

- **Current flows in loops.** A decoupler helps only if the loop from its
  pads to the IC's supply and ground pins is small. In a switching regulator
  one loop switches in nanoseconds (for a buck: the input capacitor, the
  switches and their ground return); the datasheet's layout section names it.
  Short loops matter most where current changes fastest.
- **Some connections tolerate distance and some do not.** Rank every
  connection by how much length it tolerates before placing anything, and
  give the space next to the pins to the ones that tolerate least.
- **Noisy and sensitive circuits need distance.** Switch nodes, clocks and
  buses are noisy; crystals, analog inputs, references and RF are sensitive.
- **Some things are fixed first.** Connectors, buttons, LEDs, mounting holes,
  an antenna and its keep-out, the outline. Place them from the mechanical
  requirements before anything else.
- **Every pad must stay reachable**, with room for a track to reach it and,
  for a ground pad, room for a via.

**Each part's job, and what it needs:**

| Job | Placement |
|---|---|
| Decoupling capacitor | at its supply pin, supply pad toward the pin; usually the smallest value closest, unless the vendor orders them otherwise |
| Bulk capacitor | near the pins it feeds, in line behind the small capacitor it backs |
| Switching regulator | the switching loop the datasheet names as small as possible; switch node short; output capacitor where the datasheet puts it |
| Crystal | both pads close to their two pins, at nearly equal distance; nothing routed between |
| RF matching (pi or T) | series parts in schematic order on one line from the RF pin to the port; each shunt's node pad on that line, turned across it with its ground pad away |
| Filter or RC on an input | the capacitor at the pin it filters; the series resistor beside the capacitor's signal pad |
| Pull-up, series termination | termination at the driving pin; a pull-up on a slow net anywhere on it |

Use the parts the schematic has and add none.

**Order.** Place in order of how little distance each connection tolerates:
RF and the regulator's power loop first, then decouplers and filter
capacitors (each at its own pin), then crystals, then bulk capacitors, series
resistors and pull-ups, then everything else. When a part that must be close
cannot reach its pin, move the part that tolerates distance, not the close
one.

**Two cases that go wrong often.**

- **Parts at neighbouring pins** fit side by side, each in line with its pin,
  only when their courtyard widths add up to no more than twice the pin
  pitch. Two 0201s (0.46 mm courtyards) at 0.4 mm pitch do not. Plan the pair
  together: offset them, move one out by its courtyard length, or swap which
  pin gets the nearer spot.
- **A two-pin part across two pins** (a crystal, a flying capacitor): its two
  gaps should be nearly equal. Rotate it 180 degrees, or slide it along the
  side. Prefer the balanced choice when it costs little length.

**Check each group as you go,** with `REVIEW` keys in `board.py` that
`boardwright place DIR` runs (it exits 1 on a finding) and `verify` runs again:
`near` (a pad within mm of a pin), `orient` (a decoupler not turned round),
`balance` (a crystal's two gaps), `fronts` (no part parked in front of a pin it
does not connect to), `via_site` (room for a ground via), `chain` (an RF
shunt on the series path). Then `boardwright check DIR --quick` for courtyard
and clearance errors; unconnected items are expected before routing. After
routing, `loop` (`(CAP, PIN, mm)`) measures what TI ranks above distance: the
copper from each decoupler pad to its via, and that the pin reaches the
capacitor before the plane. `apart` (`(QUIET, NOISY, mm)`) keeps a feedback
or crystal net from a switch node, and `clear_under` (`(REF, mm)`) keeps other
nets' tracks from under a crystal.

This placement guidance is adapted from kistack's layout-placement skill
(https://github.com/BackplaneWorks/kistack, `skills/layout-placement/`),
which states it was developed on a few small Nordic QFN boards and is not
qualified for electrical, RF or manufacturing sign-off. The same holds here:
where it and the datasheet or the vendor's reference layout disagree, follow
the datasheet.

kistack's notice:

> Copyright 2026 American Embedded, LLC
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> The American Embedded logo may not be reproduced without express written
> permission.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## More

The full manual is `docs/guide.md` in the boardwright repository
(https://heibench.com/boardwright/). This skill is enough to take a board
from `board.py` to `verify` PASS without it.
