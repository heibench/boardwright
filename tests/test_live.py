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


class Recorder:
    """A board and a KiCad that record every call, in order, into one list."""

    def __init__(self, refs=("U1",)):
        self.calls = []
        self.fps = [SimpleNamespace(reference_field=SimpleNamespace(text=SimpleNamespace(value=r))) for r in refs]
        self.k = SimpleNamespace(ping=lambda: self.calls.append("ping"))

    def __getattr__(self, name):
        def call(*a, **kw):
            self.calls.append(name if name != "refill_zones" else f"refill_zones(block={kw.get('block')})")
            return {"begin_commit": "c1", "get_footprints": self.fps, "get_nets": []}.get(name)
        return call


MOVE = {"ops": [{"op": "move_footprint", "ref": "U1", "x": 10, "y": 20}]}


def test_apply_save_refills_zones_after_a_move_and_before_saving():
    r = Recorder()
    live.apply(r.k, r, MOVE, save=True)
    assert r.calls[-4:] == ["push_commit", "refill_zones(block=False)", "ping", "save"]


def test_apply_without_save_neither_refills_nor_saves():
    r = Recorder()
    live.apply(r.k, r, MOVE, save=False)
    assert not [c for c in r.calls if c.startswith(("refill", "save"))]


def test_apply_save_that_changed_nothing_saves_without_refilling():
    r = Recorder()
    live.apply(r.k, r, {"ops": []}, save=True)
    assert r.calls[-2:] == ["push_commit", "save"]
    assert not [c for c in r.calls if c.startswith("refill")]


def busy():
    from kipy.errors import ApiError
    from kipy.proto.common import ApiStatusCode
    return ApiError("KiCad is busy", code=ApiStatusCode.AS_BUSY)


class Clock:
    """A fake clock that sleep advances; refuses to sleep past a cap so a missing deadline cannot hang."""

    def __init__(self, cap=1000):
        self.t, self.sleeps, self.cap = 0.0, 0, cap

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps += 1
        if self.sleeps > self.cap:
            raise AssertionError("slept past the cap: the wait is not bounded")
        self.t += s


def failing(*errors, result="ok"):
    errors = list(errors)
    def call():
        if errors:
            raise errors.pop(0)
        return result
    return call


def test_when_idle_retries_a_busy_kicad_until_it_answers():
    c = Clock()
    assert live._when_idle(failing(busy(), busy()), "saving", clock=c.now, sleep=c.sleep) == "ok"
    assert c.sleeps == 2


def test_when_idle_gives_up_after_the_bound_as_an_environment_fault():
    from boardwright.errors import EnvironmentFault
    c = Clock()
    with pytest.raises(EnvironmentFault) as e:
        live._when_idle(failing(*[busy()] * 10_000), "refilling zones", wait=30.0, poll=0.5,
                        clock=c.now, sleep=c.sleep)
    assert e.value.exit == 4
    assert "refilling zones" in e.value.message and "30" in e.value.message
    assert c.t <= 30.5


def test_when_idle_retries_a_transport_timeout():
    from kipy.errors import ConnectionError as KiConnectionError
    c = Clock()
    assert live._when_idle(failing(KiConnectionError("timed out")), "refilling zones",
                           clock=c.now, sleep=c.sleep) == "ok"
    assert c.sleeps == 1


def test_when_idle_raises_any_other_api_error_at_once():
    from kipy.errors import ApiError
    c = Clock()
    with pytest.raises(ApiError):
        live._when_idle(failing(ApiError("bad request")), "saving", clock=c.now, sleep=c.sleep)
    assert c.sleeps == 0
