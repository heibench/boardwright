"""A harmless first edit for `boardwright live apply` on the StickHub demo:
one ground via and a 0.7 mm ground track, at a spot measured from the live
snapshot to be inside the GND pour on both layers and at least 1.5 mm from any
other net's copper. Coordinates are board-relative mm."""

VIAS = [("GND", 14.5, 7.0)]
TRACKS = [("GND", [(14.5, 7.0), (15.2, 7.0)], 0.25, "F.Cu")]
