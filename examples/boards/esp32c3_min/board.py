"""ESP32-C3-WROOM-02 minimal dev board, native USB.

Reference: Espressif "ESP32-C3 Series Hardware Design Guidelines" (power
decoupling, EN RC delay, strapping pins, antenna keep-out) and the
ESP32-C3-WROOM-02 datasheet peripheral schematic. USB goes straight to the
chip's USB Serial/JTAG pins (IO18 D-, IO19 D+).
"""

from boardwright.circuit import Circuit
from boardwright.placement import pad_at

NAME = "esp32c3_min"
W, H = 30, 50

R = "Resistor_SMD:R_0402_1005Metric"
C = "Capacitor_SMD:C_0402_1005Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
LED = "LED_SMD:LED_0603_1608Metric"
SW = "Button_Switch_SMD:SW_SPST_EVQP0"
G, V = "GND", "+3V3"

CIRCUIT = c = Circuit("ESP32-C3-WROOM-02 minimal")

c.add("U1", "RF_Module:ESP32-C3-WROOM-02", "ESP32-C3-WROOM-02", "RF_Module:ESP32-C3-WROOM-02",
      {1: V, 2: "EN", 3: "IO4", 4: "IO5", 5: "IO6", 6: "IO7", 7: "IO8", 8: "IO9", 9: G,
       10: "IO10", 11: "IO20", 12: "IO21", 13: "USB_DM_M", 14: "USB_DP_M", 15: "IO3", 16: "IO2",
       17: "IO1", 18: "IO0", 19: G})
c.add("C3", "Device:C", "100n", C, {1: V, 2: G})
c.add("C4", "Device:C", "10u", C0805, {1: V, 2: G})

# EN: 10k pull-up + 1u to GND gives the power-up delay the guidelines ask for
c.add("R1", "Device:R", "10k", R, {1: V, 2: "EN"})
c.add("C5", "Device:C", "1u", C, {1: "EN", 2: G})
c.add("SW2", "Switch:SW_Push", "RESET", SW, {1: "EN", 2: G})
# strapping: IO9 low at reset = download boot; IO8 and IO2 must be high
c.add("SW1", "Switch:SW_Push", "BOOT", SW, {1: "IO9", 2: G})
c.add("R2", "Device:R", "10k", R, {1: V, 2: "IO9"})
c.add("R3", "Device:R", "10k", R, {1: V, 2: "IO8"})
c.add("R4", "Device:R", "10k", R, {1: V, 2: "IO2"})

# USB-C
c.add("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C",
      "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
      {"A1": G, "B1": G, "A12": G, "B12": G, "SH": G,
       "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
       "A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP",
       "A7": "USB_DM", "B7": "USB_DM", "A8": None, "B8": None})
c.add("R5", "Device:R", "5.1k", R, {1: "CC1", 2: G})
c.add("R6", "Device:R", "5.1k", R, {1: "CC2", 2: G})
c.add("U3", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
      {1: "USB_DP", 6: "USB_DP", 3: "USB_DM", 4: "USB_DM", 2: G, 5: "VBUS"})

# 3.3 V, 600 mA (guidelines: supply at least 500 mA)
c.add("U2", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5",
      {1: "VBUS", 2: G, 3: "VBUS", 4: None, 5: V})
c.add("C1", "Device:C", "10u", C0805, {1: "VBUS", 2: G})
c.add("C2", "Device:C", "10u", C0805, {1: V, 2: G})

c.add("R7", "Device:R", "1k", R, {1: "IO7", 2: "LED_A"})
# USB series resistors close to the module: Espressif's schematic checklist says to
# reserve 22-33 ohm in series on D+ and D- (read from the document, 2026-11-14)
c.add("R8", "Device:R", "22", R, {1: "USB_DP_M", 2: "USB_DP"})
c.add("R9", "Device:R", "22", R, {1: "USB_DM_M", 2: "USB_DM"})
c.add("D1", "Device:LED", "IO7", LED, {1: G, 2: "LED_A"})

H10 = "Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical"
c.add("J2", "Connector_Generic:Conn_01x10", "LEFT", H10,
      {i + 1: n for i, n in enumerate(["VBUS", V, "EN", "IO4", "IO5", "IO6", "IO7", "IO8", "IO9", G])})
c.add("J3", "Connector_Generic:Conn_01x10", "RIGHT", H10,
      {i + 1: n for i, n in enumerate([G, "IO0", "IO1", "IO2", "IO3", "IO10", "IO20", "IO21", V, G])})

c.groups = [["J1", "U3", "R5", "R6", "R8", "R9", "U2", "C1", "C2"],
            ["U1", "C3", "C4", "R1", "C5", "SW2", "SW1", "R2", "R3", "R4"],
            ["J2", "J3", "R7", "D1"]]

MX, MY = 15, 14.5        # module centre; antenna end at the top edge of the board
PLACE = {
    "U1": (MX, MY, 0),
    "C3": (8.4, 9.4, 0, "B"), "C4": (10.5, 11.6, 0, "B"),
    "J2": (2.3, 12, 0), "J3": (27.7, 12, 0),
    "R1": (7.0, 23.4, 0), "R2": (10.2, 23.4, 0), "R3": (10.2, 24.8, 0),
    "C5": (7.6, 11.0, 0, "B"),               # EN capacitor under the EN pin
    "R4": (20.5, 23.4, 0), "R7": (20.5, 24.8, 0), "D1": (23.6, 24.8, 0),
    # on the bottom, straight under each USB via, module-side pad up
    "R8": pad_at(1, (24.6, 15.12), toward=(24.6, 17.0), side="B"),
    "R9": pad_at(1, (25.9, 16.62), toward=(25.9, 18.5), side="B"),
    "SW1": (9, 29.5, 0), "SW2": (21, 29.5, 0),
    "U2": (8.5, 36, 0), "C1": (6.4, 39.8, 0), "C2": (10.6, 39.8, 0),
    "U3": (15, 39.5, 180),      # centred over the connector: D+/D- run up between its pad columns
    "R5": (8.3, 43.6, 90), "R6": (21.7, 43.6, 90),
    "J1": (15, 47, 0),
}
# Antenna keep-out: no copper on any layer under and beside the antenna
# (the footprint courtyard marks it: full board width, module top to 6.85 mm above centre).
KEEPOUTS = [(("F.Cu", "B.Cu"), [(0, 0), (W, 0), (W, MY - 6.85), (0, MY - 6.85)])]
# USB as a matched pair on the bottom: the module's USB pins face the right-hand
# header, and every other right-side pin has to cross to that header on top.
VIAS = [("USB_DP_M", 24.6, 14.5), ("USB_DM_M", 25.9, 16.0), ("USB_DP", 17.6, 40.45), ("USB_DM", 21.0, 38.45),
        ("USB_DM", 14.2, 41.6), ("USB_DM", 17.4, 38.45)]      # B7 joins D- through the bottom
TRACKS = [
    ("USB_DP_M", [(23.75, 14.5), (24.6, 14.5)], 0.25, "F.Cu"),
    ("USB_DM_M", [(23.75, 16.0), (25.9, 16.0)], 0.25, "F.Cu"),
    ("USB_DP_M", [(24.6, 14.5), (24.6, 15.12)], 0.25, "B.Cu"),          # via to resistor
    ("USB_DM_M", [(25.9, 16.0), (25.9, 16.62)], 0.25, "B.Cu"),
    ("USB_DP", [(24.6, 16.14), (24.9, 16.5), (24.9, 33.15), (17.6, 40.45)], 0.25, "B.Cu"),
    ("USB_DM", [(25.9, 17.64), (25.6, 17.95), (25.6, 33.85), (21.0, 38.45)], 0.25, "B.Cu"),
    ("USB_DP", [(17.6, 40.45), (16.137, 40.45)], 0.2, "F.Cu"),
    ("USB_DM", [(21.0, 38.45), (17.4, 38.45), (16.6, 38.45), (16.137, 38.55)], 0.2, "F.Cu"),
    # ESD part to connector
    # 0.15 mm in the channel: two tracks and three 0.2 mm clearances have to fit in 0.95 mm
    ("USB_DP", [(14.75, 43.32), (14.8, 42.4), (14.8, 40.45), (13.863, 40.45)], 0.15, "F.Cu"),
    ("USB_DP", [(15.75, 43.32), (15.75, 41.2), (16.137, 40.8), (16.137, 40.45)], 0.2, "F.Cu"),
    ("USB_DM", [(15.25, 43.32), (15.2, 42.4), (15.2, 38.55), (16.137, 38.55)], 0.15, "F.Cu"),
    ("USB_DM", [(15.2, 38.55), (13.863, 38.55)], 0.2, "F.Cu"),
    ("USB_DM", [(14.25, 43.32), (14.25, 42.4), (14.2, 41.6)], 0.2, "F.Cu"),
    ("USB_DM", [(14.2, 41.6), (17.35, 38.45), (17.4, 38.45)], 0.2, "B.Cu"),
]
RULES = {"min_through_hole_diameter": 0.2,     # the module footprint's own thermal vias are 0.2 mm
         # a through-hole GND pin is tied to the pour on both layers; one spoke per layer is enough
         "min_resolved_spokes": 1}
# KiCad reports the module footprint as differing from its library copy after
# kicad-tools writes it; pad, line and property counts match. Unexplained: see docs/devlog/05.
SEVERITIES = {"lib_footprint_mismatch": "ignore"}
FR_PASSES = 100
FR_BOTTOM_COST = 20         # keep the autorouter on top; the bottom is the ground plane
CLASSES = {"Default": (0.2, 0.25, 0.6, 0.3), "Power": (0.2, 0.4, 0.6, 0.3, ["VBUS", V, G])}
TEXT = [("ESP32-C3 min", 15, 34.5, 1.2, "B.SilkS"), ("BOOT", 9, 29.5, 1.0, "B.SilkS"), ("RST", 21, 29.5, 1.0, "B.SilkS")]
REVIEW = {
    "coverage": {"B.Cu": 0.6},         # of the whole board; the antenna strip is 15% and bare
    "near": [("C3.1", "U1.1", 3.5), ("C4.1", "U1.1", 6.0), ("C5.1", "U1.2", 4.0),
             ("R8.1", "U1.14", 3.0), ("R9.1", "U1.13", 3.0)],            # series resistors "close to the chip"
    # full-speed USB only: 5 mm of skew is about 30 ps against edges of 4 ns or slower
    "match": [([("J1.A6", "R8.2"), ("J1.A7", "R9.2"), ("J1.B6", "R8.2"), ("J1.B7", "R9.2")], 5.0),
              ([("U1.14", "R8.1"), ("U1.13", "R9.1")], 2.0)],
}
