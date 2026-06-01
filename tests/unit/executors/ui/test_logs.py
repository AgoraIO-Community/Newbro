from __future__ import annotations

from newbro.executors.ui.logs import ProfileLog, ui_log_path


def test_append_writes_lines_and_recent_reads_them(tmp_path):
    log = ProfileLog(path=tmp_path / "node.log")
    log.append("[start] one")
    log.append("[ready] two")
    assert log.recent() == ["[start] one", "[ready] two"]


def test_recent_caps_to_max_lines(tmp_path):
    log = ProfileLog(path=tmp_path / "node.log", max_lines=3)
    for index in range(10):
        log.append(f"line {index}")
    assert log.recent() == ["line 7", "line 8", "line 9"]


def test_recent_on_missing_file_is_empty(tmp_path):
    assert ProfileLog(path=tmp_path / "absent.log").recent() == []


def test_ui_log_path_uses_profile_id():
    path = ui_log_path("profile-abc123")
    assert path.name == "executor-ui-profile-abc123.log"
    assert path.parent.name == "logs"
