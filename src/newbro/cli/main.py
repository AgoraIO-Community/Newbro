from __future__ import annotations

import argparse
import asyncio  # noqa: F401 - exposed through cli_main for setup factories/tests.
import getpass  # noqa: F401 - exposed through cli_main for setup factories/tests.
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

from newbro.cli import checks as cli_checks
from newbro.cli import command_specs
from newbro.cli import config_files
from newbro.cli import dispatch as cli_dispatch
from newbro.cli import factories as cli_factories
from newbro.cli import parser as cli_parser
from newbro.cli import paths as cli_paths
from newbro.cli import processes as cli_processes
from newbro.cli import service_support
from newbro.cli import setup_resolvers
from newbro.cli import systemd as cli_systemd
from newbro.cli.commands import setup as setup_command
from newbro.config_home import (
    LEGACY_SYNAPSE_HOME_DIR,
    NEWBRO_HOME_DIR,
    SYNAPSE_ENV_FILE,
    ConfigHomeMigrationError,
    ensure_newbro_home,
    format_user_path,
)


MODULE_ROOT = Path(__file__).resolve().parents[3]
ROOT = MODULE_ROOT
FRONTEND = ROOT / "src" / "newbro" / "ui"
VENV_DIR = ROOT / ".venv"
ENV_LOCAL = SYNAPSE_ENV_FILE
CLI_NAME = "newbro"
ROOT_LAUNCHER = f"./{CLI_NAME}"
TRUTHY_VALUES = {"1", "true", "yes", "on", "y"}
FALSY_VALUES = {"0", "false", "no", "off", "n"}
OPENAI_KEY = "OPENAI_API_KEY"
INTERACTIVE_SETUP_KEYS = {OPENAI_KEY}
LEGACY_REAL_EXECUTOR_ENV_KEYS = {
    "SYNAPSE_CODEX_EXECUTOR_ENABLED",
    "SYNAPSE_CODEX_COMMAND",
    "SYNAPSE_ACPX_COMMAND",
    "SYNAPSE_ACPX_AGENT",
    "SYNAPSE_ACPX_PERMISSION_MODE",
    "SYNAPSE_ACPX_NON_INTERACTIVE_PERMISSIONS",
    "SYNAPSE_ACPX_TIMEOUT_SECONDS",
}
SYSTEMD_UNIT_NAME = cli_systemd.SYSTEMD_UNIT_NAME
SYSTEMD_SERVICE_DIR = cli_systemd.SYSTEMD_SERVICE_DIR
REMOVED_RUNTIME_KEYS = {"executor_node_id", "executor_node_token"}
START_PUBLIC_PORT = 8000
DEFAULT_ENV_TEMPLATE_LINES = (
    "OPENAI_API_KEY=your_openai_api_key_here",
    "SYNAPSE_OPENAI_MODEL=gpt-4o-mini",
    "SYNAPSE_OPENAI_TIMEOUT_SECONDS=30",
    "# SYNAPSE_OPENAI_BASE_URL=",
    "# SYNAPSE_CORS_ALLOWED_ORIGINS=https://app.example.com,https://your-project.vercel.app",
    "",
    f"# Shared Newbro credentials written by `{CLI_NAME} setup` to {format_user_path(ENV_LOCAL)}",
    "# AGORA_APP_ID=",
    "# AGORA_APP_CERTIFICATE=",
    "# DEEPGRAM_API_KEY=",
    "# ELEVENLABS_API_KEY=",
)


ConnectorSetupResult = config_files.ConnectorSetupResult


def build_parser() -> argparse.ArgumentParser:
    return cli_parser.build_parser(
        cli_name=CLI_NAME,
        env_file=ENV_LOCAL,
        start_public_port=START_PUBLIC_PORT,
    )


def _add_host_port(parser: argparse.ArgumentParser, backend_port: int, frontend_port: int | None = None, include_frontend_port: bool = False) -> None:
    cli_parser.add_host_port(
        parser,
        backend_port=backend_port,
        frontend_port=frontend_port,
        include_frontend_port=include_frontend_port,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        try:
            migration_result = ensure_newbro_home(
                legacy_home=LEGACY_SYNAPSE_HOME_DIR,
                new_home=NEWBRO_HOME_DIR,
            )
        except ConfigHomeMigrationError as exc:
            raise CliError(str(exc)) from exc
        if migration_result.warning:
            print(f"[warn] {migration_result.warning}", file=sys.stderr)
        parser = build_parser()
        args = parser.parse_args(argv)

        return cli_dispatch.dispatch(args, sys.modules[__name__])
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _setup_resolution_callbacks() -> setup_resolvers.SetupResolutionCallbacks:
    return cli_factories.setup_resolution_callbacks(sys.modules[__name__])


def executor_node_command(
    venv_python: Path,
    *,
    base_url: str,
    node_id: str,
    token: str,
    enabled_executors: list[str] | None = None,
    acpx_agent: str | None = None,
    audio_language: str | None = None,
    whisper_model: str | None = None,
) -> list[str]:
    return command_specs.executor_node_command(
        venv_python,
        base_url=base_url,
        node_id=node_id,
        token=token,
        enabled_executors=enabled_executors,
        acpx_agent=acpx_agent,
        audio_language=audio_language,
        whisper_model=whisper_model,
    )


def frontend_dev_command(host: str, port: int) -> list[str]:
    return command_specs.frontend_dev_command(preferred_frontend_tool(), host, port)


def preferred_frontend_tool() -> str:
    if shutil.which("bun"):
        return "bun"
    if shutil.which("npm"):
        return "npm"
    raise CliError("Missing frontend package manager: install Bun or npm.")


def service_unit_path() -> Path:
    return cli_systemd.service_unit_path()


def frontend_build_index_path() -> Path:
    return cli_paths.frontend_build_index_path(FRONTEND)


def ensure_frontend_build_ready() -> Path:
    return service_support.ensure_frontend_build_ready(
        index_path=frontend_build_index_path(),
        root_launcher=ROOT_LAUNCHER,
        cli_error=CliError,
    )


def render_service_unit(
    *,
    user: str,
    home: Path,
    workdir: Path,
    cli_bin: Path,
    host: str,
    public_port: int,
) -> str:
    return cli_systemd.render_service_unit(
        user=user,
        home=home,
        workdir=workdir,
        cli_bin=cli_bin,
        host=host,
        public_port=public_port,
    )


def require_venv_python(*, allow_missing: bool = False) -> Path:
    return service_support.require_venv_python(
        venv_python=venv_python_path(),
        allow_missing=allow_missing,
        cli_error=CliError,
    )


def service_runtime_python_path() -> Path:
    return service_support.service_runtime_python_path(
        venv_python=venv_python_path(),
        sys_module=sys,
        cli_error=CliError,
    )


def venv_python_path() -> Path:
    return cli_paths.venv_python_path(VENV_DIR)


def running_from_repo_checkout() -> bool:
    return cli_paths.running_from_repo_checkout(MODULE_ROOT)


def executor_run_python_path() -> Path:
    return service_support.executor_run_python_path(
        running_from_repo_checkout=running_from_repo_checkout(),
        require_venv_python=lambda: require_venv_python(),
        sys_module=sys,
        cli_error=CliError,
    )


def executor_run_cwd() -> Path:
    return service_support.executor_run_cwd(
        running_from_repo_checkout=running_from_repo_checkout(),
        root=ROOT,
    )


def executor_cli_invocation() -> str:
    return service_support.executor_cli_invocation(
        running_from_repo_checkout=running_from_repo_checkout(),
        root_launcher=ROOT_LAUNCHER,
        cli_name=CLI_NAME,
    )


def run_checked(cmd: list[str], cwd: Path) -> int:
    return cli_processes.run_checked(
        cmd,
        cwd=cwd,
        subprocess_module=subprocess,
        signal_module=signal,
    )


def run_managed_processes(commands: list[tuple[str, list[str], Path]]) -> int:
    specs = [
        cli_processes.ManagedProcessSpec(name=name, command=cmd, cwd=cwd)
        for name, cmd, cwd in commands
    ]
    return cli_processes.run_managed_processes(
        specs,
        subprocess_module=subprocess,
        signal_module=signal,
        time_module=time,
    )


def report_command(name: str, *, required: bool = True) -> bool:
    result = cli_checks.command_check(name, shutil_module=shutil, required=required)
    if result.detail:
        print(f"[{result.status}] command: {name} -> {result.detail}")
    else:
        print(f"[{result.status}] {result.label}")
    return result.ok


def report_path(label: str, value: str) -> bool:
    print(f"[ok] {label}: {value}")
    return True


def _print_check(result: cli_checks.CheckResult) -> bool:
    print(result.render())
    return result.ok


def report_port(port: int) -> bool:
    result = cli_checks.port_check(port, socket_factory=socket.socket)
    print(result.render().replace(": ", " ", 1))
    return result.ok


def report_reachability(label: str, url: str) -> bool:
    result = cli_checks.http_reachability_check(
        label,
        url,
        urlopen=urllib.request.urlopen,
    )
    print(result.render())
    return result.ok


def openai_api_key_present() -> bool:
    if os.getenv("OPENAI_API_KEY"):
        return True
    return cli_checks.env_file_has_key(ENV_LOCAL, OPENAI_KEY)


def setup_can_prompt() -> bool:
    return sys.stdin.isatty()


def _run_executor_setup_flow() -> None:
    app = sys.modules[__name__]
    setup_command.run_executor_setup_flow(
        cli_factories.setup_context(app),
        cli_factories.setup_callbacks(app),
    )


def _can_auto_configure_codex(
    existing_config_yaml: dict[str, object],
    *,
    enabled_executors_override: list[str] | None,
) -> bool:
    selected = (
        enabled_executors_override
        or config_files.existing_executor_enabled_types(existing_config_yaml)
        or ["codex"]
    )
    return selected == ["codex"]


def _try_auto_configure_codex_executor_runtime(
    existing_config_yaml: dict[str, object],
    *,
    enabled_executors_override: list[str] | None,
) -> bool:
    if not _can_auto_configure_codex(
        existing_config_yaml,
        enabled_executors_override=enabled_executors_override,
    ):
        return False
    result = setup_resolvers.resolve_codex_auto_setup_values(
        existing_config_yaml=existing_config_yaml,
        callbacks=_setup_resolution_callbacks(),
    )
    if result is None:
        return False
    config_files.write_connector_config_if_needed(
        result.setup,
        format_user_path=format_user_path,
    )
    print(f"[setup] auto-configured codex executor command: {result.command}")
    return True


def _ensure_executor_runtime_configured_for_run(
    *,
    enabled_executors_override: list[str] | None = None,
) -> None:
    cli_invocation = executor_cli_invocation()
    existing_values, _ = config_files.load_env_assignments(ENV_LOCAL)
    existing_config_yaml = config_files.load_existing_connector_yaml(connector_config_path())
    if _executor_runtime_config_complete(
        existing_config_yaml,
        existing_values,
        enabled_executors_override=enabled_executors_override,
    ):
        return
    if not setup_can_prompt():
        if _try_auto_configure_codex_executor_runtime(
            existing_config_yaml,
            enabled_executors_override=enabled_executors_override,
        ):
            refreshed_values, _ = config_files.load_env_assignments(ENV_LOCAL)
            refreshed_config_yaml = config_files.load_existing_connector_yaml(connector_config_path())
            if _executor_runtime_config_complete(
                refreshed_config_yaml,
                refreshed_values,
                enabled_executors_override=enabled_executors_override,
            ):
                return
        raise CliError(
            f"Local executor runtime config is incomplete. Run `{cli_invocation} executor setup` "
            f"or rerun `{cli_invocation} executor run ...` in a TTY."
        )
    print("[setup] executor run is missing local executor runtime config; launching setup.")
    _run_executor_setup_flow()
    refreshed_values, _ = config_files.load_env_assignments(ENV_LOCAL)
    refreshed_config_yaml = config_files.load_existing_connector_yaml(connector_config_path())
    if not _executor_runtime_config_complete(
        refreshed_config_yaml,
        refreshed_values,
        enabled_executors_override=enabled_executors_override,
    ):
        raise CliError(
            "Local executor runtime config is still incomplete after setup. "
            f"Check the configured executor command paths and rerun `{cli_invocation} executor setup`."
        )


def _executor_runtime_config_complete(
    existing_config_yaml: dict[str, object],
    existing_values: dict[str, str],
    *,
    enabled_executors_override: list[str] | None = None,
) -> bool:
    return setup_resolvers.executor_runtime_config_complete(
        existing_config_yaml,
        existing_values,
        enabled_executors_override=enabled_executors_override,
        callbacks=_setup_resolution_callbacks(),
    )


def bootstrap_setup_files() -> None:
    existing_values, existing_order = config_files.load_env_assignments(ENV_LOCAL)
    if not ENV_LOCAL.exists():
        template_lines = config_files.bootstrap_env_template(
            DEFAULT_ENV_TEMPLATE_LINES,
            required_key=OPENAI_KEY,
        )
        resolved_values = config_files.resolve_bootstrap_values(
            template_lines=template_lines,
            existing_values=existing_values,
            interactive_setup_keys=INTERACTIVE_SETUP_KEYS,
            openai_key=OPENAI_KEY,
        )
        config_files.write_env_file(
            template_lines=template_lines,
            resolved_values=resolved_values,
            existing_values=existing_values,
            existing_order=existing_order,
            destination=ENV_LOCAL,
        )
        print(f"[write] configured {format_user_path(ENV_LOCAL)}")

    config_path = connector_config_path()
    if not config_path.exists():
        config_files.write_connector_config_if_needed(
            ConnectorSetupResult(
                env_values={},
                config_path=config_path,
                config_text=config_files.render_connector_config(
                    runtime={},
                    connector_host=config_files.default_connector_host_config(),
                    connectors={},
                    executor_node=config_files.default_executor_node_config(),
                    executors={},
                ),
            ),
            format_user_path=format_user_path,
        )


def _detected_codex_command() -> str | None:
    return shutil.which("codex")


def _command_available(command: str) -> bool:
    return shutil.which(command) is not None


def list_available_connector_modules() -> list[str]:
    from newbro.connectors.host.catalog import list_connector_module_specs

    return [spec.slug for spec in list_connector_module_specs()]


def load_connector_settings():
    import importlib
    connector_config_module = importlib.import_module("newbro.connectors.host.config")
    return connector_config_module.load_connector_host_settings(env_file=ENV_LOCAL)


def load_executor_node_settings():
    import importlib

    executor_node_config_module = importlib.import_module("newbro.executors.node.config")
    return executor_node_config_module.load_executor_node_settings(env_file=ENV_LOCAL)


def load_connector_settings_if_enabled():
    settings = load_connector_settings()
    if not settings.enabled or not settings.enabled_connectors:
        return None
    return settings


def report_connector_status(args: argparse.Namespace) -> bool:
    del args
    try:
        settings = load_connector_settings()
    except Exception as exc:
        print(f"[missing] connector config: {exc}")
        return False
    if not settings.enabled:
        print("[ok] connector: disabled")
        return True

    ok = True
    connectors = ", ".join(settings.enabled_connectors) or "(none)"
    print(f"[ok] connector: enabled -> {connectors}")
    print(f"[ok] connector public URL: {settings.public_base_url}")
    print(f"[ok] connector standalone listener: {settings.host}:{settings.port}")

    return ok


class CliError(Exception):
    pass


def connector_config_path() -> Path:
    return ENV_LOCAL.with_name("config.yaml")


if __name__ == "__main__":
    raise SystemExit(main())
