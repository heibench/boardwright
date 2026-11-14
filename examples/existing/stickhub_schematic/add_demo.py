"""Schematic edit demo: one decoupler on the 3.3 V rail, one resistor from an
existing labelled net to a new net. Each new part copies a part already on the
sheet that uses the same symbol."""

ADD = [
    ("C99", "C2", "100n", "footprints:1005_C", {1: "+3.3V", 2: "GND"}),
    ("R99", "R1", "4.7k", "footprints:R_1005_C", {1: "LED3", 2: "TESTNET"}),
]
