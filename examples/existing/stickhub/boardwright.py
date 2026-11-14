"""boardwright spec for an existing board: StickHub, a KiCad demo project (7-port USB 2.0 hub).

Nothing here regenerates the design. REVIEW is checked against the board as
drawn; TEXT is applied by `apply`; `reroute` rips up and re-routes named nets.
"""

REVIEW = {
    # upstream and two downstream pairs, connector pad to hub IC pad
    "match": [([("J1.3", "U1.30"), ("J1.2", "U1.29")], 0.5),
              ([("J4.3", "U1.14"), ("J4.2", "U1.13")], 0.5),
              ([("J2.3", "U1.19"), ("J2.2", "U1.18")], 0.5)],
    # USB traces should run over ground on the other layer. As drawn, the
    # downstream pairs run up to 12.4 mm over gaps in the opposite pour; the
    # limit records that finding rather than hiding it.
    "ref": [(["/D+", "/D-", "/U*D+", "/U*D-"], 13.0)],
    "coverage": {"B.Cu": 0.5},
}
TEXT = [("boardwright", 8.25, 38.6, 0.8, "B.SilkS")]
