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
            return {"begin_commit": "c1", "get_footprints": self.fps, "get_nets": [], "get_tracks": [],
                    "get_vias": []}.get(name)
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


# --- which KiCad: candidate sockets, then the one that has the board open ---

from boardwright import env  # noqa: E402
from boardwright.errors import EnvironmentFault, Outcome, Usage  # noqa: E402


@pytest.fixture(params=["home_a", "home b"])
def sockets_host(request, tmp_path, monkeypatch):
    """A HOME with an empty Flatpak socket folder and a native socket folder in tmp;
    KICAD_API_SOCKET unset. Socket files are plain files: nothing listens."""
    home = tmp_path / request.param
    flat = home / ".var/app/org.kicad.KiCad/cache/tmp/kicad"
    native = tmp_path / "tmp" / "kicad"
    flat.mkdir(parents=True)
    native.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("KICAD_API_SOCKET", raising=False)
    monkeypatch.setattr(env, "_native_socket_dir", lambda: native)
    return SimpleNamespace(flat=flat, native=native, tmp=tmp_path)


def _touch(d, *names):
    for n in names:
        (d / n).write_text("")
    return [d / n for n in names]


def test_sockets_lists_flatpak_then_native_api_sock_first(sockets_host):
    h = sockets_host
    f = _touch(h.flat, "api-2.sock", "api.sock", "other.sock")
    n = _touch(h.native, "api-17.sock", "api.sock")
    assert env.kicad_api_sockets() == [f[1], f[0], n[1], n[0]]


def test_sockets_skip_folders_that_do_not_exist(sockets_host, monkeypatch):
    h = sockets_host
    monkeypatch.setattr(env, "_native_socket_dir", lambda: h.tmp / "absent")
    f = _touch(h.flat, "api.sock")
    assert env.kicad_api_sockets() == f


@pytest.mark.parametrize("prefix", ["", "ipc://"])
def test_sockets_variable_comes_first_without_ipc_prefix(sockets_host, monkeypatch, prefix):
    h = sockets_host
    mine = h.tmp / "mine.sock"
    f = _touch(h.flat, "api.sock")
    monkeypatch.setenv("KICAD_API_SOCKET", prefix + str(mine))
    assert env.kicad_api_sockets() == [mine, *f]


def test_sockets_deduplicated_by_resolved_path(sockets_host, monkeypatch):
    h = sockets_host
    f = _touch(h.flat, "api.sock")
    (h.native / "api.sock").symlink_to(f[0])
    monkeypatch.setenv("KICAD_API_SOCKET", str(h.flat / ".." / "kicad" / "api.sock"))
    assert [p.resolve() for p in env.kicad_api_sockets()] == [f[0].resolve()]


def test_native_socket_dir_mirrors_kicad_python():
    import sys
    if sys.platform != "win32":
        assert env._native_socket_dir() == __import__("pathlib").Path("/tmp/kicad")


def doc(path):
    from pathlib import Path
    p = Path(path)
    return SimpleNamespace(board_filename=p.name, project=SimpleNamespace(path=str(p.parent)))


def no_handler():
    from kipy.errors import ApiError
    from kipy.proto.common import ApiStatusCode
    return ApiError("KiCad returned error: no handler available for request of type "
                    "kiapi.common.commands.GetOpenDocuments", code=ApiStatusCode.AS_UNHANDLED)


def not_ready():
    from kipy.errors import ApiError
    from kipy.proto.common import ApiStatusCode
    return ApiError("KiCad is not ready to reply", code=ApiStatusCode.AS_NOT_READY)


class FakeKiCad:
    """One KiCad behind one socket: what ping and GetOpenDocuments do."""

    def __init__(self, socket, docs=(), ping_errors=(), docs_error=None):
        self.socket, self.docs = socket, list(docs)
        self.ping = failing(*ping_errors, result=None)
        self.docs_error = docs_error

    def get_open_documents(self, doc_type):
        if self.docs_error:
            raise self.docs_error
        return self.docs


def kicads(*fakes):
    """sockets and an opener over them; a socket with no fake does not answer."""
    from kipy.errors import ConnectionError as KiConnectionError
    by = {f.socket: f for f in fakes}
    def opener(socket, timeout_ms):
        if by.get(socket) is None:
            def dead():
                raise KiConnectionError("Failed to connect to KiCad: Connection refused")
            return SimpleNamespace(ping=dead)
        return by[socket]
    return opener


def test_find_board_picks_the_kicad_that_has_it(tmp_path):
    board = tmp_path / "a" / "a.kicad_pcb"
    pm = FakeKiCad("api.sock", docs_error=no_handler())
    ed = FakeKiCad("api-2.sock", docs=[doc(board)])
    k, d = live.find_board(str(board), sockets=["api.sock", "api-2.sock"], opener=kicads(pm, ed))
    assert k is ed and d.board_filename == "a.kicad_pcb"


def test_find_board_compares_resolved_paths(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    (real / "a.kicad_pcb").write_text("")
    (tmp_path / "link").symlink_to(real)
    ed = FakeKiCad("api.sock", docs=[doc(tmp_path / "link" / "a.kicad_pcb")])
    monkeypatch.chdir(real)
    k, _ = live.find_board("a.kicad_pcb", sockets=["api.sock"], opener=kicads(ed))
    assert k is ed


def test_find_board_none_is_an_environment_fault_naming_every_socket(tmp_path):
    pm = FakeKiCad("api.sock", docs_error=no_handler())
    other = FakeKiCad("api-2.sock", docs=[doc(tmp_path / "b.kicad_pcb")])
    with pytest.raises(EnvironmentFault) as e:
        live.find_board(str(tmp_path / "a.kicad_pcb"), sockets=["api.sock", "api-2.sock", "api-9.sock"],
                        opener=kicads(pm, other))
    m = e.value.message
    assert e.value.exit == 4
    assert "api.sock" in m and "no handler" in m
    assert "api-2.sock" in m and "b.kicad_pcb" in m
    assert "api-9.sock" in m and "does not answer" in m


def test_find_board_two_kicads_with_it_is_refused(tmp_path):
    board = tmp_path / "a.kicad_pcb"
    one, two = FakeKiCad("x/api-2.sock", docs=[doc(board)]), FakeKiCad("y/api-2.sock", docs=[doc(board)])
    with pytest.raises(Outcome) as e:
        live.find_board(str(board), sockets=["x/api-2.sock", "y/api-2.sock"], opener=kicads(one, two))
    assert e.value.exit == 1
    assert "x/api-2.sock" in e.value.message and "y/api-2.sock" in e.value.message


def test_find_board_skips_a_socket_that_does_not_answer(tmp_path):
    board = tmp_path / "a.kicad_pcb"
    ed = FakeKiCad("api-2.sock", docs=[doc(board)])
    k, _ = live.find_board(str(board), sockets=["api.sock", "api-2.sock"], opener=kicads(ed))
    assert k is ed


def test_find_board_skips_a_project_manager(tmp_path):
    board = tmp_path / "a.kicad_pcb"
    pm = FakeKiCad("api.sock", docs_error=no_handler())
    with pytest.raises(EnvironmentFault):
        live.find_board(str(board), sockets=["api.sock"], opener=kicads(pm))


def test_connect_retries_not_ready_until_kicad_answers(monkeypatch):
    c = Clock()
    k = SimpleNamespace(ping=failing(not_ready(), not_ready(), result=None))
    monkeypatch.setattr(live, "_open", lambda socket, timeout_ms: k)
    monkeypatch.setattr(live, "_clock", (c.now, c.sleep))
    assert live.connect() is k
    assert c.sleeps == 2


def test_connect_not_ready_past_the_bound_is_an_environment_fault(monkeypatch):
    c = Clock()
    k = SimpleNamespace(ping=failing(*[not_ready()] * 10_000, result=None))
    monkeypatch.setattr(live, "_open", lambda socket, timeout_ms: k)
    monkeypatch.setattr(live, "_clock", (c.now, c.sleep))
    with pytest.raises(EnvironmentFault) as e:
        live.connect()
    assert e.value.exit == 4 and "30" in e.value.message
    assert c.t <= live.BUSY_WAIT_S + live.BUSY_POLL_S


def test_connect_does_not_wait_on_a_socket_that_does_not_answer(monkeypatch):
    c = Clock()
    monkeypatch.setattr(live, "_open", kicads())
    monkeypatch.setattr(live, "_clock", (c.now, c.sleep))
    with pytest.raises(EnvironmentFault):
        live.connect("api.sock")
    assert c.sleeps == 0


@pytest.mark.parametrize("argv", [
    ["--board", "/w/a.kicad_pcb", "status"],
    ["status", "--board", "/w/a.kicad_pcb"],
    ["status", "--board=/w/a.kicad_pcb"],
])
def test_board_flag_takes_a_value_that_is_not_an_argument(monkeypatch, capsys, argv):
    seen = {}
    def find(board):
        seen["board"] = board
        return SimpleNamespace(get_version=lambda: "10.0.8"), "doc"
    monkeypatch.setattr(live, "find_board", find)
    monkeypatch.setattr(live, "_board", lambda k, d: FakeBoard("/w"))
    monkeypatch.setattr(live, "connect", lambda *a, **kw: pytest.fail("--board must not use the default socket"))
    assert live.main(argv) == 0
    assert seen == {"board": "/w/a.kicad_pcb"}


def test_board_flag_reaches_a_verb_with_arguments(monkeypatch, capsys):
    monkeypatch.setattr(live, "find_board", lambda board: (SimpleNamespace(), "doc"))
    r = Recorder()
    monkeypatch.setattr(live, "_board", lambda k, d: r)
    monkeypatch.setattr(live, "connect", lambda *a, **kw: pytest.fail("--board must not use the default socket"))
    assert live.main(["select", "--board", "/w/a.kicad_pcb", "GND"]) == 0
    assert "for ['GND']" in capsys.readouterr().out
    assert "clear_selection" in r.calls


@pytest.mark.parametrize("argv", [["status", "--board"], ["status", "--board="]])
def test_board_flag_without_a_value_is_usage(argv):
    with pytest.raises(Usage):
        live.main(argv)
