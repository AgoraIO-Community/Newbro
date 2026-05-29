from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Callable


def ensure_service_install_supported(*, platform: str, cli_name: str, cli_error) -> None:
    if not platform.startswith("linux"):
        raise cli_error(f"{cli_name} service install currently supports Linux/systemd hosts only.")


def ensure_service_manager_available(
    *,
    platform: str,
    shutil_module: ModuleType,
    os_module: ModuleType,
    cli_name: str,
    cli_error,
) -> None:
    if not platform.startswith("linux"):
        raise cli_error("systemd service management currently supports Linux hosts only.")
    if shutil_module.which("systemctl") is None:
        raise cli_error(f"systemctl is required for {cli_name} service commands.")
    if os_module.geteuid() != 0 and shutil_module.which("sudo") is None:
        raise cli_error(f"sudo is required for {cli_name} service commands.")


def ensure_frontend_build_ready(
    *,
    index_path: Path,
    root_launcher: str,
    cli_error,
) -> Path:
    if index_path.exists():
        return index_path
    raise cli_error(
        f"Frontend production build is missing at {index_path}. "
        f"Run `{root_launcher} service install` or build the frontend first."
    )


def ensure_service_runtime_ready(
    *,
    root: Path,
    frontend: Path,
    venv_dir: Path,
    sys_module: ModuleType,
    require_venv_python: Callable[..., Path],
    run_checked: Callable[[list[str], Path], int],
    bootstrap_setup_files: Callable[[], None],
    openai_api_key_present: Callable[[], bool],
    frontend_install_command: Callable[[], list[str]],
    frontend_build_command: Callable[[], list[str]],
    env_file_label: str,
) -> Path:
    venv_python = require_venv_python(allow_missing=True)
    if not venv_python.exists():
        run_checked([sys_module.executable, "-m", "venv", str(venv_dir)], root)

    venv_python = require_venv_python()
    run_checked([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], root)
    run_checked([str(venv_python), "-m", "pip", "install", "-e", "."], root)

    bootstrap_setup_files()
    if not openai_api_key_present():
        print(f"[warn] env: OPENAI_API_KEY is not configured in {env_file_label}")
    run_checked(frontend_install_command(), frontend)
    run_checked(frontend_build_command(), frontend)

    return venv_python


def ensure_service_cli_ready(
    *,
    venv_python: Path,
    cli_name: str,
    root_launcher: str,
    os_module: ModuleType,
    cli_error,
) -> Path:
    cli_bin = service_cli_bin_path(venv_python, cli_name=cli_name)
    if not cli_bin.exists():
        raise cli_error(
            f"Installed {cli_name} console script is missing at {cli_bin}. "
            f"Run `{venv_python} -m pip install -e .` or rerun `{root_launcher} service install`."
        )
    if not os_module.access(cli_bin, os_module.X_OK):
        raise cli_error(
            f"Installed {cli_name} console script is not executable at {cli_bin}. "
            f"Run `{venv_python} -m pip install -e .` or rerun `{root_launcher} service install`."
        )
    return cli_bin


def service_cli_bin_path(venv_python: Path, *, cli_name: str) -> Path:
    return venv_python.with_name(cli_name)


def run_privileged_checked(
    cmd: list[str],
    *,
    cwd: Path,
    os_module: ModuleType,
    run_checked: Callable[[list[str], Path], int],
) -> int:
    if os_module.geteuid() == 0:
        return run_checked(cmd, cwd)
    return run_checked(["sudo", *cmd], cwd)


def require_venv_python(
    *,
    venv_python: Path,
    allow_missing: bool = False,
    cli_error,
) -> Path:
    if venv_python.exists():
        return venv_python
    if allow_missing:
        return venv_python
    raise cli_error("Repo virtualenv is not ready. Run ./install.sh first.")


def service_runtime_python_path(
    *,
    venv_python: Path,
    sys_module: ModuleType,
    cli_error,
) -> Path:
    if venv_python.exists():
        return venv_python
    if sys_module.executable:
        return Path(sys_module.executable)
    raise cli_error("Python interpreter is unavailable.")


def executor_run_python_path(
    *,
    running_from_repo_checkout: bool,
    require_venv_python: Callable[[], Path],
    sys_module: ModuleType,
    cli_error,
) -> Path:
    if running_from_repo_checkout:
        return require_venv_python()
    if not sys_module.executable:
        raise cli_error("Current Python interpreter is unavailable for executor run.")
    return Path(sys_module.executable)


def executor_run_cwd(*, running_from_repo_checkout: bool, root: Path) -> Path:
    if running_from_repo_checkout:
        return root
    return Path.cwd()


def executor_cli_invocation(
    *,
    running_from_repo_checkout: bool,
    root_launcher: str,
    cli_name: str,
) -> str:
    if running_from_repo_checkout:
        return root_launcher
    return cli_name
