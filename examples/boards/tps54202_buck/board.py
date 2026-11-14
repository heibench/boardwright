"""TI TPS54202 buck, 8-28 V in -> 5 V / 2 A.

Reference: TPS54202 datasheet (SLVSD26C) Figure 7-1 "5V, 2A Reference Design"
and section 7.4 layout guidelines. Designators follow the figure.
"""

from boardwright.circuit import Circuit

NAME = "tps54202_buck"
W, H = 58, 36

R = "Resistor_SMD:R_0603_1608Metric"
C = "Capacitor_SMD:C_0603_1608Metric"
TB = "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"
G = "GND"

CIRCUIT = c = Circuit("TPS54202 5V 2A buck")
c.add("J1", "Connector:Screw_Terminal_01x02", "VIN 8-28V", TB, {1: "VIN", 2: G})
c.add("J2", "Connector:Screw_Terminal_01x02", "VOUT 5V", TB, {1: "VOUT", 2: G})
c.add("U1", "Regulator_Switching:TPS54202DDC", "TPS54202", "Package_TO_SOT_SMD:SOT-23-6",
      {1: G, 2: "SW", 3: "VIN", 4: "FB", 5: "EN", 6: "BOOT"})
c.add("C1", "Device:C", "10u 35V", "Capacitor_SMD:C_1210_3225Metric", {1: "VIN", 2: G})
c.add("C2", "Device:C", "100n 50V", C, {1: "VIN", 2: G})
c.add("C3", "Device:C", "100n", C, {1: "BOOT", 2: "SW"})
c.add("L1", "Device:L", "15u 3A", "Inductor_SMD:L_Bourns_SRN6045TA", {1: "SW", 2: "VOUT"})
c.add("C4", "Device:C", "22u 16V", "Capacitor_SMD:C_1206_3216Metric", {1: "VOUT", 2: G})
c.add("C5", "Device:C", "22u 16V", "Capacitor_SMD:C_1206_3216Metric", {1: "VOUT", 2: G})
c.add("R1", "Device:R", "49.9", R, {1: "VOUT", 2: "VSENSE"})     # loop-injection resistor
c.add("R2", "Device:R", "100k", R, {1: "VSENSE", 2: "FB"})
c.add("R3", "Device:R", "13.3k", R, {1: "FB", 2: G})
c.add("C6", "Device:C", "75p", C, {1: "VSENSE", 2: "FB"})        # feed-forward
c.add("R4", "Device:R", "511k", R, {1: "VIN", 2: "EN"})          # UVLO divider
c.add("R5", "Device:R", "105k", R, {1: "EN", 2: G})
c.add("R6", "Device:R", "2.2k", R, {1: "VOUT", 2: "LED_A"})
c.add("D1", "Device:LED", "PWR", "LED_SMD:LED_0603_1608Metric", {2: "LED_A", 1: G})
for i in range(1, 5):
    c.add(f"H{i}", "Mechanical:MountingHole", "M3", "MountingHole:MountingHole_3.2mm_M3", {}, bom=False)
c.groups = [["J1", "C1", "C2", "R4", "R5"], ["U1", "C3", "L1", "C4", "C5", "J2"],
            ["R1", "R2", "R3", "C6"], ["R6", "D1", "H1", "H2", "H3", "H4"]]

UX, UY = 24, 18
PLACE = {
    "H1": (4, 4, 0), "H2": (54, 4, 0), "H3": (4, 32, 0), "H4": (54, 32, 0),
    "J1": (7, 13, 270), "J2": (50, 20.5, 90),
    "U1": (UX, UY, 180),                 # VIN/SW/GND pins face the power stage
    "C1": (27.8, 18, 270),               # across the VIN/GND pins; SW runs under the body
    "C2": (31.6, 15.9, 0),
    "L1": (34.5, 23.5, 0),
    "C4": (39.6, 20.5, 90), "C5": (42.2, 20.5, 90),
    "C3": (23.8, 21.0, 0),
    # FB network hugs pin 4, below the VIN polygon so nothing has to cross it
    "R2": (20.3, 17.2, 0), "C6": (20.3, 15.7, 0), "R3": (20.3, 18.8, 180), "R1": (17.0, 16.4, 0),
    "R4": (13.8, 16.4, 270), "R5": (13.8, 19.5, 270),
    "R6": (44, 28.3, 0), "D1": (47.5, 28.3, 180),
}
CLASSES = {"Default": (0.2, 0.25, 0.6, 0.3),
           "Power": (0.2, 0.4, 0.8, 0.4, ["VIN", "VOUT", "SW", "GND"])}
# 0.4 mm traces only guarantee connectivity; the ZONES below carry the current.

# Power copper as polygons (datasheet 7.4.1: VIN/GND wide, SW short and wide).
ZONES = [
    ("VIN", "F.Cu", [(5, 11.2), (31.3, 11.2), (31.3, 16.5), (29.3, 17.2), (24.4, 17.4), (24.4, 14.6), (5, 14.6)]),
    ("SW", "F.Cu", [(24.4, 17.6), (33.6, 17.6), (33.6, 26.1), (31.2, 26.1), (31.2, 18.4), (24.4, 18.4)]),
    ("VOUT", "F.Cu", [(35.4, 20.6), (48.4, 20.6), (48.4, 19.0), (51.6, 19.0), (51.6, 26.1), (35.4, 26.1)]),
]
POURS = [("GND", ("F.Cu", "B.Cu"), True)]      # solid pad connections: this is a power board
# GND stitching next to every power-loop return.
VIAS = [("GND", x, y, 0.8, 0.4) for x, y in
        [(27.2, 21.3), (29.0, 21.3), (33.8, 15.9), (39.6, 17.0), (42.2, 17.0), (40.9, 17.0)]]
# Hand-routed (fixed before the autorouter runs): the VOUT sense line taps the
# output caps and runs round the quiet side on top, so it neither crosses the
# VIN polygon nor cuts the bottom GND plane under the power stage.
TRACKS = [
    ("VOUT", [(16.175, 16.4), (15.3, 16.4), (15.3, 29.5), (40.9, 29.5), (40.9, 25.0)], 0.25, "F.Cu"),
    ("VOUT", [(43.175, 28.3), (43.175, 25.5)], 0.25, "F.Cu"),
    ("VIN", [(13.8, 15.575), (13.8, 13.0)], 0.4, "F.Cu"),
    # power skeleton: every pad of the power loop is joined by hand; ZONES add the copper
    ("VIN", [(7, 13), (26.0, 13), (27.8, 14.8), (27.8, 16.525), (25.137, 17.05)], 0.5, "F.Cu"),
    ("VIN", [(27.8, 14.8), (30.825, 14.8), (30.825, 15.9)], 0.5, "F.Cu"),
    ("SW", [(25.137, 18), (31.6, 18), (32.425, 18.8), (32.425, 23.5)], 0.5, "F.Cu"),
    ("VOUT", [(36.575, 23.5), (39.6, 23.5), (39.6, 21.975)], 0.5, "F.Cu"),
    ("VOUT", [(39.6, 23.5), (42.2, 23.5), (42.2, 21.975)], 0.5, "F.Cu"),
    ("VOUT", [(42.2, 23.5), (50, 23.5), (50, 20.5)], 0.5, "F.Cu"),
    ("GND", [(25.137, 18.95), (26.4, 19.475), (27.8, 19.475)], 0.5, "F.Cu"),
    ("GND", [(32.375, 15.9), (33.8, 15.9)], 0.5, "F.Cu"),
    ("GND", [(27.2, 21.3), (27.8, 19.475), (29.0, 21.3)], 0.5, "F.Cu"),
    ("GND", [(39.6, 19.025), (39.6, 17.0), (42.2, 17.0), (42.2, 19.025)], 0.5, "F.Cu"),
]
TEXT = [("VIN 8-28V", 9, 8, 1.0), ("GND", 7, 23, 1.0), ("5V 2A", 49, 32, 1.0), ("GND", 50, 12, 1.0),
        ("TPS54202 buck", 28, 31, 1.2)]

REVIEW = {
    # the power path, hop by hop: 2 A out, at most about 1.5 A in at 8 V
    "current": [("J1.1", "C1.1", 1.5), ("C1.1", "U1.3", 1.5), ("U1.2", "L1.1", 2.0),
                ("L1.2", "C4.1", 2.0), ("C4.1", "C5.1", 2.0), ("C5.1", "J2.1", 2.0)],
    "coverage": {"B.Cu": 0.85},        # unbroken return plane under the power stage
    "near": [("C1.1", "U1.3", 3.5), ("C1.2", "U1.1", 3.5),      # input loop
             ("C3.1", "U1.6", 3.5), ("R2.2", "U1.4", 3.0), ("R3.1", "U1.4", 3.0)],
    "maxlen": {"FB": 8, "BOOT": 6},                             # small, quiet FB node
}
