from __future__ import annotations

from newbro.cli import processes


class FakeProc:
    def __init__(self, alive_polls: int = 0, returncode: int = 0):
        # poll() returns None for `alive_polls` calls, then `returncode`.
        self._remaining = alive_polls
        self._returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        if self._remaining > 0:
            self._remaining -= 1
            return None
        return self._returncode

    def wait(self):
        return self._returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class FakeTime:
    def __init__(self):
        self._t = 0.0

    def time(self):
        return self._t

    def sleep(self, seconds):
        self._t += seconds


def test_terminate_child_terminates_then_kills_if_still_alive():
    proc = FakeProc(alive_polls=1000)
    processes._terminate_child(proc, time_module=FakeTime(), timeout=5.0)
    assert proc.terminated is True
    assert proc.killed is True


def test_terminate_child_skips_kill_when_child_exits():
    proc = FakeProc(alive_polls=0)
    processes._terminate_child(proc, time_module=FakeTime(), timeout=5.0)
    assert proc.terminated is True
    assert proc.killed is False


class FakeSignal:
    SIGINT = 2
    SIGTERM = 15

    def __init__(self):
        self.handlers = {}

    def signal(self, signum, handler):
        previous = self.handlers.get(signum)
        self.handlers[signum] = handler
        return previous


def test_run_checked_registers_handlers_and_returns_zero():
    sig = FakeSignal()
    captured = {}

    class FakeSubprocess:
        def Popen(self, cmd, cwd=None):
            captured["cmd"] = cmd
            return FakeProc(alive_polls=0, returncode=0)

    rc = processes.run_checked(
        ["python", "-m", "newbro.executors.node"],
        cwd=__import__("pathlib").Path("."),
        subprocess_module=FakeSubprocess(),
        signal_module=sig,
        time_module=FakeTime(),
    )
    assert rc == 0
    assert sig.SIGTERM in sig.handlers and sig.SIGINT in sig.handlers


def test_run_checked_raises_systemexit_on_nonzero():
    sig = FakeSignal()

    class FakeSubprocess:
        def Popen(self, cmd, cwd=None):
            return FakeProc(alive_polls=0, returncode=3)

    try:
        processes.run_checked(
            ["x"],
            cwd=__import__("pathlib").Path("."),
            subprocess_module=FakeSubprocess(),
            signal_module=sig,
            time_module=FakeTime(),
        )
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert exc.code == 3
