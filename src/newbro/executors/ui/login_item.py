from __future__ import annotations

import plistlib
from pathlib import Path

LOGIN_ITEM_LABEL = "com.newbro.executor-ui"

_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


def login_item_plist_path() -> Path:
    return _LAUNCH_AGENTS_DIR / f"{LOGIN_ITEM_LABEL}.plist"


def render_login_item_plist(*, app_path: Path) -> str:
    payload = {
        "Label": LOGIN_ITEM_LABEL,
        "ProgramArguments": ["/usr/bin/open", str(app_path)],
        "RunAtLoad": True,
    }
    return plistlib.dumps(payload).decode("utf-8")


class LoginItem:
    def __init__(self, *, plist_path: Path | None = None, app_path: Path) -> None:
        self._plist_path = plist_path or login_item_plist_path()
        self._app_path = app_path

    def is_installed(self) -> bool:
        return self._plist_path.exists()

    def install(self) -> None:
        self._plist_path.parent.mkdir(parents=True, exist_ok=True)
        self._plist_path.write_text(render_login_item_plist(app_path=self._app_path), encoding="utf-8")

    def remove(self) -> None:
        self._plist_path.unlink(missing_ok=True)
