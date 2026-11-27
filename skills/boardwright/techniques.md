# Layout techniques

Small, specific moves that turned a layout a reviewer rejected into one the
reviewer accepted, with the same parts and the same rules. Each keeps its
conditions: a technique applied where its condition does not hold does harm,
and the condition is what a flattened rule loses.

Where they come from: two days of agent board work on five public BREAD slice
templates (feastorg/Slice_TEMP_*), reviewed by a designer on rendered images,
November 2026. Every board passed KiCad's DRC with 0 errors before review, and
the reviewer still found layout problems on every one. The commits cited are
on those repositories. T10 to T13 come from a later round on feastorg/Slice_IOCT:
their commits came in through its pull request #2, squash-merged as f46abfa,
so GitHub serves them but no branch holds them. The full account is heibench/research
`topics/eda-agents/field-report.md`. One project and one reviewer: read these
as cases, not laws.

The pattern across all of them: **read the structure of the problem before
placing or routing**: the route a net wants, the pin order at both ends, the
net that encloses a destination, the fill pieces a pad sits in. The failures
were the opposite: acting on the nearest local thing.

## T1. Route first, then put series parts in line

- **Problem.** Series parts (resistors, solder jumpers, ferrites, 0 Ω links)
  placed first in a neat column, then routed to: every signal takes a dog-leg
  out to the column and back.
- **Move.** Draw each signal as the route it would take with no part on it: a
  straight run, or the fewest 45° segments. Put the part on that route, turned
  to the route's angle, and split the track at its pads. Where parallel runs
  are too close for parts side by side (courtyards would overlap), stagger the
  parts along their runs. On a run that bends, put the part on a straight
  stretch, with about 1 mm of pad entry each side.
- **Applies to** a two-pin part in series on a signal that has a natural path.
- **Not when** the parts must be reachable or read as a group (a jumper bank
  set together, a DIP), a shunt part hangs off a net rather than sitting in it
  (see T7), or no straight stretch is long enough for the part.
- **A column is right** when its outputs fan out in the column's order toward
  one destination: on the Nano template a jumper column in the connector's pin
  order needed no vias at all (T2).
- **Evidence.** Slice_TEMP_NUCL_S4L-r1: the column version (edd960f) gave
  ESTOP, INT and SYNC 5, 5 and 4 F.Cu segments; with the parts on routes drawn
  first (3d9827f), 2, 2 and 2. DRC and a route lint scored both the same; the
  reviewer rejected the first at a glance. `REVIEW` `segments` measures this:
  excess 3, 3 and 2 against 0, 0 and 0.

## T2. Parts in the pin order both ends share need no vias

Read the pin order at both ends of a group before routing. If it matches,
place the parts in that order and the routes run parallel, with no crossings.
The condition is the shared order, not "make a column" (T1). Evidence:
Slice_TEMP_NANO_S2L-r2, a jumper column in J1's pin order.

## T3. Cross an enclosing net with a via pair, not a detour

A route far longer than the straight line usually goes round a net that
encloses its destination. Find that net, and cross it once with a via pair.
Evidence: the Nano template's LED route went round the board edge, 0.75 mm
from it, because the +5V loop encloses the Nano; one via pair under +5V cut it
from 93 mm to 55 mm.

## T4. End every track on the pad centre

Take the pad centre from `boardwright pads` and end the segment there; for a
45° run into a pad, choose the line through the centre and work back from it.
Evidence: on Slice_TEMP_NUCL_S4L-r1 three tracks stopped 0.04 to 0.07 mm short
(fixed in af65e07). KiCad calls such ends connected, and so does boardwright
since 0.11.0, but a reviewer reading a render takes them for open nets.

## T5. A pour fenced off by your own routes is an island: find it, then stitch it

Routes and a header column can fence off a wedge of pour with no other way to
its net; a pad whose thermal spokes land in it is starved (KiCad
`starved_thermal`). List the fill pieces near the pad to find the island, then
put one via of the pour's net inside it, to a plane. Evidence:
Slice_TEMP_PICO_L4L-r1, pin 28 (GND). A first via in the obvious gap, on the
other side of the pad, changed nothing; the fill pieces showed the island to
the west, and a via there cleared the error (f4e1a07). When a fix does not
move the DRC result, the model of the problem is wrong: read what KiCad sees
before trying again.

## T6. Where every layer is poured, a ground "route" may be redundant

A track that joins a through-hole ground pin to the pour, starting in open
pour, adds nothing and crowds the signals beside it. Check the pours on every
layer under both ends; if the pin is through-hole and every layer is poured
there, delete the track. Evidence: Slice_TEMP_PICO_L4L-r1, the GND route into
pin 23 (a47d051).

## T7. A decoupler on its pin's rail, nearest the pin, ground by a via

Beside the supply pin it serves, on the shortest straight stub, its ground pad
straight to a via into the plane; the shunt-part form of T1 is "put it where
the net already passes". Evidence: Slice_TEMP_NUCL_S4L-r1 C7 at D1 (66dcfff):
a 2.4 mm stub to D1's supply pad, a ground via 1.4 mm from its other pad.
`REVIEW` `loop` measures the copper from each decoupler pad to its via.

## T8. Give parallel runs the same exit, so their spacing stays even

When parallel 45° runs reach pads that are not on a true 45° line from their
source, some need a short exit stub to land on the pad centre and others do
not, and the spacing goes uneven: 1.3 mm instead of 1.8 mm on the Nucleo L4L.
Give every run in the group the same exit, and move a via along its own run if
it needs to. Evidence: Slice_TEMP_NUCL_L4L-r1 pull request #4, ESTOP, INT and
SYNC.

## T9. A shunt part can straddle two parallel rails

A decoupler can sit across a supply rail and a ground rail running side by
side, one pad on each, both rails passing straight through its pads. If the
rail spacing does not match the pad pitch, nudge the rail vias by fractions of
a millimetre rather than add jogs. Evidence: Slice_TEMP_NUCL_L4L-r1 C7, 1.725
mm pad pitch across +5VD and GNDD; the vias moved 0.015 and 0.13 mm. A first
try moved the ground rail instead, 0.11 mm from a neighbouring pad: a DRC
clearance error.

## T10. Lay repeated channels out as one row, repeated

When N identical channels are each placed and routed on their own, small
differences compound: vias, detours, and nets threading between each other's
parts. Design one channel's row so that every link in it is a straight track,
then repeat it at the channel pitch. Feed the net the channels share as one
rail on the other layer, with one via per channel. Run each channel's line
from the controller as nested L-shapes at one pitch, with equal 45° corners.
The line to the nearest channel bends outermost, and each farther channel's
line bends one pitch inside the last, so no line's turn crosses another's
run. Evidence: Slice_IOCT pull request #2, commit 9cfff82, four SSR output
channels. OUT1, to the nearest channel, turns outermost, and OUT2 to OUT4
each turn 0.5 mm further in. For the block's nine nets, 91
segments and 12 vias became 44 and 7; DRC was unchanged.

## T11. Put a part where its input arrives, not where its output goes

A small circuit with one input net and one output net goes where the harder
net to route is shortest. An e-stop interlock placed beside the outputs it
switches pulled its input across the whole board, through the strip the
output channels needed. Placed beside the input instead, the input became a
straight drop and only the output, a single rail, crossed the board.
Evidence: Slice_IOCT pull request #2, commit 8f77248, Q2, R14 and R15: ESTOP
lost two vias and a B.Cu wiggle of 0.375 mm segments, and the strip T10 used
was freed.

## T12. Put repeated channels on the connector's pitch, and line one pin row up with it

Channels placed at about a connector's pitch give every link a small jog,
segments of a few micrometres and odd necks, all of which pass DRC. Snap each
channel to the connector's pitch exactly, and pick the offset so one row of
pins shares a line with the connector's pins. Each link is then a straight
run or a single 45°. Turning a two-pin part 180° keeps the circuit and can put
its pad on the connector pin's line, but its reference moves with it: place
the labels again after turning. Evidence: Slice_IOCT pull request #2:
- commit 123d24d, input channels on a 7.53/7.50/7.40 mm pitch against the
  connector's 7.50: 220 segments became 85 for the block's 21 nets. The
  turned resistors left four reference labels overlapping (D11/R7, D12/R9),
  four new DRC warnings;
- commit a5967ee, output relays at x 48.40/48.30/48.30/48.55 moved onto one
  column.

## T13. Read the board's constraints before stepping a run

A small step in a run along the board edge can look like a defect, and
straightening it can run the track into something that forced it. Before
choosing where a run goes, list the graphics near it on Edge.Cuts and on the
Margin layer, and the clearance of every neighbour. A low-current neighbour
can go narrower so the main run stays level. Evidence: Slice_IOCT pull request
#2, commit 0053004: +12V along the bottom edge lost its 0.1 mm step once the
regulator's FB sense track beside it went from 0.5 to 0.3 mm. In the work
behind it, the first attempt to straighten the run hit a line on the Margin
layer, which KiCad's DRC treated as a board edge. The commit records only the
result.
