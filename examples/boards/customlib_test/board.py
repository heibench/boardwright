"""A board whose regulator comes from a library outside KiCad's stock set (LIBS)."""

from boardwright.circuit import Circuit

NAME = "customlib_test"
W, H = 24, 16
LIBS = ["../../libs/customlib"]          # directories with *.kicad_sym and *.pretty

CIRCUIT = c = Circuit("custom library test")
HDR = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
c.add("J1", "Connector_Generic:Conn_01x02", "IN", HDR, {1: "VIN", 2: "GND"})
c.add("J2", "Connector_Generic:Conn_01x02", "OUT", HDR, {1: "+3V3", 2: "GND"})
c.add("U1", "Custom:MYLDO-3.3", "MYLDO-3.3", "Custom:MY_SOT-23-5", {1: "VIN", 2: "GND", 3: "VIN", 4: None, 5: "+3V3"})
c.add("C1", "Device:C", "1u", "Capacitor_SMD:C_0603_1608Metric", {1: "VIN", 2: "GND"})
c.add("C2", "Device:C", "1u", "Capacitor_SMD:C_0603_1608Metric", {1: "+3V3", 2: "GND"})

PLACE = {"J1": (3, 6.5, 0), "J2": (21, 6.5, 0), "U1": (12, 8, 0), "C1": (8, 8, 90), "C2": (16, 8, 90)}
