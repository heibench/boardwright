# Development log

How the tool was built: each example board and each piece of existing-board
work, what broke, and what changed in the tool because of it. The entries were
written as the work happened, before the project was named boardwright, so
they use the paths and commands of the time (`boards/` is now
`examples/boards/`, `dogfood/existing/` is `examples/existing/`,
`boardwright build DIR STEP` is `boardwright STEP DIR`,
`scripts/check.sh` is `boardwright check`, and netlist comparisons are now
`netspec diff`).

Every board built with this repo gets a numbered entry here. The point is to
find where the process breaks on real reference designs and fix the tool, not
the board. One file per board:

- **Reference** -- the vendor document the circuit and layout rules come from,
  and which values were read from it versus chosen here.
- **Stresses** -- why this board was picked.
- **What broke** -- in order, with the symptom as KiCad or the plot showed it.
- **Tool changes** -- what changed in `boardwright/` because of it.
- **Left open** -- what a real engineer would still fix or check.

`gaps.md` is the running backlog of tool gaps, most painful first.

| # | Board | Reference | Stresses | Gate |
|---|-------|-----------|----------|------|
| 01 | `ldo_breakout` | AMS1117 datasheet typical application | the loop itself | PASS |
| 02 | `rp2040_min` | Raspberry Pi "Hardware design with RP2040" minimal design | 0.4 mm QFN, USB, crystal, QSPI | PASS (second pass) |
| 03 | `tps54202_buck` | TI TPS54202 datasheet (SLVSD26C) Fig. 7-1 and layout 7.4 | power polygons, hand routing, current loops | PASS |
| 04 | `stm32f103_min` | ST AN2586 and STM32F103x8 datasheet | 0.5 mm LQFP-48, bottom decoupling, crystal, USB pair | PASS |
| 05 | `esp32c3_min` | Espressif ESP32-C3 hardware design guidelines | RF module, antenna keep-out, USB pair on the bottom | PASS |
| 06 | `stm32f103_4l` | as 04, on signal / GND / GND / signal | four layers, inner planes, return path, placement by intent | PASS |
| 07 | `existing/stickhub` | a KiCad demo project nobody here drew | an existing board: read, review, edit in place, selective re-route | PASS vs baseline |
| 08 | `customlib_test` | none (fixture) | parts from a library outside KiCad's stock set | PASS |
| 09 | `existing/schtest` | the StickHub demo's schematic | an existing schematic: change a value, add two parts | netlist diff is exactly the edit |
| 10 | `existing/hier` and two read-only demos | KiCad's hierarchical, 6-layer and 9-layer demos | shared sub-sheets, routing with vias and inner layers, per-net rules | see entry |
| 11 | `stm32f103_4l` as an existing board | 06, without its spec | the whole existing-board loop on four layers: schematic edit, update, place, route, text | PASS vs baseline |
| 12 | KiCad's pic_programmer and coldfire demos | a fleet of existing boards with dead library links | re-pointing a placed footprint, removing a board-only one | PASS, judged by KiCad's DRC |

"Gate PASS" means: ERC 0, DRC 0 at every severity with schematic parity,
KiCad's netlist equals the declared circuit, the `REVIEW` checks pass, fab
files exported. It does not mean built or powered.

All five were regenerated and gated with the tool as it stands at the last
entry. Bottom GND pour coverage (share of board area): 01 92%, 02 78% in
five pieces, 03 94%, 04 77%, 05 68%.
