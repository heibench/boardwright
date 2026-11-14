# 01 ldo_breakout

**Reference:** AMS1117-3.3 typical application (10 uF in, 22 uF out). Values
from memory of the datasheet, not re-read.

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
