# Reference values: what was read and what was not

A board's circuit is only as good as the document it was taken from. This
records, per board, whether the values were read from the vendor document or
written from memory of it.

| Board | Document | Status |
|-------|----------|--------|
| 01 `ldo_breakout` | Advanced Monolithic Systems AMS1117 datasheet (ds1117.pdf, read 2026-11-14) | **Verified; one board changed.** The output capacitor is "22 uF solid tantalum" for stability; the board had a ceramic, now a tantalum (EIA-3528). The datasheet shows no input capacitor; the 10 uF remembered as one is the adjust-pin bypass, so C1 is a design choice. SOT-223 dissipation is limited to 1.2 W: about 0.7 A at 5 V in, not the 1 A headline. |
| 02 `rp2040_min` | Raspberry Pi, "Hardware design with RP2040" | **Read 2026-11-14.** Matches: 100 nF per supply pin, 1 uF on VREG_IN and VREG_OUT, 12 MHz ABM8-272-T3 (CL 10 pF) with 15 pF load caps and a 1 kohm series resistor, 27 ohm USB series resistors close to the chip, 1 kohm to the USB_BOOT switch. The guide shares one capacitor between pins 48 and 49; this board gives each its own. |
| 03 `tps54202_buck` | TI TPS54202 datasheet SLVSD26C | **Read 2026-11-14.** Every value is Figure 7-1's. |
| 04, 06 `stm32f103_*` | ST AN2586 Rev 8 (December 2022), read 2026-11-15 | **Verified; both boards changed.** VDDA takes "100 nF ceramic + 1 µF" (section 2.2); the boards had 10 nF + 1 uF, now C6 is 100 nF. Matches: one 100 nF per VDD pin plus a bulk capacitor of "min. 4.7 µF, typ. 10 µF" (4.7 uF here); VBAT tied to VDD when no battery is used; 100 nF on NRST (may be reduced to 10 nF to save power); 10 kohm on BOOT0 and BOOT1 (given as a typical example); HSE 4 to 16 MHz with CL = CL1 x CL2 / (CL1 + CL2) + Cstray, Cstray 2 to 7 pF, so 12 pF caps for a 10 pF crystal at 4 pF stray. Section 2.2 also asks for 100 nF on VBAT when tied to VDD; here VBAT (pin 1) shares C5 with VDD pin 48 beside it. AN2586 says nothing about USB: the 1.5 kohm D+ pull-up is the USB 2.0 full-speed signalling pull-up (the F103 has none inside), and the 22 ohm series resistors are a design choice. |
| 05 `esp32c3_min` | Espressif ESP32-C3 hardware design guidelines, schematic checklist | **Read 2026-11-14.** Matches: 10 uF + 0.1 uF at the supply, at least 500 mA, EN 10 kohm / 1 uF, GPIO9 pulled up with a boot switch, GPIO2 and GPIO8 pulled up, GPIO19 = D+, GPIO18 = D-. **One discrepancy found and fixed:** the checklist says to reserve 22-33 ohm series resistors on the USB lines close to the chip; the board had none. R8 and R9 (22 ohm) added. |
| impedance figures | jlcpcb.com/impedance | **Read 2026-11-14.** Prepreg thickness, dielectric constant and copper weights of both 4-layer stackups match `boardwright/si.py`. |

Every board's document has now been read. Three of them changed a board
(the AMS1117 datasheet, the ESP32-C3 checklist and AN2586): a value written
from memory of a document is a value to check.
