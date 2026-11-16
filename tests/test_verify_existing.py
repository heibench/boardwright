"""`existing verify` against the baseline (#44): a finding whose track only
changed length is the same finding; a finding of a new type or on another net
is new. The DRC reports are written by hand in KiCad's JSON shape; the item
descriptions are copied from out/freecheck/drc.json."""
import json
import os

import pytest

from boardwright.cli import main


def _drc(path, *findings):
    path.write_text(json.dumps({"violations": list(findings), "unconnected_items": [], "schematic_parity": []}))


def _dangling(net, length, unit="mm"):
    return {"type": "track_dangling", "severity": "warning", "description": "Track has unconnected end",
            "items": [{"description": f"Track [{net}] on F.Cu, length {length} {unit}", "pos": {"x": 155.19, "y": 117.0}}]}


def _verify(ldo_copy, before, after):
    o = ldo_copy / "boardwright_out"
    o.mkdir(exist_ok=True)
    _drc(o / "drc_baseline.json", *before)
    _drc(o / "drc.json", *after)
    t = ldo_copy.joinpath("ldo_breakout.kicad_pcb").stat().st_mtime
    os.utime(o / "drc.json", (t + 10, t + 10))         # the DRC ran after the last board edit
    return main(["existing", str(ldo_copy), "verify"])


@pytest.mark.parametrize("unit", ["mm", "mils", "in"])   # kicad-cli pcb drc --units
def test_length_change_is_not_new(ldo_copy, capsys, unit):
    assert _verify(ldo_copy, [_dangling("+3V3", "0.2858", unit)], [_dangling("+3V3", "0.3102", unit)]) == 0
    assert "0 new, 0 gone" in capsys.readouterr().out


def test_new_type_or_net_is_new(ldo_copy, capsys):
    assert _verify(ldo_copy, [_dangling("+3V3", "0.2858")], [_dangling("LED_USR", "0.2858")]) == 1
    assert "1 new, 1 gone" in capsys.readouterr().out
    clearance = {"type": "clearance", "severity": "error", "description": "Clearance violation ( clearance 0.2 mm; actual 0.15 mm)",
                 "items": [{"description": "Track [+3V3] on F.Cu, length 0.2858 mm"}, {"description": "Pad 1 [GND] of C1 on F.Cu"}]}
    assert _verify(ldo_copy, [_dangling("+3V3", "0.2858")], [_dangling("+3V3", "0.3102"), clearance]) == 1
    assert "1 new, 0 gone" in capsys.readouterr().out
