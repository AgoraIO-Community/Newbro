from __future__ import annotations

from pathlib import Path
import os
import stat
import subprocess
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[2]


def test_root_launcher_layout_has_only_newbro_bootstrap() -> None:
    assert (ROOT / "newbro").is_file()
    assert not (ROOT / "newbro.py").exists()


def test_root_launcher_reexecs_repo_virtualenv_python(tmp_path: Path) -> None:
    root = tmp_path
    launcher = root / "newbro"
    launcher.write_text((ROOT / "newbro").read_text(encoding="utf-8"), encoding="utf-8")

    venv_bin = root / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    invoked = root / "invoked.txt"
    fake_python = venv_bin / "python"
    fake_python.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$0\" \"$@\" > {invoked}\n",
        encoding="utf-8",
    )
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)

    subprocess.run(
        [sys.executable, str(launcher), "doctor"],
        check=True,
        cwd=root,
        env={**os.environ, "LC_ALL": "C.UTF-8"},
    )

    lines = invoked.read_text(encoding="utf-8").splitlines()
    assert lines == [str(fake_python), str(launcher.resolve()), "doctor"]


def test_public_package_metadata_documents_newbro_namespace() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    repository_url = "https://github.com/AgoraIO/newbro"

    assert project["name"] == "newbro-cli"
    assert "Newbro CLI" in project["description"]
    assert "communication-brain" in project["description"]
    assert "newbro" in set(project["keywords"])
    assert project["scripts"]["newbro"] == "newbro.cli.main:main"
    assert project["urls"]["Repository"] == repository_url
    assert project["urls"]["Documentation"] == f"{repository_url}#readme"
