from __future__ import annotations

import plistlib
from pathlib import Path

from newbro.executors.ui.login_item import (
    LOGIN_ITEM_LABEL,
    LoginItem,
    render_login_item_plist,
)


def test_render_plist_contains_label_and_app_path():
    text = render_login_item_plist(app_path=Path("/Applications/Newbro Executor.app"))
    parsed = plistlib.loads(text.encode("utf-8"))
    assert parsed["Label"] == LOGIN_ITEM_LABEL
    assert parsed["RunAtLoad"] is True
    assert "/Applications/Newbro Executor.app" in parsed["ProgramArguments"]


def test_install_then_remove(tmp_path):
    plist_path = tmp_path / f"{LOGIN_ITEM_LABEL}.plist"
    item = LoginItem(plist_path=plist_path, app_path=Path("/Applications/Newbro Executor.app"))

    assert item.is_installed() is False
    item.install()
    assert item.is_installed() is True
    assert plist_path.exists()

    item.remove()
    assert item.is_installed() is False
    assert not plist_path.exists()
