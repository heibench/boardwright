"""Rung 2: USB-C RP2040 board, per the RP2040 minimal design guide.

USB-C (5.1k CC pull-downs, USBLC6 ESD, 27R series) -> AP2112K-3.3 ->
RP2040 + W25Q128 QSPI flash + 12 MHz crystal, BOOTSEL and RESET buttons,
SWD header, 2x10 GPIO header, power header, power LED and GPIO25 LED.
"""

from boardwright.circuit import Circuit

NAME = "rp2040_min"
W, H = 60, 46

R = "Resistor_SMD:R_0402_1005Metric"
C = "Capacitor_SMD:C_0402_1005Metric"
C10U = "Capacitor_SMD:C_0805_2012Metric"
LED = "LED_SMD:LED_0603_1608Metric"
SW = "Button_Switch_SMD:SW_SPST_EVQP0"

CIRCUIT = c = Circuit("RP2040 minimal")
G = "GND"

# --- USB-C input
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
c.add("R3", "Device:R", "27", R, {1: "USB_DP_C", 2: "USB_DP"})
c.add("R4", "Device:R", "27", R, {1: "USB_DM_C", 2: "USB_DM"})

# --- 3.3 V LDO
c.add("U2", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5",
      {1: "VBUS", 2: G, 3: "VBUS", 4: None, 5: "+3V3"})
c.add("C1", "Device:C", "10u", C10U, {1: "VBUS", 2: G})
c.add("C2", "Device:C", "10u", C10U, {1: "+3V3", 2: G})

# --- RP2040
rp = {"1": "+3V3", "10": "+3V3", "22": "+3V3", "33": "+3V3", "42": "+3V3", "49": "+3V3",
      "43": "+3V3", "44": "+3V3", "48": "+3V3",           # ADC_AVDD, VREG_VIN, USB_VDD
      "45": "+1V1", "23": "+1V1", "50": "+1V1",           # VREG_VOUT -> DVDD
      "57": G, "19": G,                                   # EP, TESTEN
      "20": "XIN", "21": "XOUT_R",
      "24": "SWCLK", "25": "SWDIO", "26": "RUN",
      "46": "USB_DM", "47": "USB_DP",
      "51": "QSPI_SD3", "52": "QSPI_SCLK", "53": "QSPI_SD0", "54": "QSPI_SD2",
      "55": "QSPI_SD1", "56": "QSPI_SS"}
for i in range(16):                                       # GPIO0..15 = pins 2-9, 11-18
    rp[str(i + 2 if i < 8 else i + 3)] = f"GPIO{i}"
for i, pin in zip(range(16, 26), [27, 28, 29, 30, 31, 32, 34, 35, 36, 37]):
    rp[str(pin)] = "GPIO25" if i == 25 else None          # GPIO16-24 unused
for i, pin in zip(range(26, 30), [38, 39, 40, 41]):
    rp[str(pin)] = f"GPIO{i}"
c.add("U1", "MCU_RaspberryPi:RP2040", "RP2040", "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm", rp)

# decoupling: one 100n per IOVDD (6), ADC_AVDD, USB_VDD; 1u on VREG_VIN, VREG_VOUT; 100n per DVDD (2)
DECAP = {"C3": ("+3V3", "100n"), "C4": ("+3V3", "100n"), "C5": ("+3V3", "100n"),
         "C6": ("+3V3", "100n"), "C7": ("+3V3", "100n"), "C8": ("+3V3", "100n"),
         "C9": ("+3V3", "100n"), "C10": ("+3V3", "100n"),
         "C11": ("+3V3", "1u"), "C12": ("+1V1", "1u"),
         "C13": ("+1V1", "100n"), "C14": ("+1V1", "100n")}
for ref, (net, val) in DECAP.items():
    c.add(ref, "Device:C", val, C, {1: net, 2: G})

# --- crystal
c.add("Y1", "Device:Crystal_GND24", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
      {1: "XIN", 3: "XOUT", 2: G, 4: G})
c.add("R5", "Device:R", "1k", R, {1: "XOUT_R", 2: "XOUT"})
c.add("C15", "Device:C", "15p", C, {1: "XIN", 2: G})
c.add("C16", "Device:C", "15p", C, {1: "XOUT", 2: G})

# --- flash + BOOTSEL
c.add("U4", "Memory_Flash:W25Q128JVS", "W25Q128JVS", "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm",
      {1: "QSPI_SS", 2: "QSPI_SD1", 3: "QSPI_SD2", 4: G, 5: "QSPI_SD0", 6: "QSPI_SCLK",
       7: "QSPI_SD3", 8: "+3V3"})
c.add("C17", "Device:C", "100n", C, {1: "+3V3", 2: G})
c.add("R6", "Device:R", "1k", R, {1: "QSPI_SS", 2: "BOOT"})
c.add("SW1", "Switch:SW_Push", "BOOTSEL", SW, {1: "BOOT", 2: G})

# --- reset
c.add("R7", "Device:R", "10k", R, {1: "+3V3", 2: "RUN"})
c.add("SW2", "Switch:SW_Push", "RESET", SW, {1: "RUN", 2: G})

# --- headers
c.add("J2", "Connector_Generic:Conn_01x03", "SWD", "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical",
      {1: "SWCLK", 2: G, 3: "SWDIO"})
gp = [f"GPIO{i}" for i in range(16)] + [f"GPIO{i}" for i in range(26, 30)]
c.add("J3", "Connector_Generic:Conn_02x10_Odd_Even", "GPIO", "Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical",
      {i + 1: n for i, n in enumerate(gp)})
c.add("J4", "Connector_Generic:Conn_01x04", "PWR", "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
      {1: "VBUS", 2: "+3V3", 3: G, 4: G})

# --- LEDs
c.add("R8", "Device:R", "1k", R, {1: "+3V3", 2: "LED_PWR"})
c.add("D1", "Device:LED", "PWR", LED, {1: G, 2: "LED_PWR"})
c.add("R9", "Device:R", "1k", R, {1: "GPIO25", 2: "LED_25"})
c.add("D2", "Device:LED", "GP25", LED, {1: G, 2: "LED_25"})

# Placement (board-relative mm). RP2040 at centre; QFN pins 1-14 left side,
# 15-28 bottom, 29-42 right, 43-56 top. All RP2040 decouplers sit on the
# BOTTOM side, just outside the pad ring, right under the pin they serve.
UX, UY = 30, 24
r1, r2 = 4.9, 6.1  # bottom-side decap rows, distance from chip centre
PLACE = {
    "J1": (37, 3, 180), "R1": (31, 9, 90), "R2": (43, 9, 90),
    "U3": (37, 9.5, 0),
    # USB series resistors sit over pins 47/46 so D+ and D- leave as a mirrored pair
    "R3": (30.6, 13.6, 270), "R4": (31.8, 13.6, 270),
    "U2": (50, 8, 0), "C1": (47, 12, 90), "C2": (53, 12, 90),
    "U1": (UX, UY, 0),
    # top edge pins 43-50 -> two bottom rows
    "C9": (33.4, UY - r1, 0, "B"), "C11": (31.4, UY - r1, 0, "B"), "C10": (29.4, UY - r1, 0, "B"),
    "C12": (32.4, UY - r2, 0, "B"), "C8": (30.4, UY - r2, 0, "B"), "C14": (28.4, UY - r2, 0, "B"),
    # left pins 1, 10
    "C3": (UX - r1, UY - 2.6, 90, "B"), "C4": (UX - r1, UY + 1.0, 90, "B"),
    # bottom pins 22, 23
    "C5": (29.0, UY + r1, 0, "B"), "C13": (31.2, UY + r2, 0, "B"),
    # right pins 33, 42
    "C6": (UX + r1, UY, 90, "B"), "C7": (UX + r1, UY - 3.6, 90, "B"),
    "U4": (21, 15, 0), "C17": (26.6, 13.1, 90),
    "Y1": (26.5, 31.5, 0), "R5": (31.5, 29.8, 90), "C15": (23, 31.5, 90), "C16": (30.5, 33, 0),
    "SW1": (9, 12, 0), "R6": (14.5, 17, 0),
    "R7": (45, 29, 0), "SW2": (51, 25, 0),
    "J2": (56.5, 33, 0), "J4": (3.5, 28, 0),
    "J3": (28, 41.5, 90),
    "R8": (10, 24, 0), "D1": (10, 27, 0),
    "R9": (45, 35, 0), "D2": (49, 35, 0),
}
TRACKS = [   # USB D+/D- from the series resistors to pins 47/46: mirrored, equal length
    ("USB_DP", [(30.6, 14.11), (30.6, 14.6), (31.0, 15.0), (31.0, 20.562)], 0.2, "F.Cu"),
    ("USB_DM", [(31.8, 14.11), (31.8, 14.6), (31.4, 15.0), (31.4, 20.562)], 0.2, "F.Cu"),
]
FR_PASSES = 200
# Freerouting necks tracks at the QFN; widening them back to 0.15 mm ate the
# clearance (0.1466 mm). 0.127 mm (5 mil) is the fab minimum, so allow it.
RULES = {"min_track_width": 0.127}
POWER = ["VBUS", "+3V3", "+1V1", "GND"]
CLASSES = {"Default": (0.15, 0.2, 0.6, 0.3), "Power": (0.15, 0.3, 0.6, 0.3, POWER)}

c.groups = [
    ["J1", "U3", "R1", "R2", "R3", "R4", "U2", "C1", "C2", "J4", "R8", "D1"],     # USB + power
    ["U1", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13", "C14"],  # MCU
    ["Y1", "R5", "C15", "C16", "U4", "C17", "R6", "SW1", "R7", "SW2"],            # clock, flash, boot
    ["J2", "J3", "R9", "D2"],                                                     # I/O
]

REVIEW = {
    "near": [("C12.1", "U1.45", 3.0), ("C11.1", "U1.44", 3.0), ("C9.1", "U1.48", 3.0),
             ("C3.1", "U1.1", 3.0), ("C5.1", "U1.22", 3.0), ("C6.1", "U1.33", 3.0),
             ("Y1.1", "U1.20", 6.5), ("C17.1", "U4.8", 3.0)],
    # The crystal cannot sit closer: GPIO12-15 leave the bottom pad row through
    # that gap on their way to the header (tried at 5 mm: 3 GPIOs unroutable).
    "maxlen": {"XIN": 14, "XOUT_R": 7},
    "skew": [("USB_DP", "USB_DM", 3.0), ("USB_DP_C", "USB_DM_C", 3.0)],
}
