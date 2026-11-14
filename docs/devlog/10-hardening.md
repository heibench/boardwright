# 10 hardening on harder inputs

Before the tool meets real boards, the three places where real boards differ
most from what had been tested.

## Hierarchical schematic (`dogfood/existing/hier/`, KiCad's complex_hierarchy demo)

One sub-sheet used twice, so each of its symbols is two parts.
- `parts` at first listed none of them: it read the "Reference" property,
  which holds one of the two references. References are now read from the
  symbol's instance list.
- `set R203 Value=33K` says it also changes R303; KiCad's netlist shows both
  changed. `remove R213` refuses, because it would remove R313 too.
- `set D101` and `add` C199 (copy of C104, VCC to GND) on the root sheet.

`netdiff` between KiCad's netlists: C199 added on VCC and GND; D101, R203 and
R303 changed. Nothing else.

## Router on a 6-layer board (KiCad's cm5_minima demo, read only)

Six two-pad nets that change layer, re-routed over F.Cu, In2.Cu, In3.Cu and
B.Cu with each net's own class rules:

| Net | Result | Original |
|-----|--------|----------|
| nLED_ACTIVITY | 8.5 mm, 1 via | 10.2 mm |
| VBUS_EN | 22.5 mm, 1 via | 43.1 mm |
| nLED_SPEED_100_1000 | failed after 84 s | |
| ETH_nLED_ACTIVITY | 30.5 mm, 2 vias, uses In2 | 31.3 mm |
| Net-(D702-K) | 4.0 mm, 2 vias, uses In2 | 5.5 mm |
| PWM | 32.3 mm, 2 vias, uses In2 | 33.2 mm |

Every routed result keeps at least its class clearance (0.13 mm) from other
copper by this tool's own geometry. **Not checked by KiCad's DRC:** the
results were not written to a board. A failure now gives up in a bounded
search instead of 84 seconds.

## Per-net rules

The router read only the Default net class. It now takes each net's class
from the project file, by explicit assignment (the Jetson demo) or by pattern
(cm5_minima: `/*USB_*` -> 90ohm, 0.147 mm, 0.2 mm clearance). Rules that live
in a `.kicad_dru` file are not read.

## Also

A 9-layer, 22,151-track demo board loads and reports its net classes.

## Left open
- The 6-layer routes were not judged by KiCad.
- `.kicad_dru` rules are invisible to the router and the review.
- `add` on a sub-sheet; multi-unit parts.
