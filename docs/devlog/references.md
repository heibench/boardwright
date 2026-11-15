# Reference values: what was read and what was not

A board's circuit is only as good as the document it was taken from. This
records, per board, whether the values were read from the vendor document or
written from memory of it.

| Board | Document | Status |
|-------|----------|--------|
| 01 `ldo_breakout` | Advanced Monolithic Systems AMS1117 datasheet (ds1117.pdf, read 2026-11-14) | **Verified; one board changed.** The output capacitor is "22 uF solid tantalum" for stability; the board had a ceramic, now a tantalum (EIA-3528). The datasheet shows no input capacitor; the 10 uF remembered as one is the adjust-pin bypass, so C1 is a design choice. SOT-223 dissipation is limited to 1.2 W: about 0.7 A at 5 V in, not the 1 A headline. |
| 02 `rp2040_min` | Raspberry Pi, "Hardware design with RP2040" | **Read 2026-11-14.** Matches: 100 nF per supply pin, 1 uF on VREG_IN and VREG_OUT, 12 MHz ABM8-272-T3 (CL 10 pF) with 15 pF load caps and a 1 kohm series resistor, 27 ohm USB series resistors close to the chip, 1 kohm to the USB_BOOT switch. The guide shares one capacitor between pins 48 and 49; this board gives each its own. |
| 03 `tps54202_buck` | TI TPS54202 datasheet SLVSD26C | **Read 2026-11-14.** Every value is Figure 7-1's. |
| 04, 06 `stm32f103_*` | ST AN2586 | **Not verified.** st.com timed out on fetch and froze in a browser; on 2026-11-14 a scripted download failed again (HTTP/2 stream reset, then no bytes in 90 s over HTTP/1.1). Values are from memory. |
| 05 `esp32c3_min` | Espressif ESP32-C3 hardware design guidelines, schematic checklist | **Read 2026-11-14.** Matches: 10 uF + 0.1 uF at the supply, at least 500 mA, EN 10 kohm / 1 uF, GPIO9 pulled up with a boot switch, GPIO2 and GPIO8 pulled up, GPIO19 = D+, GPIO18 = D-. **One discrepancy found and fixed:** the checklist says to reserve 22-33 ohm series resistors on the USB lines close to the chip; the board had none. R8 and R9 (22 ohm) added. |
| impedance figures | jlcpcb.com/impedance | **Read 2026-11-14.** Prepreg thickness, dielectric constant and copper weights of both 4-layer stackups match `boardwright/si.py`. |

Reading the documents changed one board out of the three that could be read.
The two that could not be read are the ones to distrust.
