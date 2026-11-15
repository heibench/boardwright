"""STM32F103C8 dev board on four layers: signal / GND / GND / signal.

Same circuit as stm32f103_min. The two inner layers are unbroken ground
planes, so every trace on either outer layer has a reference under it.

Reference: ST AN2586 "Getting started with STM32F10xxx hardware development"
(supply decoupling scheme, reset, boot pins, HSE) and the STM32F103x8
datasheet power-supply scheme. USB front end as on rp2040_min.
"""

from boardwright.circuit import Circuit
from boardwright.placement import pad_at

NAME = "stm32f103_4l"
LAYERS = 4
PLANES = {"In1.Cu": "GND", "In2.Cu": "GND"}
W, H = 30.6, 62

R = "Resistor_SMD:R_0402_1005Metric"
C = "Capacitor_SMD:C_0402_1005Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
LED = "LED_SMD:LED_0603_1608Metric"
SW = "Button_Switch_SMD:SW_SPST_EVQP0"
G, V = "GND", "+3V3"

CIRCUIT = c = Circuit("STM32F103C8 four-layer")

# --- USB-C, device only
c.add("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C",
      "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
      {"A1": G, "B1": G, "A12": G, "B12": G, "SH": G,
       "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
       "A5": "CC1", "B5": "CC2", "A6": "USB_DP_C", "B6": "USB_DP_C",
       "A7": "USB_DM_C", "B7": "USB_DM_C", "A8": None, "B8": None})
c.add("R1", "Device:R", "5.1k", R, {1: "CC1", 2: G})
c.add("R2", "Device:R", "5.1k", R, {1: "CC2", 2: G})
c.add("U3", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
      {1: "USB_DP_C", 6: "USB_DP_C", 3: "USB_DM_C", 4: "USB_DM_C", 2: G, 5: "VBUS"})
c.add("R3", "Device:R", "22", R, {1: "USB_DP_C", 2: "PA12"})
c.add("R4", "Device:R", "22", R, {1: "USB_DM_C", 2: "PA11"})
c.add("R5", "Device:R", "1.5k", R, {1: V, 2: "PA12"})      # F103 has no internal D+ pull-up

# --- 3.3 V
c.add("U2", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5",
      {1: "VBUS", 2: G, 3: "VBUS", 4: None, 5: V})
c.add("C1", "Device:C", "10u", C0805, {1: "VBUS", 2: G})
c.add("C2", "Device:C", "10u", C0805, {1: V, 2: G})

# --- MCU. VBAT and VDDA tied to VDD (AN2586 allows both when unused / no filter).
mcu = {1: V, 24: V, 36: V, 48: V, 9: V, 23: G, 35: G, 47: G, 8: G,
       2: "PC13", 3: "PC14", 4: "PC15", 5: "OSC_IN", 6: "OSC_OUT", 7: "NRST",
       20: "BOOT1", 44: "BOOT0"}
for i, pin in enumerate(range(10, 18)):
    mcu[pin] = f"PA{i}"                                   # PA0-7 = 10-17
mcu.update({18: "PB0", 19: "PB1", 21: "PB10", 22: "PB11", 25: "PB12", 26: "PB13", 27: "PB14", 28: "PB15",
            29: "PA8", 30: "PA9", 31: "PA10", 32: "PA11", 33: "PA12", 34: "SWDIO", 37: "SWCLK",
            38: "PA15", 39: "PB3", 40: "PB4", 41: "PB5", 42: "PB6", 43: "PB7", 45: "PB8", 46: "PB9"})
c.add("U1", "MCU_ST_STM32F1:STM32F103C8Tx", "STM32F103C8T6", "Package_QFP:LQFP-48_7x7mm_P0.5mm", mcu)

# decoupling per AN2586: 100n per VDD/VSS pair + one 4.7u; VDDA 100n + 1u (AN2586 Rev 8, 2.2)
for ref, val in [("C3", "100n"), ("C4", "100n"), ("C5", "100n"), ("C6", "100n"), ("C7", "1u")]:
    c.add(ref, "Device:C", val, C, {1: V, 2: G})
c.add("C9", "Device:C", "4.7u", C0805, {1: V, 2: G})

# --- HSE 8 MHz, CL = 10 pF crystal assumed: C = 2 * (CL - ~4 pF stray) = 12 pF
c.add("Y1", "Device:Crystal_GND24", "8MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
      {1: "OSC_IN", 3: "OSC_OUT", 2: G, 4: G})
c.add("C10", "Device:C", "12p", C, {1: "OSC_IN", 2: G})
c.add("C11", "Device:C", "12p", C, {1: "OSC_OUT", 2: G})

# --- reset and boot
c.add("C12", "Device:C", "100n", C, {1: "NRST", 2: G})
c.add("SW2", "Switch:SW_Push", "RESET", SW, {1: "NRST", 2: G})
c.add("R6", "Device:R", "10k", R, {1: "BOOT0", 2: G})
c.add("SW1", "Switch:SW_Push", "BOOT0", SW, {1: "BOOT0", 2: V})
c.add("R7", "Device:R", "10k", R, {1: "BOOT1", 2: G})

# --- LEDs
c.add("R8", "Device:R", "1k", R, {1: V, 2: "LED_PWR"})
c.add("D1", "Device:LED", "PWR", LED, {1: G, 2: "LED_PWR"})
c.add("R9", "Device:R", "1k", R, {1: V, 2: "LED_USR"})
c.add("D2", "Device:LED", "PC13", LED, {1: "PC13", 2: "LED_USR"})   # PC13 sinks

# --- headers
H20 = "Connector_PinHeader_2.54mm:PinHeader_1x20_P2.54mm_Vertical"
left = [V, "PC13", "PC14", "PC15", "PA0", "PA1", "PA2", "PA3", "PA4", "PA5", "PA6", "PA7",
        "PB0", "PB1", "PB10", "PB11", "NRST", V, G, G]
right = [V, G, "VBUS", "PB9", "PB8", "PB7", "PB6", "PB5", "PB4", "PB3", "PA15", None, None,       # PA12/PA11 are USB only: no header stubs
         "PA10", "PA9", "PA8", "PB15", "PB14", "PB13", "PB12"]
c.add("J2", "Connector_Generic:Conn_01x20", "LEFT", H20, {i + 1: n for i, n in enumerate(left)})
c.add("J3", "Connector_Generic:Conn_01x20", "RIGHT", H20, {i + 1: n for i, n in enumerate(right)})
c.add("J4", "Connector_Generic:Conn_01x04", "SWD", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
      {1: V, 2: "SWDIO", 3: "SWCLK", 4: G})

c.groups = [
    ["J1", "U3", "R1", "R2", "R3", "R4", "R5", "U2", "C1", "C2", "R8", "D1"],
    ["U1", "C3", "C4", "C5", "C6", "C7", "C9"],
    ["Y1", "C10", "C11", "C12", "SW2", "R6", "SW1", "R7", "R9", "D2"],
    ["J2", "J3", "J4"],
]

# LQFP-48 at rot 0: pins 1-12 left (top to bottom), 13-24 bottom, 25-36 right, 37-48 top.
UX, UY = 14.5, 34
PLACE = {
    "J1": (14, 3, 180), "R1": (7.6, 8.6, 90), "R2": (20.4, 8.6, 90),
    "U3": (14, 9.8, 0), # USB series resistors beside pins 33/32 so D+ and D- leave the MCU as a mirrored pair
    "R3": pad_at(2, (20.525, 32.3), rot=180), "R4": pad_at(2, (20.525, 33.7), rot=180),
    "R5": pad_at(2, (20.525, 31.38), rot=270),
    "U2": (8.5, 14.5, 0), "C1": (7.2, 18.3, 0), "C2": (11.6, 18.3, 0),
    "SW1": (9.6, 23.3, 0), "SW2": (20.0, 23.3, 0),
    "R6": (12.4, 27.4, 0),
    "U1": (UX, UY, 0),
    # decouplers on the bottom, under the body, beside the pin pair they serve
    # each decoupler: its +3V3 pad a fixed step in from the VDD pin it serves
    "C3": pad_at(1, ("U1", 24), dx=0.23, dy=-1.66, rot=180, side="B"),
    "C4": pad_at(1, ("U1", 36), dx=-1.66, dy=-0.23, rot=270, side="B"),
    "C5": pad_at(1, ("U1", 48), dx=-0.23, dy=1.66, rot=0, side="B"),
    "C6": pad_at(1, ("U1", 9), dx=1.56, dy=0.23, rot=90, side="B"),
    "C7": pad_at(1, ("U1", 9), dx=2.86, dy=0.23, rot=90, side="B"),
    "C9": (UX + 0.6, UY + 0.2, 90, "B"),
    "Y1": (6.6, 33.5, 180), "C10": (7.6, 30.6, 0), "C11": (5.9, 36.4, 0),
    "C12": (7.4, 39.4, 0), "R7": (15.25, 41.2, 90),
    "R9": (22.5, 43, 0), "D2": (22.5, 45, 0), "R8": (22.5, 48.5, 0), "D1": (22.5, 50.5, 0),
    "J2": (2.6, 11, 0), "J3": (28.0, 11, 0), "J4": (10.2, 58, 90),
}
FR_PASSES = 200
FR_BOTTOM_COST = 20         # keep the autorouter on top; the bottom is the ground plane
CLASSES = {"Default": (0.15, 0.2, 0.6, 0.3), "Power": (0.15, 0.3, 0.6, 0.3, ["VBUS", V, G])}
# USB from the ESD part to the series resistors: a matched pair on the bottom,
# under the switches, so the header fan-out on top never has to cross it.
# a ground via beside every USB via, so the return current can change planes with the signal
GND_VIAS = [("GND", 18.8, 8.4), ("GND", 22.0, 10.0), ("GND", 16.0, 8.0), ("GND", 16.4, 12.3),
            ("GND", 21.7, 31.3), ("GND", 22.5, 35.0),
            ("GND", 12.55, 33.6),          # shared by the two VDDA decouplers, 1.1 mm from each
            ("GND", 15.7, 36.5), ("GND", 16.1, 32.0), ("GND", 13.3, 31.5)]   # one beside each VDD decoupler
VIAS = GND_VIAS + [("USB_DM_C", 14.75, 8.0), ("USB_DM_C", 16.2, 10.75),     # B7 joins D- through the bottom
        ("USB_DP_C", 17.4, 9.4), ("USB_DM_C", 21.0, 10.75), ("USB_DP_C", 22.5, 32.3), ("USB_DM_C", 22.5, 33.7)]
TRACKS = [
    # connector to ESD part: A6/A7 run down the channel between U3's pad columns
    ("USB_DP_C", [(14.25, 6.68), (14.2, 7.5), (14.2, 8.85), (15.137, 8.85)], 0.2, "F.Cu"),
    ("USB_DP_C", [(13.25, 6.68), (13.25, 8.85), (12.863, 8.85)], 0.2, "F.Cu"),
    ("USB_DM_C", [(13.75, 6.68), (13.8, 7.5), (13.8, 10.75), (12.863, 10.75)], 0.2, "F.Cu"),
    ("USB_DM_C", [(13.8, 10.75), (15.137, 10.75)], 0.2, "F.Cu"),
    ("USB_DM_C", [(14.75, 6.68), (14.75, 8.0)], 0.2, "F.Cu"),
    ("USB_DM_C", [(14.75, 8.0), (16.2, 9.45), (16.2, 10.75)], 0.2, "B.Cu"),
    ("USB_DP_C", [(15.137, 8.85), (16.85, 8.85), (17.4, 9.4)], 0.2, "F.Cu"),
    ("USB_DM_C", [(15.137, 10.75), (16.2, 10.75), (21.0, 10.75)], 0.2, "F.Cu"),
    ("USB_DP_C", [(17.4, 9.4), (18.6, 9.4), (24.6, 15.4), (24.6, 30.2), (22.5, 32.3)], 0.2, "B.Cu"),
    ("USB_DM_C", [(21.0, 10.75), (25.3, 15.05), (25.3, 30.9), (22.5, 33.7)], 0.2, "B.Cu"),
    ("USB_DP_C", [(22.5, 32.3), (21.48, 32.3)], 0.2, "F.Cu"),
    ("USB_DM_C", [(22.5, 33.7), (21.48, 33.7)], 0.2, "F.Cu"),
    ("PA12", [(18.662, 32.75), (19.6, 32.75), (20.05, 32.3), (20.52, 32.3)], 0.2, "F.Cu"),
    ("PA11", [(18.662, 33.25), (19.6, 33.25), (20.05, 33.7), (20.52, 33.7)], 0.2, "F.Cu"),
    ("PA12", [(20.52, 31.38), (20.52, 32.3)], 0.2, "F.Cu"),            # D+ pull-up stub
    # OSC_OUT passes between the crystal's pads instead of going round it
    ("OSC_OUT", [(10.338, 33.75), (8.9, 33.75), (8.65, 33.5), (6.3, 33.5), (5.9, 33.9), (5.5, 34.35)], 0.2, "F.Cu"),
]
TEXT = [("STM32F103 4L", 14, 53.5, 1.0), ("SWD", 14, 55.5, 0.8)]

REVIEW = {
    # each decoupler reaches the planes through a via of its own, not a shared one somewhere else
    "via_near": [("C3.2", 1.5), ("C4.2", 1.5), ("C5.2", 1.5), ("C6.2", 1.5), ("C7.2", 1.5), ("C9.2", 2.0)],
    "coverage": {"B.Cu": 0.65},        # the bottom has to stay a ground plane
    "near": [("C3.1", "U1.24", 2.5), ("C4.1", "U1.36", 2.5), ("C5.1", "U1.48", 2.5), ("C6.1", "U1.9", 2.5),
             ("Y1.1", "U1.5", 4.0), ("C10.1", "Y1.1", 3.0), ("C11.1", "Y1.3", 3.0), ("C12.1", "U1.7", 7.0)],
    "maxlen": {"OSC_IN": 8, "OSC_OUT": 10},
    # PA12 carries the 0.9 mm pull-up stub, hence 1.5 and not 0
    # full-speed USB only: 5 mm of skew is about 30 ps against edges of 4 ns or slower
    # real routed paths, connector pad to series resistor, for both plug orientations
    "match": [([("J1.A6", "R3.1"), ("J1.A7", "R4.1"), ("J1.B6", "R3.1"), ("J1.B7", "R4.1")], 5.0),
              ([("U1.33", "R3.2"), ("U1.32", "R4.2")], 0.5)],
    # every USB trace must have ground on the adjacent inner layer, and each of its vias a ground via nearby
    "ref": [(["USB_DP_C", "USB_DM_C", "PA11", "PA12"], 1.0)],   # 1 mm: the clearance hole of a neighbouring via
    "via_gnd": 2.0,
}
