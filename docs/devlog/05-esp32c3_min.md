# 05 esp32c3_min

**Reference:** Espressif "ESP32-C3 Series Hardware Design Guidelines" and the
ESP32-C3-WROOM-02 datasheet. From memory of those documents, not re-read:
10 uF + 0.1 uF at the 3V3 pin, EN RC of 10k / 1 uF, IO9 low at reset for
download boot, IO8 and IO2 pulled high, supply of at least 500 mA, no copper
under or beside the antenna, USB Serial/JTAG on IO18 (D-) / IO19 (D+).
Chosen here: AP2112K regulator, USBLC6 ESD part, header pinout, LED on IO7.

**Stresses:** an RF module with an antenna keep-out, a footprint that carries
its own thermal vias, and USB pins on the side facing a header.

**What broke**
1. `KEEPOUTS` had never been used. It worked first time: no pour, track or via
   in the antenna strip on either layer.
2. The module footprint's thermal vias are 0.2 mm; the board minimum was
   0.3 mm.
3. KiCad warns that the module footprint differs from its library copy once
   kicad-tools has written it. Pad, line, text and property counts are equal.
   Not explained; the check is set to ignore for this board only.
4. Autorouted USB ran 45-50 mm round the outside of the right-hand header with
   5.5 mm of skew.
5. My first hand-routed pair crossed itself on the bottom layer (KiCad:
   "tracks crossing", "shorting"). I drew two parallel verticals whose
   diagonals had to swap sides.
6. The EN capacitor was 14.8 mm from the EN pin.
7. Silkscreen labels collided with reference designators, whose final
   positions are chosen by a tool after I place the text.

**Tool changes**
- `RULES` can lower a board minimum; `SEVERITIES` can set a KiCad DRC check's
  severity per board (use with a written reason).
- `copper.check_tracks`: `gen` now refuses hand tracks of different nets that
  cross on a layer or pass over a foreign hand-placed via.
- Segments returned twice by SES import are de-duplicated (they doubled every
  measured length); vias and track stubs the autorouter abandoned are removed.

**Method that worked:** USB as a hand-routed pair on the bottom layer (vias at
the module pins and at the ESD part), which leaves the top free for the header
fan-out. EN capacitor on the bottom, under the EN pin. Labels on the back
silkscreen.

## Second pass

`FR_BOTTOM_COST = 20` raised the bottom pour from 44% to 68% of the board in
one piece (the bare antenna strip is 15%). The connector end of the USB pair
then wandered like on 04, so the ESD part moved to sit centred over the
connector and that section is hand-routed. This board's 0.2 mm clearance does
not fit two 0.2 mm tracks in the 0.95 mm channel; they are 0.15 mm there.

## Third pass: the vendor document, read

Espressif's schematic checklist asks for 22-33 ohm series resistors on the
USB lines close to the chip. The board had none: I had remembered "optional
placeholders". R8 and R9 (22 ohm) now sit on the bottom under the module's USB
vias, 1.05 and 2.24 mm from the pins, placed with `pad_at`. The four
connector-to-resistor paths are matched within 2.8 mm.

**Left open**
- Item 3, the footprint mismatch warning.
- The keep-out is the footprint courtyard's rectangle, not Espressif's drawing.
- No RF measurement is possible here; antenna performance depends on the
  ground edge under the module and is unverified.
- USB runs 40 mm over a bottom layer that is otherwise the ground pour.
- Not built.
