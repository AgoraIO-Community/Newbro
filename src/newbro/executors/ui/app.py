from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import rumps

from newbro.cli.command_specs import executor_node_command
from newbro.executors.ui.login_item import LoginItem, login_item_plist_path
from newbro.executors.ui.process import NodeProcessController
from newbro.executors.ui.profiles import (
    Profile,
    ProfileStore,
    conflicting_profile_ids,
    parse_connect_command,
)
from newbro.executors.ui.status import NodeStatus, StatusModel
from newbro.executors.ui.supervisor import ProfileSupervisor

_STATUS_GLYPH = {
    NodeStatus.READY: "●",
    NodeStatus.CONNECTING: "◌",
    NodeStatus.STARTING: "◌",
    NodeStatus.RETRYING: "◌",
    NodeStatus.DISCONNECTED: "⚠",
    NodeStatus.ERROR: "✕",
    NodeStatus.STOPPED: "○",
    NodeStatus.IDLE: "○",
}


def _build_argv(profile: Profile) -> list[str]:
    return executor_node_command(
        Path(sys.executable),
        base_url=profile.base_url,
        node_id=profile.node_id,
        token=profile.token,
        enabled_executors=profile.enabled_executors or None,
    )


def _is_complete(profile: Profile) -> bool:
    return bool(profile.base_url and profile.node_id and profile.token and profile.enabled_executors)


def _app_bundle_path() -> Path:
    return Path("/Applications/Newbro Executor.app")


class MenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("Newbro Executor", quit_button=None)
        self._store = ProfileStore()
        self._supervisor = ProfileSupervisor(
            controller_factory=lambda **kw: NodeProcessController(**kw),
            status_factory=StatusModel,
            build_argv=_build_argv,
            cwd=Path.home(),
        )
        self._login_item = LoginItem(app_path=_app_bundle_path())
        self._profiles = self._store.load()
        self._refresh_timer = rumps.Timer(self._tick, 1.0)
        self._refresh_timer.start()
        self._autostart()
        self._rebuild_menu()

    def _autostart(self) -> None:
        for profile in self._profiles:
            if profile.auto_activate and _is_complete(profile):
                self._supervisor.start(profile)

    def _tick(self, _timer: "rumps.Timer") -> None:
        self.title = _STATUS_GLYPH[self._supervisor.aggregate_status()]
        self._rebuild_menu()

    def _rebuild_menu(self) -> None:
        self.menu.clear()
        conflicts = conflicting_profile_ids(self._profiles)
        for profile in self._profiles:
            status = self._supervisor.status_of(profile.id)
            label = f"{profile.label} · {_STATUS_GLYPH[status]} {status.value}"
            if profile.id in conflicts:
                label += "  (duplicate node id)"
            item = rumps.MenuItem(label)
            running = profile.id in self._supervisor.active_ids() and status not in (
                NodeStatus.STOPPED,
                NodeStatus.ERROR,
            )
            if running:
                item.add(rumps.MenuItem("Stop", callback=self._make_stop(profile)))
                item.add(rumps.MenuItem("Restart", callback=self._make_restart(profile)))
            else:
                item.add(rumps.MenuItem("Start", callback=self._make_start(profile)))
            self.menu.add(item)
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Paste connect command…", callback=self._paste_connect_command))
        login = rumps.MenuItem("Launch at login", callback=self._toggle_login_item)
        login.state = 1 if login_item_plist_path().exists() else 0
        self.menu.add(login)
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Quit", callback=self._quit))

    def _make_start(self, profile: Profile):
        def _cb(_sender):
            if not _is_complete(profile):
                rumps.alert(
                    "Executor setup needed",
                    "Run `newbro executor setup` in a terminal to configure executor commands, then return here.",
                )
                return
            self._supervisor.start(profile)
        return _cb

    def _make_stop(self, profile: Profile):
        return lambda _sender: self._supervisor.stop(profile.id)

    def _make_restart(self, profile: Profile):
        return lambda _sender: self._supervisor.restart(profile)

    def _paste_connect_command(self, _sender) -> None:
        response = rumps.Window(
            "Paste the connect command from the Newbro web UI:",
            "Add / update profile",
            ok="Save",
            cancel="Cancel",
        ).run()
        if not response.clicked:
            return
        try:
            fields = parse_connect_command(response.text)
        except ValueError as exc:
            rumps.alert("Invalid connect command", str(exc))
            return
        existing = next((p for p in self._profiles if p.node_id == fields.node_id and p.base_url == fields.base_url), None)
        if existing is not None:
            existing.token = fields.token
            existing.enabled_executors = fields.enabled_executors
        else:
            self._profiles.append(
                Profile(
                    id=f"profile-{uuid4().hex[:8]}",
                    label=fields.base_url,
                    base_url=fields.base_url,
                    node_id=fields.node_id,
                    token=fields.token,
                    enabled_executors=fields.enabled_executors,
                )
            )
        self._store.save(self._profiles)
        self._rebuild_menu()

    def _toggle_login_item(self, sender) -> None:
        if login_item_plist_path().exists():
            self._login_item.remove()
            sender.state = 0
        else:
            self._login_item.install()
            sender.state = 1

    def _quit(self, _sender) -> None:
        self._supervisor.stop_all()
        rumps.quit_application()


def run_menu_bar_app() -> int:
    MenuBarApp().run()
    return 0
