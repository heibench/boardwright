# 01 ldo_breakout

**Reference:** AMS1117-3.3 typical application. First built from memory of
the datasheet; read on 2026-11-14 (see below).

**Stresses:** nothing; it exists to prove the loop from `board.py` to Gerbers.

**What broke**
- ERC: 16 library warnings: the project named libraries it did not carry.
- Schematic parity: `/VIN` on the schematic vs `VIN` on the board.
- kicad-tools' own router routed one net and overwrote `.kicad_pro`.
- Freerouting necked a track to 0.187 mm against a 0.2 mm minimum.

**Tool changes**
- Vendor the used symbols and footprints into `<board>/libs`, trimmed.
- Global labels on every pin instead of local ones.
- Route through Freerouting (DSN out, SES in); rewrite `.kicad_pro` after kct.
- Widen any segment under `min_track_width` after import.

**Left open:** none worth recording.

## Second pass: the datasheet, read

The datasheet asks for 22 uF *solid tantalum* on the output ("will ensure
stability for all operating conditions"): the regulator relies on the output
capacitor's series resistance, and the board had a ceramic. C2 is now a
22 uF tantalum in EIA-3528; the board was regenerated and passes the gate.
The "10 uF in" was a misremembering of the adjust-pin bypass in Figure 1; the
datasheet shows no input capacitor, so C1 stays as a choice. SOT-223
dissipation is capped at 1.2 W, about 0.7 A from 5 V.
