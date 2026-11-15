from types import SimpleNamespace

import pytest

from boardwright import live

pytest.importorskip("kipy")


class FakeBoard:
    name = "StickHub.kicad_pcb"

    def __init__(self, project_dir):
        self.project_dir = project_dir

    def get_project(self):
        return SimpleNamespace(path=self.project_dir)

    def get_copper_layer_count(self):
        return 2

    def get_footprints(self):
        return []

    get_tracks = get_vias = get_zones = get_nets = get_selection = get_footprints


def test_status_names_the_board_by_its_full_path(monkeypatch, capsys):
    fake_kicad = SimpleNamespace(get_version=lambda: "10.0.8")
    monkeypatch.setattr(live, "connect", lambda: fake_kicad)
    monkeypatch.setattr(live, "board_of", lambda k: FakeBoard("/work/a/stickhub"))
    assert live.main(["status"]) == 0
    assert "board: /work/a/stickhub/StickHub.kicad_pcb |" in capsys.readouterr().out
