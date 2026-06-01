from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable


class NodeProcessController:
    """Supervises one `newbro executor run` subprocess for a single profile.

    Emits raw output lines and the final exit code. Does not interpret meaning.
    """

    def __init__(
        self,
        *,
        argv: list[str],
        cwd: Path,
        on_line: Callable[[str], None],
        on_exit: Callable[[int], None],
    ) -> None:
        self._argv = list(argv)
        self._cwd = Path(cwd)
        self._on_line = on_line
        self._on_exit = on_exit
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None

    def start(self) -> None:
        if self.is_running():
            return
        self._proc = subprocess.Popen(
            self._argv,
            cwd=str(self._cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        for line in proc.stdout:
            self._on_line(line.rstrip("\n"))
        self._on_exit(proc.wait())

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self, *, timeout: float = 5.0) -> None:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if self._reader is not None:
            self._reader.join(timeout=timeout)
