from __future__ import annotations

import sys


def run_executor_ui() -> int:
    try:
        from newbro.executors.ui.app import run_menu_bar_app
    except ImportError as exc:
        print(
            "The macOS menu-bar executor app requires the 'macos-ui' extra.\n"
            "Install it with: pip install 'newbro-cli[macos-ui]'",
            file=sys.stderr,
        )
        print(f"(import error: {exc})", file=sys.stderr)
        return 1
    return run_menu_bar_app()
