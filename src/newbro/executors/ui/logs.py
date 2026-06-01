from __future__ import annotations

from pathlib import Path

from newbro.config_home import NEWBRO_HOME_DIR

UI_LOG_DIR = NEWBRO_HOME_DIR / "logs"


def ui_log_path(profile_id: str) -> Path:
    return UI_LOG_DIR / f"executor-ui-{profile_id}.log"


class ProfileLog:
    """Per-profile append-only log file with a bounded tail reader."""

    def __init__(self, *, path: Path, max_lines: int = 200) -> None:
        self._path = path
        self._max_lines = max_lines

    def append(self, line: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def recent(self) -> list[str]:
        if not self._path.exists():
            return []
        lines = self._path.read_text(encoding="utf-8").splitlines()
        return lines[-self._max_lines :]
