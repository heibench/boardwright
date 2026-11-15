"""Rung 1: 5 V -> 3.3 V LDO breakout with power LED."""

from boardwright.circuit import Circuit

NAME = "ldo_breakout"
W, H = 30, 20

HDR2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
C0805 = "Capacitor_SMD:C_0805_2012Metric"

CIRCUIT = c = Circuit("LDO breakout")
c.add("J1", "Connector_Generic:Conn_01x02", "VIN", HDR2, {1: "VIN", 2: "GND"})
c.add("U1", "Regulator_Linear:AMS1117-3.3", "AMS1117-3.3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
      {1: "GND", 2: "+3V3", 3: "VIN"})
# Input capacitor: a design choice; the AMS1117 datasheet's Figure 1 shows none
# (its 10 uF is the adjust-pin bypass of the adjustable part).
c.add("C1", "Device:C", "10u", C0805, {1: "VIN", 2: "GND"})
# Output: "22 uF solid tantalum on the output will ensure stability for all
# operating conditions" (AMS1117 datasheet, Stability). The regulator needs the
# output capacitor's series resistance, which a ceramic part does not give.
c.add("C2", "Device:C_Polarized", "22u tantalum", "Capacitor_Tantalum_SMD:CP_EIA-3528-21_Kemet-B",
      {1: "+3V3", 2: "GND"})
c.add("R1", "Device:R", "1k", "Resistor_SMD:R_0805_2012Metric", {1: "+3V3", 2: "LED_A"})
c.add("D1", "Device:LED", "green", "LED_SMD:LED_0805_2012Metric", {1: "GND", 2: "LED_A"})
c.add("J2", "Connector_Generic:Conn_01x02", "3V3", HDR2, {1: "+3V3", 2: "GND"})

PLACE = {
    "J1": (3, 8.7, 0),
    "C1": (8.5, 10, 90),
    "U1": (15, 10, 270),
    "C2": (21.5, 10, 90),
    "J2": (27, 8.7, 0),
    "R1": (12, 16.5, 0),
    "D1": (18, 16.5, 180),
}
