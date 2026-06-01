from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from newbro.executors.ui.process import NodeProcessController


def _controller(script: str, lines: list[str], exits: list[int]) -> NodeProcessController:
    return NodeProcessController(
        argv=[sys.executable, "-c", script],
        cwd=Path.cwd(),
        on_line=lines.append,
        on_exit=exits.append,
    )


def test_captures_lines_and_exit_code():
    lines: list[str] = []
    exits: list[int] = []
    script = "import sys; print('[start] hello'); print('[ready] go'); sys.exit(0)"
    controller = _controller(script, lines, exits)

    controller.start()
    deadline = time.time() + 10
    while not exits and time.time() < deadline:
        time.sleep(0.05)

    assert "[start] hello" in lines
    assert "[ready] go" in lines
    assert exits == [0]


def test_stop_terminates_a_long_running_process():
    lines: list[str] = []
    exits: list[int] = []
    script = "import time\nprint('[start] up', flush=True)\nwhile True: time.sleep(0.1)"
    controller = _controller(script, lines, exits)

    controller.start()
    deadline = time.time() + 10
    while not lines and time.time() < deadline:
        time.sleep(0.05)
    assert controller.is_running() is True

    controller.stop(timeout=5.0)
    assert controller.is_running() is False
    assert exits  # on_exit fired after stop
