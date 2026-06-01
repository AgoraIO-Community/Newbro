"""py2app build script for the Newbro Executor menu-bar app.

Build from the repo root with the macos-ui-build extra installed:

    python packaging/menubar/setup.py py2app

Produces `dist/Newbro Executor.app`.
"""
from __future__ import annotations

from pathlib import Path

from setuptools import setup

_ENTRY = Path(__file__).parent / "main.py"

setup(
    app=[str(_ENTRY)],
    name="Newbro Executor",
    options={
        "py2app": {
            "argv_emulation": False,
            "plist": {
                "CFBundleIdentifier": "com.newbro.executor-ui",
                "CFBundleName": "Newbro Executor",
                "LSUIElement": True,
            },
            "packages": ["newbro", "rumps"],
        }
    },
    setup_requires=["py2app>=0.28,<1"],
)
